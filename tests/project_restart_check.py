"""Subprocess fixture for save/restart and abrupt pre-commit termination tests."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.models import (ConnectedAccount, Project, SessionLocal, Transcript, TranscriptSegment,
                        Video, engine, init_db)
from app.services.project_state import load_project_state, save_project_state, _store_snapshot


def main() -> None:
    directory = Path(sys.argv[2])
    mode = sys.argv[1]
    if mode.startswith("migration-"):
        from app import database
        from alembic import command
        from unittest.mock import patch
        if mode in {"migration-create", "migration-unversioned-create"}:
            command.upgrade(database.alembic_config(), "beb1f4933f58")
            with engine.begin() as connection:
                connection.exec_driver_sql("INSERT INTO app_preferences (key,value_json,updated_at) VALUES ('kept','123',CURRENT_TIMESTAMP)")
                if mode == "migration-unversioned-create":
                    connection.exec_driver_sql("DROP TABLE alembic_version")
        elif mode in {"migration-crash", "migration-empty-crash"}:
            def interrupted(*args, **kwargs):
                with engine.begin() as connection:
                    if mode == "migration-empty-crash":
                        connection.exec_driver_sql("CREATE TABLE partial_initial (id INTEGER)")
                    else:
                        connection.exec_driver_sql("DELETE FROM app_preferences")
                os._exit(25 if mode == "migration-empty-crash" else 24)
            with patch.object(database.command, "upgrade", side_effect=interrupted):
                database.upgrade_database()
        else:
            init_db()
            with engine.connect() as connection:
                if mode == "migration-empty-read":
                    from sqlalchemy import inspect
                    assert "partial_initial" not in inspect(connection).get_table_names()
                else:
                    assert str(connection.exec_driver_sql("SELECT value_json FROM app_preferences WHERE key='kept'").scalar()) == '123'
                assert database.current_revision() == database.head_revision()
                from alembic.autogenerate import compare_metadata
                from alembic.migration import MigrationContext
                from app.models import Base
                assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        engine.dispose()
        print("PASS", mode)
        return
    init_db()
    expected_path = directory / "expected.json"
    if mode == "create":
        source = directory / "Исходник с пробелом.mp4"
        music = directory / "music.wav"
        source.write_bytes(b"source retained")
        music.write_bytes(b"music retained")
        with SessionLocal.begin() as session:
            project = Project(name="Restart project")
            account = ConnectedAccount(provider="youtube", external_id="restart-fixture", display_name="Fixture")
            session.add_all([project, account])
            session.flush()
            video = Video(project_id=project.id, filename=source.name, original_path=str(source),
                          status="uploaded", duration=12, width=1920, height=1080)
            session.add(video)
            session.flush()
            session.add(Transcript(video_id=video.id, language="ru", model_name="fixture", status="ready",
                text="Пример речи", segments=[TranscriptSegment(start_time=1, end_time=3, text="Пример речи")]))
            state = {"schema_version": 1, "primary_id": video.id,
                "clips": [{"video_id": video.id, "start_time": 1, "end_time": 9, "duration": 12, "name": source.name}],
                "transition": "dissolve", "transition_duration": 0.5,
                "music_path": str(music), "music_volume": 0.25,
                "title_layers": [{"text": "Титр", "start": 0, "end": 3, "keyframes": [
                    {"time": 0, "x": 0.2, "y": 0.5, "opacity": 0.5},
                    {"time": 3, "x": 0.8, "y": 0.6, "opacity": 1}]}],
                "video_layers": [{"video_id": video.id, "start": 1, "end": 4, "source_start": 0,
                    "width": 0.4, "x": 0.5, "y": 0.1, "opacity": 0.8}],
                "editor": {"start_time": 1, "end_time": 9, "crop_position": 0.3, "is_vertical": True,
                    "subtitle_text": "Подпись", "auto_subtitles": True, "font_size": 64, "font_color": "white"},
                "publication": {"account_id": account.id, "title": "My title", "description": "Caption",
                                "options": {"youtube_privacy": "private"}},
                "active_index": 0, "playhead": 2.5, "dirty": True}
            project_id = project.id
        save_project_state(project_id, state, 0)
        expected_path.write_text(json.dumps({"project_id": project_id, "state": state}, ensure_ascii=False), encoding="utf-8")
    else:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        loaded = load_project_state(expected["project_id"])
        assert loaded.state == expected["state"] and loaded.revision == 1
        with SessionLocal() as session:
            transcript = session.scalar(select(Transcript))
            assert transcript.text == "Пример речи" and transcript.segments[0].start_time == 1
        if mode == "crash":
            changed = {**loaded.state, "playhead": 7.0}
            with SessionLocal.begin() as session:
                _store_snapshot(session, expected["project_id"], changed, 1)
                session.flush()
                os._exit(23)  # Simulate power/process loss after writes, before commit.
    engine.dispose()
    print("PASS", mode)


if __name__ == "__main__":
    main()
