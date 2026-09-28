from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.config import settings
from app.models import ClipCandidate, SessionLocal, Transcript, Video
from gui.components import page_header
from gui.worker import ContentAnalysisWorker, SceneDetectionWorker, TranscriptionWorker


class AIClipsWidget(QWidget):
    edit_clip_requested = pyqtSignal(int, int, float, float)
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_id: int | None = None
        self.video_id: int | None = None
        self.transcription_worker: TranscriptionWorker | None = None
        self.analysis_worker: ContentAnalysisWorker | None = None
        self.scenes_worker: SceneDetectionWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(
            page_header(
                "AI-клипы",
                "Транскрибация исходника и поиск сильных фрагментов с таймкодами.",
            )
        )
        self.context_label = QLabel("Сначала добавьте видео в редакторе.")
        self.context_label.setObjectName("contextBanner")
        layout.addWidget(self.context_label)

        actions = QHBoxLayout()
        self.transcribe_button = QPushButton("1. Распознать речь")
        self.analyze_button = QPushButton("2. Найти лучшие фрагменты")
        self.analyze_button.setObjectName("secondaryButton")
        self.scenes_button = QPushButton("Найти смены сцен")
        self.scenes_button.setObjectName("secondaryButton")
        self.scenes_button.setToolTip("Локальный анализ изображения FFmpeg, без оценки смысла и прав")
        self.transcribe_button.clicked.connect(self.start_transcription)
        self.analyze_button.clicked.connect(self.start_analysis)
        self.scenes_button.clicked.connect(self.start_scene_detection)
        actions.addWidget(self.transcribe_button)
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.scenes_button)
        actions.addStretch()
        provider = QLabel(
            f"Транскрибация: {settings.transcription_provider} · AI: {settings.ai_provider}"
        )
        provider.setObjectName("muted")
        actions.addWidget(provider)
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Ожидание")
        layout.addWidget(self.progress)

        transcript_title = QLabel("Транскрипт")
        transcript_title.setObjectName("sectionTitle")
        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setPlaceholderText("Здесь появится распознанный текст.")
        self.transcript_view.setMaximumHeight(150)
        layout.addWidget(transcript_title)
        layout.addWidget(self.transcript_view)

        clips_title = QLabel("Рекомендованные фрагменты")
        clips_title.setObjectName("sectionTitle")
        layout.addWidget(clips_title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Название", "Начало", "Конец", "Оценка", "Почему", "Действие"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 5):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self.table, 1)
        self._update_enabled()

    def set_context(self, project_id: int, video_id: int) -> None:
        self.project_id = project_id
        self.video_id = video_id
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            name = video.filename if video else f"Видео #{video_id}"
        self.context_label.setText(f"Проект #{project_id} · {name}")
        self.refresh()

    def refresh(self) -> None:
        if self.video_id is None:
            self._update_enabled()
            return
        with SessionLocal() as session:
            transcript = session.scalar(
                select(Transcript)
                .where(Transcript.video_id == self.video_id)
                .order_by(Transcript.created_at.desc())
            )
            candidates = list(
                session.scalars(
                    select(ClipCandidate)
                    .where(ClipCandidate.video_id == self.video_id)
                    .order_by(ClipCandidate.score.desc())
                )
            )
        self.transcript_view.setPlainText(transcript.text if transcript else "")
        self.table.setRowCount(len(candidates))
        for row, clip in enumerate(candidates):
            self.table.setItem(row, 0, QTableWidgetItem(clip.title))
            self.table.setItem(row, 1, QTableWidgetItem(f"{clip.start_time:.1f} с"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{clip.end_time:.1f} с"))
            score = QTableWidgetItem(f"{clip.score:.0f}/100")
            score.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, score)
            self.table.setItem(row, 4, QTableWidgetItem(clip.reason))
            button = QPushButton("В редактор")
            button.setObjectName("secondaryButton")
            button.clicked.connect(
                lambda checked=False, item=clip: self.edit_clip_requested.emit(
                    item.video_id, item.project_id, item.start_time, item.end_time
                )
            )
            self.table.setCellWidget(row, 5, button)
        self._update_enabled()

    def start_transcription(self) -> None:
        if self.video_id is None or self.transcription_worker is not None:
            return
        self.progress.setValue(1)
        self.progress.setFormat("Распознавание речи — %p%")
        self.transcription_worker = TranscriptionWorker(self.video_id, self)
        self.transcription_worker.progress.connect(self.progress.setValue)
        self.transcription_worker.succeeded.connect(self._transcription_succeeded)
        self.transcription_worker.error.connect(self._failed)
        self.transcription_worker.finished.connect(self._transcription_finished)
        self._update_enabled()
        self.transcription_worker.start()

    def _transcription_succeeded(self, transcript_id: int) -> None:
        self.progress.setValue(100)
        self.progress.setFormat("Транскрипция готова")
        self.log_message.emit(f"Транскрипция #{transcript_id} готова.")
        self.refresh()

    def _transcription_finished(self) -> None:
        if self.transcription_worker:
            self.transcription_worker.deleteLater()
        self.transcription_worker = None
        self._update_enabled()

    def start_analysis(self) -> None:
        if (
            self.video_id is None
            or self.project_id is None
            or self.analysis_worker is not None
        ):
            return
        self.progress.setRange(0, 0)
        self.progress.setFormat("AI анализирует материал…")
        self.analysis_worker = ContentAnalysisWorker(
            self.project_id, self.video_id, self
        )
        self.analysis_worker.succeeded.connect(self._analysis_succeeded)
        self.analysis_worker.error.connect(self._failed)
        self.analysis_worker.finished.connect(self._analysis_finished)
        self._update_enabled()
        self.analysis_worker.start()

    def _analysis_succeeded(self, pack: dict, candidate_ids: list[int]) -> None:
        self.log_message.emit(
            f"AI-пакет «{pack.get('title', '')}»: {len(candidate_ids)} клипов."
        )
        self.refresh()
        QMessageBox.information(
            self,
            "AI-анализ завершён",
            f"Найдено фрагментов: {len(candidate_ids)}\n\n"
            f"{pack.get('copyright_note', '')}",
        )

    def _analysis_finished(self) -> None:
        if self.analysis_worker:
            self.analysis_worker.deleteLater()
        self.analysis_worker = None
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("AI-анализ готов")
        self._update_enabled()

    def start_scene_detection(self) -> None:
        if self.video_id is None or self.project_id is None or self.is_busy():
            return
        self.progress.setRange(0, 0)
        self.progress.setFormat("FFmpeg ищет смены сцен…")
        worker = SceneDetectionWorker(self.project_id, self.video_id, self)
        self.scenes_worker = worker
        worker.succeeded.connect(self._scenes_succeeded)
        worker.error.connect(self._failed)
        worker.finished.connect(self._scenes_finished)
        self._update_enabled()
        worker.start()

    def _scenes_succeeded(self, candidate_ids: list[int]) -> None:
        self.log_message.emit(f"Новых фрагментов по смене сцен: {len(candidate_ids)}.")
        self.refresh()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Поиск сцен завершён")

    def _scenes_finished(self) -> None:
        worker = self.scenes_worker
        self.scenes_worker = None
        if worker:
            worker.deleteLater()
        self._update_enabled()

    def _failed(self, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Ошибка")
        self.log_message.emit(f"AI-модуль: {message}")
        QMessageBox.critical(self, "Ошибка", message)

    def _update_enabled(self) -> None:
        busy = self.is_busy()
        self.transcribe_button.setEnabled(self.video_id is not None and not busy)
        self.analyze_button.setEnabled(self.video_id is not None and not busy)
        self.scenes_button.setEnabled(self.video_id is not None and not busy)

    def is_busy(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self.transcription_worker, self.analysis_worker, self.scenes_worker)
        )
