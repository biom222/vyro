from __future__ import annotations

from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PyQt6.QtWidgets import (
    QFrame,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.projects import create_project_for_video, add_video_to_project
from app.models import AppPreference, Project, SessionLocal, Video, utc_now
from gui.edit_widget import EditWidget
from gui.timeline_widget import TimelineWidget
from gui.upload_widget import UploadWidget
from gui.worker import PreviewFrameWorker, PreviewRenderWorker
from gui.preview_canvas import PreviewCanvas
from gui.theme import set_flat_icon
from gui.sequence_widget import SequenceWidget
from gui.layers_widget import LayersWidget
from gui.video_layers_widget import VideoLayersWidget


class EditorWorkspace(QWidget):
    video_ready = pyqtSignal(int, int)
    render_completed = pyqtSignal(int, str, float)
    publish_requested = pyqtSignal()
    ai_requested = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_id: int | None = None
        self.project_id: int | None = None
        self.source_path: str | None = None
        self._preview_worker: PreviewFrameWorker | None = None
        self._pending_preview_time: float | None = None
        self._selection_end = 0.0
        self._generation = 0
        self._player_failed = False
        self._last_frame_time = None
        self._append_next_video = False
        self._restoring_sequence = False
        self._sequence_playback = False
        self._sequence_index = -1
        self._sequence_advancing = False
        self._sequence_switching = False
        self._effect_preview_worker: PreviewRenderWorker | None = None
        self._effect_preview_active = False
        self._effect_preview_path: str | None = None
        self._effect_restore_index = 0
        self._effect_restore_position = 0.0
        self._draft_dirty = True
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(400)
        self._draft_timer.timeout.connect(self._write_draft)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        title_box = QVBoxLayout()
        heading = QLabel("Редактор")
        heading.setObjectName("pageTitle")
        self.project_label = QLabel("Новый проект · добавьте исходное видео")
        self.project_label.setObjectName("pageSubtitle")
        self.project_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_box.addWidget(heading)
        title_box.addWidget(self.project_label)
        toolbar.addLayout(title_box, 1)
        self.ai_button = QPushButton("Найти AI-клипы")
        self.ai_button.setObjectName("secondaryButton")
        self.ai_button.clicked.connect(self.ai_requested.emit)
        self.ai_button.setEnabled(False)
        toolbar.addWidget(self.ai_button)
        root.addLayout(toolbar)

        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self.vertical_splitter = vertical_splitter
        vertical_splitter.setChildrenCollapsible(False)
        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setChildrenCollapsible(False)

        self.upload_widget = UploadWidget()
        self.media_scroll = QScrollArea()
        self.media_scroll.setWidgetResizable(True)
        self.media_scroll.setMinimumWidth(160)
        self.media_scroll.setMaximumWidth(225)
        self.media_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.media_scroll.setWidget(self.upload_widget)
        workspace.addWidget(self.media_scroll)

        preview_panel = QFrame()
        preview_panel.setObjectName("previewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(8)
        preview_header = QHBoxLayout()
        preview_title = QLabel("ПРОСМОТР")
        preview_title.setObjectName("panelEyebrow")
        self.preview_status = QLabel("Нет медиа")
        self.preview_status.setObjectName("muted")
        self.preview_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        preview_header.addWidget(preview_title)
        preview_layout.addLayout(preview_header)

        self.canvas = PreviewCanvas()
        preview_layout.addWidget(self.canvas, 1)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.65)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._video_frame_changed)
        self.player.setVideoSink(self.video_sink)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.errorOccurred.connect(self._player_error)
        self.player.mediaStatusChanged.connect(self._media_status_changed)

        controls = QHBoxLayout()
        jump_start = self._transport_button("", lambda: self.seek_seconds(self.edit_widget.start_time.value()))
        set_flat_icon(jump_start, QStyle.StandardPixmap.SP_MediaSkipBackward)
        back = self._transport_button("−5", lambda: self.seek_seconds(self.player.position() / 1000 - 5))
        self.play_button = self._transport_button("", self.toggle_playback)
        set_flat_icon(self.play_button, QStyle.StandardPixmap.SP_MediaPlay)
        self.play_button.setObjectName("playButton")
        forward = self._transport_button("+5", lambda: self.seek_seconds(self.player.position() / 1000 + 5))
        jump_end = self._transport_button("", lambda: self.seek_seconds(self.edit_widget.end_time.value()))
        set_flat_icon(jump_end, QStyle.StandardPixmap.SP_MediaSkipForward)
        self.time_label = QLabel("00:00.0 / 00:00.0")
        self.time_label.setObjectName("timecode")
        for button in (jump_start, back, self.play_button, forward, jump_end):
            controls.addWidget(button)
        preview_layout.addLayout(controls)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.time_label)
        preview_layout.addWidget(self.preview_status)
        workspace.addWidget(preview_panel)

        self.edit_widget = EditWidget()
        toolbar.addWidget(self.edit_widget.render_button)
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setMinimumWidth(280)
        self.inspector_scroll.setMaximumWidth(315)
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector_scroll.setWidget(self.edit_widget)
        workspace.addWidget(self.inspector_scroll)
        workspace.setStretchFactor(0, 0)
        workspace.setStretchFactor(1, 1)
        workspace.setStretchFactor(2, 0)
        workspace.setSizes([220, 650, 310])
        vertical_splitter.addWidget(workspace)

        timeline_panel = QFrame()
        timeline_panel.setObjectName("timelinePanel")
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_toolbar = QHBoxLayout()
        timeline_title = QLabel("ТАЙМЛАЙН")
        timeline_title.setObjectName("panelEyebrow")
        self.selection_label = QLabel("Выделение: —")
        self.selection_label.setObjectName("muted")
        self.selection_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        set_in = QPushButton("I  Начало")
        set_out = QPushButton("O  Конец")
        for button in (set_in, set_out):
            button.setObjectName("secondaryButton")
        set_in.clicked.connect(lambda: self._set_mark(True))
        set_out.clicked.connect(lambda: self._set_mark(False))
        timeline_toolbar.addWidget(timeline_title)
        timeline_toolbar.addWidget(self.selection_label, 1)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setToolTip("Масштаб таймлайна для точной обрезки")
        for factor in (1, 2, 4, 8, 16):
            self.zoom_combo.addItem(f"{factor}x", factor)
        self.zoom_combo.currentIndexChanged.connect(self._zoom_timeline)
        timeline_toolbar.addWidget(self.zoom_combo)
        timeline_toolbar.addWidget(set_in)
        timeline_toolbar.addWidget(set_out)
        timeline_layout.addLayout(timeline_toolbar)
        self.timeline = TimelineWidget()
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline_scroll.setMinimumHeight(195)
        self.timeline_scroll.setWidget(self.timeline)
        self.sequence_widget = SequenceWidget()
        self.layers_widget = LayersWidget()
        self.video_layers_widget = VideoLayersWidget()
        self.sequence_scroll = QScrollArea()
        self.sequence_scroll.setWidgetResizable(True)
        self.sequence_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sequence_scroll.setWidget(self.sequence_widget)
        self.editor_tabs = QTabWidget()
        self.editor_tabs.addTab(self.timeline_scroll, "Активный клип")
        self.editor_tabs.addTab(self.sequence_scroll, "Сборка")
        self.editor_tabs.addTab(self.layers_widget, "Титры и ключевые кадры")
        self.editor_tabs.addTab(self.video_layers_widget, "Видеослои")
        self.editor_tabs.currentChanged.connect(self._editor_tab_changed)
        timeline_layout.addWidget(self.editor_tabs)
        vertical_splitter.addWidget(timeline_panel)
        vertical_splitter.setStretchFactor(0, 1)
        vertical_splitter.setStretchFactor(1, 0)
        vertical_splitter.setSizes([560, 190])
        root.addWidget(vertical_splitter, 1)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(110)
        self._preview_timer.timeout.connect(self._start_preview_request)

        self.upload_widget.video_ready.connect(self._on_video_ready)
        self.upload_widget.probe_failed.connect(self._append_probe_failed)
        self.sequence_widget.add_requested.connect(self.add_sequence_clip)
        self.sequence_widget.preview_requested.connect(self.play_sequence)
        self.sequence_widget.effect_preview_requested.connect(self.toggle_effect_preview)
        self.sequence_widget.selected.connect(self._preview_sequence_clip)
        self.sequence_widget.changed.connect(self._sequence_changed)
        self.layers_widget.changed.connect(self._mark_modified)
        self.video_layers_widget.changed.connect(self._mark_modified)
        self.edit_widget.sequence_provider = self._project_render_params
        self.upload_widget.existing_selected.connect(self.open_existing)
        self.upload_widget.log_message.connect(self.log_message.emit)
        self.edit_widget.render_completed.connect(self._on_render_completed)
        self.edit_widget.render_started.connect(lambda: self.save_project(silent=True))
        self.edit_widget.publish_requested.connect(self.publish_requested.emit)
        self.edit_widget.log_message.connect(self.log_message.emit)
        self.edit_widget.busy_changed.connect(self._render_busy_changed)
        self.edit_widget.range_changed.connect(self._inspector_range_changed)
        self.edit_widget.overlay_changed.connect(self._overlay_changed)
        self.edit_widget.text_position.currentIndexChanged.connect(self._update_overlay_position)
        self.edit_widget.font_size.valueChanged.connect(self._update_overlay_position)
        self.edit_widget.font_color.currentIndexChanged.connect(self._update_overlay_position)
        self.edit_widget.auto_subtitles.toggled.connect(lambda _checked: self._mark_modified())
        self.edit_widget.vertical_checkbox.toggled.connect(self._update_overlay_position)
        self.edit_widget.crop_position.valueChanged.connect(self._update_overlay_position)
        self.timeline.position_changed.connect(self._timeline_seek)
        self.timeline.range_changed.connect(self._timeline_range_changed)
        self.shortcuts = []
        for key, callback in (("Space", self.toggle_playback), ("I", lambda: self._set_mark(True)), ("O", lambda: self._set_mark(False))):
            shortcut = QShortcut(QKeySequence(key), self.canvas)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.play_button.setEnabled(False)

    @staticmethod
    def _transport_button(text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("transportButton")
        button.setFixedSize(42, 34)
        button.clicked.connect(callback)
        return button

    def _zoom_timeline(self) -> None:
        factor = self.zoom_combo.currentData() or 1
        width = self.timeline_scroll.viewport().width()
        self.timeline.setMinimumWidth(round(width * factor) if factor > 1 else 0)
        QTimer.singleShot(0, self._scroll_to_playhead)

    def _scroll_to_playhead(self) -> None:
        self.timeline_scroll.ensureVisible(round(self.timeline._x_for_time(self.timeline.position)), 60, 60, 0)

    def _editor_tab_changed(self, index: int) -> None:
        if index in (1, 2, 3):
            self.vertical_splitter.setSizes([320, 470])
        else:
            self.vertical_splitter.setSizes([560, 190])

    def _on_video_ready(
        self, video_id: int, duration: float, width: int, height: int, source_path: str
    ) -> None:
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            display_name = video.filename if video is not None else Path(source_path).name
        if self._append_next_video and self.project_id is not None and self.video_id is not None:
            self._append_next_video = False
            add_video_to_project(self.project_id, video_id)
            self.sequence_widget.add_video(video_id, display_name, duration)
            self.editor_tabs.setCurrentWidget(self.sequence_scroll)
            self.log_message.emit(f"Клип #{video_id} добавлен в проект #{self.project_id}.")
            return
        self.save_project(silent=True)
        self._leave_effect_preview(restore=False)
        self._sequence_playback = False
        self._append_next_video = False
        self.player.stop()
        self._generation += 1
        self._player_failed = False
        self.canvas.clear()
        self.video_id = video_id
        self.source_path = source_path
        project = create_project_for_video(video_id, Path(display_name).stem)
        self.project_id = project.id
        self._restoring_sequence = True
        self.sequence_widget.set_clips(video_id, [{"video_id": video_id, "name": display_name,
            "duration": duration, "start_time": 0.0, "end_time": duration}])
        self.layers_widget.set_layers([], duration)
        self.video_layers_widget.set_layers([], self.sequence_widget.clips, duration)
        self.project_label.setText(f"{project.name} · {width}×{height} · {duration:.1f} сек.")
        self.edit_widget.set_video(video_id, duration, width, height, source_path, display_name)
        self._update_overlay_position()
        self.timeline.set_media(duration, Path(source_path).name)
        self._selection_end = duration
        self._update_selection_label(0.0, duration)
        self.player.setSource(QUrl.fromLocalFile(str(Path(source_path).resolve())))
        self.canvas.output_width = width
        self.preview_status.setText("Подготовка кадра…")
        self.ai_button.setEnabled(True)
        self.play_button.setEnabled(True)
        self.request_preview(0.0)
        self._restoring_sequence = False
        self._draft_dirty = True
        self._schedule_draft_save()
        self.log_message.emit(f"Проект #{project.id} создан для видео #{video_id}.")
        self.video_ready.emit(project.id, video_id)

    def _render_busy_changed(self, busy: bool) -> None:
        self.upload_widget.setEnabled(not busy)
        self.timeline.setEnabled(not busy)
        self.sequence_widget.setEnabled(not busy)
        self.layers_widget.setEnabled(not busy)
        self.video_layers_widget.setEnabled(not busy)
        self.ai_button.setEnabled(not busy and self.video_id is not None)

    def shutdown_preview(self) -> None:
        self._preview_timer.stop()
        self._pending_preview_time = None
        self.player.stop()

    def _on_render_completed(self, video_id: int, output_path: str, duration: float) -> None:
        self._draft_dirty = False
        self.save_project(silent=True)
        self.preview_status.setText(f"Экспорт готов · {Path(output_path).name}")
        self.render_completed.emit(video_id, output_path, duration)

    def open_existing(self, video_id: int) -> None:
        from sqlalchemy import select
        from app.models import AppPreference, EditParams, SessionLocal, Video

        if self.is_busy():
            return
        self.save_project(silent=True)
        self._leave_effect_preview(restore=False)
        self._sequence_playback = False
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video is None:
                return
            edit = session.scalar(select(EditParams).where(EditParams.video_id == video_id).order_by(EditParams.id.desc()))
            preference = session.get(AppPreference, f"editor.video.{video_id}")
            saved = preference.value_json if preference and isinstance(preference.value_json, dict) else {}
            project_id = video.project_id
            sequence_pref = session.get(AppPreference, f"editor.project.{project_id}.sequence") if project_id else None
            sequence_saved = sequence_pref.value_json if sequence_pref and isinstance(sequence_pref.value_json, dict) else {}
            draft_editor = sequence_saved.get("editor") if isinstance(sequence_saved.get("editor"), dict) else {}
            primary_id = sequence_saved.get("primary_id", video_id)
            if primary_id != video_id:
                primary_video = session.get(Video, primary_id)
                if primary_video and primary_video.project_id == project_id:
                    video = primary_video
                    video_id = primary_id
                    edit = session.scalar(select(EditParams).where(EditParams.video_id == video_id).order_by(EditParams.id.desc()))
                    preference = session.get(AppPreference, f"editor.video.{video_id}")
                    saved = preference.value_json if preference and isinstance(preference.value_json, dict) else {}
        if not Path(video.original_path).is_file():
            QMessageBox.warning(self, "Исходник недоступен", "Файл был перемещён или удалён. Добавьте его заново.")
            return
        project_id = video.project_id or create_project_for_video(video_id).id
        self._restoring_sequence = True
        self.load_clip(video_id, project_id, edit.start_time if edit else 0, (edit.end_time if edit else None) or video.duration)
        clips = []
        missing = []
        with SessionLocal() as session:
            for item in sequence_saved.get("clips", []):
                if not isinstance(item, dict):
                    continue
                member = session.get(Video, item.get("video_id"))
                if member is None or member.project_id != project_id:
                    missing.append(str(item.get("video_id")))
                    continue
                if not Path(member.original_path).is_file():
                    missing.append(member.original_path)
                duration = member.duration or 0
                start, end = item.get("start_time", 0), item.get("end_time", duration)
                if duration and 0 <= start < end <= duration + 0.05:
                    clips.append({"video_id": member.id, "name": member.filename, "duration": duration,
                                  "start_time": start, "end_time": min(end, duration)})
        if not clips or not any(clip["video_id"] == video_id for clip in clips):
            clips = [{"video_id": video_id, "name": video.filename,
                      "duration": video.duration or 0, "start_time": edit.start_time if edit else 0,
                      "end_time": (edit.end_time if edit else None) or video.duration or 0}]
        self.sequence_widget.set_clips(video_id, clips,
            str(sequence_saved.get("music_path") or ""), float(sequence_saved.get("music_volume", 0.25)),
            str(sequence_saved.get("transition") or "cut"),
            float(sequence_saved.get("transition_duration", 0.5)),
            int(sequence_saved.get("active_index", 0)))
        self.layers_widget.set_layers(sequence_saved.get("title_layers", []), self._sequence_duration())
        self.video_layers_widget.set_layers(sequence_saved.get("video_layers", []),
                                           self.sequence_widget.clips, self._sequence_duration())
        music_path = str(sequence_saved.get("music_path") or "")
        if music_path and not Path(music_path).is_file():
            missing.append(music_path)
        self.edit_widget.subtitle_edit.setText(str(draft_editor.get("subtitle_text", edit.subtitle_text if edit else "")))
        self.edit_widget.auto_subtitles.blockSignals(True)
        self.edit_widget.auto_subtitles.setChecked(bool(draft_editor.get("auto_subtitles", saved.get("auto_subtitles", False))))
        self.edit_widget.auto_subtitles.blockSignals(False)
        self.edit_widget.vertical_checkbox.setChecked(bool(draft_editor.get("is_vertical", edit.is_vertical if edit else True)))
        self.edit_widget.crop_position.setValue(round(float(draft_editor.get("crop_position", saved.get("crop_position", 0.5))) * 100))
        self.edit_widget.font_size.setValue(int(draft_editor.get("font_size", saved.get("font_size", 64))))
        for combo, key, default in ((self.edit_widget.text_position, "text_position", "bottom"),
                                    (self.edit_widget.font_color, "font_color", "white")):
            combo.setCurrentIndex(max(0, combo.findData(draft_editor.get(key, saved.get(key, default)))))
        self._draft_dirty = bool(sequence_saved.get("dirty", not bool(video.output_path)))
        self._update_overlay_position()
        self._restoring_sequence = False
        self._preview_sequence_clip(self.sequence_widget.table.currentIndex().row())
        if "playhead" in sequence_saved:
            self.seek_seconds(float(sequence_saved["playhead"]))
        if missing:
            QMessageBox.warning(self, "Файлы недоступны", "Некоторые файлы проекта не найдены:\n" + "\n".join(missing[:5]))
        if video.output_path and Path(video.output_path).is_file() and video.status == "ready" and not self._draft_dirty:
            self.edit_widget.output_path = video.output_path
            self.edit_widget.save_button.show()
            self.edit_widget.publish_button.show()
            self.render_completed.emit(video_id, video.output_path, video.output_duration or 0)
        self.video_ready.emit(project_id, video_id)

    def load_clip(self, video_id: int, project_id: int, start: float, end: float) -> None:
        from app.models import SessionLocal, Video

        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video is None:
                return
            source = video.original_path
            display_name = video.filename
            duration = video.duration or end
            width, height = video.width or 0, video.height or 0
        if self.is_busy():
            self.log_message.emit("Дождитесь завершения текущей операции перед сменой клипа.")
            return
        self.player.stop()
        self._generation += 1
        self._player_failed = False
        self.canvas.clear()
        self.canvas.output_width = width
        self.video_id = video_id
        self.project_id = project_id
        was_restoring = self._restoring_sequence
        self._restoring_sequence = True
        self.sequence_widget.set_clips(video_id, [{"video_id": video_id, "name": display_name,
            "duration": duration, "start_time": start, "end_time": end}])
        self._restoring_sequence = was_restoring
        self.source_path = source
        self.project_label.setText(f"{Path(display_name).stem} · {width}×{height}")
        self.upload_widget.path_edit.setText(display_name)
        self.upload_widget.path_edit.setToolTip(source)
        self.upload_widget.metadata_label.setText(f"{duration:.1f} сек. · {width}×{height}")
        self.edit_widget.set_video(video_id, duration, width, height, source, display_name)
        self._update_overlay_position()
        self.edit_widget.set_range(start, end)
        self.timeline.set_media(duration, display_name)
        self.timeline.set_range(start, end)
        self._selection_end = end
        self._update_selection_label(start, end)
        self.player.setSource(QUrl.fromLocalFile(str(Path(source).resolve())))
        self.seek_seconds(start)
        self.ai_button.setEnabled(True)
        self.play_button.setEnabled(True)

    def add_sequence_clip(self) -> None:
        if self.video_id is None or self.is_busy():
            return
        self._append_next_video = self.upload_widget.choose_video()

    def _append_probe_failed(self, _message: str) -> None:
        self._append_next_video = False

    def _preview_sequence_clip(self, index: int) -> None:
        if self._restoring_sequence or self.project_id is None or not 0 <= index < len(self.sequence_widget.clips) or self.edit_widget.is_busy():
            return
        if self._effect_preview_active:
            self._leave_effect_preview(restore=False)
        if self._sequence_playback and not self._sequence_switching:
            self._sequence_playback = False
            self.player.pause()
        clip = self.sequence_widget.clips[index]
        with SessionLocal() as session:
            video = session.get(Video, clip["video_id"])
            if video is None:
                return
            source = video.original_path
            width = video.width or 0
        if not Path(source).is_file():
            return
        self.player.stop()
        self._generation += 1
        self._player_failed = False
        self.canvas.clear()
        self.canvas.output_width = width
        self.source_path = source
        self.project_label.setText(f"{clip['name']} · клип {index + 1}/{len(self.sequence_widget.clips)}")
        self.timeline.set_media(clip["duration"], clip["name"])
        self.timeline.set_range(clip["start_time"], clip["end_time"])
        self.edit_widget.source_label.setText(f"{clip['name']}\n{clip['duration']:.1f} сек.")
        self.edit_widget.set_range(clip["start_time"], clip["end_time"])
        self._selection_end = clip["end_time"]
        self._update_selection_label(clip["start_time"], clip["end_time"])
        self.player.setSource(QUrl.fromLocalFile(str(Path(source).resolve())))
        self.seek_seconds(clip["start_time"])
        self._schedule_draft_save()

    def _sequence_changed(self) -> None:
        if self._restoring_sequence or self.project_id is None or self.video_id is None:
            return
        if self._effect_preview_active:
            self._leave_effect_preview(restore=False)
        self.layers_widget.set_duration(self._sequence_duration())
        self.video_layers_widget.set_sources(self.sequence_widget.clips, self._sequence_duration())
        current = self.sequence_widget.table.currentIndex().row()
        if 0 <= current < len(self.sequence_widget.clips):
            if self.source_path and self.source_path == self._effect_preview_path:
                self._preview_sequence_clip(current)
            clip = self.sequence_widget.clips[current]
            self.edit_widget.set_range(clip["start_time"], clip["end_time"])
            self.timeline.set_range(clip["start_time"], clip["end_time"])
        self._mark_modified()

    def play_sequence(self) -> None:
        """Preview all source trims in project order without exporting a proxy."""
        if not self.sequence_widget.clips or self.edit_widget.is_busy():
            return
        if self._effect_preview_active:
            self._leave_effect_preview(restore=False)
        self._sequence_playback = True
        self._sequence_index = 0
        self._sequence_advancing = False
        self._sequence_switching = True
        try:
            if self.sequence_widget.table.currentIndex().row() != 0:
                self.sequence_widget.table.selectRow(0)
            self._preview_sequence_clip(0)
        finally:
            self._sequence_switching = False
        self.preview_status.setText("Просмотр сборки · клип 1")
        self.player.play()

    def toggle_effect_preview(self) -> None:
        if self._effect_preview_active:
            self._leave_effect_preview()
            return
        if self.video_id is None or not self.sequence_widget.clips or self._effect_preview_worker is not None:
            return
        if self.upload_widget.is_busy() or self.edit_widget.is_busy() or self.sequence_widget.is_busy():
            return
        self.save_project(silent=True)
        self._sequence_playback = False
        self._effect_restore_index = max(0, self.sequence_widget.table.currentIndex().row())
        self._effect_restore_position = self.player.position() / 1000
        self._preview_timer.stop()
        self._pending_preview_time = None
        self._generation += 1
        self.player.stop()
        self._render_busy_changed(True)
        self.edit_widget.edit_tabs.setEnabled(False)
        self.edit_widget.render_button.setEnabled(False)
        self.preview_status.setText("Подготовка просмотра с эффектами…")
        worker = PreviewRenderWorker(self.video_id, self.edit_widget.build_render_params(), self)
        self._effect_preview_worker = worker
        worker.progress.connect(lambda percent: self.preview_status.setText(f"Предпросмотр FFmpeg · {percent}%"))
        worker.succeeded.connect(self._effect_preview_ready)
        worker.error.connect(self._effect_preview_failed)
        worker.finished.connect(self._effect_preview_finished)
        worker.start()

    def _effect_preview_ready(self, path: str, duration: float) -> None:
        self._effect_preview_active = True
        self._effect_preview_path = path
        self.sequence_widget.set_effect_preview_active(True)
        self.canvas.clear()
        self.canvas.vertical = False
        self.canvas.caption = ""
        self.canvas.output_width = 540 if self.edit_widget.vertical_checkbox.isChecked() else 640
        self.source_path = path
        self.timeline.set_media(duration, "Предпросмотр сборки")
        self.timeline.set_range(0.0, duration)
        self._selection_end = duration
        self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.player.setPosition(0)
        self.preview_status.setText("Предпросмотр с переходами и музыкой")
        self.player.play()

    def _effect_preview_failed(self, message: str) -> None:
        self.log_message.emit(f"Ошибка предпросмотра FFmpeg: {message}")
        self.preview_status.setText("Предпросмотр не удался")
        QMessageBox.warning(self, "Ошибка предпросмотра", message)
        self._preview_sequence_clip(self._effect_restore_index)

    def _effect_preview_finished(self) -> None:
        worker = self._effect_preview_worker
        self._effect_preview_worker = None
        if worker:
            worker.deleteLater()
        self._render_busy_changed(False)
        self.edit_widget.edit_tabs.setEnabled(True)
        self.edit_widget.render_button.setEnabled(self.edit_widget.video_id is not None)

    def _leave_effect_preview(self, restore: bool = True) -> None:
        if not self._effect_preview_active:
            return
        self.player.stop()
        self._effect_preview_active = False
        self.sequence_widget.set_effect_preview_active(False)
        self.canvas.caption = self.edit_widget.subtitle_edit.text()
        was_restoring = self._restoring_sequence
        self._restoring_sequence = True
        self._update_overlay_position()
        self._restoring_sequence = was_restoring
        if restore and self.sequence_widget.clips:
            self._preview_sequence_clip(self._effect_restore_index)
            self.seek_seconds(self._effect_restore_position)

    def _advance_sequence(self) -> None:
        if not self._sequence_playback or self._sequence_advancing:
            return
        self._sequence_advancing = True
        self.player.pause()
        QTimer.singleShot(0, self._finish_sequence_advance)

    def _finish_sequence_advance(self) -> None:
        self._sequence_advancing = False
        if not self._sequence_playback:
            return
        next_index = self._sequence_index + 1
        if next_index >= len(self.sequence_widget.clips):
            self._sequence_playback = False
            self._sequence_index = -1
            self.preview_status.setText("Просмотр сборки завершён")
            return
        self._sequence_index = next_index
        self._sequence_switching = True
        try:
            if self.sequence_widget.table.currentIndex().row() != next_index:
                self.sequence_widget.table.selectRow(next_index)
            self._preview_sequence_clip(next_index)
        finally:
            self._sequence_switching = False
        self.preview_status.setText(f"Просмотр сборки · клип {next_index + 1}/{len(self.sequence_widget.clips)}")
        self.player.play()

    def _schedule_draft_save(self) -> None:
        if (not self._restoring_sequence and not self._effect_preview_active
                and self.project_id is not None and self.video_id is not None):
            self._draft_timer.start()

    def _write_draft(self) -> bool:
        if self.project_id is None or self.video_id is None or self._restoring_sequence:
            return False
        state = {"schema_version": 1, "primary_id": self.video_id,
                 **self.sequence_widget.render_params(),
                 "title_layers": self.layers_widget.export_layers(),
                 "video_layers": self.video_layers_widget.export_layers(),
                 "editor": self.edit_widget.current_params(),
                 "active_index": max(0, self.sequence_widget.table.currentIndex().row()),
                 "playhead": self.player.position() / 1000,
                 "dirty": self._draft_dirty}
        try:
            with SessionLocal() as session:
                key = f"editor.project.{self.project_id}.sequence"
                preference = session.get(AppPreference, key)
                if preference is None:
                    preference = AppPreference(key=key)
                    session.add(preference)
                preference.value_json = state
                project = session.get(Project, self.project_id)
                if project is not None:
                    project.updated_at = utc_now()
                session.commit()
        except SQLAlchemyError as exc:
            self.log_message.emit(f"Не удалось сохранить проект #{self.project_id}: {exc}")
            return False
        return True

    def _sequence_duration(self) -> float:
        clips = self.sequence_widget.clips
        total = sum(max(0.0, clip["end_time"] - clip["start_time"]) for clip in clips)
        if self.sequence_widget.transition.currentData() == "dissolve":
            total -= max(0, len(clips) - 1) * self.sequence_widget.transition_duration.value()
        return max(0.0, total)

    def _project_render_params(self) -> dict:
        return {**self.sequence_widget.render_params(),
                "title_layers": self.layers_widget.export_layers(),
                "video_layers": self.video_layers_widget.export_layers()}

    def save_project(self, silent: bool = False) -> None:
        if self.project_id is None or self.video_id is None:
            return
        self._draft_timer.stop()
        saved = self._write_draft()
        if saved and not silent:
            self.log_message.emit(f"Проект #{self.project_id} сохранён в SQLite без экспорта MP4.")

    def _mark_modified(self) -> None:
        if self._restoring_sequence or self.project_id is None or self.video_id is None:
            return
        if self._effect_preview_active:
            self._leave_effect_preview()
        self._draft_dirty = True
        self._schedule_draft_save()
        self.edit_widget.output_path = None
        self.edit_widget.save_button.hide()
        self.edit_widget.publish_button.hide()
        self.edit_widget.progress.setValue(0)
        self.edit_widget.progress.setFormat("Изменения не экспортированы")
        self.edit_widget.busy_changed.emit(False)

    def toggle_playback(self) -> None:
        if not self.source_path or self._player_failed:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            if not self._effect_preview_active:
                self.request_preview(self.player.position() / 1000)
        else:
            if (not self._effect_preview_active and
                    not self.edit_widget.start_time.value() <= self.player.position() / 1000 < self.edit_widget.end_time.value() - 0.05):
                self.player.setPosition(round(self.edit_widget.start_time.value() * 1000))
            self.preview_status.setText("Воспроизведение")
            self.player.play()

    def seek_seconds(self, seconds: float) -> None:
        if not self.source_path:
            return
        duration = self.timeline.duration
        seconds = min(max(seconds, 0.0), duration)
        self.player.pause()
        self.player.setPosition(round(seconds * 1000))
        self.timeline.set_position(seconds)
        self.request_preview(seconds)
        self._schedule_draft_save()

    def _timeline_seek(self, seconds: float) -> None:
        self.seek_seconds(seconds)

    def _playback_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        set_flat_icon(self.play_button,
                      QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay)
        if not playing and self.source_path:
            self.preview_status.setText("Пауза · перетаскивайте playhead на таймлайне")

    def _position_changed(self, position: int) -> None:
        seconds = position / 1000
        self.timeline.set_position(seconds)
        self.time_label.setText(
            f"{self._format_time(seconds)} / {self._format_time(self.player.duration() / 1000)}"
        )
        if (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and seconds >= self._selection_end
        ):
            if self._effect_preview_active:
                self.player.pause()
                self.preview_status.setText("Предпросмотр завершён · вернитесь к исходникам")
            elif self._sequence_playback:
                self._advance_sequence()
            else:
                self.player.pause()
                self.seek_seconds(self.edit_widget.start_time.value())

    def _duration_changed(self, duration: int) -> None:
        self.time_label.setText(
            f"{self._format_time(self.player.position() / 1000)} / {self._format_time(duration / 1000)}"
        )

    def _media_status_changed(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.preview_status.setText("Предпросмотр с эффектами" if self._effect_preview_active
                                        else "Готово · пробел для воспроизведения")
        elif (status == QMediaPlayer.MediaStatus.EndOfMedia and self._sequence_playback
              and self.player.position() / 1000 >= self._selection_end - 0.1):
            self._advance_sequence()

    def _player_error(self, error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        detail = message or "Qt Multimedia не смог воспроизвести кодек"
        self.preview_status.setText("Покадровый режим FFmpeg")
        self._player_failed = True
        self.play_button.setEnabled(False)
        self.preview_status.setToolTip(detail)
        self.log_message.emit(f"Предпросмотр: {detail}. Используется FFmpeg-покадровый режим.")

    def request_preview(self, seconds: float) -> None:
        if not self.source_path:
            return
        self._pending_preview_time = min(max(0.0, seconds), max(0.0, self.timeline.duration - 0.1))
        self._preview_timer.start()

    def _start_preview_request(self) -> None:
        if self._preview_worker is not None or self._pending_preview_time is None or not self.source_path:
            return
        seconds = self._pending_preview_time
        self._pending_preview_time = None
        self._preview_worker = PreviewFrameWorker(self.source_path, seconds, self)
        self._preview_worker.generation = self._generation
        self._preview_worker.succeeded.connect(self._preview_succeeded)
        self._preview_worker.error.connect(self._preview_failed)
        self._preview_worker.finished.connect(self._preview_finished)
        self._preview_worker.start()

    def _preview_succeeded(self, data: bytes, seconds: float) -> None:
        worker = self.sender()
        if worker is not None and worker.generation != self._generation:
            return
        if self._pending_preview_time is not None or self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        image = QImage.fromData(data)
        if not image.isNull():
            self.canvas.set_image(image)
            self._last_frame_time = seconds
            self.preview_status.setText(f"Кадр {self._format_time(seconds)}")

    def _preview_failed(self, message: str) -> None:
        self.canvas.message = "Не удалось прочитать кадр\nПодробности — в журнале"
        self.canvas.update()
        self.preview_status.setText("Ошибка предпросмотра")
        self.log_message.emit(f"FFmpeg preview: {message}")

    def _preview_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is self._preview_worker:
            self._preview_worker = None
        if self._pending_preview_time is not None:
            self._preview_timer.start(20)

    def _video_frame_changed(self, frame) -> None:
        if frame.isValid() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.canvas.set_image(frame.toImage())

    def _timeline_range_changed(self, start: float, end: float) -> None:
        self.edit_widget.set_range(start, end)
        self.sequence_widget.set_selected_range(start, end)
        self._selection_end = end
        self._update_selection_label(start, end)

    def _inspector_range_changed(self, start: float, end: float) -> None:
        if end <= start:
            return
        self.timeline.set_range(start, end)
        self.sequence_widget.set_selected_range(start, end)
        self._selection_end = end
        self._update_selection_label(start, end)

    def _update_selection_label(self, start: float, end: float) -> None:
        self.selection_label.setText(
            f"Выделение: {self._format_time(start)} — {self._format_time(end)} · {end - start:.1f} сек."
        )

    def _set_mark(self, is_start: bool) -> None:
        if self.edit_widget.is_busy():
            return
        value = self.player.position() / 1000
        start = self.edit_widget.start_time.value()
        end = self.edit_widget.end_time.value()
        if is_start and value < end:
            start = value
        elif not is_start and value > start:
            end = value
        self.timeline.set_range(start, end, emit=True)

    def _overlay_changed(self, text: str) -> None:
        self.timeline.set_overlay_text(text)
        self.canvas.caption = text
        self._update_overlay_position()

    def _update_overlay_position(self) -> None:
        self.canvas.text_position = self.edit_widget.text_position.currentData()
        self.canvas.font_size = self.edit_widget.font_size.value()
        self.canvas.font_color = self.edit_widget.font_color.currentData()
        self.canvas.vertical = self.edit_widget.vertical_checkbox.isChecked()
        self.canvas.crop_position = self.edit_widget.crop_position.value() / 100
        self.canvas.update()
        self._mark_modified()

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0.0, seconds)
        minutes = int(seconds // 60)
        return f"{minutes:02d}:{seconds - minutes * 60:04.1f}"

    def is_busy(self) -> bool:
        workers_busy = self._preview_worker is not None or self._preview_timer.isActive()
        return (self.upload_widget.is_busy() or self.edit_widget.is_busy()
                or self.sequence_widget.is_busy() or self._effect_preview_worker is not None or workers_busy)
