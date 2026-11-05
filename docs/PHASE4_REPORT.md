# Phase 4 - Media library and project management

Date: 2026-11-05. Baseline: `60fcd81` on main. Scope: local project/media workflows;
no live provider calls, new server, schema migration or filesystem media deletion.

Status: implemented and locally verified. Earlier native Windows/DPI manual signoff
remains open, and this is not a production release or multi-OS release certification.

## Done

- Replace project/video history tables with searchable, sortable QTableViews. Display
  project title, created/updated/opened dates in local time, sequence duration, draft/
  export state and missing source/music markers. Project Files filters videos by project.
- Add rename, independent duplication, last/recent project actions and confirmed
  project deletion. Recent projects are bounded to 20 and persist across processes;
  missing/deleted project IDs are ignored. Startup does not silently auto-open a project.
- Deletion defaults to No. It removes project/edit-history metadata and detaches video
  records while retaining source/music/export files, video edits/transcripts and posts.
  In-flight/uncertain posts, processing media and stale revisions block deletion. The
  active editor/publication/AI target clears after successful deletion; no stale draft
  autosave recreates the deleted project.
- Load project inventory/filesystem availability and selected source metadata in
  background workers. Cache technical metadata and first-frame thumbnails by resolved
  path, size and modification timestamp; reuse them for shared media, invalidate when
  the source changes and rebuild malformed/incomplete cache fixtures.
- Retain locate/relink UI and matching-duration/resolution validation. Extend the
  existing import service with copy-only mode and commit relink path, export invalidation
  and a new dirty draft revision in one transaction. A failed snapshot leaves the old
  link/state intact and removes only the newly generated copy. Old media/MP4s remain.
- Remember the last successful MP4 copy folder. Copy in QThread, drain progress, support
  cancellation and atomically replace the selected destination after completion. Protect
  current sources/exports, pinned publication paths and retained previous exports.
- Add file-manager reveal from editor results and source/export actions in the library.
  Missing-file errors are readable; subprocess arguments are lists with shell disabled.

## Architecture changes

`app/services/library.py` owns inventory, recency, rename and metadata-only deletion.
It uses existing SQLAlchemy models/AppPreference JSON. SQLite deletion takes a write
transaction before checking state; project foreign keys provide established CASCADE/
SET NULL semantics without traversing ORM media deletion cascades.

`LibraryWorker`, `MediaInfoWorker` and `ExportCopyWorker` extend existing QThreads.
Inventory/probing/thumbnail generation/copying are background work; Qt model/pixmap
updates remain in GUI slots. The history widget serializes refreshes and selected-media
inspection, retains workers through finish, and exposes existing publishing/details UI.

Derived cache uses `media-<fingerprint>.json` and `thumbnail-<fingerprint>.jpg`; temporary
writes use unique names. No project-owned thumbnail copy or parallel media database is
introduced. File-manager integration lives in `gui/local_files.py`.

## Changed files

Runtime: `app/services/library.py` (new), `app/services/media_library.py`,
`gui/local_files.py` (new), `gui/history_widget.py`, `gui/worker.py`, `gui/edit_widget.py`,
`gui/editor_workspace.py`, `gui/main_window.py`.

`gui/ai_clips_widget.py` also adds explicit context clearing after project removal/relink;
active AI work blocks these project changes.

Verification: `tests/library_smoke.py` (new), `tests/test_desktop.py`,
`tests/editor_smoke.py`. Documentation: README, PRODUCT_STATUS, PRODUCTION_ROADMAP,
TECHNICAL_CORE, DECISIONS, EDITOR_WORKFLOW and this report.

## Migrations

None. Existing Alembic head remains `7c1e4d2a9100`. Recency and export-directory values
use existing preferences. Project deletion intentionally removes its revisions and
candidates; retained videos/ideas are detached by the existing FK rules. User databases
and source files were not used as deletion/relink fixtures.

## Tests

