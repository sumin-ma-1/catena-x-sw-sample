from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from sqlalchemy import create_engine, text

from aas import upsert_submodel


PROTOCOL = "dataspace-protocol-http"
ASSET_ID_FIELD = "https://w3id.org/edc/v0.0.1/ns/id"

# Backward-compatible defaults used by existing onboarding flow.
EDC_URL = os.getenv("CATENAX_EDC_MANAGEMENT_URL", "http://localhost:9191/management")
EDC_API_KEY = os.getenv("CATENAX_EDC_API_KEY", "")

# Optional split endpoints for provider/consumer exchange tests.
PROVIDER_MANAGEMENT_URL = os.getenv("CATENAX_EDC_PROVIDER_MANAGEMENT_URL", EDC_URL)
PROVIDER_API_KEY = os.getenv("CATENAX_EDC_PROVIDER_API_KEY", EDC_API_KEY)
CONSUMER_MANAGEMENT_URL = os.getenv("CATENAX_EDC_CONSUMER_MANAGEMENT_URL", EDC_URL)
CONSUMER_API_KEY = os.getenv("CATENAX_EDC_CONSUMER_API_KEY", EDC_API_KEY)
PROVIDER_PROTOCOL_URL = os.getenv("CATENAX_EDC_PROVIDER_PROTOCOL_URL", "")
EDC_METRICS_DATABASE_URL = os.getenv("EDC_METRICS_DATABASE_URL", os.getenv("DATABASE_URL", ""))

_METRICS_ENGINE = create_engine(EDC_METRICS_DATABASE_URL, future=True) if EDC_METRICS_DATABASE_URL else None
_METRICS_TABLE_READY = False


class ExchangeError(Exception):
    """
    ExchangeError captures the stage-specific context so we can persist precise
    failure metrics for negotiation/transfer pipelines.
    """

    def __init__(self, message: str, context: dict[str, Any]) -> None:
        super().__init__(message)
        self.context = context


