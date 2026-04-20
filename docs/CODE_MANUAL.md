# 코드 매뉴얼

## 개요

텔레메트리를 **PostgreSQL**에 넣고 **REST**로 조회합니다. HTTP 수집은 **`server.service.save_telemetry` 단일 경로**입니다. **EDC·AAS**는 선택 CLI(`edc.py`, `aas.py`)입니다.

전체 구성·데이터 흐름은 저장소 루트 [readme.md](../readme.md)의 Mermaid를 먼저 보세요.

---

## 실행 순서

### 1) DB 준비

```bash
createdb catenax
psql catenax -f sql/001_init.sql
```

### 2) 서버 실행

```bash
export DATABASE_URL="postgresql+psycopg2://catenax:catenax@localhost:5432/catenax"
uvicorn server.app:app --host 0.0.0.0 --port 8080
```

### 3) 텔레메트리 전송

```bash
curl -X POST http://localhost:8080/api/v1/cobot/telemetry \
  -H "Content-Type: application/json" \
  --data @sample_telemetry.json
```

응답에 `duplicate`가 포함됩니다. 동일 `event_id` 재전송 시 `duplicate: true`입니다.

### 4) 최신 데이터 조회

```bash
curl http://localhost:8080/api/v1/cobot/telemetry/latest
```

### 4-1) 예지보전(선택)

```bash
curl "http://localhost:8080/api/v1/cobot/predictive-maintenance?robot_id=cobot-01&window_hours=24"
```

상세는 [PREDICTIVE_MAINTENANCE.md](PREDICTIVE_MAINTENANCE.md)를 참고하세요.

### 5) 이력 조회

```bash
curl "http://localhost:8080/api/v1/cobot/telemetry?robot_id=cobot-01&limit=20"
```

### 6) EDC 자산 온보딩

```bash
export CATENAX_EDC_MANAGEMENT_URL="http://localhost:9191/management"
export CATENAX_EDC_API_KEY="your-edc-api-key"

python3 edc.py onboard \
  --asset-id cobot-01-telemetry \
  --provider-bpn BPNL000000000001 \
  --cobot-api-base-url http://localhost:8080
```

### 7) AAS 동기화

```bash
export CATENAX_AAS_BASE_URL="http://localhost:8081/shells/cobot-01"
export CATENAX_AAS_SUBMODEL_ID="urn:uuid:cobot-operational-data-submodel"
export CATENAX_AAS_API_KEY="your-aas-api-key"

python3 edc.py sync-aas --telemetry-json sample_telemetry.json
```

---

## 필수 필드

| 필드명 |
|---|
| `robot_id` |
| `line_id` |
| `station_id` |
| `cycle_time_ms` |
| `power_watts` |
| `program_name` |
| `status` |

## 선택 필드

| 필드명 |
|---|
| `good_parts` |
| `reject_parts` |
| `temperature_c` |
| `vibration_mm_s` |
| `pose` |
| `joint_positions_deg` |
| `alarms` |
| `produced_at` |

---

## 모듈 설명

| 파일 | 설명 |
|---|---|
| `server/app.py` | HTTP API 엔드포인트 정의 |
| `server/service.py` | 수집 검증·저장·감사·AAS 동기 큐(HTTP 수집의 단일 경로) |
| `server/repository.py` | 최소 upsert(스크립트/테스트용, HTTP는 `service` 사용) |
| `server/schemas.py` | Pydantic 입력 검증 |
| `server/predictive_maintenance.py` | 예지보전 집계·리스크 점수 |
| `aas.py` | AAS Submodel 빌드 및 업서트 |
| `edc.py` | EDC 자산, 정책, 계약 정의 등록 |
| `sql/001_init.sql` | DB 스키마 생성 |

## 관련 문서

- [운영 매뉴얼](OPERATIONS.md)
- [예지보전 기능 상세](PREDICTIVE_MAINTENANCE.md)
