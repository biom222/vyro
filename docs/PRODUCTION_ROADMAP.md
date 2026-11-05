# vyro production roadmap

Source: the user's MASTER specification supplied on 2026-11-05. This roadmap covers
Phase 0 through Phase 16 and preserves the current Python/PyQt6/SQLite/FFmpeg desktop
architecture. Current evidence and known findings: [PRODUCT_STATUS.md](PRODUCT_STATUS.md).

Phase 0 audit and Phases 1-2 implementation have been executed; see their status/report
documents. Phase 3 is implemented with automated verification; its native manual gate
remains open. Phase 4 is implemented and locally verified; see its report. Phase 5
has live YouTube evidence; see PHASE5_REPORT.md for scope and remaining limitations.
Phase 6 and later require separate commands. Do not combine the roadmap
into one implementation change.

## Rules shared by every phase

1. Inspect current services, models, migrations, GUI, tests and behavior before editing.
2. Reuse existing implementations and adapters; add no parallel OAuth or editor core.
3. Use Alembic for schema changes and a verified backup before changes to existing data.
4. Run relevant tests, then the full regression suite; perform and record the manual
   checks automation cannot establish. Mock contracts are not live verification.
5. Update status/technical documentation and list changed files, migrations, actual
   verification, unverified scenarios and known limitations.
6. Stop after the phase report. A provider/credentials blocker is a recorded outcome,
   not permission to claim live success or silently skip the release gate.

Windows 10/11 x64 is the first production target. Normal users must not edit `.env` or
SQLite, run CLI commands, inspect tracebacks or remove lock/temp files. Local editing
and export remain usable without AI/provider keys. CLI remains an engineering tool.

Maintain flat desktop design: top menu/toolbar/status bar, splitters and useful docks,
compact inspector/tabs and normal views/tables; no persistent SaaS sidebar, gradients,
decorative cards, emoji or oversized headings. Dark palette `#1a1a1a`/`#242424`, text
`#e5e5e5`, muted near `#8a8a8a`, one restrained amber accent `#d97706`, radius 0-2 px,
system font around 12 px, section titles 13-14 px, spacing 4/8/12 px.

Every feature needs understandable empty/ready/loading/success/warning/error/disabled
states. Explain disabled actions. Show user-oriented errors; keep technical detail in
redacted logs. Verify 1040x700, 1380x860, 1920x1080 at 100%, 125% and 150% scaling.

Do not add cloud storage, vyro login/subscriptions, feeds/community/chat, marketplaces,
generic AI assistants or a new server/frontend without a concrete separate requirement.
Minor conservative decisions go in [DECISIONS.md](DECISIONS.md); changes to architecture,
data, provider flows, security or running cost require an explicit decision point.

## Phase 0 - Audit and baseline

Status: executed; see the verification and limitations in PRODUCT_STATUS.

- Inventory repository, models/migrations/GUI/tests and current Git state.
- Run existing automated tests, real editor smoke and FFmpeg/FFprobe doctor.
- Reconcile README, technical core and actual implementation.
- Identify legacy web/Taisly/dead-code candidates, obsolete environment settings,
  mock/placeholder branches and undocumented/misdocumented functionality.
- Audit migration safety, application paths, missing media and shutdown behavior.
- Deliver PRODUCT_STATUS, this roadmap and a corrected TECHNICAL_CORE.

Gate: answer what locally works, is mock-only, is unverified live, is externally blocked,
and is absent. No redesign, provider fix or architecture change in this phase.

## Phase 1 - Data safety and project reliability

Status: implemented and locally verified; see [PHASE1_REPORT.md](PHASE1_REPORT.md).
Initial inputs were audit A01-A03, A07-A08 and A13. Production-wide verification and
external provider gates remain open as described in that report.

- Establish atomic complete project snapshots, meaningful dirty/autosave state and
  crash recovery with a last valid version after an interrupted save.
- Repair legacy schema drift through Alembic; validate backup/restore, interrupted
  migrations and useful corrupt-database errors. Test consistency while data is active.
- Validate project/media/output paths; protect original sources; detect/relink missing
  media and clean orphan caches/temporary renders conservatively.
- Implement project duplication and Save As Project with intentional media ownership.
- Preserve clips/order/trims/transitions/crop/music/subtitles/overlays/titles/keyframes,
  selected publishing account and publication metadata.

Gate: automated `create -> edit -> save -> shutdown -> reopen -> state equality`, plus
interrupted-save/migration and restore evidence. Never close after an unhandled save failure.

## Phase 2 - Video editor hardening

Status: implemented and locally verified; see [PHASE2_REPORT.md](PHASE2_REPORT.md).
Clean-machine/native playback and broader device/performance coverage remain open.

- Test mixed/common FPS, VFR, portrait/landscape/square, silent media and sample rates,
  H.264/available HEVC, odd dimensions, long/Unicode/Russian/space-containing Windows
  paths, corrupt and audio-only inputs, 30 clips and long projects.
- Compare preview/export crop, order, trim, transitions, titles/opacity, subtitles,
  overlays and music with measurable tolerances and recorded architecture limits.