Local environment: Windows 10 x64, Python 3.13.1, PyQt6 6.11, FFmpeg 9.0.2.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -q` | 65 tests pass. New cases cover recency/rename, deletion with shared media and completed posts, stale/in-flight/processing deletion rejection, atomic relink rollback/revision, copy cancel/failure/destination retention, source protection and thumbnail cache reuse/invalidation/repair. |
| `python tests/library_smoke.py` | Pass with real H.264 media and two real exports: thumbnail reuse, Unicode search, rename/duplicate, No/Yes deletion paths, shared source/export hashes preserved, missing managed source detection, relink through QFileDialog/RelinkWorker, revision increment/dirty state, last project, cancellable background copy path, project-video filter and saved export directory. |
| New-process persistence | Library smoke reads the same isolated SQLite DB in another process and verifies the remaining recent project and export directory. The deleted duplicate is absent from recents. |
| GUI responsiveness | A 10 ms Qt timer fires during real relink; recorded successful runs have 28-30 ticks. Render/copy/library work uses retained QThreads. This is evidence for the fixture, not a whole-app latency guarantee. |
| Reveal contract | Library smoke verifies the Windows explorer argument invocation with Popen mocked. It does not launch/control the user's Explorer or establish macOS/Linux behavior. |
| `python tests/editor_smoke.py` | Pass: existing import/playback/trim/crop/text, sequence/music/dissolve/titles/subtitles/overlay/proxy, save/reopen/Save As and render cancellation still work with the background QTableView library. |
| `python tests/editor_ui_check.py` | Pass at the default offscreen DPR: source-frame stepping, guarded shortcuts, layout/zoom, maximum layer display, export/cancel and close. The Phase 3 nine-combination matrix was not rerun for this phase. |
| Desktop bundle | `python build_desktop.py` rebuilds `dist/vyro/vyro.exe` and passes its isolated startup self-test. Archive/source comparison matches all nine changed runtime modules. This is an onedir developer build, not a signed installer. |
| Static checks | `compileall` for app/gui/tests/main and `git diff --check` pass. |

Machine-readable lifecycle result: ignored `work/library-check/latest.json`; unique run
folders contain the isolated DB/media and `library.png`, `metadata.png`, `missing-small.png`.
Tests explicitly answer confirmation dialogs using mocks on their own fixtures; they
do not confirm deletion of user projects. Expected injected errors remain test failures
when unexpected, rather than being hidden by production exception handling.

## Manually inspected

Code/diff review and visual inspection of generated offscreen project-library screenshot
at 1380x860, including project columns, preview, technical metadata and file actions.
Also inspected the 1040x700 missing-media screenshot. No full native manual
Windows interaction or live provider verification is claimed.

## Not verified

- Real Explorer selection on Windows/macOS Finder/Linux file managers, all target DPI
  combinations on this library, multi-monitor moves and a clean Windows installation.
- Large libraries/slow disconnected network paths, many simultaneous background operations,
  storage exhaustion and physical power loss at every write boundary.
- Scheduler/provider state reconciliation beyond the deletion guards. No real account,
  publication, analytics request, AI call or credentials change was performed.

## Known limitations

- Deletion reclaims editing metadata, not disk space. Video rows/media/old exports and
  provider history remain deliberately retained; cache/backup/export retention and
  user-managed permanent media removal belong to later storage work.
- Inventory currently loads the local library in a background pass; it is not a paged
  large-library index. Metadata/thumbnail workers serialize selected-source inspection.
  Closing waits for them; general task cancellation/shutdown belongs to later phases.
- Relink matches duration within 0.25 seconds and resolution; it does not prove identical
  content. Another project sharing the old source keeps its own link. The active project
  is saved/closed before relink and opened again after success.
- Thumbnails/metadata are disposable derivatives and have no new automatic retention
  policy. Old cache entries remain when fingerprints change.
- A cancelled/failed export copy preserves an existing destination. A physical crash
  may leave its unique temporary `.part` in the chosen folder; it never substitutes an
  incomplete file for the completed destination.
- Project deletion has no undo. Uncertain/pending posts cannot be automatically cancelled
  merely to enable deletion. Native manual Phase 3 acceptance remains open.

## Next phase

Phase 5: live YouTube OAuth/upload/status E2E with an explicitly selected real account.
It requires a separate user command and actual consent/provider verification. Stop here;
do not treat mocked upload or the local library checks as LIVE VERIFIED publishing.
