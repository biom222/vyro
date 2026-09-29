# vyro

Cross-platform PyQt6 desktop application for trimming, positioning a vertical crop, captioning, exporting, and publishing vertical videos. All media processing runs locally through FFmpeg in `QThread`; no FastAPI server, Redis, or RQ worker is required.

## Features

- Eight-section creator workspace with dashboard, editor, AI clips, trends,
  content calendar, publishing, history, and settings
- Built-in video preview, clip timeline, and in/out point controls
- Ordered multi-clip assembly with per-clip trim, cut/dissolve transitions, and optional music
- Up to four independent silent picture-in-picture video layers and eight animated title layers
- Keyframes for title position and opacity with linear interpolation
- Cached low-resolution preview with transitions, music, subtitles, and layers before final export
- Local SQLite database through SQLAlchemy
- Background FFprobe inspection with duration and resolution
- Time trim, optional 1080×1920 crop with manual horizontal positioning, and Unicode text overlay
- Stage-based render progress without blocking the interface
- Save As export for completed MP4 files
- Direct YouTube, TikTok, and Instagram account connection and publishing in background threads
- Top Accounts menu with per-service account submenus and a checked active publishing target
- SQLite history with details and repeat publishing
- Speech-to-text and AI clip suggestions with one-click transfer to the editor
- Local FFmpeg scene-change suggestions (visual cuts only, not semantic ranking)
- Optional automatic timed subtitle burn from saved transcripts, aligned to sequence trims
- Trend discovery with scoring, copyright-risk hints, idea generation, and a short-video topic search
- Active-account analytics dashboard and YouTube OAuth connection flow
- Immediate or scheduled publication with a local background scheduler
- Flat dark/light desktop themes, top menus, a compact action toolbar, and an operation log

## Technical core

The backend is now independent from the GUI and includes:

- Projects, videos, timed transcripts, clip candidates, content ideas, connected accounts,
  analytics snapshots, trend snapshots, and scheduled posts
- Local faster-whisper adapter with a dependency-free mock provider
- SRT/VTT generation and FFmpeg subtitle burning
- Pluggable content assistant with deterministic mock mode and OpenAI Responses API mode
- YouTube `mostPopular` trend ingestion with historical snapshots and a velocity score
- YouTube Analytics normalization for an OAuth-connected active account
- PKCE OAuth request/token helpers; refresh tokens are referenced from the database and stored
  in the operating-system keyring
- Local post scheduler and a dashboard aggregation service
- Atomic publication claiming, retry/backoff, and duplicate-publication protection
- OAuth state persistence/validation and automatic access-token refresh for Analytics
- Idempotent Analytics periods and deduplicated unchanged trend snapshots
- Shared retry handling for transient HTTP, 429, and 5xx failures
- Copyright-risk hints that always require manual review
- A CLI and environment doctor for headless administration and diagnostics
- Alembic migrations with automatic upgrades and a backup/stamp path for legacy SQLite databases
- Local YouTube OAuth callback server with PKCE/state validation and channel discovery
- A graceful background scheduler that starts and stops with the desktop process

The GUI calls this technical core through `QThread` workers, so FFmpeg, speech recognition,
network requests, and AI analysis do not block the interface.

## Requirements

- Python 3.11 or newer
- FFmpeg and FFprobe available on `PATH`

