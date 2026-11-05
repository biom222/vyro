# Technical core

Phase 0 baseline `06ba4df`, updated with Phases 1-3 implementation on 2026-11-05.
Detailed verification, risks and status labels: [PRODUCT_STATUS.md](PRODUCT_STATUS.md).
Future scope and gates: [PRODUCTION_ROADMAP.md](PRODUCTION_ROADMAP.md).
Data-safety implementation and exact verification: [PHASE1_REPORT.md](PHASE1_REPORT.md).
Media execution/preset/matrix verification: [PHASE2_REPORT.md](PHASE2_REPORT.md).
Editor interaction verification and open manual gate: [PHASE3_REPORT.md](PHASE3_REPORT.md).

## Runtime and source map

| Area | Existing implementation | Verification boundary |
| --- | --- | --- |
| Desktop lifecycle | Root `main.py`, `gui/main_window.py`, QThread workers, scheduler thread | GUI construction and offscreen editor smoke pass; shutdown during uploads and crashes remains incomplete. |
| Storage/schema | `app/models.py`, `app/database.py`, Alembic `7c1e4d2a9100` | Fresh, legacy and unversioned migration tests pass. Copies of both existing DBs match models after backed-up upgrade; originals update on next startup. |
| Managed media | `media_library.py`, `storage.py` | Atomic managed copy/relink and conservative reference-aware stale cleanup; originals and final exports retained. Full storage/performance management remains later work. |
| Video | `app/video_processor.py`, `app/media_process.py`, `app/tasks.py` | Real smoke, mixed codec/FPS/path matrix, proxy/export sampled frame/audio agreement, cancel/reap/timeout tests pass locally. Broad native/device coverage remains open. |
| Editor/project state | `project_state.py`, `projects.py`, editor widgets | Atomic versioned snapshots, conflict/recovery, project duplication; equality after new-process reopen and pre-commit crash is tested. |
| Transcription/subtitles | `transcription.py`, `subtitles.py`, `scenes.py` | Mock/real faster-whisper adapter, timed segments, SRT/VTT, subtitle burn, technical shot boundaries; real speech inference not reverified in audit. |
| AI/ideas | `ai.py`, `content_pipeline.py` | Deterministic mock, real structured-output OpenAI adapter, persisted suggestions; real AI quality unverified. |
| Trends/rights | `trends.py`, `copyright.py` | YouTube metadata/search/snapshots/score and heuristic risk labels; no semantic watching or determination of reuse rights. |
| Accounts/secrets | `accounts.py`, `credentials.py`, YouTube/social OAuth services | PKCE/state, account records and keyring references; mocked contracts pass, live completion and distributed-secret design unverified. |
| Direct publishing | `direct_publishing.py`, tasks and publish/account GUI | YouTube/TikTok/Instagram adapters exist; contracts do not establish live publication/final provider processing status. |
| Scheduler | `scheduler.py`, `scheduler_runner.py`, calendar | Persistent scheduled records and claims; uncertain-state retry, restart recovery and shutdown have known gaps. |
| Analytics | `analytics.py`, `dashboard.py`, dashboard widget | YouTube normalization/period upsert and token refresh tested with fixtures; real account sync and metric provenance UI incomplete. |
| Engineering/distribution | CLI doctor, rotating log, `build_desktop.py` | Local onedir executable exists; installer, signing, updater and clean-machine release checks are absent. |

The runtime requires no FastAPI, Redis, Celery, RQ or web frontend. Synchronous media,
OAuth, AI and most network operations are invoked from background workers. Small DB
queries/draft writes and Settings health checks still execute on the UI thread; the
latter can block and needs later hardening.

## Implemented editor boundaries

- Up to 30 ordered clips with per-clip trim, common crop/output settings, cut or dissolve
  transition selection and one background music track.
- Up to four independently timed silent video overlays with source offset, position,
  width and opacity; not a general audio/video multitrack editor.
- Up to eight timed title layers with linear x/y/opacity keyframes, plus a basic caption.
- Existing sequence/title/video-layer models drive a selectable assembly overview;
  each overlapping title/video layer has its own row. Exact edits use the existing
  tables and contextual right inspector. The overview is not a new compositing engine.
- Splitter sizes, selected inspector tab/layers and zoom persist in the existing draft's
  optional `workspace` JSON. Old drafts use defaults; no schema migration.
- Qt input filtering scopes transport/frame/mark/delete shortcuts to the visible editor,
  preserving text/spin/combo input, modal dialogs, popups and native text undo. There is
  no global project undo. FPS metadata is inspected asynchronously and cached per source;
  CFR stepping uses its frame grid, VFR stepping uses a clearly marked approximation.
- Closing explicitly detaches Qt Multimedia sinks/audio/source and removes the editor
  event filter before QApplication teardown. Other task/shutdown hardening remains later scope.
- Timed subtitle burn uses saved transcript ranges aligned to sequence offsets and
  dissolves. A complete subtitle segment editor is absent.
