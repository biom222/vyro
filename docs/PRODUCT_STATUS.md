# Product status and Phase 0 baseline

## Current update: Phase 3

Phase 3 implements a contextual inspector, independently resizable/saved editor areas,
an assembly overview with separate title/overlay rows, persistent visible export status,
millisecond timecode, source-rate frame stepping and guarded keyboard editing.
60 regression tests and the real editor smoke pass; an additional Qt UI check passes
all nine size/scale combinations, 8-title/4-overlay display, selection, shortcuts,
layout reopen and process exit. A Qt Multimedia teardown fault found during testing
was corrected by detaching player resources before application destruction.
Native Windows accessibility was inspected, but complete interactive/manual acceptance
remains OPEN: capture timed out and computer-use subsequently reported Escape stop.
See [PHASE3_REPORT.md](PHASE3_REPORT.md) for evidence and limits.

Phase 1 implementation and verification are recorded in [PHASE1_REPORT.md](PHASE1_REPORT.md).
Current code adds transactional versioned drafts, recovery, project duplication/Save As,
SQLite online backups and interrupted-migration recovery, physical schema validation,
safe disposable cleanup, a single-instance guard and pinned media for new posts.
Phase 2 added bounded/cancellable FFmpeg execution, saved FPS/quality presets, readable
media errors, short-audio padding and proportional proxy text. See [PHASE2_REPORT.md](PHASE2_REPORT.md).
The full suite now has 60 passing tests; the expanded real editor smoke and real-file
media matrix pass. The matrix includes 295-character Unicode/apostrophe Windows paths,
VFR, software HEVC, odd dimensions, 30 mixed clips in final export and a 600-second
30-clip proxy. Sampled proxy/export frame errors are below 2.3/255, with identical
decoded audio in the tested fixture. These are local synthetic checks, not a full
native playback/device/performance release gate.
The following Phase 0 inventory and A01-A17 findings remain the historical baseline;
they are not all unresolved current claims. Resolution:

| Findings | Phases 1-2 outcome |
| --- | --- |
| A01-A03 | Migration `7c1e4d2a9100` repairs schema drift; online backups/restore and interrupted upgrade tests pass. Transactional snapshots, conflict checks and failed-save close prevention are implemented. Verified on read-only copies of both existing DBs; originals upgrade on next startup. |
| A07 | New posts pin export path/duration; old exports are retained. Legacy unpinned posts still need Phase 8 handling. |
| A08 | Old-export deletion removed; conservative stale artifact cleanup added. Phase 2 adds FFmpeg cancel/timeouts/reaping and partial-output cleanup. Broader task lifecycle remains Phase 13. |
| A13 | Publishing draft/account is part of project snapshots; duplicate and Save As now exist with independent edits/shared immutable media. |
| A17 | The checkout-env test now makes its own fixture. No production CI/clean-machine release claim is made. |

Remaining A04-A06/A09-A12/A14-A16 are not fixed by these phases. Live providers still
have no LIVE VERIFIED status. See the Phase 1 report for the autosave window, shared
media, backup/recovery and untouched live-DB limitations.

Audit date: 2026-11-05 (Europe/Moscow). Source baseline: `06ba4df` on `main`.
Phase 0 changes are documentation only. No provider fixes, redesign, schema changes,
legacy deletion, or production release are included in this audit.

## Verdict and status vocabulary

vyro is a working local desktop editor with a real FFmpeg export path. It is not a
production-ready release. Provider adapters and contract tests do not establish live
publication, account analytics, crash recovery, or installer readiness.

| Status | Meaning in this document |
| --- | --- |
| IMPLEMENTED | Code exists and the stated local behavior has relevant verification. This is not a blanket production guarantee. |
| IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | A real adapter exists; only local/contract tests establish its behavior so far. |
| PARTIAL | Some required behavior exists, but material requirements or verification are missing. |
| MOCK_ONLY | The named demonstration/test path returns synthetic results. A separate real adapter may also exist. |
| NOT_IMPLEMENTED | No implementation of the named requirement was found. |
| BLOCKED_BY_EXTERNAL_PROVIDER | A known external authorization/approval condition prevents the stated live scenario. |