FFmpeg is available from [ffmpeg.org](https://ffmpeg.org/download.html). On Windows, verify installation with `ffmpeg -version` and `ffprobe -version` in a new terminal.

## Installation

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS/Linux
source .venv/bin/activate
```

Install dependencies and prepare configuration:

```bash
pip install -r requirements.txt
```

For real local speech-to-text, install the optional AI dependencies as well:

```bash
pip install -r requirements-ai.txt
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS/Linux
cp .env.example .env
```

## Run

The editor opens on startup. Import a video or double-click a recent item in the media
library. Drag the amber clip edges to trim, click the ruler to seek, and use the timeline
zoom selector for precise edits. The inspector has **Клип** and **Текст** tabs; center
crop position and caption style appear in the preview before export. Click **Экспортировать MP4**
in the top toolbar to render; the editor remains open. The operation log is available
through **Журнал** in the bottom bar.

To burn timed subtitles, recognize speech for the source in **AI-клипы**, then enable
**Субтитры из распознанной речи** in the editor's **Текст** tab. Each clip with a
saved transcript contributes cues in its exported time range.

The editor supports a sequence of up to 30 source clips, one caption overlay on the
finished video, cut or dissolve transitions, and one background music track. Add clips
on the **Сборка** tab; select a row to preview and trim that source. **Видеослои** adds
project clips above the sequence with independent in/out times, source offset, size,
position, and opacity. Overlay video audio is intentionally muted. **Титры и ключевые
кадры** adds timed titles and animated position/opacity; keyframe values interpolate
linearly. Both kinds of layers are saved in the editable SQLite project.

**Просмотр сборки** plays source clips in order without effects. **Просмотр с переходами
и музыкой** builds a cached 540×960 (or 640×360) FFmpeg proxy that includes the same
transition, audio mix, subtitles, video layers, and title layers as the final export.
The proxy is not a full-resolution MP4 export, but generating it can still take time.
Playback uses decoded Qt video frames on a painted canvas; paused seeking has an FFmpeg fallback.
If the playback decoder cannot open a file, the UI reports the error and permits frame
inspection through FFmpeg rather than leaving an unexplained black preview.

```bash
python main.py
```

On Windows, you can also double-click `Запустить vyro.bat` in the project folder.

The application upgrades `video_editor.sqlite3` to the latest Alembic revision automatically.
Before adopting or upgrading an existing SQLite database, it writes a timestamped backup to `data/`.
Rendered files are written to `outputs/` before they can be copied elsewhere with **Сохранить как…**.

Projects are editable drafts stored in the local SQLite database; an MP4 is needed only for
export or publication. Changes to clip order/ranges, music, transitions, overlays, title keyframes, caption/style, crop,
and the selected clip are saved automatically. Use **Файл → Сохранить проект** (`Ctrl+S`) to
save immediately, then **Файл → Открыть проект…** or **История → Проекты** to resume editing.
Newly imported videos and music selected through the GUI are copied into `uploads/` in a
background thread, so moving the original files does not break new projects. Older projects
may still reference external paths. If a video source is missing, open its details under
**История → Видео и публикации** and use **Перепривязать исходник…**; the replacement must
match the original duration and resolution. Relinking invalidates the previous export, so
render again before publishing. Missing files are reported when reopening a project.

## Technical CLI

Initialize or upgrade the SQLite schema and verify the machine:

```powershell
.\.venv\Scripts\python.exe -m app.cli init-db
.\.venv\Scripts\python.exe -m app.cli doctor
```

Other available commands:

```text
python -m app.cli dashboard
python -m app.cli connect-youtube
python -m app.cli refresh-trends
python -m app.cli transcribe VIDEO_ID
python -m app.cli probe VIDEO_ID
python -m app.cli analyze PROJECT_ID VIDEO_ID
python -m app.cli detect-scenes PROJECT_ID VIDEO_ID
python -m app.cli render VIDEO_ID --start 0 --end 30 --text "Caption"
python -m app.cli publish POST_ID
python -m app.cli sync-analytics ACCOUNT_ID 2026-09-01 2026-09-30
python -m app.cli schedule POST_ID 2026-10-01T18:30:00+03:00
python -m app.cli run-scheduler
```

AI ideas and the general trend feed work in mock mode by default. Topic search for real
3–90 second YouTube videos requires `YOUTUBE_API_KEY`; it reads public metadata and
statistics but does not analyze video frames or establish reuse rights. YouTube search
with a date filter can omit matching videos, so the results are discovery leads rather
than a complete ranking. Set `TRANSCRIPTION_PROVIDER=faster-whisper`,
`AI_PROVIDER=openai`, or `TRENDS_MOCK_MODE=false` only after configuring the corresponding
dependencies and keys in `.env`.

The current development machine has faster-whisper installed and the `tiny` model cached under
`cache/whisper`. Use `WHISPER_MODEL=small` later for better accuracy at the cost of a larger download
and slower CPU inference.

The **Найти смены сцен** action in AI-клипы scans the selected local video with FFmpeg and
adds timestamped shot suggestions without an AI key. It does not identify dramatic moments
or grant reuse rights; review each suggestion before editing or publishing.

## Desktop bundle

Install the optional build dependency and build on the operating system you want to ship:

```bash
python -m pip install -r requirements-build.txt
python build_desktop.py
```

The output is `dist/vyro/` (with `vyro.exe` on Windows). PyInstaller
builds for the current operating system only. The build script runs an isolated
offscreen startup check against the bundled executable. FFmpeg and FFprobe must still be on the
machine's `PATH`. In a bundled installation, `.env`, SQLite, rendered files, and logs
live under `%LOCALAPPDATA%/vyro` on Windows,
`~/Library/Application Support/vyro` on macOS, or
`${XDG_DATA_HOME:-~/.local/share}/vyro` on Linux. Existing installations that already
have a `ShortsStudio` data folder continue using it so their projects and media remain
available without an automatic move. Copy `.env.example` to the active data folder
if live services are needed. The source checkout continues to use its own `.env` and data.

## Git repository

The repository contains source code, migrations, tests, and `.env.example` only.
Personal `.env` files, SQLite databases, imported media, rendered videos, AI model caches,
logs, virtual environments, and PyInstaller output are ignored. Never commit API keys,
OAuth credentials, or project footage. Build the desktop executable locally with
`python build_desktop.py`; the entire `dist/vyro/` directory is needed to run it.
The executable inside this checkout reads the checkout's `.env` while keeping its media
and database in the application data directory. A copy distributed outside the checkout
reads `.env` from that application data directory instead. The Settings page shows the
actual configuration path so a stale or separately installed executable is easy to identify.

## Direct account connection and publication

Copy `.env.example` to `.env` and register developer applications with the providers you plan to use. Set `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`, `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET`, and/or `INSTAGRAM_APP_ID`/`INSTAGRAM_APP_SECRET`. Register the exact corresponding loopback redirect URI shown in `.env.example` with each provider. Enable the upload/publishing scopes and obtain any required app approval.

Open **Аккаунты** in the top menu, hover over a service, and choose **Добавить аккаунт…**. Authorization opens in the browser. Connected accounts appear under that service; a check mark identifies the current publishing target. Choose an account before going to **Публикация**. The post stores that account ID, so changing the menu selection later will not redirect a scheduled post. OAuth tokens are kept in the operating system credential store; do not put account tokens in the repository.

The publication screen offers the selected account's TikTok privacy options or YouTube visibility. Confirm the target before sending. Instagram publication supports professional accounts connected to a Facebook Page and creates Reels. TikTok and Instagram can remain in a pending state while the provider processes the upload; vyro polls for completion without uploading a second copy. If the provider's response is uncertain, inspect the account before retrying. With no developer keys, the editor and export still work, but live publication is unavailable; the old Taisly mock is no longer used by the desktop workflow.

Provider restrictions apply: YouTube uploads from unverified API projects can be private-only, TikTok unaudited clients are restricted to private viewing, and Instagram requires a professional account and applicable Meta permissions. These are provider-side requirements, not settings vyro can bypass.

## Project structure

```text
app/
  config.py             Environment settings
  models.py             SQLAlchemy models and SQLite initialization
  video_processor.py    FFprobe and FFmpeg pipeline
  publisher.py          Legacy web-prototype Taisly client (unused by desktop)
  tasks.py              Synchronous local operations
  cli.py                Headless commands and diagnostics
  services/             Projects, media, AI, trends, direct publishing, OAuth, scheduler
gui/
  worker.py             QThread workers
  main_window.py        Top menus, action toolbar, page navigation, and log
  accounts_menu.py      Service icons, connected account submenus, and active target
  theme.py              Shared flat palette, system fonts, and monochrome icons
  dashboard_widget.py   Active-account metrics and recent videos
  editor_workspace.py   Preview player, timeline, upload, and render controls
  sequence_widget.py    Ordered clips, per-clip ranges, transitions, and music
  layers_widget.py      Animated title layers and keyframe editing
  video_layers_widget.py  Independent video overlay tracks
  ai_clips_widget.py    Transcription and AI clip candidates
  trends_widget.py      Trend discovery and content ideas
  calendar_widget.py    Scheduled publication calendar
  settings_widget.py    OAuth accounts, modes, and environment health
  upload_widget.py      Video selection and metadata inspection
  edit_widget.py        Edit controls, progress, and export
  publish_widget.py     Account-targeted direct publishing and status polling
  history_widget.py     SQLite project history and repeat publishing
main.py                 Desktop entry point
```

`app/main.py`, `app/templates/`, and `app/static/` are retained only for compatibility with the earlier web prototype. They are not loaded by the desktop application.

## Tests

The tests use an offscreen Qt platform and do not require a display server:

```bash
python -m unittest discover -s tests -v
```

For the real FFmpeg/Qt editor integration check (playback, decoded frames, mouse trim,
preview, export, reopening edits, and screenshots at two window sizes):

```bash
python tests/editor_smoke.py
```

It creates test media, an isolated database, and screenshots under `work/editor-check/`.

They cover Alembic upgrades, database updates, projects, transcripts, subtitle formats, AI contracts, trend snapshots,
OAuth refresh, idempotent analytics, scheduler failure isolation, duplicate-publication protection,
OAuth channel connection, mocked direct API upload contracts, background scheduler lifecycle, probe/render contracts, and construction of
the complete eight-section workspace.

An optional containerized headless check remains available:

```bash
docker compose up --build --abort-on-container-exit
```

The desktop GUI itself should be launched directly on the host with `python main.py`; displaying a native GUI from Docker is intentionally outside this MVP.