def _headers(api_key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["X-Api-Key"] = api_key
    return h


def _post_json(url: str, *, payload: dict[str, Any], api_key: str, timeout: int = 30) -> Any:
    resp = requests.post(url, json=payload, headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    if not resp.content:
        return {}
    return resp.json()


def _get_json(url: str, *, api_key: str, timeout: int = 30) -> Any:
    resp = requests.get(url, headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    if not resp.content:
        return {}
    return resp.json()


def _extract_first_dataset(catalog_response: Any, asset_id: str | None) -> dict[str, Any]:
    # EDC catalog payload shape can differ by version; support common variants.
    datasets: list[dict[str, Any]] = []
    if isinstance(catalog_response, dict):
        if isinstance(catalog_response.get("dcat:dataset"), list):
            datasets = [x for x in catalog_response["dcat:dataset"] if isinstance(x, dict)]
        elif isinstance(catalog_response.get("datasets"), list):
            datasets = [x for x in catalog_response["datasets"] if isinstance(x, dict)]
        elif isinstance(catalog_response.get("items"), list):
            datasets = [x for x in catalog_response["items"] if isinstance(x, dict)]
    elif isinstance(catalog_response, list):
        datasets = [x for x in catalog_response if isinstance(x, dict)]

    if not datasets:
        raise RuntimeError("Catalog response does not contain datasets.")

    if asset_id is None:
        return datasets[0]

    for ds in datasets:
        ds_id = ds.get("@id") or ds.get("id") or ds.get(ASSET_ID_FIELD)
        if ds_id == asset_id:
            return ds
        # Some EDC responses nest asset id in properties.
        props = ds.get("properties")
        if isinstance(props, dict) and props.get(ASSET_ID_FIELD) == asset_id:
            return ds

    raise RuntimeError(f"Asset '{asset_id}' not found in catalog response.")


def _extract_offer(dataset: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    policy = dataset.get("odrl:hasPolicy") or dataset.get("policy")
    if not isinstance(policy, dict):
        raise RuntimeError("Could not extract offer policy from dataset.")

    offer_id = policy.get("@id") or policy.get("id")
    if not isinstance(offer_id, str) or not offer_id:
        raise RuntimeError("Could not extract offer id from offer policy.")

    return offer_id, policy


def _extract_state(doc: dict[str, Any], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        value = doc.get(key)
        if isinstance(value, str) and value:
            return value.upper()
    return ""


def _poll_state(
    *,
    url: str,
    api_key: str,
    state_keys: tuple[str, ...],
    success_states: set[str],
    failure_states: set[str],
    timeout_s: int,
    interval_s: int,
) -> dict[str, Any]:
    # Polling is required because EDC contract negotiation and transfer are async processes.
    deadline = time.time() + timeout_s
    last_doc: dict[str, Any] = {}
    while time.time() < deadline:
        doc = _get_json(url, api_key=api_key, timeout=30)
        if isinstance(doc, dict):
            last_doc = doc
        state = _extract_state(last_doc, state_keys)
        if state in success_states:
            return last_doc
        if state in failure_states:
            raise RuntimeError(f"EDC process failed with state={state}: {json.dumps(last_doc)}")
        time.sleep(interval_s)

    raise TimeoutError(f"Timed out while polling EDC process: {json.dumps(last_doc)}")


def _ensure_metrics_table() -> None:
    global _METRICS_TABLE_READY
    if _METRICS_ENGINE is None or _METRICS_TABLE_READY:
        return

    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS edc_exchange_metrics (
            id BIGSERIAL PRIMARY KEY,
            event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            attempt_id UUID NOT NULL UNIQUE,
            asset_id TEXT NOT NULL,
            provider_protocol_url TEXT NOT NULL,
            consumer_management_url TEXT NOT NULL,
            result TEXT NOT NULL, -- SUCCESS or FAILED
            failure_stage TEXT,
            contract_negotiation_id TEXT,
            contract_agreement_id TEXT,
            transfer_process_id TEXT,
            fetched_status_code INTEGER,
            duration_ms INTEGER NOT NULL,
            error_message TEXT,
            detail JSONB
        );
        """
    )
    with _METRICS_ENGINE.begin() as conn:
        conn.execute(ddl)
    _METRICS_TABLE_READY = True


def _record_exchange_metric(payload: dict[str, Any]) -> None:
    """
    Persist one exchange attempt result.
    If no metrics DB URL is configured, this becomes a no-op by design.
    """
    if _METRICS_ENGINE is None:
        return

    _ensure_metrics_table()
    sql = text(
        """
        INSERT INTO edc_exchange_metrics (
            attempt_id, asset_id, provider_protocol_url, consumer_management_url,
            result, failure_stage, contract_negotiation_id, contract_agreement_id,
            transfer_process_id, fetched_status_code, duration_ms, error_message, detail
        )
        VALUES (
            CAST(:attempt_id AS uuid), :asset_id, :provider_protocol_url, :consumer_management_url,
            :result, :failure_stage, :contract_negotiation_id, :contract_agreement_id,
            :transfer_process_id, :fetched_status_code, :duration_ms, :error_message, CAST(:detail AS jsonb)
        )
        """
    )
    with _METRICS_ENGINE.begin() as conn:
        conn.execute(
            sql,
            {
                "attempt_id": payload["attempt_id"],
                "asset_id": payload["asset_id"],
                "provider_protocol_url": payload["provider_protocol_url"],
                "consumer_management_url": payload["consumer_management_url"],
                "result": payload["result"],
                "failure_stage": payload.get("failure_stage"),
                "contract_negotiation_id": payload.get("contract_negotiation_id"),
                "contract_agreement_id": payload.get("contract_agreement_id"),
                "transfer_process_id": payload.get("transfer_process_id"),
                "fetched_status_code": payload.get("fetched_status_code"),
                "duration_ms": payload["duration_ms"],
                "error_message": payload.get("error_message"),
                "detail": json.dumps(payload.get("detail") or {}, ensure_ascii=False),
            },
        )


def onboard(asset_id: str, provider_bpn: str, cobot_api_base_url: str) -> None:
    asset_payload = {
        "@context": {},
        "@id": asset_id,
        "properties": {
            "name": "Cobot Telemetry API",
            "contenttype": "application/json",
            "description": "Operational telemetry of cobot",
            "cx-common:version": "1.0.0",
            "cx-common:tenant": provider_bpn,
        },
        "dataAddress": {
            "type": "HttpData",
            "baseUrl": f"{cobot_api_base_url}/api/v1/cobot/telemetry/latest",
            "proxyPath": "true",
            "proxyMethod": "true",
            "proxyQueryParams": "true",
        },
    }

    access_policy = {
        "@id": f"{asset_id}-access-policy",
        "policy": {
            "@type": "Set",
            "permission": [{"action": "use"}],
        },
    }

    contract_policy = {
        "@id": f"{asset_id}-contract-policy",
        "policy": {
            "@type": "Set",
            "permission": [
                {
                    "action": "use",
                    "constraint": {
                        "leftOperand": "PURPOSE",
                        "operator": "eq",
                        "rightOperand": "cx.cobot.telemetry",
                    },
                }
            ],
        },
    }

    contract_def = {
        "@id": f"{asset_id}-contract-definition",
        "accessPolicyId": f"{asset_id}-access-policy",
        "contractPolicyId": f"{asset_id}-contract-policy",
        "assetsSelector": [
            {
                "@type": "Criterion",
                "operandLeft": ASSET_ID_FIELD,
                "operator": "=",
                "operandRight": asset_id,
            }
        ],
    }

    _post_json(f"{EDC_URL}/v3/assets", payload=asset_payload, api_key=EDC_API_KEY, timeout=20)
    _post_json(f"{EDC_URL}/v3/policydefinitions", payload=access_policy, api_key=EDC_API_KEY, timeout=20)
    _post_json(f"{EDC_URL}/v3/policydefinitions", payload=contract_policy, api_key=EDC_API_KEY, timeout=20)
    _post_json(f"{EDC_URL}/v3/contractdefinitions", payload=contract_def, api_key=EDC_API_KEY, timeout=20)

    print(json.dumps({"status": "ok", "assetId": asset_id}, indent=2))


def discover_catalog(
    *,
    consumer_management_url: str,
    consumer_api_key: str,
    provider_protocol_url: str,
    asset_id: str | None,
    limit: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "counterPartyAddress": provider_protocol_url,
        "protocol": PROTOCOL,
        "querySpec": {"offset": 0, "limit": limit},
    }
    if asset_id:
        payload["querySpec"]["filterExpression"] = [
            {
                "operandLeft": ASSET_ID_FIELD,
                "operator": "=",
                "operandRight": asset_id,
            }
        ]
    result = _post_json(
        f"{consumer_management_url}/v3/catalog/request",
        payload=payload,
        api_key=consumer_api_key,
        timeout=30,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected catalog response format.")
    return result


def exchange(
    *,
    asset_id: str,
    provider_protocol_url: str,
    consumer_management_url: str,
    consumer_api_key: str,
    timeout_s: int,
    interval_s: int,
) -> dict[str, Any]:
    started = time.time()
    context: dict[str, Any] = {
        "asset_id": asset_id,
        "provider_protocol_url": provider_protocol_url,
        "consumer_management_url": consumer_management_url,
        "failure_stage": "discover",
    }

    # 1) Discover catalog and extract one dataset offer for the requested asset.
    try:
        catalog = discover_catalog(
            consumer_management_url=consumer_management_url,
            consumer_api_key=consumer_api_key,
            provider_protocol_url=provider_protocol_url,
            asset_id=asset_id,
            limit=50,
        )
        dataset = _extract_first_dataset(catalog, asset_id=asset_id)
        offer_id, offer_policy = _extract_offer(dataset)

        # 2) Start contract negotiation.
        context["failure_stage"] = "negotiation"
        neg_payload = {
            "counterPartyAddress": provider_protocol_url,
            "protocol": PROTOCOL,
            "offer": {
                "offerId": offer_id,
                "assetId": asset_id,
                "policy": offer_policy,
            },
        }
        neg_resp = _post_json(
            f"{consumer_management_url}/v3/contractnegotiations",
            payload=neg_payload,
            api_key=consumer_api_key,
            timeout=30,
        )
        if not isinstance(neg_resp, dict):
            raise RuntimeError("Unexpected contract negotiation response format.")
        negotiation_id = neg_resp.get("@id") or neg_resp.get("id")
        if not isinstance(negotiation_id, str) or not negotiation_id:
            raise RuntimeError(f"Could not read contract negotiation id from: {json.dumps(neg_resp)}")
        context["contract_negotiation_id"] = negotiation_id

        neg_doc = _poll_state(
            url=f"{consumer_management_url}/v3/contractnegotiations/{negotiation_id}",
            api_key=consumer_api_key,
            state_keys=("state", "contractNegotiationState"),
            success_states={"FINALIZED"},
            failure_states={"TERMINATED", "DECLINED", "FAILED", "ERROR"},
            timeout_s=timeout_s,
            interval_s=interval_s,
        )
        agreement_id = neg_doc.get("contractAgreementId")
        if not isinstance(agreement_id, str) or not agreement_id:
            # Some EDC versions nest it in policy-like objects or aliases.
            agreement_id = neg_doc.get("agreementId")
        if not isinstance(agreement_id, str) or not agreement_id:
            raise RuntimeError(f"Negotiation finalized but agreement id was not found: {json.dumps(neg_doc)}")
        context["contract_agreement_id"] = agreement_id

        # 3) Start transfer process using the contract agreement id.
        context["failure_stage"] = "transfer"
        transfer_payload = {
            "counterPartyAddress": provider_protocol_url,
            "contractId": agreement_id,
            "assetId": asset_id,
            "protocol": PROTOCOL,
            "managedResources": False,
            # HttpProxy is the most common destination for API-style transfers.
            "dataDestination": {"type": "HttpProxy"},
        }
        transfer_resp = _post_json(
            f"{consumer_management_url}/v3/transferprocesses",
            payload=transfer_payload,
            api_key=consumer_api_key,
            timeout=30,
        )
        if not isinstance(transfer_resp, dict):
            raise RuntimeError("Unexpected transfer process response format.")
        transfer_id = transfer_resp.get("@id") or transfer_resp.get("id")
        if not isinstance(transfer_id, str) or not transfer_id:
            raise RuntimeError(f"Could not read transfer process id from: {json.dumps(transfer_resp)}")
        context["transfer_process_id"] = transfer_id

        transfer_doc = _poll_state(
            url=f"{consumer_management_url}/v3/transferprocesses/{transfer_id}",
            api_key=consumer_api_key,
            state_keys=("state", "transferProcessState"),
            success_states={"COMPLETED", "FINISHED"},
            failure_states={"TERMINATED", "DECLINED", "FAILED", "ERROR"},
            timeout_s=timeout_s,
            interval_s=interval_s,
        )

        result = {
            "status": "ok",
            "assetId": asset_id,
            "contractNegotiationId": negotiation_id,
            "contractAgreementId": agreement_id,
            "transferProcessId": transfer_id,
            "durationMs": int((time.time() - started) * 1000),
        }

        # 4) Optional best-effort fetch from transfer data endpoint if exposed by this EDC setup.
        context["failure_stage"] = "fetch"
        data_address = transfer_doc.get("dataAddress") or transfer_doc.get("contentDataAddress")
        if isinstance(data_address, dict):
            endpoint = data_address.get("endpoint") or data_address.get("baseUrl")
            auth_code = data_address.get("authCode")
            if isinstance(endpoint, str) and endpoint:
                headers: dict[str, str] = {}
                if isinstance(auth_code, str) and auth_code:
                    headers["Authorization"] = f"Bearer {auth_code}"
                fetch = requests.get(endpoint, headers=headers, timeout=30)
                result["fetchedStatusCode"] = fetch.status_code
                result["fetchedBody"] = fetch.text[:1000]
            else:
                result["note"] = "Transfer succeeded, but no fetch endpoint was returned by EDC."
        else:
            result["note"] = "Transfer succeeded, but no dataAddress was returned by EDC."

        return result
    except Exception as exc:
        context["duration_ms"] = int((time.time() - started) * 1000)
        raise ExchangeError(str(exc), context) from exc


def sync_aas(telemetry_json: str) -> None:
    payload = json.loads(Path(telemetry_json).read_text(encoding="utf-8"))
    resp = upsert_submodel(payload)
    resp.raise_for_status()
    print(json.dumps({"status": "ok", "aas": "synced"}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    onboard_p = sub.add_parser("onboard")
    onboard_p.add_argument("--asset-id", required=True)
    onboard_p.add_argument("--provider-bpn", required=True)
    onboard_p.add_argument("--cobot-api-base-url", required=True)

    discover_p = sub.add_parser("discover")
    discover_p.add_argument("--provider-protocol-url", default=PROVIDER_PROTOCOL_URL, required=not bool(PROVIDER_PROTOCOL_URL))
    discover_p.add_argument("--consumer-management-url", default=CONSUMER_MANAGEMENT_URL)
    discover_p.add_argument("--consumer-api-key", default=CONSUMER_API_KEY)
    discover_p.add_argument("--asset-id", default=None)
    discover_p.add_argument("--limit", type=int, default=50)

    exchange_p = sub.add_parser("exchange")
    exchange_p.add_argument("--asset-id", required=True)
    exchange_p.add_argument("--provider-protocol-url", default=PROVIDER_PROTOCOL_URL, required=not bool(PROVIDER_PROTOCOL_URL))
    exchange_p.add_argument("--consumer-management-url", default=CONSUMER_MANAGEMENT_URL)
    exchange_p.add_argument("--consumer-api-key", default=CONSUMER_API_KEY)
    exchange_p.add_argument("--timeout-s", type=int, default=120)
    exchange_p.add_argument("--interval-s", type=int, default=3)

    sync_p = sub.add_parser("sync-aas")
    sync_p.add_argument("--telemetry-json", required=True)

    args = parser.parse_args()

    if args.cmd == "onboard":
        onboard(args.asset_id, args.provider_bpn, args.cobot_api_base_url)
    elif args.cmd == "discover":
        result = discover_catalog(
            consumer_management_url=args.consumer_management_url,
            consumer_api_key=args.consumer_api_key,
            provider_protocol_url=args.provider_protocol_url,
            asset_id=args.asset_id,
            limit=args.limit,
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "exchange":
        attempt_id = str(uuid4())
        try:
            result = exchange(
                asset_id=args.asset_id,
                provider_protocol_url=args.provider_protocol_url,
                consumer_management_url=args.consumer_management_url,
                consumer_api_key=args.consumer_api_key,
                timeout_s=args.timeout_s,
                interval_s=args.interval_s,
            )
            _record_exchange_metric(
                {
                    "attempt_id": attempt_id,
                    "asset_id": args.asset_id,
                    "provider_protocol_url": args.provider_protocol_url,
                    "consumer_management_url": args.consumer_management_url,
                    "result": "SUCCESS",
                    "failure_stage": None,
                    "contract_negotiation_id": result.get("contractNegotiationId"),
                    "contract_agreement_id": result.get("contractAgreementId"),
                    "transfer_process_id": result.get("transferProcessId"),
                    "fetched_status_code": result.get("fetchedStatusCode"),
                    "duration_ms": int(result.get("durationMs") or 0),
                    "error_message": None,
                    "detail": result,
                }
            )
            result["attemptId"] = attempt_id
            print(json.dumps(result, indent=2))
        except ExchangeError as exc:
            ctx = exc.context
            _record_exchange_metric(
                {
                    "attempt_id": attempt_id,
                    "asset_id": args.asset_id,
                    "provider_protocol_url": args.provider_protocol_url,
                    "consumer_management_url": args.consumer_management_url,
                    "result": "FAILED",
                    "failure_stage": ctx.get("failure_stage"),
                    "contract_negotiation_id": ctx.get("contract_negotiation_id"),
                    "contract_agreement_id": ctx.get("contract_agreement_id"),
                    "transfer_process_id": ctx.get("transfer_process_id"),
                    "fetched_status_code": None,
                    "duration_ms": int(ctx.get("duration_ms") or 0),
                    "error_message": str(exc),
                    "detail": ctx,
                }
            )
            raise
    elif args.cmd == "sync-aas":
        sync_aas(args.telemetry_json)


if __name__ == "__main__":
    main()