`LIVE VERIFIED` is reserved for an observed real provider operation. None of the
three publishing integrations currently has that evidence. `BLOCKED_BY_EXTERNAL_CREDENTIALS`
may be recorded as a live-test gate; it does not mean the adapter is absent.

## Phase 0 capability inventory (historical)

| Capability | Status | Evidence and boundary |
| --- | --- | --- |
| Desktop entry point, eight workspaces, flat themes | IMPLEMENTED | `main.py`, `gui/main_window.py`, `gui/theme.py`; GUI construction and screenshot inspection. |
| Video import and metadata | IMPLEMENTED | `ProbeWorker`, managed copy, FFprobe; real smoke import plus service tests. Configured defaults are 500 MiB and 600 seconds. |
| Managed video/music and relink | IMPLEMENTED | `app/services/media_library.py`; copy uses `.part`, fsync, replace; relink validates duration/resolution and invalidates export. Relink probing is mocked in its unit test. |
| Trim and manually positioned 9:16 crop | IMPLEMENTED | Real smoke verifies trim drag, crop position, a three-second 1080x1920 result. |
| Ordered sequence and music | IMPLEMENTED | Up to 30 clips; global cut/dissolve and one music track; real two-clip export/reopen smoke. Per-boundary transition editing and general audio multitrack are absent. |
| Video overlays | IMPLEMENTED | Up to four independently timed silent overlays with size, position, opacity and source offset; smoke verifies persistence and a sample proxy pixel. |
| Animated title layers | IMPLEMENTED | Up to eight titles; linear x/y/opacity keyframes; real title-motion check and project reopen smoke. |
| Basic and effect preview | IMPLEMENTED | Qt decoded frames, FFmpeg paused-frame fallback, and rendered low-resolution effect proxy. Full pixel/audio equivalence with export is not established. |
| MP4 export | IMPLEMENTED | FFmpeg H.264/yuv420p/AAC/faststart; real generated media exports. The full codec/FPS/VFR/path/long-project matrix is not covered. |
| Render cancellation/timeouts | NOT_IMPLEMENTED | Render workers have no cancellation contract; common FFmpeg/probe calls lack a timeout. Progress is stage based. |
| Draft save, autosave, reopen | PARTIAL | One JSON draft transaction, 400 ms debounce, selected clip/playhead/layers/edit settings. Tested reopen is in the same process; crash/relaunch state equality is absent. |
| Project recovery, duplicate, Save As Project | NOT_IMPLEMENTED | No recovery journal/version history or project duplication/Save As service found. MP4 Save As is a different feature. |
| Timed subtitles | PARTIAL | Timed transcript segments, SRT/VTT services and burn aligned to sequence trims are tested. No complete subtitle segment editing UI. |
| Real local speech recognition | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | Lazy faster-whisper model, segment timestamps/progress/cancellation callback; installed here, but no new real-speech inference in Phase 0. |
| Mock transcript/content pack | MOCK_ONLY | Deterministic providers for tests/development; these results do not demonstrate speech recognition or AI quality. |
| OpenAI content assistant | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | Structured-output adapter and contract test; default local AI mode is mock; no real API call in this audit. |
| Clip suggestions and scene cuts | PARTIAL | Transcript/content-pack ranges and local FFmpeg shot boundaries exist. Scene selection/quality is not semantically validated. |
| Metadata trends | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | YouTube popular feed, topic search, snapshots/scoring and mocked HTTP tests; current local general feed uses mock mode. |
| Mock trend feed | MOCK_ONLY | Synthetic fixture is explicitly selected by `TRENDS_MOCK_MODE`. |
| Semantic film/series trend understanding | NOT_IMPLEMENTED | No cross-platform viewing/understanding of third-party footage, face tracking or smart reframing. Metadata results do not establish reuse rights. |
| Account selection and OAuth services | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | Service submenus/check mark, state/PKCE and keyring references; contract tests. Native/client-secret distribution review remains open. |
| Latest observed Google sign-in attempt | BLOCKED_BY_EXTERNAL_PROVIDER | Last user-supplied evidence was Google Testing/test-user `403 access_denied` (September 2026). It was not repeated in this audit. |
| YouTube upload/final status | PARTIAL | Direct resumable upload adapter exists, contract tested. It marks upload response as published and its status helper does not query YouTube processing state. No upload progress or live E2E proof. |
| TikTok publication | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | OAuth/refresh, creator privacy, chunk upload and status contracts; no local credentials/live account verification. |
| Instagram publication | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | Facebook-linked account discovery, resumable container upload and publish contracts; no local credentials/live verification. Capability diagnosis and token lifecycle need work. |
| Publication/scheduler reliability | PARTIAL | Database scheduling, claims, bounded retry intent and isolation tests exist. Unknown-state retry and restart recovery have important gaps (below). |
| Account analytics | IMPLEMENTED_BUT_NOT_LIVE_VERIFIED | YouTube normalization, OAuth refresh and period upsert tested with fixtures. No connected local accounts or real sync proof. TikTok/Instagram analytics absent. |
| Dashboard presentation | PARTIAL | Real stored snapshots feed metrics. Missing data becomes zero rather than a clear unavailable state; provider/period/last-sync labels are incomplete. |
| Settings, logs, diagnostics | PARTIAL | Environment config, health table and rotating logs exist; normal user configuration still depends on `.env`; no global secret-redaction layer or diagnostic archive. |
| Windows distribution | PARTIAL | PyInstaller onedir builder and local executable exist; last build 2026-09-29. No installer/signing/clean-machine release proof; FFmpeg remains external. |
| Update system | NOT_IMPLEMENTED | Source version `0.2.0` exists, but no update check, release feed or package integrity workflow. |

