# Phase 5 - Live YouTube E2E

Date: 2026-11-05. **LIVE VERIFIED**, scoped to one approved private synthetic upload
through existing services on Windows. Not a production release or native GUI signoff.

## Done

- Real browser OAuth, channel discovery/active selection and OS-keyring persistence.
  The initial Google Testing denial was resolved by the user adding their test account.
- Exactly one approved six-second 1080x1920 H.264/AAC synthetic MP4 was uploaded with
  title `vyro YouTube API test`, empty description and private visibility. The user
  explicitly approved the target channel/media/privacy; no personal footage was used.
- Separate processes queried the real provider ID using videos.list: first
  uploaded/processing, then processed/succeeded, matching owner, actual privacy private.
  The test video remains on the channel. A subsequent repeated-operation check was
  blocked before the adapter, with zero additional upload calls.
- Upload progress and durable intent/ID checkpoints; actual remote status/privacy;
  safe provider errors; same-session recovery after a lost upload acknowledgement.
- The publication screen restores recent YouTube operations from SQLite after restart
  and explicitly checks status without another upload. History and scheduler paths
  cannot automatically resend known/uncertain YouTube operations.

## Architecture

Existing PKCE/state/local callback, keyring, account, task and QThread services are
reused. State is checked before success or denial, callbacks are accepted once, and
transient state is cleaned on success/bind/browser/timeout errors. Callback logs omit
query strings; YouTube errors omit response bodies/URLs. Entry points suppress normal
HTTP client INFO request logs. Broader logging hardening remains a later phase.

Post JSON records `youtube_upload_attempted` before media bytes and checkpoints the
provider ID after acknowledgement. Acknowledgement means pending; only remote status
verification can mark it published. Published means processed, not necessarily public.
Requested/actual privacy are distinct. Uncertain PUT queries the same session once,
never a new insert. Unified publication state/operation design remains Phase 8.

## Changed files

Runtime: `app/cli.py`, `app/tasks.py`, `app/services/direct_publishing.py`,
`app/services/scheduler.py`, `app/services/youtube_oauth.py`,
`app/services/youtube_oauth_server.py`, new `app/services/youtube_errors.py`,
`gui/history_widget.py`, `gui/publish_widget.py`, `gui/worker.py`, root `main.py`.
Engineering: new `tools/youtube_live.py`, `tests/test_desktop.py`, README,
PRODUCT_STATUS, TECHNICAL_CORE, PRODUCTION_ROADMAP, DECISIONS and this report.

## Migrations

No new schema migration. Existing Post JSON/status/ID fields hold checkpoints/results.
The source-mode run upgraded checkout SQLite to existing head `7c1e4d2a9100` through
the verified-backup workflow. The installed AppData database was not modified.
These are separate profiles: an account connected in source mode is not automatically
copied into the installed profile. Connect OAuth in the profile you actually use.
Live identifiers/reports are ignored under `work/youtube-e2e/`; tokens stay in keyring.

## Tests

`python -m unittest discover -s tests -q`: **71 passed**, Windows/Python 3.13.1.
New contracts cover pending acknowledgement, processing/privacy/owner, missing video,
same-session lost-response recovery with one insert, progress/checkpoint order,
duplicate operations/posts, revoked refresh preserving credentials, safe quota errors,
and actual loopback wrong-state/denied callback handling. Existing regression passes.

`python build_desktop.py` rebuilt `dist/vyro/vyro.exe`; its isolated offscreen self-test
passed. Embedded bytecode matches source for all nine changed bundled service/GUI
modules. This is local bundle startup evidence, not clean-machine release acceptance.

Live checks used `tools/youtube_live.py connect`, approved `upload-test`, and `status`
in new processes. The helper refuses a second test operation when its local marker
exists. Never remove that marker to retry blindly. Real errors were not induced on
the user's channel; simulated contracts are distinct from live success evidence.

## Manually inspected

The user completed browser consent. The target channel and neutral clip were presented
before explicit upload approval. API responses, persisted result and duplicate guard
were inspected locally. No authenticated browser automation was used.

## Not verified

Native GUI upload click-through; earlier Windows resizing/DPI manual gate; live token
expiry/revocation/quota/removed-channel/network-disconnect cases; public/unlisted or
large live uploads; Brand-account edge cases; clean-machine installation/signing.
Live analytics, AI, TikTok and Instagram remain separate phases.

## Known limitations

- Progress measures bytes consumed by HTTP transport, not server processing percent.
- Unknown operations without provider IDs require manual channel inspection. Automatic
  resumable transfer across restarts is absent; reconciliation is explicit in the UI.
- Local operation/account/video/pinned-path protection is not content-hash deduplication
  or a remote exactly-once guarantee. A new export can still contain identical media.
- OAuth Testing is developer configuration, not Google verification of a released app.
  Testing token restrictions and quotas may affect subsequent sessions.

## Next phase

Phase 6: official TikTok OAuth/capabilities/upload/status/restart E2E, reporting real
approval/credential blockers explicitly. Do not begin automatically.

## Official references

- [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Audience/test users](https://support.google.com/cloud/answer/15549945)
- [Resumable uploads](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [videos.list](https://developers.google.com/youtube/v3/docs/videos/list)
- [Video status fields](https://developers.google.com/youtube/v3/docs/videos)
