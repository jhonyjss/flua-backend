# Classroom v2 — review and release contract

This change keeps GPT Realtime and gives the backend control over lesson turns. It is OFF by default. Do not enable broadly before voice acceptance on physical devices.

## Components

- `app/services/classroom/orchestrator.py`: pure question/clarification/resume and exercise transitions. Language starts in pt-BR and changes only on intentional requests. Questions never consume attempts.
- `app/services/prompts/flua_teacher_v2.md`: versioned teacher persona, calm narrative blocks, one learner request per turn.
- `realtime_connection.py`: WebRTC SDP proxy + server-side control WebSocket. Semantic VAD, manual response creation, interruptions, silent tool classification before speech, playback acknowledgements, bounded idle lifetime, cancel-on-new-generation, safe usage logs.
- `repository.py` + migration in Flue.AI: owner-scoped durable snapshots/events, CAS, replay keys, lease fencing, one connection per account and server-clock usage against the existing per-lesson budget.
- Generated catalog snapshots: mobile content `0.2.0`, English web `web-2026-11-05`. Spanish and other legacy modes remain on their existing path. Regenerate catalogs with their client changes; never accept a plan or prompt from the browser.
- Mobile and web reuse their existing WebRTC transport. The new branch does not send local `response.create`, evaluation tools or system directions. Both currently read snapshots once per second; the backend also offers SSE with cursor replay.

## API

Bearer authentication required; session ownership checked on every request.

- POST `/api/classroom/sessions`: `{sessionId,lessonId,contentVersion}` → 201 snapshot.
- POST `/sessions/{id}/connection`: `{connectionAttemptId,sdpOffer}` → 201 `{connectionId,sdpAnswer}`. One connection per account. A failed/uncertain attempt must wait for the 30s lease or close the existing call; it cannot create duplicates.
- GET `/sessions/{id}` → 200 snapshot. Reconciles a completed lesson's idempotent progress result if a crash interrupted finalization.
- POST `/sessions/{id}/commands`: `{commandId,expectedVersion,type,text?,language?,scope?}` → 202 persisted state/version. Types: ready, pause, resume, stop, disconnect, interrupt, set_language, text_turn. Commands are serialized in each client; version conflicts refresh/retry at most twice.
- GET `/sessions/{id}/events?after=N` → SSE. Bounded 120s connections require reauthentication; reconnect using the last sequence.

401 authentication; 403 entitlement/time; 404 disabled/unknown/foreign session; 409 concurrent state/connection; 410 closed session; 422 invalid input; 429 rate limit; 502/503/504 infrastructure. Provider errors never expose the API key. The audio response is asynchronous: 202 is not proof of playback.

## Validation

Backend: `python -m pytest`, `python -m ruff check app tests` (new files may be checked separately if unrelated baseline warnings exist).

Real Postgres: install psycopg and set `CLASSROOM_TEST_DSN` to a disposable database whose name ends in `_test`, and `CLASSROOM_MIGRATION_PATH` to the web repository's `supabase/migrations/20261105_classroom_v2.sql`; run `pytest tests/test_classroom_postgres.py`. This test creates the minimal auth/budget dependencies and replaces ONLY classroom tables in that dedicated database.

Mobile: `bun run typecheck`, `bun run lint`, `bun run test --runInBand`.
Web: `pnpm build`, `pnpm test`.

A live OpenAI smoke test accepted the configuration and classified synthetic English repetition, Portuguese question and intentional English preference. Earlier probes timed out or returned malformed tool arguments: Pydantic rejects invalid decisions, and the runtime uses low reasoning effort, a text-only classification token ceiling and response watchdog. This is NOT a real microphone/latency benchmark.

## Release order

1. Review the three PRs together; deploy the additive SQL migration first in staging, then backend with `CLASSROOM_V2_ENABLED=false`.
2. Set `CLASSROOM_V2_ENABLED=true` and `CLASSROOM_V2_USERS` to internal account UUIDs. Keep production clients off.
3. Build internal mobile with `EXPO_PUBLIC_CLASSROOM_V2=true`; web preview with `NUXT_PUBLIC_CLASSROOM_V2=true`. Client flags select the new path; no silent fallback from an interrupted v2 session to the legacy machine.
4. Test physical iPhone/Android and browser, headphones AND speaker: interruptions, echo, bilingual speech, 20s silence, question followups, pause/background, reconnect, downgrade/upgrade and final progress. Check the complete closing audio and XP before marking voice acceptance.
5. Measure end-of-speech to first audible response, classification latency, interruption delay, question/resume success, errors and cost per active minute. Goals from the design are targets, not measured results.
6. Only then approve merge/publication and expand the account allowlist. Removing the backend enable flag prevents new connections; existing calls keep their pinned controller. Disable client flags for rollback on subsequent sessions. Do not drop state tables.

## Remaining release checks / limitations

- Full WebRTC + server-side-control + real microphone has not yet been validated on a physical device. Speaker echo with an open microphone is a release blocker until measured.
- Mobile and web end-to-end progression must be tested against a staging Supabase instance with its existing progress functions, not just the isolated SQL concurrency fixture. The app progress RPC is idempotent; reconciliation after a crash retries the same session id.
- No latency or dollar-per-minute guarantee is established. Polling and the extra classification pass add work; measure before broad activation. Logs contain usage counts, model, prompt revision and elapsed time; dashboards/alerts must be connected to the deployment's log sink.
- The new connection lease governs v2 sessions; legacy sessions still use their existing budget heartbeat. Mixed-version concurrency across legacy/v2 needs a rollout audit before broad activation.
- Events include short question summaries and state. Before production activation, configure retention: delete event history older than 7 days and inactive sessions older than 30 days, after reviewing the learning-record retention policy. Never put audio, complete transcripts, SDP, or credentials in ordinary logs.
- `gpt-realtime-2.1-mini` is a configurable starting model, not a promise of ChatGPT Voice parity.
