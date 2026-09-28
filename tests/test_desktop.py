import os
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_ROOT.name, 'test.sqlite3').as_posix()}"
os.environ["UPLOAD_FOLDER"] = str(Path(TEST_ROOT.name, "uploads"))
os.environ["OUTPUT_FOLDER"] = str(Path(TEST_ROOT.name, "outputs"))
os.environ["TAISLY_API_KEY"] = ""

from PyQt6.QtWidgets import QApplication

from app.models import (
    AnalyticsSnapshot,
    ConnectedAccount,
    Post,
    Project,
    SessionLocal,
    Transcript,
    TranscriptSegment,
    TrendSnapshot,
    Video,
    engine,
    init_db,
)
from app.config import settings
from app.database import current_revision, head_revision
from app.services.ai import MockContentAssistant, OpenAIContentAssistant
from app.services.accounts import get_active_account_id, set_active_account, upsert_account
from app.services.analytics import AnalyticsDataError, store_youtube_snapshot, sync_youtube_analytics
from app.services.content_pipeline import analyze_video_for_clips
from app.services.credentials import MemoryCredentialStore
from app.services.dashboard import get_dashboard_summary
from app.services.media_library import relink_video, store_imported_video, store_project_music
from app.services.projects import create_project_for_video
from app.services.scheduler import run_due_posts, schedule_post
from app.services.scheduler_runner import LocalScheduler
from app.services.scenes import scene_ranges, suggest_scenes
from app.services.subtitles import SubtitleCue, render_srt, render_vtt
from app.services.transcription import MockTranscriber, transcribe_video as transcribe
from app.services.trends import (
    YouTubeTrendClient, calculate_trend_score, refresh_short_clip_trends,
    refresh_youtube_trends,
)
from app.services.youtube_oauth import (
    build_authorization_request,
    get_valid_access_token,
    save_youtube_account_tokens,
)
from app.services.youtube_oauth_server import complete_youtube_oauth
from app.tasks import probe_video, publish_video, render_video
from app.video_processor import (
    VideoProcessingError, _auto_subtitles, _keyframe_expression,
    _validated_title_layers, _validated_video_layers, make_vertical,
)
from gui.main_window import MainWindow
from gui.publish_widget import PublishWidget


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.qt_app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        TEST_ROOT.cleanup()

    def create_video(self, name: str = "source.mp4") -> int:
        source = Path(TEST_ROOT.name, name)
        source.write_bytes(b"video")
        with SessionLocal() as session:
            video = Video(
                filename=source.name,
                original_path=str(source),
                status="queued",
            )
            session.add(video)
            session.commit()
            session.refresh(video)
            return video.id

    def test_title_keyframes_and_project_video_layers(self):
        primary_id = self.create_video("layer-primary.mp4")
        overlay_id = self.create_video("layer-overlay.mp4")
        foreign_id = self.create_video("layer-foreign.mp4")
        project = create_project_for_video(primary_id)
        create_project_for_video(foreign_id)
        with SessionLocal() as session:
            for video_id in (primary_id, overlay_id, foreign_id):
                session.get(Video, video_id).duration = 5
            session.get(Video, overlay_id).project_id = project.id
            session.commit()
        title = {"text": "Motion", "start": 0, "end": 3,
                 "keyframes": [{"time": 0, "x": 0.2, "y": 0.8, "opacity": 0},
                               {"time": 3, "x": 0.8, "y": 0.2, "opacity": 1}]}
        validated = _validated_title_layers([title], 4)
        self.assertEqual(len(validated[0]["keyframes"]), 2)
        self.assertIn("if(lt(t,3.0000)", _keyframe_expression(validated[0]["keyframes"], "x"))
        with self.assertRaises(VideoProcessingError):
            _validated_title_layers([{**title, "start": float("nan")}], 4)
        with self.assertRaises(VideoProcessingError):
            _validated_title_layers([{**title, "end": 5}], 4)
        overlay = {"video_id": overlay_id, "start": 1, "end": 3,
                   "source_start": 0, "x": 0.5, "y": 0.1,
                   "width": 0.5, "opacity": 0.8}
        self.assertEqual(_validated_video_layers([overlay], primary_id, 4)[0]["path"].name,
                         "layer-overlay.mp4")
        with self.assertRaises(VideoProcessingError):
            _validated_video_layers([{**overlay, "video_id": foreign_id}], primary_id, 4)
        with self.assertRaises(VideoProcessingError):
            _validated_video_layers([{**overlay, "source_start": 4}], primary_id, 4)

    def test_import_copies_source_into_managed_storage(self):
        video_id = self.create_video("managed.mp4")
        original = Path(TEST_ROOT.name, "managed.mp4")
        progress = []
        stored = store_imported_video(video_id, progress.append)
        self.assertEqual(stored.parent, settings.upload_folder)
        self.assertEqual(stored.read_bytes(), b"video")
        self.assertEqual(original.read_bytes(), b"video")
        self.assertEqual(progress[-1], 100)
        self.assertEqual(store_imported_video(video_id), stored)
        with SessionLocal() as session:
            self.assertEqual(session.get(Video, video_id).original_path, str(stored))

    @patch("app.video_processor.probe_video_metadata", return_value=(12.5, 1920, 1080))
    def test_relink_validates_before_replacing_source(self, _probe):
        video_id = self.create_video("old-source.mp4")
        replacement = Path(TEST_ROOT.name, "replacement.mp4")
        replacement.write_bytes(b"replacement")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            old_path = video.original_path
            video.duration = 12.5
            video.width = 1920
            video.height = 1080
            video.status = "error"
            video.output_path = str(Path(TEST_ROOT.name, "old-export.mp4"))
            session.commit()
        with patch("app.video_processor.probe_video_metadata", return_value=(9.0, 1920, 1080)):
            with self.assertRaisesRegex(ValueError, "duration"):
                relink_video(video_id, replacement)
        with SessionLocal() as session:
            self.assertEqual(session.get(Video, video_id).original_path, old_path)
        managed = relink_video(video_id, replacement)
        self.assertEqual(managed.read_bytes(), b"replacement")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            self.assertEqual(video.original_path, str(managed))
            self.assertEqual(video.status, "uploaded")
            self.assertIsNone(video.output_path)

    @patch("app.services.media_library.subprocess.run")
    def test_music_import_creates_managed_copy(self, probe):
        probe.return_value.returncode = 0
        probe.return_value.stdout = "0\n"
        source = Path(TEST_ROOT.name, "sound.wav")
        source.write_bytes(b"audio")
        stored = store_project_music(source)
        self.assertEqual(stored.parent, settings.upload_folder)
        self.assertEqual(stored.read_bytes(), b"audio")
        self.assertTrue(source.is_file())
        self.assertEqual(store_project_music(stored), stored)

    def test_scene_suggestions_are_clamped_and_idempotent(self):
        video_id = self.create_video("scenes.mp4")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            video.duration = 10.0
            session.commit()
        project = create_project_for_video(video_id)
        self.assertEqual(scene_ranges([1.0, 4.0], 10.0), [(0.0, 4.0), (4.0, 10.0)])
        with patch("app.services.scenes.detect_scene_cuts", return_value=[4.0]):
            first = suggest_scenes(project.id, video_id)
            second = suggest_scenes(project.id, video_id)
        self.assertEqual(len(first), 2)
        self.assertEqual(second, [])

    @patch("app.video_processor._run")
    def test_vertical_crop_uses_selected_horizontal_position(self, run_command):
        make_vertical("source.mp4", "result.mp4", 0.25)
        command = run_command.call_args.args[0]
        self.assertIn("(iw-ow)*0.2500", command[command.index("-vf") + 1])

    @patch("app.tasks.probe_video_metadata", return_value=(12.5, 1920, 1080))
    def test_probe_updates_video_metadata(self, _probe):
        video_id = self.create_video("probe.mp4")
        probe_video(video_id)
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            self.assertEqual(video.status, "uploaded")
            self.assertEqual(video.duration, 12.5)
            self.assertEqual((video.width, video.height), (1920, 1080))

    def test_render_reports_progress_and_updates_video(self):
        video_id = self.create_video("render.mp4")
        output = Path(TEST_ROOT.name, "outputs", "rendered.mp4")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            video.status = "uploaded"
            video.duration = 15.0
            session.commit()

        observed_progress: list[int] = []

        def fake_process(_video_id, _params, callback):
            callback(5)
            callback(100)
            return str(output), 10.0

        with patch("app.tasks.process_video", side_effect=fake_process):
            result = render_video(
                video_id,
                {"start_time": 1.0, "end_time": 11.0, "is_vertical": True},
                observed_progress.append,
            )

        self.assertEqual(result, (str(output), 10.0))
        self.assertEqual(observed_progress, [5, 100])
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            self.assertEqual(video.status, "ready")
            self.assertEqual(video.output_duration, 10.0)

    def test_mock_publication_updates_post(self):
        video_id = self.create_video("publish.mp4")
        output = Path(TEST_ROOT.name, "outputs", "publish-ready.mp4")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            video.status = "ready"
            video.output_path = str(output)
            video.output_duration = 8.0
            post = Post(
                video_id=video_id,
                platform="mock-youtube",
                title="Demo",
                description="Caption",
                status="queued",
            )
            session.add(post)
            session.commit()
            session.refresh(post)
            post_id = post.id

        publish_video(post_id)
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            self.assertEqual(post.status, "published")
            self.assertTrue(post.external_id.startswith("mock-"))

    def test_duplicate_publication_cannot_steal_an_active_post(self):
        video_id = self.create_video("duplicate-publish.mp4")
        with SessionLocal() as session:
            post = Post(
                video_id=video_id,
                platform="mock-youtube",
                status="publishing",
            )
            session.add(post)
            session.commit()
            post_id = post.id
        with self.assertRaisesRegex(ValueError, "cannot be published"):
            publish_video(post_id)
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            self.assertEqual(post.status, "publishing")
            self.assertEqual(post.retry_count, 0)

    def test_main_window_has_complete_workspace(self):
        window = MainWindow()
        self.assertEqual(window.pages.count(), 8)
        self.assertEqual(
            [item[2] for item in window.PAGE_ORDER],
            [
                "Обзор",
                "Редактор",
                "AI-клипы",
                "Тренды",
                "Календарь",
                "Публикация",
                "История",
                "Настройки",
            ],
        )
        window.navigate("ai")
        self.assertEqual(window.pages.currentIndex(), window.page_indexes["ai"])
        window.close()

    def test_platform_worker_is_not_replaced_before_queued_cleanup(self):
        video_id = self.create_video("platform-race.mp4")
        output = Path(TEST_ROOT.name, "outputs", "platform-race-ready.mp4")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            video.status = "ready"
            video.output_path = str(output)
            video.output_duration = 8.0
            session.commit()

        widget = PublishWidget()
        widget.set_video(video_id, str(output), 8.0)
        first_worker = widget.platform_worker
        self.assertIsNotNone(first_worker)
        widget.load_platforms()
        self.assertIs(widget.platform_worker, first_worker)
        first_worker.wait(1000)
        self.qt_app.processEvents()
        self.assertIsNone(widget.platform_worker)
        widget.close()

    def test_database_is_at_alembic_head(self):
        self.assertEqual(current_revision(), head_revision())

    def test_project_and_mock_transcript_are_persisted(self):
        video_id = self.create_video("project-source.mp4")
        project = create_project_for_video(video_id, "Pilot project")
        transcript_id = transcribe(video_id, MockTranscriber())

        with SessionLocal() as session:
            stored_project = session.get(Project, project.id)
            video = session.get(Video, video_id)
            transcript = session.get(Transcript, transcript_id)
            self.assertEqual(stored_project.name, "Pilot project")
            self.assertEqual(video.project_id, project.id)
            self.assertEqual(transcript.status, "ready")
            self.assertEqual(len(transcript.segments), 1)

    def test_subtitle_export_formats(self):
        cues = [SubtitleCue(1.25, 3.5, "Hello")]
        self.assertIn("00:00:01,250 --> 00:00:03,500", render_srt(cues))
        self.assertIn("00:00:01.250 --> 00:00:03.500", render_vtt(cues))

    def test_sequence_subtitles_follow_clip_offsets_and_dissolve(self):
        first_id = self.create_video("speech-first.mp4")
        second_id = self.create_video("speech-second.mp4")
        with SessionLocal() as session:
            session.add(Transcript(video_id=first_id, status="ready", text="first",
                segments=[TranscriptSegment(start_time=1.5, end_time=2.0, text="first")]))
            session.add(Transcript(video_id=second_id, status="ready", text="second",
                segments=[TranscriptSegment(start_time=1.0, end_time=1.5, text="second")]))
            session.commit()
        path = Path(TEST_ROOT.name, "sequence.srt")
        _auto_subtitles([(first_id, 1.0, 4.0), (second_id, 0.5, 2.5)], path, overlap=0.5)
        content = path.read_text(encoding="utf-8")
        self.assertIn("00:00:00,500 --> 00:00:01,000", content)
        self.assertIn("00:00:03,000 --> 00:00:03,500", content)

    def test_mock_content_assistant_returns_valid_pack(self):
        pack = MockContentAssistant().generate("Сильный момент фильма", duration=22.0)
        self.assertTrue(pack.title)
        self.assertEqual(pack.clip_suggestions[0].end_time, 22.0)
        self.assertIn("права", pack.copyright_note.lower())

    def test_trends_are_snapshotted_and_scored(self):
        trend_ids = refresh_youtube_trends(
            items=[
                {
                    "id": "unit-trend",
                    "snippet": {
                        "title": "Test trend",
                        "publishedAt": "2026-09-26T12:00:00Z",
                    },
                    "statistics": {
                        "viewCount": "10000",
                        "likeCount": "1000",
                        "commentCount": "50",
                    },
                }
            ]
        )
        with SessionLocal() as session:
            snapshot = session.query(TrendSnapshot).filter_by(
                trend_video_id=trend_ids[0]
            ).one()
            self.assertGreater(snapshot.trend_score, 0)
        score = calculate_trend_score(
            10000,
            1000,
            50,
            datetime.now(timezone.utc) - timedelta(hours=10),
        )
        self.assertGreater(score, 0)

    def test_short_clip_search_fetches_real_statistics_and_persists(self):
        requests = []

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"items": [{"id": {"videoId": "film-short-1"}}]})
            return httpx.Response(200, json={"items": [{
                "id": "film-short-1",
                "snippet": {"title": "Сцена из фильма", "publishedAt": "2026-09-27T12:00:00Z",
                            "channelTitle": "Film Channel"},
                "statistics": {"viewCount": "12345", "likeCount": "500", "commentCount": "20"},
                "contentDetails": {"duration": "PT45S"},
            }]})

        client = httpx.Client(base_url=YouTubeTrendClient.base_url,
                              transport=httpx.MockTransport(respond))
        with client, patch.object(settings, "youtube_api_key", "test-key"):
            ids = refresh_short_clip_trends("сцена сериала", YouTubeTrendClient(client))
        self.assertEqual([request.url.path.rsplit("/", 1)[-1] for request in requests], ["search", "videos"])
        self.assertEqual(requests[0].url.params["videoDuration"], "short")
        self.assertEqual(requests[0].url.params["type"], "video")
        with SessionLocal() as session:
            snapshot = session.query(TrendSnapshot).filter_by(trend_video_id=ids[0]).one()
            self.assertEqual(snapshot.views, 12345)
            self.assertEqual(snapshot.video.content_type, "short_clip_search")

    def test_analytics_payload_is_normalized(self):
        with SessionLocal() as session:
            account = ConnectedAccount(
                provider="youtube",
                external_id="unit-channel",
                display_name="Unit Channel",
            )
            session.add(account)
            session.commit()
            account_id = account.id
        snapshot_id = store_youtube_snapshot(
            account_id,
            date(2026, 9, 1),
            date(2026, 9, 27),
            {
                "columnHeaders": [
                    {"name": "views"},
                    {"name": "likes"},
                    {"name": "estimatedMinutesWatched"},
                ],
                "rows": [[1500, 120, 420.5]],
            },
        )
        with SessionLocal() as session:
            snapshot = session.get(AnalyticsSnapshot, snapshot_id)
            self.assertEqual(snapshot.views, 1500)
            self.assertEqual(snapshot.likes, 120)
            self.assertEqual(snapshot.watch_time_minutes, 420.5)

    def test_scheduler_returns_due_posts_only(self):
        video_id = self.create_video("scheduled.mp4")
        with SessionLocal() as session:
            due = Post(video_id=video_id, platform="mock-youtube")
            future = Post(video_id=video_id, platform="mock-youtube")
            session.add_all([due, future])
            session.commit()
            due_id, future_id = due.id, future.id
        now = datetime.now(timezone.utc)
        schedule_post(due_id, now - timedelta(minutes=1))
        schedule_post(future_id, now + timedelta(hours=1))
        called: list[int] = []
        self.assertEqual(run_due_posts(called.append, now=now), [due_id])
        self.assertEqual(called, [due_id])

    def test_local_scheduler_starts_ticks_and_stops(self):
        import threading

        ticked = threading.Event()

        def tick() -> list[int]:
            ticked.set()
            return []

        scheduler = LocalScheduler(tick, interval_seconds=0.05)
        scheduler.start()
        self.assertTrue(ticked.wait(timeout=1.0))
        self.assertTrue(scheduler.is_running)
        scheduler.stop(timeout=1.0)
        self.assertFalse(scheduler.is_running)

    def test_scheduler_claims_posts_and_continues_after_failure(self):
        video_id = self.create_video("scheduler-failure.mp4")
        with SessionLocal() as session:
            first = Post(video_id=video_id, platform="mock-youtube")
            second = Post(video_id=video_id, platform="mock-youtube")
            session.add_all([first, second])
            session.commit()
            first_id, second_id = first.id, second.id
        now = datetime.now(timezone.utc)
        schedule_post(first_id, now - timedelta(minutes=2))
        schedule_post(second_id, now - timedelta(minutes=1))
        observed: list[tuple[int, str]] = []

        def publish(post_id: int) -> None:
            with SessionLocal() as session:
                observed.append((post_id, session.get(Post, post_id).status))
            if post_id == first_id:
                raise RuntimeError("temporary failure")

        with self.assertLogs("app.services.scheduler", level="ERROR"):
            completed = run_due_posts(publish, now=now, base_backoff_seconds=1)
        self.assertEqual(completed, [second_id])
        self.assertEqual(observed, [(first_id, "dispatching"), (second_id, "dispatching")])
        with SessionLocal() as session:
            failed = session.get(Post, first_id)
            self.assertEqual(failed.status, "scheduled")
            self.assertEqual(failed.retry_count, 1)

    def test_content_pipeline_persists_valid_clip_candidates(self):
        video_id = self.create_video("content-pipeline.mp4")
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            video.duration = 18.0
            session.commit()
        project = create_project_for_video(video_id, "Content pipeline")
        pack, candidate_ids = analyze_video_for_clips(
            project.id, video_id, MockContentAssistant()
        )
        self.assertTrue(pack.hooks)
        self.assertEqual(len(candidate_ids), 1)

    def test_active_account_drives_dashboard_summary(self):
        account_id = upsert_account(
            "youtube", "dashboard-channel", "Dashboard Channel", "@dashboard"
        )
        set_active_account(account_id)
        self.assertEqual(get_active_account_id(), account_id)
        store_youtube_snapshot(
            account_id,
            date(2026, 9, 1),
            date(2026, 9, 27),
            {
                "columnHeaders": [{"name": "views"}, {"name": "likes"}],
                "rows": [[9900, 850]],
            },
        )
        summary = get_dashboard_summary()
        self.assertEqual(summary.active_account_id, account_id)
        self.assertEqual(summary.views, 9900)
        self.assertEqual(summary.likes, 850)

    def test_openai_adapter_requests_strict_structured_output(self):
        original_key = settings.openai_api_key
        settings.openai_api_key = "test-key"

        def handler(request: httpx.Request) -> httpx.Response:
            payload = __import__("json").loads(request.content)
            self.assertEqual(request.url.path, "/v1/responses")
            self.assertEqual(payload["text"]["format"]["type"], "json_schema")
            self.assertTrue(payload["text"]["format"]["strict"])
            content = MockContentAssistant().generate("Fixture", 12.0).model_dump_json()
            return httpx.Response(
                200,
                json={
                    "output": [
                        {"content": [{"type": "output_text", "text": content}]}
                    ]
                },
            )

        try:
            client = httpx.Client(
                base_url="https://api.openai.com/v1",
                transport=httpx.MockTransport(handler),
            )
            pack = OpenAIContentAssistant(client).generate("Fixture", 12.0)
            client.close()
            self.assertEqual(pack.clip_suggestions[0].end_time, 12.0)
        finally:
            settings.openai_api_key = original_key

    def test_oauth_request_and_refresh_token_reference(self):
        original_client_id = settings.youtube_client_id
        settings.youtube_client_id = "unit-client"
        store = MemoryCredentialStore()
        try:
            request = build_authorization_request(store)
            self.assertIn("code_challenge=", request.url)
            self.assertTrue(request.state)
            self.assertIsNotNone(store.get(request.state_reference))
        finally:
            settings.youtube_client_id = original_client_id

        account_id = upsert_account("youtube", "oauth-channel", "OAuth Channel")
        save_youtube_account_tokens(
            account_id,
            {
                "refresh_token": "refresh-secret",
                "access_token": "access-secret",
                "expires_in": 3600,
            },
            store,
        )
        with SessionLocal() as session:
            account = session.get(ConnectedAccount, account_id)
            bundle = json.loads(store.get(account.credential_ref))
            self.assertEqual(bundle["refresh_token"], "refresh-secret")
            self.assertEqual(bundle["access_token"], "access-secret")

    def test_oauth_refresh_is_used_by_analytics_and_snapshot_is_idempotent(self):
        original_client_id = settings.youtube_client_id
        settings.youtube_client_id = "unit-client"
        account_id = upsert_account("youtube", "refresh-channel", "Refresh Channel")
        store = MemoryCredentialStore()
        save_youtube_account_tokens(
            account_id,
            {"refresh_token": "refresh-value", "access_token": "expired", "expires_in": 60},
            store,
        )
        with SessionLocal() as session:
            account = session.get(ConnectedAccount, account_id)
            reference = account.credential_ref
        bundle = json.loads(store.get(reference))
        bundle["expires_at"] = "2020-01-01T00:00:00+00:00"
        store.set(reference, json.dumps(bundle))

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "oauth2.googleapis.com":
                return httpx.Response(
                    200,
                    json={"access_token": "fresh-access", "expires_in": 3600},
                )
            self.assertEqual(request.headers["Authorization"], "Bearer fresh-access")
            return httpx.Response(
                200,
                json={
                    "columnHeaders": [{"name": "views"}, {"name": "likes"}],
                    "rows": [["1,234", "100"]],
                },
            )

        client = httpx.Client(
            base_url="https://youtubeanalytics.googleapis.com/v2",
            transport=httpx.MockTransport(handler),
        )
        try:
            first = sync_youtube_analytics(
                account_id,
                date(2026, 9, 1),
                date(2026, 9, 27),
                credential_store=store,
                http_client=client,
            )
            second = sync_youtube_analytics(
                account_id,
                date(2026, 9, 1),
                date(2026, 9, 27),
                credential_store=store,
                http_client=client,
            )
        finally:
            client.close()
            settings.youtube_client_id = original_client_id
        self.assertEqual(first, second)
        with SessionLocal() as session:
            snapshot = session.get(AnalyticsSnapshot, first)
            self.assertEqual(snapshot.views, 1234)

    def test_complete_oauth_connects_channel_and_selects_account(self):
        original_client_id = settings.youtube_client_id
        settings.youtube_client_id = "unit-client"
        store = MemoryCredentialStore()
        request = build_authorization_request(store)

        def handler(http_request: httpx.Request) -> httpx.Response:
            if http_request.url.host == "oauth2.googleapis.com":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "channel-access",
                        "refresh_token": "channel-refresh",
                        "expires_in": 3600,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "connected-channel-id",
                            "snippet": {
                                "title": "Connected Channel",
                                "customUrl": "@connected",
                                "thumbnails": {"default": {"url": "https://example/avatar"}},
                            },
                        }
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            result = complete_youtube_oauth(
                "authorization-code", request.state, store, client
            )
        finally:
            client.close()
            settings.youtube_client_id = original_client_id
        self.assertEqual(result.channel_id, "connected-channel-id")
        self.assertEqual(get_active_account_id(), result.account_id)
        with SessionLocal() as session:
            account = session.get(ConnectedAccount, result.account_id)
            self.assertEqual(account.username, "@connected")
            self.assertIsNotNone(account.credential_ref)

    def test_empty_analytics_payload_is_not_silently_stored(self):
        account_id = upsert_account("youtube", "empty-channel", "Empty Channel")
        with self.assertRaises(AnalyticsDataError):
            store_youtube_snapshot(
                account_id,
                date(2026, 9, 1),
                date(2026, 9, 27),
                {"columnHeaders": [{"name": "views"}], "rows": []},
            )


if __name__ == "__main__":
    unittest.main()