- Basic continuous preview follows source trims. Effect preview separately renders a
  cached 540x960 vertical proxy (or 640x360 landscape) with transitions/music/subtitles/
  titles/overlays through the existing pipeline. It is not a zero-latency compositor.
- H.264/yuv420p/AAC MP4 export with faststart, saved common/source FPS and CRF 23/18
  presets. VFR is converted to CFR; source mode uses the first clip's average rate.
  The main encoding pass reports FFmpeg output time; later effect passes report stages.
  Independent worker cancellation contexts propagate through nested FFmpeg/FFprobe calls;
  pipes are drained with bounded tails, tools terminate/kill/wait on cancel or deadline.
  Probe timeout is 30 seconds, a tool pass 30 minutes, a render operation 60 minutes.
  Cancelled exports restore the previous ready/uploaded DB state and retain older MP4s.
  Proxy/final agreement
  is sampled by smoke tests, not exhaustively established for all media and effects.

These compositing/title/keyframe/effect-proxy features are implemented; the former
document's claim that they were all absent was incorrect.

## Persistence and migration details

Projects, media, transcript segments, suggestions/ideas, accounts, posts and analytics/
trend snapshots have SQLAlchemy models. Editable draft state is stored in
`AppPreference` JSON under `editor.project.<id>.sequence`, schema version 1. It includes
sequence/music/transitions, title and video layers, editor settings, active clip, playhead
and an export-dirty flag. Phase 1 also stores the selected account and publication draft;
Post remains the actual publication operation. Project copies remap media IDs and copy
transcripts/edits while sharing immutable source files; they do not clone post jobs.

The same transaction updates draft JSON, an optimistic project revision and a checksum-
protected snapshot; the last 20 versions are retained. Close/switch refuses a failed save,
and missing/corrupt current state falls back to the latest valid snapshot. New-process
state equality and forced exit before commit are tested. Up to 400 ms of debounced,
uncommitted edits can be lost; physical storage failure remains outside that guarantee.

Alembic has the initial revision and Phase 1 repair/revision-storage migration. Legacy
adoption stamps the historical baseline then runs the repair, rather than stamping the
latest head. SQLite online backups include committed WAL data and are integrity checked.
A durable marker enables failed/interrupted migration restore, preserving replaced DB
files/sidecars under data/recovery. Physical schema parity is verified at startup.
Tests cover WAL backup, injected DDL failure and process termination during upgrades
and first creation; ambiguous orphan/duplicate data is preserved and migration refused.

## Publication boundaries

Posts store provider/account, metadata, status, external ID/URL, schedule and attempts.
New posts also pin the selected rendered media path/duration in their payload; rendering
keeps previous final exports. Legacy unpinned posts retain their compatibility fallback.
Current lowercase states include queued/scheduled/dispatching/publishing/pending/
published/error/unknown; the target production state machine is not implemented yet.

Direct adapters upload through official APIs. OAuth credentials are referenced through
keyring, with a memory store available for tests. Taisly is not imported by the desktop
publication path. YouTube currently regards a successful upload response as published;
its status helper returns that assumption without querying remote processing. Pending
polling is widget-local and does not recover after restart. Scheduler retry can requeue
an unknown remote result, so blanket duplicate-protection claims are not justified.

No provider is marked LIVE VERIFIED. The last observed Google attempt was blocked by
Testing/test-user authorization; TikTok/Instagram live credentials are not configured
in the audited local development setup. No new live provider operation was performed.

## Paths and retained compatibility

Startup uses a Qt instance lock, readable database/restore dialogs and conservative
reference-aware cleanup of old disposable artifacts; it does not delete source media.
Source data root is the checkout. Frozen data root is LOCALAPPDATA/`vyro` on Windows,
with an existing `ShortsStudio` directory deliberately retained; no move occurs. The
macOS/Linux alternatives are defined but production bundles are not verified. A local
`dist/` bundle can read checkout `.env`; distributed bundles use the data-directory
`.env`. Frozen resource paths resolve bundled Alembic assets through `_MEIPASS`.

`app/main.py` forwards to the desktop entry point for old `python -m app.main` shortcuts.
`app/templates`/`app/static`, Taisly `app/publisher.py`, its settings and the unused
YouTube-only worker are cleanup candidates. None was removed in Phase 0.

## Configuration and verification

Example defaults are `AI_PROVIDER=mock`, `TRANSCRIPTION_PROVIDER=mock` and
`TRENDS_MOCK_MODE=true`. Local editing/export do not need external API credentials.
The audited development configuration selects real faster-whisper but mock AI/general
trends. The installed module alone does not establish real inference quality.

```powershell
.\.venv\Scripts\python.exe -m app.cli doctor
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe tests/editor_smoke.py
```

Phase 0 evidence: doctor 8/8, 37 regression tests, and real editor smoke passed.
Screenshots at 1040x700 and 1380x860 were visually inspected. Clean Windows installation,
scaling matrix, live providers, speech/AI quality, crash recovery and update/signing
were not checked. See PRODUCT_STATUS for exact findings and evidence limits.
