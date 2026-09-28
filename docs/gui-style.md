# Desktop GUI conventions

Use dense, functional desktop layouts inspired by OBS Studio, Audacity, Kdenlive,
and HandBrake. Do not use marketing-page or card-dashboard layouts.

- Navigation uses `QMenuBar`; frequent actions use `QToolBar` and standard,
  monochrome icons. Do not add a sidebar.
- Use `QSplitter` for resizable work areas and Qt item views for lists/tables.
- Separate sections with spacing. Avoid decorative frame borders, shadows,
  gradients, repeated metric cards, and oversized headings.
- Corner radii are zero or two pixels. No emoji in interface text.
- The single interface accent is amber `#d97706`.
- Dark theme: background `#1a1a1a`, surface `#242424`, text `#e5e5e5`,
  muted text `#8a8a8a`.
- Light theme: background `#f5f5f5`, surface `#ffffff`, text `#1a1a1a`.
- Interface fonts are Segoe UI on Windows, SF Pro Text on macOS, and Cantarell
  on Linux, with system fallback. Normal text is 12px; secondary labels may be 11px.
- Keep interface styling in `gui/theme.py`. Painted widgets use palette roles.
  Caption colors/fonts belong to the edited video and are independent of the UI theme.

Switch themes using **View / Theme** (`Вид / Тема`). Sections are available in
**View** (`Вид`); the operation log can also be toggled there.

Verify changes in both themes and at 1040×700 and 1380×860. Run
`python tests/editor_smoke.py` to exercise import, decoded playback, trimming,
live crop/caption preview, export, and reopening saved edits. This offscreen test
also captures editor and dashboard screenshots under `work/editor-check/`.