## Phase 0 verification record

Environment: Windows 10 x64 build 19045, Python 3.13.1, PyQt6 6.11.0,
SQLAlchemy 2.0.52, Alembic 1.20.0, httpx 0.28.1; FFmpeg/FFprobe
`9.0.2-essentials_build-www.gyan.dev` as reported by this machine.

| Check | Result | What it actually establishes |
| --- | --- | --- |
| `python -m unittest discover -s tests -q` | PASS: 37 tests | Service contracts, isolated fresh migrations, GUI construction, mocked provider/OAuth requests and scheduler behavior. No live network by default. |
| `python tests/editor_smoke.py` | PASS | Real generated H.264 + AAC/silent media, Qt decoded frames, seek/trim/crop/text, draft reopen, managed music/video, cut/dissolve exports, titles/keyframes, video overlay and effect proxy. |
| `python -m app.cli doctor` | PASS: 8 checks | FFmpeg, FFprobe, installed faster-whisper module, DB connection and four storage folders. It does not run inference or provider authorization. |
| Source and existing bundled DB `PRAGMA integrity_check` | `ok` | Read-only SQLite structural check; not a crash-recovery or backup restore test. |
| Current/head revision | Both `beb1f4933f58` | One baseline migration exists. Revision equality alone does not prove schema equivalence. |
| Fresh migration vs ORM metadata | No differences | A new isolated database made from Alembic matches current models. |
| Existing source DB vs ORM metadata | Differences found | Legacy adoption left missing constraints/indexes/FKs and nullable differences; see A01. |
| Manual visual inspection | Performed | Viewed `editor-small.png` (1040x700) and `sequence-dark.png` (1380x860) produced by smoke; top menus, preview, inspector, timeline and primary export control visible. |

Restricted Windows execution initially failed before tests/rendering could write inside
temporary directories (`PermissionError`). The full suite and smoke passed when run
outside that sandbox restriction. This is recorded as a verification-environment issue,
not silently converted into an application test failure or a code fix.

Smoke artifacts are generated under ignored `work/editor-check/`. They include images,
test clips, proxy and exports; they are not committed user media. The automated smoke
is an offscreen GUI exercise, not a human-operated native desktop session. Visual
inspection of its images is the manual part performed in Phase 0.

