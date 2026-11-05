# Decisions

## 2026-11-05 - Phase 0 evidence and scope

- Preserve the Python/PyQt6/SQLite/FFmpeg desktop architecture and all compatibility
  code during the audit. Record gaps rather than implementing later phases early.
- Use `PRODUCT_STATUS.md` for verification/status claims and `PRODUCTION_ROADMAP.md`
  for the user-approved phased scope. A passing mocked request is not live verification.
- Distinguish code inspection, automated offscreen GUI exercise and manual visual
  inspection of screenshots. None substitutes for a clean-machine native UI/release test.
- Record the local schema drift without repairing or restamping the user's database.
  Phase 1 must choose a backed-up Alembic repair path and prove legacy/fresh parity.
- Keep current storage-directory precedence, local environment configuration and
  legacy files unchanged in Phase 0. Their production redesign/cleanup belongs to the
  relevant later phase and must preserve existing user data.

## 2026-11-05 - Phase 1 project safety

- Extend the existing AppPreference JSON draft path through a persistence service;
  do not introduce a parallel project format. Append checksum-protected snapshots in
  the same transaction and keep 20 versions. Preserve the 400 ms autosave debounce.
- Save As means an independent local-library project. Share immutable managed media,
  clone/remap edit/transcript entities, and never clone publication operations.
- Use SQLite online backups and durable migration recovery markers. Archive replaced
  DB files/sidecars, validate schema parity and refuse ambiguous duplicate/orphan repairs
  rather than deleting user rows. Keep the existing application-data-directory policy.
- Keep old final exports and pin new publication media; broader publication-state and
  legacy-post recovery remain Phase 8. Cleanup only old known disposable names under
  validated managed roots, protecting DB references and skipping links/junctions.
- Use Qt's existing QLockFile facility for normal GUI single-instance startup; stale
  lock handling stays automatic. No new lock service or manual lock-file workflow.
- Verify migrations on copies of current source and installed DBs. Let normal startup
  apply the backed-up upgrade to originals; test execution does not mutate them.

## 2026-11-05 - Phase 2 local media hardening

- Retain the existing sequence graph and QThreads. Add one managed process runner,
  thread-local operation contexts and explicit worker cancel events; never use a global
  current process or terminate QThreads. Reap each process and drain bounded pipes.
- Preserve the previous export on cancellation. Check the temporary result before
  moving it to its final filename. Later application-crash orphan recovery remains
  covered by conservative Phase 1 cleanup, not immediate deletion of final exports.
- Keep two quality presets (CRF 23/18) and six FPS choices (24/25/30/50/60/source).
  Source means the first clip's average FPS converted to CFR, including rational rates.
  Persist both in the existing editor JSON; no migration or separate export model.
- Keep proxy at half resolution, correct proportional text geometry, and invalidate
  old cache signatures. Sample proxy/export frame and decoded-audio differences;
  do not claim identical pixels or a real-time compositor.
- Pad short source audio to its clip length before concatenation. Add no new loudness
  normalization. Use ASCII local filter filenames plus a subprocess cwd for text and
  subtitle filters so user paths do not enter FFmpeg's second escaping layer.
- Expose cancellation in the toolbar/menu as well as the scrollable inspector. Defer
  the broader editor layout/selection/keyboard/scaling redesign to Phase 3.

## 2026-11-05 - Phase 3 editor interaction

- Reparent existing properties into contextual right-hand inspector pages. Keep the
  established models, signals, tables and render payloads; no second editor state tree.
- Draw a selectable assembly overview from existing clips/layers/music. Use independent
  layer rows and scrollbars for the maximum layer count. Reordering, exact trims and
  keyframe edits remain in their existing controls, not misleading fake drag gestures.
- Remove fixed maximum panel widths and forced tab-driven splitter sizes. Respect user
  splitters, viewport minimums and optional workspace JSON for layout/zoom/selection.
- Keep export progress/result/cancel actions outside scrollable properties. Expose frame
  and delete commands in the Montage menu, with editor-scoped shortcuts that preserve
  text fields, spin boxes, combo boxes, dialogs and popups.
- Step CFR sources on their asynchronously inspected FPS grid. Mark VFR stepping as
  approximate rather than implying packet-accurate seeking; retain effect-proxy workflow.
- Do not add a partial global undo. Native text Ctrl+Z remains available; project undo
  requires a separate complete command/history design.
- A fractional-DPI test exposed a Qt Multimedia exit access violation. Detach media
  source/sinks/audio and the application event filter on accepted close. Repeat the
  actual process-exit matrix rather than suppressing the child-process failure.
- Distinguish nine offscreen logical-size/DPR checks from native Windows manual signoff.
  Failed capture/Escape-stopped computer use is not evidence of a passing manual gate.

## 2026-11-05 - Phase 4 project/media ownership

- Delete project editing metadata only, with explicit default-No consent. Keep video
  rows, their edits/transcripts, immutable sources/music/exports and publication records.
  Use the existing foreign-key CASCADE/SET NULL behavior for project revisions,
  candidates and detached media/ideas. Never infer filesystem deletion from ownership.
- Refuse changed revisions, processing media and queued/scheduled/dispatching/publishing/
  pending/unknown posts before deletion. Acquire the SQLite write transaction before
  checking; preserve completed provider history. These guards do not redesign scheduling.
- Persist recency (20 projects) and export destinations in existing AppPreference JSON;
  no new project format or schema migration. Expose last/recent actions explicitly,
  rather than automatically opening a potentially missing project at startup.
- Keep source metadata and thumbnails as derived fingerprint caches, shared by project
  copies. Read/probe/copy in QThreads; Qt pixmaps and table models stay on the GUI thread.
- Extend the existing source import path with a copy-only option. Commit relink path,
  export invalidation and a dirty checksum-protected revision together. Roll back both
  DB changes and a newly generated copy on failure; never remove the original source.
- Copy an export through a destination-local temporary file and atomic replace. Check
  cancellation, protect current sources/exports, pinned publication media and retained
  previous exports. Remember destination only on success; defer file-manager behavior
  verification on every OS and broad cache/retention management to later phases.

## 2026-11-05 - Phase 5 YouTube delivery and verification

- Reuse existing OAuth/keyring/account services. Validate state before denial as well
  as success, accept one callback and omit callback query strings from logs.
- Persist intent before media bytes and checkpoint the provider ID before final task
  completion. An uncertain upload may query only the same session; never blindly insert
  again. Preserve any existing checkpointed ID when recording uncertain status.
- Upload acknowledgement is pending. Query videos.list for matching ownership, actual
  processing and visibility. Published means processing complete, not public access.
- Restore YouTube operations from SQLite for explicit status checks after restart,
  without automatic upload. Block history/scheduler resend of known/uncertain operations
  and matching pinned exports. Broader operation state machine remains Phase 8.
- Keep live evidence separate from mock contracts. One neutral private test was
  explicitly approved and verified; no private account IDs/tokens are committed.

## 2026-11-05 - Remove Instagram from product scope

- User explicitly removed Instagram. Delete its OAuth, token handling, upload/status
  adapter, service icon/menu/settings, environment fields and legacy web/mock options.
  YouTube and TikTok are the only supported account/publication providers.
- Retain existing database/account/post rows and project drafts. Filter unsupported
  accounts, ignore saved active selections and clear them when restoring drafts.
  Reject manual scheduling/publication and skip old unsupported scheduled posts.
  No schema migration, token-store deletion or destructive data cleanup is required.
- Cancel Phase 7 and retain later phase numbers. Historical reports remain historical;
  update the active roadmap and setup documentation instead of rewriting evidence.
