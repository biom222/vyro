# Technical core status

## Implemented

| Area | Current implementation |
| --- | --- |
| Storage | SQLite/SQLAlchemy models plus Alembic baseline, automatic upgrades, and legacy backups |
| Video | FFprobe metadata, managed import/relink, trim, manually positioned 9:16 crop, multi-clip cut/dissolve assembly, optional music, static text, transcript-aligned subtitle burn, MP4 export |
| Transcription | Mock and real faster-whisper providers, cached tiny model, timed segments, progress/cancellation |
| AI | Provider interface, deterministic mock, OpenAI Responses API with strict JSON Schema output |
| Clip ideas | Transcript-to-content-pack pipeline with range validation and persisted candidates |
| Scene changes | Local FFmpeg shot-boundary scan with deduplicated timestamp suggestions; no semantic or copyright judgment |
| Trends | YouTube public API adapter, short-video topic search, mock fixtures, metrics snapshots, trend score |
| Rights safety | Heuristic risk label plus mandatory manual-review language |
| Analytics | Automatic OAuth refresh, normalized/idempotent snapshots, active-account dashboard summary |
| Accounts | Account registry, local OAuth callback, PKCE/state validation, channel discovery, configurable credential store |
| Publishing | Taisly/mock publishing, atomic claims, duplicate protection, retry/backoff, background scheduler |
| Operations | Headless CLI, machine health checks, mock-first configuration, unit tests |

## Intentionally not completed yet

- Multi-layer compositing, animated titles, keyframes, semantic scene understanding,
  and an effects-accurate preview of the entire assembled sequence. Current continuous
  preview follows clip order and trims but not rendered transitions or mixed music.
- Live provider setup and end-to-end verification with connected accounts. The default
  configuration uses mock AI, mock trends, and mock publishing.
- Direct YouTube upload. Taisly remains the publishing transport in this iteration.
- TikTok and Instagram analytics. Their official API access and review requirements must be
  evaluated separately; no scraping fallback will be added.
- Semantic scene detection, face tracking, and smart reframing. The current clip analyzer uses
  transcript/content signals and center crop.
- A PyInstaller onedir build script exists; signed installers and cross-platform bundle
  verification are still pending.

## Configuration modes

The repository starts without paid services:

```text
AI_PROVIDER=mock
TRANSCRIPTION_PROVIDER=mock
TRENDS_MOCK_MODE=true
TAISLY_API_KEY=
```

Real integrations are enabled independently. This keeps local rendering and project management
usable when an external provider is unavailable.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m app.cli doctor
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
