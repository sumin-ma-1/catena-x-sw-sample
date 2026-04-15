from __future__ import annotations

"""Catena-X EDC integration helper.

This module provides a pragmatic Python integration layer for:

1. Registering EDC assets, policies and contract definitions.
2. Negotiating and starting data transfers against an EDC connector.
3. Registering Catena-X compatible Digital Twin / AAS metadata.
4. Mapping collaborative robot telemetry into AAS Submodels.

The implementation is intentionally HTTP-first so it can be used with
commercial Catena-X service providers, self-hosted Eclipse Dataspace
Connector deployments, or Tractus-X based environments that expose
compatible management APIs.

Notes
-----
- Exact endpoint paths can differ slightly by deployment. Override the
  defaults through the config dataclasses if your environment uses
  different routes.
- The AAS payload shapes are kept compatible with common AAS v3 JSON
  conventions, but vendors may require additional fields.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import uuid
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

import requests


JsonDict = Dict[str, Any]


class EDCError(RuntimeError):
    """Raised when an EDC or AAS request fails."""


@dataclass(slots=True)
class EDCConfig:
    """Connection settings for an EDC management / protocol API."""

    management_url: str
    api_key: Optional[str] = None
    protocol_url: Optional[str] = None
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    management_api_key_header: str = "X-Api-Key"

    # Common default paths; override if your connector uses different ones.
    assets_path: str = "/v3/assets"
    policies_path: str = "/v3/policydefinitions"
    contract_definitions_path: str = "/v3/contractdefinitions"
    catalog_request_path: str = "/v3/catalog/request"
    negotiation_path: str = "/v3/contractnegotiations"
    transfer_path: str = "/v3/transferprocesses"


@dataclass(slots=True)
class AASConfig:
    """Connection settings for an AAS registry / server / DTR deployment."""

    registry_url: str
    server_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    api_key_header: str = "X-Api-Key"

    shells_path: str = "/shell-descriptors"
    submodel_descriptors_path: str = "/submodel-descriptors"
    submodels_path: str = "/submodels"


@dataclass(slots=True)
class EDCAssetDefinition:
    """EDC asset metadata used for publication."""

    asset_id: str
    data_address_type: str
    data_address_properties: JsonDict
    private_properties: JsonDict = field(default_factory=dict)
    public_properties: JsonDict = field(default_factory=dict)

    def to_payload(self) -> JsonDict:
        return {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "@id": self.asset_id,
            "properties": self.public_properties,
            "privateProperties": self.private_properties,
            "dataAddress": {
                "type": self.data_address_type,
                **self.data_address_properties,
            },
        }


@dataclass(slots=True)
class ContractPolicy:
    """Minimal Catena-X/EDC policy definition wrapper."""

    policy_id: str
    permissions: List[JsonDict]
    prohibitions: List[JsonDict] = field(default_factory=list)
    obligations: List[JsonDict] = field(default_factory=list)

    def to_payload(self) -> JsonDict:
        return {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "@id": self.policy_id,
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "Set",
                "permission": self.permissions,
                "prohibition": self.prohibitions,
                "obligation": self.obligations,
            },
        }


@dataclass(slots=True)
class ContractDefinition:
    """Contract definition linking assets and policies."""

    definition_id: str
    access_policy_id: str
    contract_policy_id: str
    asset_id: str

    def to_payload(self) -> JsonDict:
        return {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "@id": self.definition_id,
            "accessPolicyId": self.access_policy_id,
            "contractPolicyId": self.contract_policy_id,
            "assetsSelector": [
                {
                    "@type": "Criterion",
                    "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                    "operator": "=",
                    "operandRight": self.asset_id,
                }
            ],
        }


@dataclass(slots=True)
class AASPropertyMapping:
    """Maps a source telemetry field into an AAS property."""

    source_key: str
    id_short: str
    value_type: str = "xs:string"
    semantic_id: Optional[str] = None
    category: str = "PARAMETER"
    formatter: Optional[Callable[[Any], Any]] = None

    def to_submodel_element(self, source: Mapping[str, Any]) -> JsonDict:
        raw_value = source.get(self.source_key)
        value = self.formatter(raw_value) if self.formatter else raw_value
        payload: JsonDict = {
            "modelType": "Property",
            "idShort": self.id_short,
            "category": self.category,
            "valueType": self.value_type,
            "value": None if value is None else str(value),
        }
        if self.semantic_id:
            payload["semanticId"] = {
                "type": "ExternalReference",
                "keys": [
                    {
                        "type": "GlobalReference",
                        "value": self.semantic_id,
                    }
                ],
            }
        return payload


@dataclass(slots=True)
class RobotTelemetry:
    """Structured collaborative-robot event / telemetry message."""

    robot_id: str
    workstation_id: str
    timestamp: datetime
    status: str
    program_id: Optional[str] = None
    cycle_count: Optional[int] = None
    energy_wh: Optional[float] = None
    temperature_c: Optional[float] = None
    vibration_mm_s: Optional[float] = None
    torque_nm: Optional[float] = None
    payload_kg: Optional[float] = None
    joint_positions_deg: Optional[Sequence[float]] = None
    additional_properties: JsonDict = field(default_factory=dict)

    def to_flat_dict(self) -> JsonDict:
        data: JsonDict = {
            "robotId": self.robot_id,
            "workstationId": self.workstation_id,
            "timestamp": self.timestamp.astimezone(timezone.utc).isoformat(),
            "status": self.status,
            "programId": self.program_id,
            "cycleCount": self.cycle_count,
            "energyWh": self.energy_wh,
            "temperatureC": self.temperature_c,
            "vibrationMmPerS": self.vibration_mm_s,
            "torqueNm": self.torque_nm,
            "payloadKg": self.payload_kg,
            "jointPositionsDeg": list(self.joint_positions_deg or []),
        }
        data.update(self.additional_properties)
        return data


class AASSubmodelBuilder:
    """Builds an AAS Submodel JSON payload from collaborative robot data."""

    def __init__(
        self,
        semantic_id: str,
        mappings: Optional[Sequence[AASPropertyMapping]] = None,
    ) -> None:
        self.semantic_id = semantic_id
        self.mappings = list(mappings or self.default_mappings())

    @staticmethod
    def default_mappings() -> List[AASPropertyMapping]:
        return [
            AASPropertyMapping("robotId", "robotId", "xs:string"),
            AASPropertyMapping("workstationId", "workstationId", "xs:string"),
            AASPropertyMapping("timestamp", "timestamp", "xs:dateTime"),
            AASPropertyMapping("status", "status", "xs:string"),
            AASPropertyMapping("programId", "programId", "xs:string"),
            AASPropertyMapping("cycleCount", "cycleCount", "xs:integer"),
            AASPropertyMapping("energyWh", "energyWh", "xs:double"),
            AASPropertyMapping("temperatureC", "temperatureC", "xs:double"),
            AASPropertyMapping("vibrationMmPerS", "vibrationMmPerS", "xs:double"),
            AASPropertyMapping("torqueNm", "torqueNm", "xs:double"),
            AASPropertyMapping("payloadKg", "payloadKg", "xs:double"),
            AASPropertyMapping(
                "jointPositionsDeg",
                "jointPositionsDeg",
                "xs:string",
                formatter=lambda v: json.dumps(v or []),
            ),
        ]

    def build(
        self,
        telemetry: RobotTelemetry,
        *,
        submodel_id: Optional[str] = None,
        id_short: str = "CollaborativeRobotTelemetry",
        description: Optional[str] = None,
    ) -> JsonDict:
        flat = telemetry.to_flat_dict()
        elements = [m.to_submodel_element(flat) for m in self.mappings]

        mapped_keys = {m.source_key for m in self.mappings}
        for key, value in flat.items():
            if key in mapped_keys or value is None:
                continue
            elements.append(
                {
                    "modelType": "Property",
                    "idShort": key,
                    "category": "PARAMETER",
                    "valueType": "xs:string",
                    "value": json.dumps(value) if isinstance(value, (dict, list)) else str(value),
                }
            )

        payload: JsonDict = {
            "id": submodel_id or f"urn:uuid:{uuid.uuid4()}",
            "idShort": id_short,
            "kind": "Instance",
            "modelType": "Submodel",
            "semanticId": {
                "type": "ExternalReference",
                "keys": [{"type": "GlobalReference", "value": self.semantic_id}],
            },
            "submodelElements": elements,
        }
        if description:
            payload["description"] = [{"language": "en", "text": description}]
        return payload


class _BaseHTTPClient:
    def __init__(self, timeout_seconds: float, verify_tls: bool) -> None:
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.session = requests.Session()

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        json_body: Optional[Any] = None,
        params: Optional[Mapping[str, Any]] = None,
    ) -> JsonDict:
        response = self.session.request(
            method=method,
            url=url,
            headers=dict(headers or {}),
            json=json_body,
            params=params,
            timeout=self.timeout_seconds,
            verify=self.verify_tls,
        )
        if response.status_code >= 400:
            raise EDCError(
                f"HTTP {response.status_code} for {method} {url}: {response.text[:500]}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}


class EDCManagementClient(_BaseHTTPClient):
    """Thin wrapper around the EDC management and protocol APIs."""

    def __init__(self, config: EDCConfig) -> None:
        super().__init__(config.timeout_seconds, config.verify_tls)
        self.config = config

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers[self.config.management_api_key_header] = self.config.api_key
        return headers

    def create_or_update_asset(self, asset: EDCAssetDefinition) -> JsonDict:
        return self._request(
            "POST",
            f"{self.config.management_url.rstrip('/')}{self.config.assets_path}",
            headers=self._headers(),
            json_body=asset.to_payload(),
        )

    def create_or_update_policy(self, policy: ContractPolicy) -> JsonDict:
        return self._request(
            "POST",
            f"{self.config.management_url.rstrip('/')}{self.config.policies_path}",
            headers=self._headers(),
            json_body=policy.to_payload(),
        )

    def create_or_update_contract_definition(self, definition: ContractDefinition) -> JsonDict:
        return self._request(
            "POST",
            f"{self.config.management_url.rstrip('/')}{self.config.contract_definitions_path}",
            headers=self._headers(),
            json_body=definition.to_payload(),
        )

    def request_catalog(self, counterparty_protocol_url: str, counterparty_id: str) -> JsonDict:
        if not self.config.protocol_url:
            raise EDCError("protocol_url must be configured to request a catalog")
        payload = {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "counterPartyAddress": counterparty_protocol_url,
            "protocol": "dataspace-protocol-http",
            "counterPartyId": counterparty_id,
        }
        return self._request(
            "POST",
            f"{self.config.management_url.rstrip('/')}{self.config.catalog_request_path}",
            headers=self._headers(),
            json_body=payload,
        )

    def negotiate_contract(
        self,
        *,
        counterparty_protocol_url: str,
        counterparty_id: str,
        offer_id: str,
        asset_id: str,
    ) -> JsonDict:
        payload = {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "counterPartyAddress": counterparty_protocol_url,
            "protocol": "dataspace-protocol-http",
            "counterPartyId": counterparty_id,
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "Offer",
                "@id": offer_id,
                "assigner": counterparty_id,
                "target": asset_id,
                "permission": [{"action": "use"}],
            },
        }
        return self._request(
            "POST",
            f"{self.config.management_url.rstrip('/')}{self.config.negotiation_path}",
            headers=self._headers(),
            json_body=payload,
        )

    def initiate_transfer(
        self,
        *,
        counterparty_protocol_url: str,
        counterparty_id: str,
        contract_agreement_id: str,
        asset_id: str,
        data_destination: Mapping[str, Any],
        transfer_type: str = "HttpData-PULL",
    ) -> JsonDict:
        payload = {
            "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
            "counterPartyAddress": counterparty_protocol_url,
            "protocol": "dataspace-protocol-http",
            "counterPartyId": counterparty_id,
            "contractId": contract_agreement_id,
            "assetId": asset_id,
            "transferType": transfer_type,
            "dataDestination": dict(data_destination),
        }
        return self._request(
            "POST",
            f"{self.config.management_url.rstrip('/')}{self.config.transfer_path}",
            headers=self._headers(),
            json_body=payload,
        )


class AASClient(_BaseHTTPClient):
    """HTTP client for AAS registry and submodel server interactions."""

    def __init__(self, config: AASConfig) -> None:
        super().__init__(config.timeout_seconds, config.verify_tls)
        self.config = config

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers[self.config.api_key_header] = self.config.api_key
        return headers

    def register_shell_descriptor(
        self,
        *,
        shell_id: str,
        global_asset_id: str,
        id_short: str,
        specific_asset_ids: Optional[Sequence[str]] = None,
        endpoint: Optional[str] = None,
    ) -> JsonDict:
        payload: JsonDict = {
            "id": shell_id,
            "idShort": id_short,
            "globalAssetId": global_asset_id,
            "specificAssetIds": [
                {"name": "assetId", "value": v} for v in (specific_asset_ids or [])
            ],
        }
        if endpoint:
            payload["endpoints"] = [
                {
                    "interface": "AAS-3.0",
                    "protocolInformation": {
                        "href": endpoint,
                        "endpointProtocol": "HTTP",
                        "endpointProtocolVersion": ["1.1"],
                    },
                }
            ]
        return self._request(
            "POST",
            f"{self.config.registry_url.rstrip('/')}{self.config.shells_path}",
            headers=self._headers(),
            json_body=payload,
        )

    def register_submodel_descriptor(
        self,
        *,
        shell_id: str,
        submodel_id: str,
        semantic_id: str,
        endpoint: str,
        id_short: str,
    ) -> JsonDict:
        payload = {
            "id": submodel_id,
            "idShort": id_short,
            "semanticId": {
                "type": "ExternalReference",
                "keys": [{"type": "GlobalReference", "value": semantic_id}],
            },
            "endpoints": [
                {
                    "interface": "SUBMODEL-3.0",
                    "protocolInformation": {
                        "href": endpoint,
                        "endpointProtocol": "HTTP",
                        "endpointProtocolVersion": ["1.1"],
                    },
                }
            ],
        }
        return self._request(
            "POST",
            (
                f"{self.config.registry_url.rstrip('/')}{self.config.shells_path}/"
                f"{requests.utils.quote(shell_id, safe='')}{self.config.submodel_descriptors_path}"
            ),
            headers=self._headers(),
            json_body=payload,
        )

    def create_or_update_submodel(self, submodel: Mapping[str, Any]) -> JsonDict:
        base = (self.config.server_url or self.config.registry_url).rstrip("/")
        return self._request(
            "POST",
            f"{base}{self.config.submodels_path}",
            headers=self._headers(),
            json_body=dict(submodel),
        )


class CatenaxEDCConnector:
    """Facade that combines EDC and AAS operations for Catena-X scenarios."""

    def __init__(self, edc: EDCManagementClient, aas: Optional[AASClient] = None) -> None:
        self.edc = edc
        self.aas = aas

    @classmethod
    def from_env(cls) -> "CatenaxEDCConnector":
        edc = EDCManagementClient(
            EDCConfig(
                management_url=_require_env("EDC_MANAGEMENT_URL"),
                api_key=os.getenv("EDC_API_KEY"),
                protocol_url=os.getenv("EDC_PROTOCOL_URL"),
                verify_tls=_env_bool("EDC_VERIFY_TLS", default=True),
            )
        )

        aas_registry = os.getenv("AAS_REGISTRY_URL")
        aas = None
        if aas_registry:
            aas = AASClient(
                AASConfig(
                    registry_url=aas_registry,
                    server_url=os.getenv("AAS_SERVER_URL"),
                    api_key=os.getenv("AAS_API_KEY"),
                    verify_tls=_env_bool("AAS_VERIFY_TLS", default=True),
                )
            )
        return cls(edc=edc, aas=aas)

    def publish_http_json_asset(
        self,
        *,
        asset_id: str,
        endpoint_url: str,
        policy_id: Optional[str] = None,
        contract_definition_id: Optional[str] = None,
        public_properties: Optional[JsonDict] = None,
        private_properties: Optional[JsonDict] = None,
    ) -> JsonDict:
        asset = EDCAssetDefinition(
            asset_id=asset_id,
            data_address_type="HttpData",
            data_address_properties={
                "baseUrl": endpoint_url,
                "proxyMethod": "true",
                "proxyPath": "true",
                "proxyQueryParams": "true",
                "contentType": "application/json",
            },
            public_properties=public_properties or {},
            private_properties=private_properties or {},
        )
        asset_result = self.edc.create_or_update_asset(asset)

        result = {"asset": asset_result}
        if policy_id:
            default_policy = ContractPolicy(
                policy_id=policy_id,
                permissions=[{"action": "use"}],
            )
            result["policy"] = self.edc.create_or_update_policy(default_policy)

            definition = ContractDefinition(
                definition_id=contract_definition_id or f"cd-{asset_id}",
                access_policy_id=policy_id,
                contract_policy_id=policy_id,
                asset_id=asset_id,
            )
            result["contractDefinition"] = self.edc.create_or_update_contract_definition(definition)
        return result

    def register_robot_aas(
        self,
        *,
        shell_id: str,
        global_asset_id: str,
        robot_id: str,
        submodel: Mapping[str, Any],
        submodel_endpoint: Optional[str] = None,
    ) -> JsonDict:
        if not self.aas:
            raise EDCError("AAS client is not configured")

        submodel_id = str(submodel["id"])
        submodel_id_short = str(submodel.get("idShort", "CollaborativeRobotTelemetry"))
        semantic_id = str(submodel["semanticId"]["keys"][0]["value"])
        resolved_endpoint = submodel_endpoint
        if not resolved_endpoint:
            base = (self.aas.config.server_url or self.aas.config.registry_url).rstrip("/")
            resolved_endpoint = f"{base}{self.aas.config.submodels_path}/{requests.utils.quote(submodel_id, safe='')}"

        shell_result = self.aas.register_shell_descriptor(
            shell_id=shell_id,
            global_asset_id=global_asset_id,
            id_short=robot_id,
            specific_asset_ids=[robot_id],
        )
        submodel_result = self.aas.create_or_update_submodel(submodel)
        descriptor_result = self.aas.register_submodel_descriptor(
            shell_id=shell_id,
            submodel_id=submodel_id,
            semantic_id=semantic_id,
            endpoint=resolved_endpoint,
            id_short=submodel_id_short,
        )
        return {
            "shellDescriptor": shell_result,
            "submodel": submodel_result,
            "submodelDescriptor": descriptor_result,
        }

    def expose_robot_submodel_via_edc(
        self,
        *,
        robot_id: str,
        shell_id: str,
        submodel: Mapping[str, Any],
        submodel_endpoint_url: str,
        policy_id: Optional[str] = None,
    ) -> JsonDict:
        asset_id = f"urn:cx:asset:robot:{robot_id}:submodel:{submodel['idShort']}"
        semantic_id = submodel["semanticId"]["keys"][0]["value"]
        return self.publish_http_json_asset(
            asset_id=asset_id,
            endpoint_url=submodel_endpoint_url,
            policy_id=policy_id,
            contract_definition_id=f"cd-{robot_id}-{submodel['idShort']}",
            public_properties={
                "asset:prop:id": asset_id,
                "asset:prop:description": f"AAS submodel for collaborative robot {robot_id}",
                "cx-common:globalAssetId": shell_id,
                "cx-common:semanticId": semantic_id,
                "cx-common:contentType": "application/json",
            },
            private_properties={
                "robotId": robot_id,
            },
        )


def build_robot_submodel(
    telemetry: RobotTelemetry,
    *,
    semantic_id: str,
    submodel_id: Optional[str] = None,
    id_short: str = "CollaborativeRobotTelemetry",
    description: str = "Collaborative robot telemetry mapped into an AAS Submodel for Catena-X integration.",
    mappings: Optional[Sequence[AASPropertyMapping]] = None,
) -> JsonDict:
    """Create an AAS Submodel document from collaborative robot telemetry."""

    builder = AASSubmodelBuilder(semantic_id=semantic_id, mappings=mappings)
    return builder.build(
        telemetry,
        submodel_id=submodel_id,
        id_short=id_short,
        description=description,
    )


def build_robot_contract_policy(
    *,
    policy_id: str,
    purpose: str = "cx:DigitalTwin:Read",
    assignee: Optional[str] = None,
) -> ContractPolicy:
    """Construct a simple read-only ODRL policy for robot telemetry sharing."""

    constraint: JsonDict = {
        "leftOperand": "purpose",
        "operator": {"@id": "odrl:eq"},
        "rightOperand": purpose,
    }
    permission: JsonDict = {"action": "use", "constraint": [constraint]}
    if assignee:
        permission["assignee"] = assignee
    return ContractPolicy(policy_id=policy_id, permissions=[permission])


def example_robot_payload() -> RobotTelemetry:
    """Reference telemetry payload for integration testing."""

    return RobotTelemetry(
        robot_id="cobot-ur10e-01",
        workstation_id="ws-assembly-07",
        timestamp=datetime.now(tz=timezone.utc),
        status="RUNNING",
        program_id="pick-place-v2",
        cycle_count=14823,
        energy_wh=124.8,
        temperature_c=41.7,
        vibration_mm_s=1.8,
        torque_nm=37.2,
        payload_kg=3.2,
        joint_positions_deg=[-12.5, -83.1, 102.7, -110.4, 90.0, 12.8],
        additional_properties={
            "oeeState": "productive",
            "gripperState": "closed",
            "alarmCode": None,
        },
    )


__all__ = [
    "AASClient",
    "AASConfig",
    "AASPropertyMapping",
    "AASSubmodelBuilder",
    "CatenaxEDCConnector",
    "ContractDefinition",
    "ContractPolicy",
    "EDCAssetDefinition",
    "EDCConfig",
    "EDCError",
    "EDCManagementClient",
    "RobotTelemetry",
    "build_robot_contract_policy",
    "build_robot_submodel",
    "example_robot_payload",
]


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EDCError(f"Environment variable {name} is required")
    return value


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
