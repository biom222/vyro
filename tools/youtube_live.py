"""Explicit live YouTube checks; never log tokens, authorization codes or session URLs."""
from pathlib import Path
import argparse
import json
import logging
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.models import Post, SessionLocal, init_db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("connect", "status", "upload-test"))
    parser.add_argument("--post-id", type=int)
    parser.add_argument("--account-id", type=int)
    parser.add_argument("--confirm-private-test", action="store_true")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    directory = ROOT / "work" / "youtube-e2e"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if settings.credential_backend != "keyring":
            raise ValueError("Live OAuth requires CREDENTIAL_BACKEND=keyring")
        init_db()
        if args.command == "connect":
            from app.services.youtube_oauth_server import run_local_youtube_oauth
            result = run_local_youtube_oauth(timeout_seconds=300)
            report = {"status": "connected", "account_id": result.account_id,
                      "channel_id": result.channel_id, "display_name": result.display_name}
        elif args.command == "upload-test":
            from app.models import ConnectedAccount, Video
            from app.tasks import publish_video
            from app.video_processor import probe_video_metadata
            if not args.confirm_private_test or not args.account_id:
                raise ValueError("Explicit private test approval and account ID are required")
            marker = directory / "upload-operation.json"
            if marker.exists():
                raise ValueError("Test operation already exists; check its post status instead of uploading again")
            path = directory / "vyro-private-test.mp4"
            duration, width, height = probe_video_metadata(path)
            with SessionLocal.begin() as session:
                account = session.get(ConnectedAccount, args.account_id)
                if not account or account.provider != "youtube" or account.status != "connected":
                    raise ValueError("Connected YouTube account required")
                video = Video(filename=path.name, original_path=str(path), output_path=str(path),
                              duration=duration, output_duration=duration,
                              width=width, height=height, status="ready")
                session.add(video)
                session.flush()
                post = Post(video_id=video.id, account_id=account.id, platform="youtube",
                            title="vyro YouTube API test", description="", status="queued",
                            payload_json={"youtube_privacy": "private", "media_path": str(path),
                                          "media_duration": duration})
                session.add(post)
                session.flush()
                post_id = post.id
            marker.write_text(json.dumps({"post_id": post_id}), encoding="utf-8")
            publish_video(post_id)
            with SessionLocal() as session:
                post = session.get(Post, post_id)
                report = {"status": post.status, "post_id": post.id,
                          "external_id": post.external_id, "url": post.external_url}
        else:
            from app.tasks import refresh_publication
            status = refresh_publication(args.post_id)
            with SessionLocal() as session:
                post = session.get(Post, args.post_id)
                report = {"status": status, "post_id": post.id, "external_id": post.external_id,
                          "url": post.external_url, "verification": post.payload_json}
        (directory / f"{args.command}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
        return 0
    except Exception as exc:
        report = {"status": "blocked", "error_type": type(exc).__name__, "message": str(exc)}
        (directory / f"{args.command}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
