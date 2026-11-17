# Pull Request: `feat/ver_1.0.0` -> `main`

## Title

```text
feat(v1.0.0): VSICO Zalo Bot & TMS Integration — Multi-Channel Dispatch, Local NLP, Transport Assistant & Admin Dashboard
```

## Description

```markdown
## Summary
Release **v1.0.0** of **VSICO Zalo Bot & TMS Integration** (`feat/ver_1.0.0` -> `main`).

## Core Changes
- **Backend (`backend/`)**:
  - FastAPI Clean Architecture with `FIFOExtractionQueue`, Snowflake 64-bit IDs, JWT/RBAC (`users`), and Alembic migrations.
  - Deterministic rules (`domain/rules.py`: ISO 6346 check-digit, plate/phone normalization, PII masking) and upgraded local NLP pipeline (`IntentClassifier`, `MessageSegmenter`, `TripParser`, `PhoBertLocalNlpEngine`, `AIFallbackExtractor`).
  - 6-branch `PlanResolutionEngine`, `ReviewCase` approval/cancel flows with optimistic `version` locking, `ZaloOutboundThrottler`, MinIO storage, and dry-run `/api/sandbox/simulate`.
  - Role-scoped Transport Assistant (`CUSTOMER`, `CARRIER` 2-step confirmation, read-only `DHVT` with `BLOCK_WRITE`) and bidirectional `be-tms` master/plan sync.
- **AI Microservice (`ai-service/`)**:
  - Stateless FastAPI endpoints (`/extract`, `/ocr`, `/match-warehouse`, `/assistant-intent`) with `X-Internal-Token`, PaddleOCR/Gemini Vision, Qdrant matching, `PrivacyMasker`, and closed `allowed_tools` enforcement.
- **Frontend (`frontend/`)**:
  - Next.js 16 + TypeScript + Tailwind v4 dashboard (`plans`, `messages`, `results`, `reviews`, `groups`, `sandbox`, `master/*`, `admin/users`) with `httpOnly` cookie auth, RBAC middleware, OpenAPI types, TanStack Query/Table, and SSE realtime updates.
- **Zalo Bridges (`oa-bridge/`, `zca-js/`)**:
  - Zalo OA webhook gateway, token manager, GMF & `DIRECT_CHAT` support, live group sync, and ZCA-JS WebSocket/REST outbound bridge.
- **Database, Infra & Tests (`database/`, `docs/`, `backend/tests/`)**:
  - 23-table MySQL 8.4+ schema, Docker Compose (`MySQL` + `MinIO`), Postman guides (`01`–`16`), backend pytest suite (`99 passed`), and 25,000-scenario proxy evaluator (`run_proxy_25000_eval.py`).
```