- Retain a clear vertical preset: 1080x1920, H.264, yuv420p, AAC, faststart; add only
  useful FPS/quality controls, with advanced settings kept compact.
- Add safe render progress/cancel/timeout/process termination, error detail and partial
  output cleanup. Audio normalization must be validated rather than blindly applied.

Gate: real-file integration matrix passes; preview/export agreement and cancellation
behavior are documented. No effects expansion before existing paths are dependable.

## Phase 3 - Editor UI/UX refinement

Status: implemented; automated keyboard/layout/size/DPI checks pass. The native manual
workspace/resize matrix is not signed off; see [PHASE3_REPORT.md](PHASE3_REPORT.md).

- Keep media bin left, preview center, contextual inspector right and timeline below,
  resized through splitters. Make selected clip, trims/playhead/boundaries/transitions,
  text/overlay layers and zoom legible and functional.
- Show properties for the current selection; keep the empty instruction compact.
- Provide Space, Ctrl+O, Ctrl+S, Ctrl+E, Delete and correct frame stepping where possible.
  Ctrl+Z/Y require a complete safe undo architecture; no misleading partial undo.
- Cover required window sizes/scaling, hidden-control prevention and splitter behavior.

Gate: manual workspace/keyboard/resizing matrix and applicable GUI regressions pass.

## Phase 4 - Media library and project management

Status: implemented and locally verified; see [PHASE4_REPORT.md](PHASE4_REPORT.md).
The earlier native manual/DPI gate remains open; file-manager integration is contract
tested locally, not signed off across operating systems.

- Recent/last-opened projects, titles and created/updated dates, duration/export status,
  missing-media markers, locate/relink, duplicate and confirmed deletion.
- Remember export destination, reveal in Explorer, media metadata and thumbnail cache.
- Use compact normal lists/tables, not decorative dashboard cards.

Gate: real multi-project lifecycle, duplication/deletion ownership and missing-media
scenarios pass without damaging shared/original assets.

## Phase 5 - Live YouTube E2E

Status: LIVE VERIFIED for the approved private test upload through the existing
services on Windows; see [PHASE5_REPORT.md](PHASE5_REPORT.md). Native GUI upload and
clean-machine release acceptance remain unverified.

- Reuse existing state/PKCE/local callback/keyring/account/upload/analytics services.
- Test browser authorization, channel discovery and active selection, export and
  title/description/privacy, upload progress, provider ID and actual remote final status.
- Prove remote video existence, duplicate prevention and persisted status after restart.
- Handle denied consent, timeout, wrong state, token expiry/refresh failure, removed
  account, quota and network loss with useful messages, including Google tester denial.
- Keep tokens in OS keyring and secrets/codes/tokens out of logs.

Gate: recorded real account/video result labelled `LIVE VERIFIED`. Contract tests alone
do not pass. If unavailable, report `BLOCKED_BY_EXTERNAL_CREDENTIALS` or the actual
external provider block. Respect the provider's current capabilities and approval rules.

## Phase 6 - Live TikTok E2E

- After YouTube is stable, verify official Content Posting OAuth/scopes, token refresh,
  creator information, allowed privacy, upload, processing/polling/failure and restart.
- Display actual unaudited/account restrictions; offer only supported choices.
- Prove duplicate protection and actual remote result. Do not publish through browser
  automation or scraping.

Gate: live evidence or an explicit external credentials/approval blocker; local contract
tests stay mandatory and distinct from live results.

## Phase 7 - Cancelled

Instagram was removed from the product at the user's request on 2026-11-05.
Its account connection, publishing adapter, UI and configuration were removed.
Historical records are retained but inactive. Keep phase numbers stable: after Phase 6,
continue with Phase 8; do not implement another Instagram integration.

## Phase 8 - Publication engine and scheduler

- Unify states: DRAFT, QUEUED, CLAIMED, UPLOADING, PROCESSING, PUBLISHED,
  FAILED_RETRYABLE, FAILED_FINAL, CANCELLED, UNKNOWN_REMOTE_STATE.
- Persist unique provider operations/idempotency and the intended media version;
  bound retry/backoff and distinguish retryable errors from uncertain remote outcomes.
- Reconcile remote state before any resend; recover unfinished work and pending polls
  after startup. Persist scheduling, timestamps/timezone and visible local time.
- Add safe cancellation/manual retry, provider permalinks and last-attempt/error detail.
- Include A04-A09: unknown responses, published-post rescheduling, restart recovery,
  widget-only pending state, mutable exports and scheduler shutdown.

Gate: restart/crash/uncertain-response tests and live scheduled operation establish
no unintended duplicate upload. The local scheduler's app-running requirement is clear.

## Phase 9 - AI clips and transcription

- Real transcription model/language auto/manual selection, cache, timestamps,
  progress/cancel/retry and readable failures outside the UI thread.
- Structured suggestions: start/end/title/reason/hook and a meaningful labelled score.
  Require confirmation before transferring suggestions into edits.
- Keep deterministic mock and real provider paths distinguishable; graceful unconfigured
  behavior states that local editing/export remain available.