Not verified: Windows 11/clean VM install; 1920x1080 and 125%/150% scaling; subjective
audio listening; exported MP4 in an external player; broad codec/path/VFR matrix;
forced crash/save/migration recovery; render/upload cancellation; real speech/AI/trends;
live OAuth/upload/analytics; provider approvals; macOS/Linux bundles; Docker check;
full-history secret scan and real signing/update infrastructure.

## Phase 0 audit findings and phase ownership

These findings are intentionally not fixed in Phase 0. They are not covered by the
passing suite unless the verification column explicitly says otherwise.

| ID | Finding and evidence | Priority / owner |
| --- | --- | --- |
| A01 | `prepare_legacy_schema()` adds columns and stamps head without bringing all constraints/indexes/FKs to baseline parity. Existing source DB lacks the analytics period unique constraint, several FKs/indexes and NOT NULL parity. Fresh baseline has no drift. | High, Phase 1; add a proper tested Alembic repair path after backup. |
| A02 | Draft JSON is transactional, but `save_project()` does not return failure to `MainWindow.closeEvent()`. Close proceeds after a failed silent save. No forced-crash/relaunch recovery test exists; `dirty` describes export staleness rather than a complete unsaved-state model. | High, Phase 1. |
| A03 | Backup uses `shutil.copy2` on a SQLite file. Consistency under concurrent writes/WAL and interrupted migration restore are unverified. Legacy adoption is custom DDL followed by stamp. | High, Phase 1. |
| A04 | `publish_video()` marks a `PublicationUncertain` post `unknown`, then `run_due_posts()` can change it back to `scheduled` without increasing the retry counter. Scheduled unknown responses can be uploaded again and evade the intended retry bound. | High, Phase 8; publication release blocker. |
| A05 | `schedule_post()` does not restrict source state, so the calendar can schedule an already published/active post. No durable provider operation key or startup reconciliation for `dispatching`/`publishing` is implemented. | High, Phase 8. |
| A06 | Pending polling keeps a single post ID in a widget; it is not rebuilt from the DB on startup and scheduler-created pending posts do not activate that widget path. YouTube status is assumed rather than remotely verified. | High, Phases 5/8. |
| A07 | Scheduled posts retain the selected account ID but resolve the mutable `Video.output_path` at send time. A later render replaces/deletes the old export; the scheduled media version is not pinned. | High, Phases 1/8. |
| A08 | Common FFmpeg/probe subprocess calls have no timeout/cancel interface. Normal temporary-directory cleanup exists, but interrupted-process/orphan cleanup does not. Old-output deletion trusts the DB path without managed-path validation. | High, Phases 1/2/13. |
| A09 | GUI close refuses active widget workers. It does not track an in-flight scheduler upload; scheduler is a daemon thread and `stop()` joins for at most five seconds. It logs stopped even if still running. | High, Phases 8/13. |
| A10 | Global secret redaction is absent. Provider exception strings/HTTP URLs may reach logs and GUI; Meta token exchange uses secret-bearing query parameters. No exposure was deliberately triggered. Confidential client credentials in desktop distribution require a provider-specific decision. | High, Phase 12; review earlier in provider phases. |
| A11 | Network retry helper exists but direct publication adapters do not share one complete error taxonomy. Generic failures and unknown outcomes need different treatment. | Phases 5-8. |
| A12 | `SettingsWidget.refresh_health()` runs synchronous subprocess/database checks on the GUI thread; many worker errors show raw exception text. Disabled states and cancellation explanations are incomplete. | Phases 3/12/13. |
| A13 | Project selected publishing account/metadata are not in the editor draft snapshot; active account is an application preference and metadata is stored on posts. No project duplicate/Save As service was found. | Phases 1/4. |
| A14 | Dockerfile omits `alembic.ini` and `migrations/` although initialization imports them. README's advertised container check is not supported by the current copied assets; Docker was not executed in Phase 0. | Engineering packaging follow-up; not desktop runtime. |
| A15 | No splitter-state persistence, complete subtitle editor, general undo/redo, diagnostic archive, installer, signing or update workflow was found. | Phases 3/4/9/12/14/15. |
| A16 | Dashboard uses zero for absent snapshots, compares the latest two captures without enforcing comparable periods, and lacks full provider/period/last-sync provenance. | Phase 11. |
| A17 | `test_bundle_in_checkout_uses_project_env` expects the real ignored checkout `.env` to exist instead of building its own fixture. The local 37-test result does not establish a clean-clone/CI pass. No tracked CI workflow was found. | Verification hardening, Phases 1/16. |

