# Catena-X Cobot Telemetry Sample - 운영 매뉴얼

## 1. 목적

이 문서는 협동로봇 텔레메트리 수집 서버, PostgreSQL 저장소, AAS 동기화, EDC 자산 온보딩 예제의 운영 절차를 설명합니다.

목표 아키텍처·요약은 저장소 루트 [readme.md](../readme.md) (영문, Catena-X north star)를 참고하세요.

구성 요소:

- Telemetry API Server (`server/app.py`, 수집은 `server/service.py`)
- PostgreSQL DB
- 예지보전 조회 API (`GET /api/v1/cobot/predictive-maintenance`)
- AAS Sync Client (`aas.py`)
- EDC Onboarding CLI (`edc.py`)

---

## 2. 시스템 구성

```text
[Cobot / PLC / Edge]
        |
        v
POST /api/v1/cobot/telemetry
        |
        v
[FastAPI: server.app]
        |
        v
[service.save_telemetry]
   ├─ raw 저장 (+ checksum)
   ├─ latest upsert (신규 event일 때만)
   ├─ measurements (신규 event일 때만)
   ├─ audit 기록 (항상)
   └─ aas_sync_status = PENDING (신규 event일 때만)
        |
        +--> [AAS Server] sync  (edc.py sync-aas / aas.py)
        |
        +--> [EDC] asset / policy / contract definition  (edc.py onboard)
```

## 3. 환경 변수

### 3.1 API 서버

```bash
export DATABASE_URL="postgresql+psycopg2://catenax:catenax@localhost:5432/catenax"
```

### 3.2 EDC

```bash
export CATENAX_EDC_MANAGEMENT_URL="http://localhost:9191/management"
export CATENAX_EDC_API_KEY="your-edc-api-key"
```

### 3.3 AAS

```bash
export CATENAX_AAS_BASE_URL="http://localhost:8081/shells/cobot-01"
export CATENAX_AAS_SUBMODEL_ID="urn:uuid:cobot-operational-data-submodel"
export CATENAX_AAS_API_KEY="your-aas-api-key"
```

## 4. 기동 절차

### 4.1 PostgreSQL 준비

DB 및 스키마 생성:

```bash
createdb catenax
psql catenax -f sql/001_init.sql
```

### 4.2 API 서버 실행

```bash
uvicorn server.app:app --host 0.0.0.0 --port 8080
```

### 4.3 상태 확인

```bash
curl http://localhost:8080/health
```

정상 응답 예시:

```json
{"status":"ok"}
```

## 5. 운영 기본 절차

### 5.1 텔레메트리 수신 확인

```bash
curl -X POST http://localhost:8080/api/v1/cobot/telemetry \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: test-001" \
  --data @sample_telemetry.json
```

정상 응답 예시:

```json
{
  "accepted": true,
  "event_id": "2a0d0c76-31d0-487d-9bf8-a1a55f8c66cd",
  "duplicate": false
}
```

### 5.2 최신값 확인

```bash
curl http://localhost:8080/api/v1/cobot/telemetry/latest
```

특정 로봇만 조회:

```bash
curl "http://localhost:8080/api/v1/cobot/telemetry/latest?robot_id=cobot-01"
```

### 5.3 이력 조회

```bash
curl "http://localhost:8080/api/v1/cobot/telemetry?limit=20"
```

특정 로봇:

```bash
curl "http://localhost:8080/api/v1/cobot/telemetry?robot_id=cobot-01&limit=50"
```

### 5.4 예지보전 조회

최근 `window_hours` 동안의 `cobot_measurements`를 집계합니다. (`produced_at` 기준 — 과거 시각만 있는 샘플은 빈 결과가 될 수 있음)

```bash
curl "http://localhost:8080/api/v1/cobot/predictive-maintenance?robot_id=cobot-01&window_hours=24"
```

상세는 [PREDICTIVE_MAINTENANCE.md](PREDICTIVE_MAINTENANCE.md)를 참고하세요.

## 6. EDC 운영 절차

### 6.1 자산 온보딩

```bash
python3 edc.py onboard \
  --asset-id cobot-01-telemetry \
  --provider-bpn BPNL000000000001 \
  --cobot-api-base-url http://localhost:8080
```

### 6.2 확인 항목

온보딩 후 아래를 확인합니다.

- asset 생성 여부
- access policy 생성 여부
- contract policy 생성 여부
- contract definition 생성 여부

### 6.3 운영 시 주의점

- `asset-id`는 환경별로 고유해야 합니다.
- `provider-bpn`은 운영 조직 BPN과 일치해야 합니다.
- EDC API Key는 서버 로그에 출력하지 않습니다.
- contract policy는 목적 제한, 파트너 제한, 기간 제한 등으로 확장 가능합니다.

## 7. AAS 운영 절차

### 7.1 단건 동기화

```bash
python3 edc.py sync-aas --telemetry-json sample_telemetry.json
```

### 7.2 확인 항목

- AAS 서버에서 Submodel upsert 성공 여부
- `cobot_aas_sync_status` 상태 확인
- 실패 시 `last_error` 확인

예시 SQL:

```sql
SELECT event_id, robot_id, sync_status, retry_count, last_error, synced_at
FROM cobot_aas_sync_status
ORDER BY updated_at DESC
LIMIT 20;
```

