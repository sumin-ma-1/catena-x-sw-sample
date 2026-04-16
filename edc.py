from __future__ import annotations

import argparse
import json
import os
import requests
from pathlib import Path

from aas import upsert_submodel


EDC_URL = os.getenv("CATENAX_EDC_MANAGEMENT_URL", "http://localhost:9191/management")
EDC_API_KEY = os.getenv("CATENAX_EDC_API_KEY", "")


def headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if EDC_API_KEY:
        h["X-Api-Key"] = EDC_API_KEY
    return h


def onboard(asset_id: str, provider_bpn: str, cobot_api_base_url: str) -> None:
    asset_payload = {
        "@context": {},
        "@id": asset_id,
        "properties": {
            "name": "Cobot Telemetry API",
            "contenttype": "application/json",
            "description": "Operational telemetry of cobot",
            "cx-common:version": "1.0.0",
            "cx-common:tenant": provider_bpn
        },
        "dataAddress": {
            "type": "HttpData",
            "baseUrl": f"{cobot_api_base_url}/api/v1/cobot/telemetry/latest",
            "proxyPath": "true",
            "proxyMethod": "true",
            "proxyQueryParams": "true"
        }
    }

    access_policy = {
        "@id": f"{asset_id}-access-policy",
        "policy": {
            "@type": "Set",
            "permission": [
                {
                    "action": "use"
                }
            ]
        }
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
                        "rightOperand": "cx.cobot.telemetry"
                    }
                }
            ]
        }
    }

    contract_def = {
        "@id": f"{asset_id}-contract-definition",
        "accessPolicyId": f"{asset_id}-access-policy",
        "contractPolicyId": f"{asset_id}-contract-policy",
        "assetsSelector": [
            {
                "@type": "Criterion",
                "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                "operator": "=",
                "operandRight": asset_id
            }
        ]
    }

    requests.post(f"{EDC_URL}/v3/assets", json=asset_payload, headers=headers(), timeout=20).raise_for_status()
    requests.post(f"{EDC_URL}/v3/policydefinitions", json=access_policy, headers=headers(), timeout=20).raise_for_status()
    requests.post(f"{EDC_URL}/v3/policydefinitions", json=contract_policy, headers=headers(), timeout=20).raise_for_status()
    requests.post(f"{EDC_URL}/v3/contractdefinitions", json=contract_def, headers=headers(), timeout=20).raise_for_status()

    print(json.dumps({"status": "ok", "assetId": asset_id}, indent=2))


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

    sync_p = sub.add_parser("sync-aas")
    sync_p.add_argument("--telemetry-json", required=True)

    args = parser.parse_args()

    if args.cmd == "onboard":
        onboard(args.asset_id, args.provider_bpn, args.cobot_api_base_url)
    elif args.cmd == "sync-aas":
        sync_aas(args.telemetry_json)


if __name__ == "__main__":
    main()