Observed legacy source-schema differences include the missing analytics account/period
unique constraint; indexes on analytics/trend capture time, content-idea project,
post account/schedule and video project; FKs on content-idea project, post account and
video project; and nullable differences on post retry count and the two snapshot
schema-version columns. The audit comparison was read-only; it generated no migration.

## Repository, legacy and configuration audit

- Active entry: root `main.py`; `app/main.py` is a compatibility desktop launcher for
  `python -m app.main`. It is not a FastAPI server and must not be described as one.
- Runtime dependencies are PyQt6, SQLAlchemy, httpx, dotenv/Pydantic settings, keyring
  and Alembic. No FastAPI, Redis, Celery, RQ, React or Electron runtime is required.
- `app/templates/index.html` and `app/static/*` are orphaned web assets referencing
  old HTTP endpoints. No current desktop references were found. Keep pending a
  deliberate compatibility/removal decision.
- `app/publisher.py` is the old Taisly/mock transport; no active application import
  was found. `TAISLY_API_KEY`/`TAISLY_BASE_URL` remain in settings/example configuration;
  the key is also set in test/build/container scaffolding. They are obsolete for
  desktop publication, not removed in this phase.
- `gui.worker.YouTubeConnectWorker` has no current consumer; the account menu uses
  `AccountConnectWorker`. It is a cleanup candidate, not proof that external consumers
  do not exist.
- `YOUTUBE_ACCESS_TOKEN` still has a low-level analytics fallback use. Treat it as a
  development/compatibility setting, not as proven dead code or the normal account flow.
- Explicit mock implementations exist for content AI, transcription, trends and the
  legacy Taisly client. Abstract `NotImplementedError` methods are interface contracts,
  not missing concrete implementations. No application TODO/FIXME markers were found
  by the scoped source search; missing requirements are tracked here instead.
- `.gitignore` excludes `.env`, token/certificate patterns, databases, logs, media,
  caches, virtual environments, `dist/`, build artifacts and `work/`. Local `.env` is
  ignored. This audit does not certify all historical commits as secret-free.
- Start state was clean `main...origin/main` at `06ba4df`. No CI workflow was found
  under tracked `.github/`. Phase 0 preserves source/legacy files and user data.

## Application paths and missing media

Source launch uses the checkout as data root. A frozen executable uses the OS application
data root; on this Windows machine the existing `%LOCALAPPDATA%/ShortsStudio` directory
is retained. New installations use `%LOCALAPPDATA%/vyro`. No automatic directory move
is implemented. A bundle inside this checkout's `dist/` reads the checkout `.env` but
still resolves its relative storage paths under the application data root. A distributed
bundle reads `.env` from its data root. Settings displays the chosen configuration path.

New imports/music are copied to managed storage; original user files are retained.
Project reopening warns about missing primary/sequence/music paths. History offers
validated video relink. Some preview branches simply return on a missing source;
complete capability-aware missing-media UX and recovery remain Phase 1/4 work.

## Documentation reconciliation

The previous technical status incorrectly listed video compositing, animated titles,
keyframes and effects preview as absent. Code and real smoke establish their limited
implemented forms. README also called `app/main.py` a web prototype and overstated
blanket duplicate protection, migration coverage and the optional container check.
Those claims are corrected or qualified with links to this baseline. No runtime feature
was added to satisfy documentation.

Phase 0 acceptance: local implemented behavior, mock-only paths, unverified real adapters,
external blocker evidence and absent production requirements are now distinguished.
Phase 1 has since been implemented and verified as recorded at the top of this file.
Phase 2 has not been started.
