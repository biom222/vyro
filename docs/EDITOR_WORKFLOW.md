# Editor workflow

Import a video with Ctrl+O. The left media bin lists recent sources. The center shows
the decoded source with the current crop/basic caption; it is explicitly labelled
Source. Select an existing project from History to continue its saved edits.

## Workspace and selection

- Drag the horizontal/vertical splitters to resize media, preview, inspector and timeline.
  Changing a timeline tab no longer applies arbitrary preset splitter sizes. Qt may
  enforce minimum widget sizes. Layout and zoom are saved with the current project.
- Active Clip shows the source-time ruler, in/out handles and playhead. Drag the handles
  or use the right Clip inspector for precise source trim/crop/basic caption/export settings.
- Assembly shows clips in order and their source trims. Select a row or a clip in the
  assembly overview; the right inspector shows that clip's trim and common transitions/music.
  Use Above/Below to reorder; Remove only removes an additional clip from the assembly.
  The project's primary clip is retained, and source files are not deleted.
- Titles and Video Layers show their existing tables, with selected properties on the
  right. Title keyframes are edited in the inspector's keyframe table. Layer timing
  uses output assembly time, whereas clip trim fields use source time.
- The assembly overview draws every title/overlay on an independent row. Select a bar
  to select its object; click the ruler to seek output time into the corresponding source
  trim. During dissolve overlap, source mode selects the later clip. Scroll to see many
  layers; use zoom for a longer timeline. Exact trims/reordering use the normal controls.

## Preview and export

Basic source playback verifies source frames/trims and crop/basic caption. It is not
a live renderer of animated titles, video overlays, music or transitions. Use View With
Effects to prepare the existing temporary composition preview; its header identifies
the assembly with effects. Return to Sources to edit. Mark changes are ignored in the
effect proxy so output time cannot accidentally overwrite source trims.

Export MP4 with Ctrl+E. Export progress, cancellation and completed-result actions
remain in a fixed footer; cancellation is also in the top toolbar/menu (Ctrl+.).
The Export inspector offers saved FPS and quality presets. FPS choices affect export;
frame stepping in source mode follows the source's own inspected rate.

## Keyboard

| Key | Editor action |
| --- | --- |
| Ctrl+O | Import a video |
| Ctrl+S | Save the editable project without rendering |
| Ctrl+Shift+S | Save an independent project copy |
| Ctrl+E | Export MP4 |
| Ctrl+. | Cancel current export/effect-preview preparation |
| Space | Play/pause from preview, timeline or object tables |
| Left / Right | Previous/next source frame on a CFR frame grid |
| Shift+Left / Shift+Right | Seek five seconds backward/forward |
| I / O | Set the source trim start/end at the playhead |
| Delete | Remove selected additional clip, title, video layer or focused keyframe |

The timecode includes milliseconds. VFR stepping uses average FPS and explicitly says
it is approximate. Text fields, spin boxes and combo boxes keep their own editing keys;
Space/I/O/Delete do not unexpectedly control the timeline there. Modal dialogs and
popup menus also retain their normal behavior. Ctrl+Z/Y apply to native text editing
where supported; project-wide undo/redo is not implemented.
