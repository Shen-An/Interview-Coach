# Response Speed Research Notes

**Date:** 2026-09-03
**Scope:** Phase 1 — LLM 链路与耗时可观测性

## Findings

1. **Retrieval is not the dominant latency source.** Local measurement over the current knowledge base (~395 items) showed ~32ms cold load, sub-millisecond cached load, and ~0.6–0.8ms question search. Keep the cache and instrument it rather than rewriting retrieval first.
2. **The backend already streams correctly at the application boundary.** Both interview turns and standalone QA use `StreamingResponse`, `text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no`.
3. **The main interview path already has a fast profile.** It uses `fast=True`, `max_tokens=1200`, and `cache_last=True`. The next investigation should measure whether provider reasoning, prompt size, or fallback timeout dominates.
4. **Standalone QA intentionally uses a slower profile.** It uses `fast=False`, `max_tokens=5000`, and up to eight history messages. This should be preserved as a quality-oriented profile but trimmed where it adds no value.
5. **Fallback is sequential and can wait too long.** `_rotate()` tries providers in sequence, while the shared read timeout is up to 120 seconds. Phase 1 should introduce bounded first-token behavior and error classification without switching after output has started.
6. **Frontend update frequency is a separate bottleneck.** Each streamed piece currently schedules a Vue next-tick scroll. That work belongs in Phase 2, but Phase 1 should expose timestamps that distinguish backend generation from browser rendering.
7. **TTS is already incremental but can compete with generation.** Sentence-level prefetch is useful; it should remain, with cancellation and failure behavior addressed separately.

## Recommended Investigation Order

1. Add request id and phase timestamps with opt-in debug visibility.
2. Run fake-provider benchmarks for short interview turns, long QA answers, slow first token, slow inter-token gap, provider failure, and mid-stream failure.
3. Compare prompt and history sizes against complete-answer time and answer quality.
4. Tune scene-specific output caps and reasoning flags, keeping report generation unchanged.
5. Add bounded first-token / stream-idle timeout and verify fallback only before any visible output.
6. Re-run existing smoke tests and manually compare answer completeness for tool fallback, hallucination, RAG, and agent evaluation questions.

## Risks

- Lowering output caps too aggressively can truncate architecture answers.
- Passing provider-specific reasoning or cache parameters through incompatible gateways can create an extra retry and make the fast path slower.
- A short read timeout can incorrectly abort a valid long answer if it measures the whole response instead of the gap between chunks.
- Returning debug timings by default may expose user content or implementation details; keep them opt-in or aggregate-only.

## Research Status

This is a codebase-first discovery note. External provider-specific tuning should be verified against the configured provider's current API support during Phase 1 planning, because this project supports both official APIs and compatibility gateways.