### 7.3 실패 처리 원칙

- 외부 AAS 응답 실패는 `FAILED`
- 네트워크 타임아웃은 `FAILED`
- 재시도 시 `retry_count` 증가
- 성공 시 `SUCCESS`, `last_error = NULL`

## 8. DB 운영

### 8.1 주요 테이블

#### `cobot_telemetry_raw`

원본 이벤트 저장

#### `cobot_telemetry_latest`

로봇별 최신 상태

#### `cobot_measurements`

분석/조회용 정규화 테이블

#### `cobot_aas_sync_status`

AAS 반영 상태

#### `cobot_access_audit`

감사 로그

### 8.2 운영 SQL 예시

최근 수신 데이터:

```sql
SELECT event_id, robot_id, produced_at, received_at
FROM cobot_telemetry_raw
ORDER BY received_at DESC
LIMIT 20;
```

로봇별 최신 상태:

```sql
SELECT robot_id, produced_at, updated_at
FROM cobot_telemetry_latest
ORDER BY updated_at DESC;
```

AAS 실패 건 조회:

```sql
SELECT event_id, robot_id, retry_count, last_error, updated_at
FROM cobot_aas_sync_status
WHERE sync_status = 'FAILED'
ORDER BY updated_at DESC;
```

감사 로그 조회:

```sql
SELECT event_time, actor_type, action, target_resource, result, correlation_id
FROM cobot_access_audit
ORDER BY event_time DESC
LIMIT 100;
```

## 9. 장애 대응

### 9.1 증상: POST 요청이 500 반환

점검 순서:

- API 서버 프로세스 정상 여부 확인
- PostgreSQL 접속 가능 여부 확인
- DB 스키마 적용 여부 확인
- 입력 JSON 필수 필드 누락 여부 확인
- 서버 로그의 `ValidationError` / DB 예외 확인

빠른 점검 명령:

```bash
curl http://localhost:8080/health
psql "$DATABASE_URL" -c "SELECT NOW();"
```

### 9.2 증상: latest 조회는 되는데 AAS 반영이 안 됨

점검 순서:

- `cobot_aas_sync_status`에서 `FAILED` 여부 확인
- `CATENAX_AAS_BASE_URL` 확인
- AAS API Key 확인
- AAS 서버의 Submodel endpoint 지원 여부 확인
- payload 필드 매핑 누락 여부 확인

### 9.3 증상: EDC 온보딩 실패

점검 순서:

- `CATENAX_EDC_MANAGEMENT_URL` 확인
- EDC Management API 접근 가능 여부 확인
- API Key 확인
- `asset-id` 중복 여부 확인
- payload 포맷이 해당 EDC 버전과 맞는지 확인

## 10. 보안 운영 기준

### 10.1 권장 사항

- API Key는 환경 변수 또는 Secret Manager로만 주입
- DB 계정 권한 최소화
- 운영/개발 DB 분리
- 감사 로그는 삭제보다 보존 우선
- 외부 연계 호출에 타임아웃 설정
- Request ID를 전 구간에 전달

### 10.2 권장 추가 기능

- JWT 또는 mTLS 기반 클라이언트 인증
- 파트너/BPN 기준 접근 제어
- Row-Level Security
- 데이터 보존주기 정책
- 백업 및 복구 리허설
- OpenTelemetry 기반 추적

## 11. 백업 및 복구

### 11.1 논리 백업 예시

```bash
pg_dump catenax > catenax_backup.sql
```

### 11.2 복구 예시

```bash
createdb catenax_restore
psql catenax_restore < catenax_backup.sql
```

### 11.3 권장 정책

- 일일 백업
- 주간 복구 테스트
- 월 단위 장기 보관
- 장애 대응 문서 별도 유지

## 12. 로그 운영

서버 로그에는 아래 정보를 포함하는 것이 좋습니다.

- `timestamp`
- `level`
- `request_id`
- `robot_id`
- `event_id`
- `action`
- `result`
- `error`

로그 예시:

```json
{
  "timestamp": "2026-04-16T09:10:00Z",
  "level": "INFO",
  "request_id": "test-001",
  "action": "ingest_telemetry",
  "robot_id": "cobot-01",
  "event_id": "2a0d0c76-31d0-487d-9bf8-a1a55f8c66cd",
  "result": "success"
}
```

## 13. 운영 체크리스트

### 일일 점검

- `/health` 정상 응답
- 최근 1시간 수신 건수 확인
- AAS 실패 건수 확인
- 감사 로그 이상 여부 확인

### 주간 점검

- DB 용량 증가 추이
- 인덱스/쿼리 성능
- 백업 성공 여부
- API Key 교체 필요 여부
- EDC/AAS 연결 상태 점검

### 월간 점검

- 보존 정책 실행 여부
- 장애 복구 훈련
- contract policy 검토
- schema version 변경 영향 분석

## 14. 향후 확장 권장안

- 비동기 AAS 재시도 워커
- Kafka 또는 메시지 큐 연계
- 월별 파티셔닝
- 대시보드(Grafana)
- 이상치 탐지 룰
- SLA/알람 시스템
- 멀티 공장/멀티 BPN 지원
