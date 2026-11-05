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