Gate: real speech/AI fixtures, invalid structured output, cancellation, missing key and
quality review. Synthetic output is never labelled real recognition or analysis.

## Phase 10 - Trends and content intelligence

- Level 1: permitted public metadata (title, description, time, views, available likes/
  comments, channel, historical snapshot); display snapshot time and calculate velocity,
  growth, age-normalized score and repeated topics with explainable limits.
- Level 2: analyze imported user-owned content, transcripts, cuts and structure.
- Explicitly distinguish metadata discovery from semantic viewing. Do not mass-download
  third-party footage, infer reuse rights or promise safe reuploads; require rights review.

Gate: reproducible scoring/history and honest source/capability labels, live metadata
verification and useful no-data/errors. Semantic understanding is absent until proven.

## Phase 11 - Analytics

- Display only available real account/provider/period metrics, publications, recent
  videos and supported history; attach period and last-sync provenance to each metric.
- Use a connect/no-data state instead of synthetic charts or misleading zero values.
- Validate comparable periods and refresh behavior; evaluate each additional provider
  separately through official access, not scraping.

Gate: real account sync, zero-vs-unavailable semantics and comparable-period tests.

## Phase 12 - Settings, security, privacy and diagnostics

- Compact General/Video/AI/Accounts/Storage/Diagnostics/Updates sections; remove normal
  user dependence on `.env`. Retain environment config for development.
- Audit keyring, packaged behavior, `.gitignore`, rotating logs, timestamp/severity/
  subsystem and systematic secret redaction.
- Decide per provider whether public/native PKCE is supported or a confidential secret
  requires a minimal OAuth broker. Never claim an embedded secret is safe by obfuscation;
  introduce a backend only for a demonstrated requirement and an explicit decision.
- Offer a diagnostic archive with versions/OS/FFmpeg/schema, redacted config and logs;
  exclude keys/tokens/passwords/media/private raw project content.

Gate: redaction/security tests and inspection of the actual archive/bundle; documented
provider credential architecture with required approvals.

## Phase 13 - Performance and stability

- Profile real bottlenecks: repeated preview/project switches, memory/cache/thumbnail
  growth, QThread/session lifetimes, orphan FFmpeg processes and long projects.
- Exercise repeated OAuth and scheduler lifecycle, closing during render/upload and
  safe cancellation. Move long health/network/media work off the GUI thread.

Gate: measured stress runs and bounded resources/shutdown, with reproducible findings.

## Phase 14 - Windows distribution

- Versioned Windows 10/11 x64 installer, icon, Start Menu and optional desktop shortcut,
  uninstall and preserved user data unless explicitly removed; bundle migrations and
  first-run checks using correct LOCALAPPDATA and tested legacy-directory behavior.
- Choose/document a legally suitable bundled FFmpeg build or guided setup. A manual
  PATH instruction alone does not meet the production user requirement.
- Prepare signing hooks and verification; without a certificate state exactly:
  `Signing infrastructure ready; actual certificate required.`

Gate: clean-machine install/update/uninstall/reinstall, media/export and data survival.
An onedir executable folder alone does not pass this phase.

## Phase 15 - Update system

- Show current/latest stable versions, check update, release notes and a clear download/
  update path. Verify package integrity; no unverified silent executable replacement.
- Prevent updates while rendering/uploading and preserve recoverable user state.

Gate: successful, missing/offline/corrupt update and busy-operation tests.

## Phase 16 - Final QA and release candidate

- Maintain a release matrix for unit/services/migrations/GUI/editor/render/reopen/
  scheduler/provider contracts/idempotency/OAuth/crash recovery. Keep good tests.
- On clean Windows: install/first launch; import/preview/trim/sequence/transitions/crop/
  music/subtitles/layers/titles; save/restart/reopen/export; external MP4 playback;
  YouTube connect/publish/restart/status; schedule/execute; disconnect network and
  interrupt/restart unfinished work; diagnostics/update/uninstall/reinstall without loss.
- Run analogous live TikTok cases when production credentials are available.

Gate: completed automated and manual release matrix with actual evidence, remaining
provider approvals and any known limits explicitly signed off.

## Release and legacy gates

Call the product `vyro 1.0 production-ready` only after proven project safety, real-file
export/preview agreement, safe migrations, no known critical data-loss bug, terminal-free
clean Windows installation, safe secrets, responsive GUI/useful errors, live YouTube E2E,
scheduler restart recovery, duplicate prevention, passing regressions and an honest manual
release checklist. TikTok may remain provider-approval-pending only when the
application handles that state correctly and labels it honestly.

Legacy web assets, Taisly transport/settings, duplicate workers and compatibility code
are cleanup candidates after dependency checks, not Phase 0 deletions. Keep existing
ShortsStudio data intact; any directory migration must be explicit, backed up, tested
and documented. Do not silently drop old data or stamp schema parity without validation.

Phase reports use: Done; Architectural changes; Changed files; Migrations; Tests;
Manually verified; Not verified; Known limitations; Next phase. Start that next phase
only after the user's command.
