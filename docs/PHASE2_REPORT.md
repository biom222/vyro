# Phase 2 - Video editor hardening

Date: 2026-11-05. Scope: the existing local editor, not new effects or provider work.
Phase 0/1 baseline was committed and pushed as `e6deb28`, `376f8b9`, `6aae8ab` before
this phase. The desktop remains a technical alpha; no production release claim.

## Done

- Managed FFmpeg/FFprobe execution with independent worker cancellation, bounded pipe
  tails, deadlines and terminate/kill/wait cleanup. No QThread termination or shell.
- Cancel from the inspector, top toolbar or Montage menu (Ctrl+.). Main export/save
  actions are disabled during both export and effect-proxy preparation. Errors expose
  a short explanation with expandable technical details, also retained in the GUI log.
- FFmpeg output-time progress for the main sequence encode (10-75%), with existing
  effect stages through completion. The older single-source API retains stage progress.
- Validate temporary output before its final move; remove partial failed/cancelled
  output. Cancellation restores ready/uploaded state and keeps the previous export.
- Saved common 24/25/30/50/60 or source FPS; source uses the first clip's average rate
  as CFR, including 30000/1001. Two quality presets: Standard CRF 23, High CRF 18.
  Quality propagates through later effect encoding passes, not only the initial pass.
- Preserve 1080x1920 H.264/yuv420p/AAC/faststart vertical export. Landscape assembly
  remains 1280x720; proxy is half resolution. Pad short audio before concatenation,
  synthesize silent tracks where needed and resample to stereo 44.1 kHz.
- Reject audio-only, corrupt and nonfinite metadata with media errors. The single-source
  trim path rounds odd dimensions down to even dimensions before yuv420p encoding.
- Correct proxy caption size, line spacing, border and small title scaling. Use ASCII
  local text/subtitle filter filenames with per-process cwd to support quoted paths.
  Cache signature changes to preview-v2 so old proxies are not reused.

## Architecture changes

`app/media_process.py` owns the subprocess lifecycle and `RenderControl`. ContextVar
operation scopes propagate cancellation/deadlines through existing nested processor
calls while keeping unrelated worker threads independent. Each process has two pipe
reader threads; retained output is bounded to 64 chunks of up to 4096 bytes per pipe.
The UI receives Qt signals and keeps workers alive until QThread.finished.

Probe deadline: 30 seconds. Individual encoding pass: 1800 seconds. Render operation:
3600 seconds. The poll interval is 50 ms; forced termination follows a 3-second wait.
Filesystem/driver latency can add to cancellation time. No new loudness normalization
was added; the existing music mixing behavior is preserved.

FPS/quality live in the existing project/editor JSON and checksum-protected revisions.
No parallel project format, queue, HTTP service or database model was introduced.

## Changed files

Runtime: `app/media_process.py`, `app/video_processor.py`, `app/tasks.py`,
`app/services/project_state.py`, `gui/worker.py`, `gui/edit_widget.py`,
`gui/editor_workspace.py`, `gui/main_window.py`.

Verification: `tests/test_media_process.py`, `tests/media_matrix.py`,
`tests/editor_smoke.py`. Documentation: README, PRODUCT_STATUS, PRODUCTION_ROADMAP,
TECHNICAL_CORE, DECISIONS and this report.

## Migrations

None. Existing Alembic head remains `7c1e4d2a9100`. Missing FPS/quality fields in older
drafts default to 30 FPS and Standard quality. User databases/media are not test fixtures.

## Tests

