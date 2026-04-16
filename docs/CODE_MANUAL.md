# 코드 매뉴얼

## 개요

이 프로젝트는 협동로봇 텔레메트리를 수집해 아래 흐름으로 처리하는 예제입니다.

1. 내부 DB에 저장
2. 최신 상태 조회 API 제공
3. Catena-X EDC 자산으로 노출
4. AAS Submodel로 동기화

핵심 관점은 다음과 같습니다.

- **Catena-X**: EDC 기반의 데이터 주권 보장형 공유
- **AAS**: 디지털 트윈 의미 구조 표준화

Tractus-X 문서에서도 `DTR/AAS/EDC` 조합을 기본 패턴으로 설명합니다.

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

### 4) 최신 데이터 조회

```bash
curl http://localhost:8080/api/v1/cobot/telemetry/latest
```

### 5) EDC 자산 온보딩

```bash
export CATENAX_EDC_MANAGEMENT_URL="http://localhost:9191/management"
export CATENAX_EDC_API_KEY="your-edc-api-key"

python3 edc.py onboard \
  --asset-id cobot-01-telemetry \
  --provider-bpn BPNL000000000001 \
  --cobot-api-base-url http://localhost:8080
```

### 6) AAS 동기화

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
| `server/repository.py` | DB 저장/조회 로직 |
| `server/schemas.py` | Pydantic 입력 검증 |
| `aas.py` | AAS Submodel 빌드 및 업서트 |
| `edc.py` | EDC 자산, 정책, 계약 정의 등록 |
| `sql/001_init.sql` | DB 스키마 생성 |
