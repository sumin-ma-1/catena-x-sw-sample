from __future__ import annotations

import os
import requests


AAS_BASE_URL = os.getenv("CATENAX_AAS_BASE_URL", "http://localhost:8081/shells/cobot-01")
AAS_API_KEY = os.getenv("CATENAX_AAS_API_KEY", "")

SUBMODEL_ID = os.getenv(
    "CATENAX_AAS_SUBMODEL_ID",
    "urn:uuid:cobot-operational-data-submodel"
)


def build_submodel(payload: dict) -> dict:
    return {
        "id": SUBMODEL_ID,
        "idShort": "OperationalData",
        "kind": "Instance",
        "semanticId": {
            "type": "ExternalReference",
            "keys": [
                {
                    "type": "GlobalReference",
                    "value": "urn:example:semantic:submodel:cobot-operational-data:1.0.0"
                }
            ]
        },
        "submodelElements": [
            {
                "modelType": "Property",
                "idShort": "robotId",
                "valueType": "xs:string",
                "value": payload["robot_id"],
                "semanticId": {
                    "type": "ExternalReference",
                    "keys": [{"type": "GlobalReference", "value": "urn:example:semantic:robot-id"}]
                }
            },
            {
                "modelType": "Property",
                "idShort": "lineId",
                "valueType": "xs:string",
                "value": payload["line_id"]
            },
            {
                "modelType": "Property",
                "idShort": "stationId",
                "valueType": "xs:string",
                "value": payload["station_id"]
            },
            {
                "modelType": "Property",
                "idShort": "cycleTimeMs",
                "valueType": "xs:int",
                "value": str(payload["cycle_time_ms"])
            },
            {
                "modelType": "Property",
                "idShort": "powerWatts",
                "valueType": "xs:double",
                "value": str(payload["power_watts"])
            },
            {
                "modelType": "Property",
                "idShort": "programName",
                "valueType": "xs:string",
                "value": payload["program_name"]
            },
            {
                "modelType": "Property",
                "idShort": "status",
                "valueType": "xs:string",
                "value": payload["status"]
            }
        ]
    }


def upsert_submodel(payload: dict) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    if AAS_API_KEY:
        headers["X-Api-Key"] = AAS_API_KEY

    submodel = build_submodel(payload)
    url = f"{AAS_BASE_URL}/submodels/{SUBMODEL_ID}"
    return requests.put(url, json=submodel, headers=headers, timeout=20)