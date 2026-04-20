# Catena-X Cobot Telemetry Sample

협동로봇 텔레메트리를 **PostgreSQL**에 저장하고, **REST API**로 조회·예지보전 집계를 제공하는 예제입니다. **EDC / AAS** 연동은 선택(별도 CLI·서비스 필요)입니다.

## 전체 구성 (코드·모듈)

```mermaid
flowchart TB
  subgraph clients["클라이언트"]
    Edge["로봇 / PLC / Edge"]
    Ops["운영·테스트 curl"]
  end

  subgraph server["Python 패키지 server"]
    App["app.py\nHTTP 라우트"]
    Svc["service.py\n수집·검증·감사·AAS 큐"]
    PM["predictive_maintenance.py\n집계·리스크 점수"]
    Sch["schemas.py\n입력 검증"]
    Repo["repository.py\n최소 upsert\n(HTTP 비사용)"]
  end

  subgraph pg["PostgreSQL"]
    Raw["cobot_telemetry_raw"]
    Latest["cobot_telemetry_latest"]
    Meas["cobot_measurements"]
    Audit["cobot_access_audit"]
    SyncQ["cobot_aas_sync_status"]
  end

  subgraph opt["선택: Catena-X"]
    EDCCli["edc.py"]
    AASMod["aas.py"]
    EDC["EDC"]
    AAS["AAS 서버"]
  end

  Edge -->|POST /telemetry| App
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
  EDCCli --> EDC
  EDCCli --> AASMod
  AASMod --> AAS
```

## 데이터 워크플로

```mermaid
flowchart TD
  A["① POST /api/v1/cobot/telemetry\nJSON 바디"] --> B["② Pydantic 검증\nschemas.TelemetryIn"]
  B --> C["③ service.save_telemetry\n비즈니스 검증"]
  C --> D{"event_id\n신규?"}
  D -->|예| E["raw INSERT\nchecksum 포함"]
  E --> F["latest UPSERT\n시간 비교"]
  E --> G["measurements INSERT"]
  E --> H["aas_sync_status PENDING"]
  D -->|아니오 중복| I["latest / measurements\n스킵"]
  C --> J["항상 audit INSERT"]
  E --> K["④ 커밋\nget_db"]
  I --> K
  J --> K

  K --> L["⑤ GET /api/v1/cobot/telemetry/latest\nGET /api/v1/cobot/telemetry"]
  L --> M["DB에서 조회\nget_db_read"]

  K --> N["⑥ GET /api/v1/cobot/predictive-maintenance"]
  N --> O["최근 window_hours\nproduced_at 기준\nmeasurements 집계"]
  O --> P["risk_score / risk_level\nJSON 응답"]
```

**예지보전 주의:** 집계는 `produced_at`이 **현재 시각 기준 `window_hours` 이내**인 행만 포함합니다. 샘플 JSON에 과거 시각만 넣으면 DB에는 있어도 최근 창에서는 **빈 결과**가 나올 수 있습니다. (`produced_at` 생략 시 서버가 현재 시각을 채움)

---

## 빠른 실행 (로컬)

| 단계 | 할 일 |
|------|--------|
| 1 | Python 3.10+, PostgreSQL 준비 |
| 2 | `pip install -r requirements.txt` (저장소 루트) |
| 3 | DB·스키마: `createdb catenax` 후 `psql … -f sql/001_init.sql` |
| 4 | `DATABASE_URL` 설정(미설정 시 `server/db.py` 기본값 사용) |
| 5 | `uvicorn server.app:app --host 0.0.0.0 --port 8080` |

PowerShell 예시:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://catenax:catenax@localhost:5432/catenax"
uvicorn server.app:app --host 0.0.0.0 --port 8080
```

`psql`이 PATH에 없으면 PostgreSQL 설치 경로의 `psql.exe` 전체 경로를 사용합니다. 자세한 단계는 [setup.txt](setup.txt)를 참고하세요.

---

## 실행 후 과정·결과 (요약)

1. **헬스** `GET /health` → `{"status":"ok"}` 이면 API 기동 완료.
2. **수집** `POST /api/v1/cobot/telemetry` + JSON  
   - **과정:** 검증 → `save_telemetry` → (신규 `event_id`일 때만) raw / latest / measurements / AAS 대기행, 항상 감사 로그.  
   - **결과:** `{"accepted": true, "event_id": "…", "duplicate": false}` — 동일 `event_id` 재전송 시 `"duplicate": true`이고 측정·최신 테이블은 다시 쓰지 않음.  
   - 검증 실패 시 **HTTP 400** (`detail` 메시지).
3. **최신** `GET /api/v1/cobot/telemetry/latest` (선택 `?robot_id=`) → 최신 payload 등. 단일 로봇 없으면 **404**.
4. **이력** `GET /api/v1/cobot/telemetry?limit=20` → raw 이력 목록.
5. **예지보전** `GET /api/v1/cobot/predictive-maintenance?window_hours=24&robot_id=…` → 최근 구간 집계·`risk_score` 등. 상세·예시는 [docs/PREDICTIVE_MAINTENANCE.md](docs/PREDICTIVE_MAINTENANCE.md).

**선택:** EDC 온보딩·AAS 동기는 [docs/CODE_MANUAL.md](docs/CODE_MANUAL.md)의 `edc.py` / `aas.py` 절차를 따릅니다.

---

## 문서

- [코드 매뉴얼](docs/CODE_MANUAL.md) — 모듈·실행 순서·EDC/AAS
- [운영 매뉴얼](docs/OPERATIONS.md) — 환경 변수·운영 절차·응답 예시
- [예지보전](docs/PREDICTIVE_MAINTENANCE.md) — 입력·출력·Mermaid
