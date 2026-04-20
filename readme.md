# Catena-X Cobot Telemetry Sample

This repository is a **stepping-stone sample**: a minimal **telemetry ingest + PostgreSQL + REST** service. The sections below describe the **intended end-state** for a production-grade, Catena-X–aligned deployment—not only what is wired today.

---

## Target architecture

In a full Catena-X data space, the **center of gravity** is **not** “open the provider database to partners”. It is **two Eclipse Dataspace Components (EDC) connectors** mediating access under **identity, policies, and contracts**.

```mermaid
flowchart TB
  subgraph identity["Identity & participation"]
    IdP["IdP / OIDC\n(e.g. Keycloak)"]
    Mem["Membership / BPN registry\n(who may join the dataspace)"]
  end

  subgraph provider["Provider organization"]
    DomP["Domain applications\n(MES / SCADA / telemetry API)"]
    DbP[(Operational datastore)]
    ConP["EDC Provider Connector"]
    DomP --> DbP
    ConP --> DomP
  end

  subgraph consumer["Consumer organization"]
    DomC["Domain applications\n(planning / analytics)"]
    ConC["EDC Consumer Connector"]
    ConC --> DomC
  end

  subgraph semantics["Semantics & digital twin (as needed)"]
    DTR["DTR / twin registry"]
    AAS["AAS repositories"]
  end

  subgraph governance["Dataspace governance"]
    Gov["Catalog, policies,\ncontract templates"]
  end

  IdP --> ConP
  IdP --> ConC
  Mem --> ConP
  Mem --> ConC

  ConP <-->|"Contract negotiation\n& controlled data plane"| ConC
  ConP -.->|"Asset & policy registration"| Gov
  ConC -.->|"Discovery & negotiation"| Gov

  ConP -.-> DTR
  ConC -.-> DTR
  ConP -.-> AAS
  ConC -.-> AAS
```

**Roles in one sentence:** each side keeps its **systems of record**; **connectors** enforce **who may access what, for which purpose**, and optional **DTR/AAS** layers align **meaning** across companies.

---

## Target end-to-end data flow (ideal)

```mermaid
flowchart LR
  Edge["Shop floor\n(robot / PLC)"] --> ApiP["Provider domain API\n(telemetry ingress)"]
  ApiP --> DbP[(Store & historize)]
  DbP --> ConP["Provider EDC"]
  ConP --> ConC["Consumer EDC"]
  ConC --> AppC["Consumer apps"]
  ApiP -.->|"Async / outbox"| Twin["AAS / aspect models\n(semantic publish)"]
  Twin --> ConP
```

**Design goals this implies**

- **Decouple** “fast ingest” from “governed share”: commit operational data first; publish/share via **EDC contracts** and optional **semantic** pipelines.
- **Never** expose raw DB credentials to partners; expose **contract-bound** interfaces (HTTP, streaming, etc.) through the connector.
- **Observability & audit**: correlate `request_id`, `event_id`, connector transfer logs, and policy decisions.

---

## Evolution: from this sample to production

| Area | Today (sample) | Target |
|------|------------------|--------|
| Share | Manual `edc.py` / `aas.py` CLI | **Automated** publish: outbox/worker, idempotent AAS updates, minimal synchronous coupling |
| Security | Open HTTP APIs | **AuthN/Z** (API keys, mTLS, OAuth2), rate limits, secret management |
| Data | Single Postgres | Migrations, retention, partitioning, backups |
| Ops | Basic health | Metrics, tracing, structured logging, SLOs |
| Semantics | Example submodel | **SAMM / aspect models** aligned with your use case |

---

## This repository today (what actually ships)

- **Runtime:** FastAPI (`server/app.py`) + `server/service.save_telemetry` (checksum, audit, duplicate handling, AAS sync queue row) + read APIs + heuristic **predictive maintenance** query.
- **Catena-X:** EDC/AAS are **optional** operator workflows (`edc.py`, `aas.py`); they are **not** invoked automatically on every HTTP request in the current code.

Operational steps (DB init, `uvicorn`, curls) are kept short in **[setup.txt](setup.txt)** and detailed in **[docs/CODE_MANUAL.md](docs/CODE_MANUAL.md)** / **[docs/OPERATIONS.md](docs/OPERATIONS.md)** (Korean). Predictive maintenance: **[docs/PREDICTIVE_MAINTENANCE.md](docs/PREDICTIVE_MAINTENANCE.md)**.

**Predictive maintenance note:** aggregates use `produced_at` within `window_hours`. Historical `produced_at` in sample JSON may fall outside the window and return empty `items`; omit `produced_at` to let the server stamp “now”.

---

## Appendix — sample codebase layout (as implemented)

For a file-level view of the **current** Python layout and DB tables, use this diagram when reading the code (not the long-term Catena-X figure above).

```mermaid
flowchart TB
  subgraph clients["Clients"]
    Edge["Robot / PLC / edge"]
    Ops["curl / tests"]
  end

  subgraph py["Python package server"]
    App["app.py"]
    Svc["service.py"]
    PM["predictive_maintenance.py"]
    Sch["schemas.py"]
    Repo["repository.py\n(legacy minimal upsert)"]
  end

  subgraph pg["PostgreSQL"]
    Raw["cobot_telemetry_raw"]
    Latest["cobot_telemetry_latest"]
    Meas["cobot_measurements"]
    Audit["cobot_access_audit"]
    SyncQ["cobot_aas_sync_status"]
  end

  subgraph opt["Optional Catena-X CLI"]
    EDCCli["edc.py"]
    AASMod["aas.py"]
  end

  Edge -->|POST| App
  Ops -->|GET| App
  App --> Sch
  App --> Svc
  App --> PM
  Svc --> Raw
  Svc --> Latest
  Svc --> Meas
  Svc --> Audit
  Svc --> SyncQ
  PM --> Meas
  EDCCli --> AASMod
```

---

## Documentation

- [CODE_MANUAL.md](docs/CODE_MANUAL.md) — modules, run order, EDC/AAS CLI
- [OPERATIONS.md](docs/OPERATIONS.md) — env vars, operations, example responses
- [PREDICTIVE_MAINTENANCE.md](docs/PREDICTIVE_MAINTENANCE.md) — inputs, outputs, diagram
