# Phase 3 - Editor UI/UX refinement

Date: 2026-11-05. Baseline: `2625743` on main, already committed and pushed before this
phase. Scope: the existing desktop editor; no provider/API changes or new effects.

Status: implementation and automated verification completed. The full native Windows
manual workspace/keyboard/resize gate remains OPEN; this is not production signoff.

## Done

- Preserve media-left/preview-center/inspector-right/timeline-below splitters. Remove
  hard maximum widths and forced tab-specific splitter resize jumps. Save layout,
  active inspector tab/layer and zoom in the existing project draft.
- Move existing clip/assembly/title/video-layer properties into contextual inspector
  pages. Make the lower area useful tables rather than large stacked forms. Allow
  vertical scrolling of detailed properties, including title keyframe controls.
- Add a selectable assembly overview driven by the existing sequence model: ordered
  trimmed clips, dissolve regions, independent title/overlay rows, music and playhead.
  Selecting a bar opens its existing table/inspector. The ruler maps output time to
  source trim time; transitions in source mode select the later overlapping clip.
- Keep export progress, result actions and cancellation outside the inspector scroll.
  Fix disabled primary-button styling and the missing Stop icon. Improve empty/max-count
  action states and distinguish source preview from the prepared effect composition.
- Add previous/next frame buttons and Montage menu commands, a millisecond timecode,
  editor-scoped Space/I/O/Left/Right/Shift+Left/Right/Delete, and existing Ctrl+O/S/E/.
  Preserve normal text/spin/combo/dialog/popup input. Delete in the keyframe table only
  removes a keyframe. The primary clip and media source files remain protected.
- Inspect source FPS asynchronously in the existing preview worker and cache it per
  source. Step CFR on its own frame grid, independently of the export FPS. VFR steps
  are explicitly approximate; no false frame-exact VFR claim.
- Fix an exit access violation found during fractional-DPI tests by explicitly detaching
  Qt Multimedia source/sinks/audio and removing the input filter before QApplication
  teardown. Repeated matrix runs then exited successfully without suppressing failures.

## Architecture changes

The existing SequenceWidget/LayersWidget/VideoLayersWidget keep their models, methods,
signals and renderer payloads. Each exposes its existing properties as an inspector
widget. CompositionTimeline is a view/selection layer over these models, not a new
timeline engine. The existing FFmpeg composition/effect-proxy implementation is retained.

An editor-scoped application event filter handles non-text editing shortcuts while
standard QAction shortcuts retain project/file actions. Layout metadata is optional
`workspace` JSON inside the existing versioned project draft.

## Changed files

Runtime: `gui/editor_workspace.py`, `gui/layers_widget.py`, `gui/video_layers_widget.py`,
`gui/sequence_widget.py`, `gui/timeline_widget.py`, `gui/worker.py`, `gui/theme.py`,
`gui/main_window.py`.

Verification: `tests/editor_ui_check.py` (new). Documentation: README, PRODUCT_STATUS,
PRODUCTION_ROADMAP, TECHNICAL_CORE, DECISIONS, EDITOR_WORKFLOW and this report.

## Migrations

None. Existing SQLite/Alembic schema is unchanged. Older drafts without `workspace`
settings use defaults; source files, accounts and credentials are not migrated or
used as test fixtures.

## Tests

Local platform: Windows 10 x64, Python 3.13.1, PyQt6 6.11, FFmpeg 9.0.2.

- `python -m unittest discover -s tests -q`: 60 regression tests pass.
- `python tests/editor_smoke.py`: real import/playback/decoded frame/trim/crop/text,
  cut/dissolve/music/subtitles/titles/overlay/proxy, saved edits/Save As/export/cancel
  and previous-export preservation pass with the new widget layout.
- `python tests/editor_ui_check.py --matrix`: pass in three separate processes with
  QT_SCALE_FACTOR 1/1.25/1.5 (observed devicePixelRatio 1/1.25/1.5). Each covers logical
  1040x700, 1380x860, 1920x1080, empty and four populated editor tabs, visible footer,
  usable minimum preview, contextual selection, output-time seek, resize/zoom scroll,
  preserved splitter proportions, saved layout reopen, light theme and clean exit.
- The same UI check exercises real 25 FPS frame steps (1.000 -> 1.040 -> 1.080 -> 1.040),
  end boundary, ±5-second clamp, source I/O marks, Space playback, guarded text input
  and native text undo, Ctrl+O/S/E/., selected clip/title/overlay/keyframe deletion,
  primary-clip protection and cancellation of a real RenderWorker.
- Maximum layer display: eight overlapping titles and four video overlays occupy 14
  separate rows including video/music; a vertical scrollbar exposes every layer.
- A final single-scale UI run covers the final menu/popup-guard refinements.
- `python build_desktop.py`: rebuilt `dist/vyro/vyro.exe` and passed its isolated
  offscreen startup self-test. Archive/source comparison matches all eight changed
  GUI modules. This remains an onedir developer build, not a signed installer.
- `compileall` for app/gui/tests/main and `git diff --check` pass.

Artifacts and measured JSON: ignored `work/editor-ui/scale-1.json`, `scale-1.25.json`,
`scale-1.5.json` plus their unique run directories. Tests use isolated DB/media paths;
offscreen Windows fixtures register installed system fonts for glyph rendering.

## Manually inspected

Code/diff review and visual inspection of generated Qt screenshots at small and normal
sizes, including source preview, title inspector, assembly overview and fixed footer.
An isolated native Windows fixture opened and its accessibility tree exposed the
expected tables, inspector, transport, menu and toolbar controls.

This is partial evidence only. Native computer-use capture failed twice with
`FrameArrived timed out: timed out waiting on channel`. Later calls reported a physical
Escape stop, including after the user's resume instruction; no further app input was
attempted after that response. The owned fixture process was closed after the check.
The full interactive native matrix is not marked passed.

## Not verified

- Full native Windows resize/keyboard/drag matrix and actual monitor DPI changes.
  The nine automated combinations use Qt offscreen logical sizes/device ratios, not
  Windows display-setting changes or a clean-machine native acceptance session.
- Native 1920x1080 client area on the current 1080-high display: Windows reserves
  title bars/work area and clamps client height. The logical size was tested offscreen.
- Multi-monitor DPI moves, macOS/Linux UI, assistive technology beyond the inspected
  native tree, arbitrary codecs for frame stepping and long editing sessions.
- Real provider accounts/publications/analytics/AI; no such requests were made.

## Known limitations

- Assembly overview is selection/navigation, not drag-to-reorder/trim or a fully general
  multitrack timeline. Existing table controls and source trim handles perform edits.
- Small windows necessarily scroll inspector details and many layer rows. Preview can
  reach its 96-pixel minimum height; users can enlarge it with the splitter.
- Source playback omits transitions/music/animated titles/overlays. Prepared effect
  preview remains necessary for the actual composition and is explicitly labelled.
- VFR frame stepping is approximate; CFR uses inspected average FPS and millisecond
  seeks, with Qt/decoder timestamp tolerances. Packet-accurate VFR editing is absent.
- Project undo/redo is absent; no misleading partial Ctrl+Z/Y implementation was added.
- Snapshot/draft storage, provider/scheduler/security/distribution limits from previous
  phase reports remain. This phase does not claim production readiness.

## Next phase

Complete the open native manual Phase 3 gate when app input/capture is available.
Phase 4 is media library/project management and requires a separate user command.
Do not silently start it as part of this change.
