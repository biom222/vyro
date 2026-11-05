# Phase 1 - Data safety and project reliability

Date: 2026-11-05. This phase extends the existing desktop application. It does not
complete the production release or start Phase 2. Phase 0 documents are retained.

## Implemented behavior

- `project_state.py` now owns the existing `AppPreference` draft persistence path.
  One SQLite transaction updates the draft, project revision counter and immutable
  checksum-protected snapshot. The last 20 snapshots are retained per project.
- A compare-and-set revision check rejects stale writers. Identical saves are
  deduplicated; invalid state, cross-project video references, non-finite values,
  relative music paths and credential fields do not replace a valid saved draft.
- Existing 400 ms autosave remains. The status bar distinguishes pending edits,
  successful save and save error. Window close and project switching require a
  successful save. Save As can preserve pending edits in an independent copy.
- Reopen validates the current draft and checksum, then falls back to the most recent
  valid snapshot, even when current draft/latest snapshot JSON cannot be decoded.
  Legacy drafts with revision zero are adopted on their first save. Cleanup is skipped
  if database references cannot be read safely, rather than risking deletion.
  A recovered older draft requires a new export; opening a non-exported project clears
  the previous project's publication video target.
- Drafts preserve sequence/order/trims/transition/crop/music/subtitle settings, title
  layers/keyframes, video layers, selected clip/playhead, selected publishing account,
  title/description and publication options. Transcripts/segments remain database entities.
- File -> Save Project As (`Ctrl+Shift+S`) and History -> Duplicate Project create
  independent database records, remap video IDs and copy transcript/segment data,
  edit preferences, candidates and project ideas. They share immutable source media
  and managed music. Publication jobs and exports are not cloned. Save MP4 Copy uses
  `Ctrl+Alt+S` to avoid the project shortcut collision.
- Rendering no longer deletes the previous export by a path taken from the database.
  New publication records pin the selected export path and duration, so later rendering
  does not change that selected file. Existing unpinned posts retain the legacy fallback;
  provider state-machine/retry fixes remain Phase 8.
- Startup cleanup only targets known disposable preview/partial/render names older
  than 24 hours inside managed roots. Database, revision and publication references
  protect assets; symlinks/junctions are skipped. Sources, music and final exports are
  not automatically deleted.
- Normal GUI startup holds an automatic Qt instance lock. Stale locks are handled by
  Qt; users are not instructed to delete lock files. Corrupt/unavailable DB startup
  offers a backup selection dialog, and storage-path failures have a readable dialog.

## Database and migration

New Alembic revision: `7c1e4d2a9100`, after `beb1f4933f58`.

It repairs missing legacy foreign keys/indexes/analytics-period uniqueness and nullable
default columns, adds `projects.draft_revision` and `project_revisions`. SQLite runtime
connections enable FK enforcement and a bounded busy timeout. Startup compares the
physical schema with ORM metadata rather than trusting the revision stamp alone.

Backups use SQLite's online backup API, including committed WAL content, and are
integrity checked before atomic publication under `data/backups/`. A migration marker
is fsynced before schema changes. Failure restores the verified backup. After process
termination, the next startup restores first and retries the upgrade. Interrupted initial
DB creation is also recoverable. Replaced partial/corrupt database files and sidecars
are retained under `data/recovery/`, not discarded.

Ambiguous existing orphan references or duplicate non-null analytics periods abort
the migration with a preserved backup; the migration does not delete/reassign those
rows. A repair decision is required for such data. Restore validates SQLite integrity
and, for a user-selected backup, checks for vyro tables before replacing the DB.

The source and installed ShortsStudio user databases were copied read-only into
ignored `work/` fixtures. Both copies upgraded to the new revision, matched ORM metadata,
passed SQLite integrity checks and had zero FK violations. The originals were not
upgraded during verification; the next application startup performs the backed-up
upgrade. Existing application-data-directory precedence is unchanged.

## Verification

- Full regression: `python -m unittest discover -s tests -q` - 52 tests pass.
- Acceptance subprocesses: create/edit/save -> process shutdown -> reopen with equal
  state, including subtitle segments/layers/keyframes/publication metadata. Another
  subprocess exits abruptly after SQL writes but before commit; the saved state remains equal.
- Fault tests cover failed snapshot writes, stale revisions, corrupted draft/latest
  snapshot fallback, bounded history, missing media, invalid paths/secret fields,
  independent duplication without cloned post jobs, and refusal to close on save failure.
- Migration tests cover fresh/legacy/unversioned schema parity, online backup with WAL,
  injected DDL failure/restore, abrupt process termination during upgrade and first
  creation, plus corrupt-file preservation.
- Real `tests/editor_smoke.py` passes with FFmpeg: playback/crop/trim/export, sequence,
  music/subtitles/titles/keyframes/video overlay/proxy, reopen, Save As and restored
  publication text. Test configuration and media/DB are isolated under work/editor-check.
- Manually inspected generated project-copy/history-copy screenshots. This is visual
  inspection of automated offscreen output, not a clean-machine human-driven UI session.
- The actual local Windows executable is rebuilt with bundled migrations and passes
  the build script's isolated startup self-test. It remains an onedir development build,
  not a signed installer or a clean-machine release verification.
- Archive inspection confirms the packaged code matches current source for all ten
  changed imported runtime modules, the main entry script and the new migration
  (12/12 comparisons). Launcher check, compileall and `git diff --check` also pass.

Tests with intentional faults log their simulated errors. Successful runs required
execution outside this environment's temporary-directory sandbox restrictions.

## Limits and not verified

- An abrupt crash can lose edits still inside the 400 ms autosave debounce. The last
  committed valid snapshot remains available; arbitrary hardware/storage failure is
  not simulated or guaranteed recoverable.
- Snapshot history is in the same DB; physical DB corruption requires a valid external
  backup. Automatic backups occur before migrations, not as a timed continuous backup.
- Project copies share media; external deletion/overwriting still requires relink or
  restoration of that media. Save As creates a local library project, not a portable archive.
- Real power loss, disk exhaustion/permission changes at every filesystem boundary,
  long-running multi-instance stress and a clean Windows installation remain unverified.
- Backup/recovery files and old final exports are deliberately retained; there is no
  automatic final-export or backup-retention deletion policy in this phase.
- Legacy provider posts without pinned media, unknown-state retries, scheduler upload
  shutdown and remote reconciliation remain known Phase 8 issues. No live provider
  OAuth/upload/analytics or real AI operation was performed.
- Window/scaling/codec/performance matrices and render cancellation remain later phases.

## Changed files

Runtime: `app/models.py`, `app/database.py`, `app/tasks.py`,
`app/services/project_state.py`, `app/services/projects.py`, `app/services/storage.py`,
`main.py`, `gui/editor_workspace.py`, `gui/main_window.py`, `gui/history_widget.py`,
`gui/publish_widget.py`.

Migration: `migrations/versions/7c1e4d2a9100_project_safety.py`.

Verification: `tests/test_desktop.py`, `tests/project_restart_check.py`, `tests/editor_smoke.py`.

Documentation: README, PRODUCT_STATUS, TECHNICAL_CORE, PRODUCTION_ROADMAP, DECISIONS
and this report. Phase 0 documentation changes were already pending and are preserved.

Next phase: Phase 2, video editor hardening. Do not begin it without a separate command.
