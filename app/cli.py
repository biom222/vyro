from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from typing import Sequence

from app import __version__
from app.models import init_db
from app.services.content_pipeline import analyze_video_for_clips
from app.services.dashboard import get_dashboard_summary
from app.services.health import health_report
from app.services.scheduler import schedule_post
from app.services.scenes import suggest_scenes
from app.services.transcription import transcribe_video
from app.services.trends import refresh_youtube_trends
from app.services.youtube_oauth_server import run_local_youtube_oauth
from app.tasks import (
    probe_video,
    publish_video,
    render_video,
    run_scheduled_publications,
    sync_account_analytics,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="vyro technical core CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--verbose", action="store_true", help="Show diagnostic tracebacks")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("dashboard")
    commands.add_parser("doctor")
    commands.add_parser("refresh-trends")
    connect_youtube = commands.add_parser("connect-youtube")
    connect_youtube.add_argument(
        "--no-browser",
        action="store_true",
        help="Write the authorization URL to the log instead of opening the browser",
    )

    transcribe = commands.add_parser("transcribe")
    transcribe.add_argument("video_id", type=int)

    probe = commands.add_parser("probe")
    probe.add_argument("video_id", type=int)

    analyze = commands.add_parser("analyze")
    analyze.add_argument("project_id", type=int)
    analyze.add_argument("video_id", type=int)

    scenes = commands.add_parser("detect-scenes")
    scenes.add_argument("project_id", type=int)
    scenes.add_argument("video_id", type=int)

    schedule = commands.add_parser("schedule")
    schedule.add_argument("post_id", type=int)
    schedule.add_argument("when", help="ISO-8601 timestamp including timezone")

    render = commands.add_parser("render")
    render.add_argument("video_id", type=int)
    render.add_argument("--start", type=float, default=0.0)
    render.add_argument("--end", type=float)
    render.add_argument("--no-vertical", action="store_true")
    render.add_argument("--text", default="")

    publish = commands.add_parser("publish")
    publish.add_argument("post_id", type=int)

    analytics = commands.add_parser("sync-analytics")
    analytics.add_argument("account_id", type=int)
    analytics.add_argument("start_date", type=date.fromisoformat)
    analytics.add_argument("end_date", type=date.fromisoformat)

    commands.add_parser("run-scheduler")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        init_db()
        if args.command == "init-db":
            print("Database is ready.")
        elif args.command == "dashboard":
            print(json.dumps(asdict(get_dashboard_summary()), ensure_ascii=False, indent=2, default=str))
        elif args.command == "doctor":
            report = health_report()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if all(item["ok"] for item in report) else 1
        elif args.command == "refresh-trends":
            print(json.dumps({"trend_video_ids": refresh_youtube_trends()}))
        elif args.command == "connect-youtube":
            result = run_local_youtube_oauth(open_browser=not args.no_browser)
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        elif args.command == "probe":
            probe_video(args.video_id)
            print(json.dumps({"video_id": args.video_id, "status": "probed"}))
        elif args.command == "transcribe":
            print(json.dumps({"transcript_id": transcribe_video(args.video_id)}))
        elif args.command == "analyze":
            pack, candidates = analyze_video_for_clips(args.project_id, args.video_id)
            print(
                json.dumps(
                    {"content_pack": pack.model_dump(), "clip_candidate_ids": candidates},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "detect-scenes":
            print(json.dumps({"clip_candidate_ids": suggest_scenes(args.project_id, args.video_id)}))
        elif args.command == "schedule":
            when = datetime.fromisoformat(args.when)
            if when.tzinfo is None:
                raise ValueError("Schedule timestamp must include a timezone, for example +03:00")
            schedule_post(args.post_id, when)
            print("Post scheduled.")
        elif args.command == "render":
            output, duration = render_video(
                args.video_id,
                {
                    "start_time": args.start,
                    "end_time": args.end,
                    "is_vertical": not args.no_vertical,
                    "subtitle_text": args.text,
                },
            )
            print(json.dumps({"output_path": output, "duration": duration}, ensure_ascii=False))
        elif args.command == "publish":
            publish_video(args.post_id)
            print(json.dumps({"post_id": args.post_id, "status": "submitted"}))
        elif args.command == "sync-analytics":
            snapshot_id = sync_account_analytics(
                args.account_id, args.start_date, args.end_date
            )
            print(json.dumps({"analytics_snapshot_id": snapshot_id}))
        elif args.command == "run-scheduler":
            print(json.dumps({"published_post_ids": run_scheduled_publications()}))
        return 0
    except Exception as exc:
        if args.verbose:
            logger.exception("Command %s failed", args.command)
        else:
            logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
