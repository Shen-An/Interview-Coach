# Phase 3: 独立问答多会话管理 — Plan

**Created:** 2026-09-03
**Status:** Ready for execution

## Goal

为独立问答增加持久化且隔离的本地多会话能力，并将其接入现有 SSE 流。

## Wave 1 — Backend session store and API

### Task 1.1: Add local QA conversation store
- **Files:** `backend/app.py`
- Add safe id/path helpers, JSON read/write helpers, metadata normalization and atomic writes under `DATA_DIR / "qa-conversations"`.
- Add Pydantic request models for conversation creation and `conversation_id` on QA ask.
- Add list/create/get/delete endpoints.
- Verify corrupted files are skipped and path traversal is rejected.

### Task 1.2: Bind QA SSE to a conversation
- **Files:** `backend/app.py`
- Resolve or create a conversation before retrieval and generation.
- Use stored current-session messages for context; preserve `history` fallback for old clients.
- Persist the user question before streaming, persist sanitized assistant + sources only on success.
- Add `conversation_id` to `done` and error payloads without changing existing event types.

## Wave 2 — Frontend conversation workspace

### Task 2.1: Add conversation list and switching
- **Files:** `frontend/app.js`, `frontend/index.html`, `frontend/style.css`
- Load conversations on mount, select most recently updated conversation, load messages on switch.
- Add create-new and delete-current actions, disabled during generation.
- Show empty/loading/error states and session metadata.

### Task 2.2: Update ask flow and persistence sync
- **Files:** `frontend/app.js`
- Send `conversation_id` with ask request.
- Update active id/title from SSE done, refresh list metadata after success/error.
- Keep current batched streaming rendering and copy/source behavior.

## Wave 3 — Verification and docs

### Task 3.1: Regression tests and documentation
- **Files:** `README.md`, `.env.example` only if needed
- Add fake CRUD/isolation/stream persistence checks and run existing syntax checks.
- Document storage location and multi-session behavior.

## Verification Loop

- Python: `python -m compileall -q backend`
- JavaScript: `node --check frontend/app.js`
- Formatting: `git diff --check`
- Smoke: fake LLM CRUD + two-session isolation + successful and failed QA SSE persistence.
- Regression: existing interview SSE fake smoke remains green.

---

*Phase: 03-qa-conversations*
*Plan created: 2026-09-03*