Verified locally on Windows 10 x64, Python 3.13.1, PyQt6 6.11 and FFmpeg 9.0.2:

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -q` | 60 tests pass, including real child-process timeout/reaping, independent cancellation, bounded stdout/stderr, partial cleanup and metadata errors. |
| `python tests/editor_smoke.py` | Pass: playback/frames/trims/crop/text, cut/dissolve/music/subtitles/titles/layers, draft reopen/Save As, saved FPS/quality and cancellation through the actual toolbar action. Old MP4 and DB ready state survive; actions become usable again. |
| `python tests/media_matrix.py` | Pass: generated landscape24, portrait29.97, square60/silent, confirmed VFR, odd321x181 FFV1, software HEVC, 32/44.1/48 kHz audio including shorter audio, corrupt/audio-only rejection, spaces/Russian/apostrophe paths, a rendered 295-character Windows path. |
| Output preset | H.264, yuv420p, 1080x1920, AAC and moov-before-mdat faststart verified with FFprobe/MP4 bytes; 24/25/30/50/60 and source25/30000:1001 verified. |
| Proxy/export agreement | Same trim/crop/order/dissolve/music/timed subtitles/animated title opacity and position/overlay fixture: five frame samples at 0.1/0.5/0.9/1.5/2.4 seconds, downscaled to 160x284. Mean absolute RGB errors: 0.596, 1.491, 2.253, 1.171, 0.914 out of 255; assertion threshold 12. Duration difference below 0.05 seconds. |
| Decoded audio agreement | Same fixture decoded to 16 kHz mono signed PCM; MAE 0.0, non-silent signal, sample-count tolerance under 100; assertion threshold 0.01 full scale. |
| 30-clip/long project | 30 mixed inputs render to a 12.0-second 1080x1920 final MP4. A separate 30-clip, 600-second landscape proxy completes. |
| Worker cancellation | Real RenderWorker and PreviewRenderWorker cancel a running FFmpeg process, reap it, clean temporary directories and retain previous output. Qt timer continues firing; both complete cancellation under the 10-second test deadline. |
| Desktop bundle | `python build_desktop.py` passes and rebuilds `dist/vyro/vyro.exe`; its isolated offscreen self-test passes. Archived code matches all eight changed runtime modules. This is an onedir developer build, not an installer or clean-machine release. |
| Static checks | `compileall` for app/gui/tests/main and `git diff --check` pass. |

Matrix artifacts and machine-readable measurements: ignored `work/media-check/latest.json`.
GUI screenshots: ignored `work/editor-check/export-settings.png` and
`export-cancellation.png`. Intentional failure tests log simulated errors. Test execution
uses isolated DBs/directories and requires execution outside the sandbox's temporary
directory ACL restrictions in this development environment.

## Manually inspected

Code/diff review and visual inspection of automated offscreen export-settings and
export-cancellation screenshots at 1380x860. This is not a native interactive session
or listening test.

## Not verified

- Clean Windows installation, macOS/Linux runs, all target DPI/window combinations,
  GPU codecs, HDR/10-bit/color-managed output, rotation metadata and arbitrary damaged
  files. The tested HEVC path uses software decoding/encoding support in local FFmpeg.
- Full-resolution 10-minute stress with many high-resolution concurrent source streams,
  maximum 8-title/4-overlay compositions, extremely high-FPS media and 4K performance.
- Real-device listening, perceptual title/subtitle comparisons at every frame, disk-full
  and permission faults at every filesystem boundary, real power loss.
- Live OAuth, uploads, analytics and AI. This phase makes no provider requests.

## Known limitations

- Proxy is a lossy half-resolution render; exact pixels and rasterized font outlines
  differ. Sampled agreement is evidence for the fixture, not a guarantee for all media.
- Basic source playback remains an approximate view; use the existing effect-preview
  action for transitions/music/layers. Proxy preparation is not real time.
- Later effect passes show stage progress and may spend time at one percentage. Fixed
  conservative deadlines can reject unusually slow valid projects on weak machines.
- CFR conversion duplicates/drops frames for VFR; source FPS uses the first clip rather
  than a per-clip variable-rate timeline. Portrait and landscape presets remain fixed.
- The existing multi-pass encoder can accumulate compression loss; no single-pass
  compositor rewrite or loudness-processing expansion was attempted.
- Closing while a background operation runs still asks the user to wait. Render can
  now be cancelled first; broader scheduler/network shutdown belongs to later phases.
- Previous audit provider/scheduler/security/distribution gaps remain open.

## Next phase

Phase 3: editor UI/UX refinement, selection/inspector/timeline/keyboard behavior and
native resize/DPI verification. Stop here until the user requests that phase.
