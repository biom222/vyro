from __future__ import annotations

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.config import settings
from app.models import ContentIdea, SessionLocal, TrendSnapshot, TrendVideo
from gui.components import page_header
from gui.worker import TrendIdeaWorker, TrendRefreshWorker


class TrendsWidget(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.refresh_worker: TrendRefreshWorker | None = None
        self.idea_worker: TrendIdeaWorker | None = None
        self.selected_trend_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        refresh = QPushButton("Обновить тренды")
        refresh.clicked.connect(self.start_refresh)
        layout.addWidget(
            page_header(
                "Тренды и идеи",
                "Популярные ролики как источник форматов и хуков — с предупреждением о правах.",
                refresh,
            )
        )
        mode = "mock-данные" if settings.trends_mock_mode else "YouTube Data API"
        note = QLabel(
            f"Источник: {mode}. Поиск использует заголовки, описания и метрики публичных роликов 3–90 сек.; права проверяются вручную."
        )
        note.setObjectName("contextBanner")
        note.setWordWrap(True)
        layout.addWidget(note)

        search_row = QHBoxLayout()
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("Тема или название фильма/сериала")
        self.topic_edit.returnPressed.connect(self.search_clips)
        search_row.addWidget(self.topic_edit, 1)
        search_button = QPushButton("Найти короткие ролики")
        search_button.clicked.connect(self.search_clips)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Видео", "Канал", "Просмотры", "Лайки", "Score", "Риск", "Действия"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        idea_row = QHBoxLayout()
        self.idea_button = QPushButton("Создать идею из выбранного тренда")
        self.idea_button.clicked.connect(self.generate_idea)
        self.idea_button.setEnabled(False)
        idea_row.addWidget(self.idea_button)
        idea_row.addStretch()
        layout.addLayout(idea_row)
        self.idea_view = QTextEdit()
        self.idea_view.setReadOnly(True)
        self.idea_view.setPlaceholderText("Выберите тренд и создайте собственную идею ролика.")
        self.idea_view.setMaximumHeight(150)
        layout.addWidget(self.idea_view)
        self.refresh()

    def refresh(self) -> None:
        rows: list[tuple[TrendVideo, TrendSnapshot | None]] = []
        with SessionLocal() as session:
            trends = list(session.scalars(select(TrendVideo).order_by(TrendVideo.updated_at.desc())))
            for trend in trends:
                snapshot = session.scalar(
                    select(TrendSnapshot)
                    .where(TrendSnapshot.trend_video_id == trend.id)
                    .order_by(TrendSnapshot.captured_at.desc())
                    .limit(1)
                )
                rows.append((trend, snapshot))
        rows.sort(key=lambda item: item[1].trend_score if item[1] else 0, reverse=True)
        self.table.setRowCount(len(rows))
        for row, (trend, snapshot) in enumerate(rows):
            title = QTableWidgetItem(trend.title)
            title.setData(256, trend.id)
            self.table.setItem(row, 0, title)
            self.table.setItem(row, 1, QTableWidgetItem(trend.channel_name or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{snapshot.views:,}" if snapshot else "—"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{snapshot.likes:,}" if snapshot else "—"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{snapshot.trend_score:.1f}" if snapshot else "—"))
            self.table.setItem(row, 5, QTableWidgetItem(trend.copyright_risk))
            open_button = QPushButton("Открыть")
            open_button.setObjectName("secondaryButton")
            open_button.clicked.connect(
                lambda checked=False, url=trend.url: QDesktopServices.openUrl(QUrl(url))
            )
            self.table.setCellWidget(row, 6, open_button)

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        self.selected_trend_id = int(item.data(256)) if item else None
        self.idea_button.setEnabled(self.selected_trend_id is not None and not self.is_busy())
        if self.selected_trend_id:
            with SessionLocal() as session:
                idea = session.scalar(
                    select(ContentIdea)
                    .where(ContentIdea.trend_video_id == self.selected_trend_id)
                    .order_by(ContentIdea.created_at.desc())
                )
            if idea:
                self._show_idea(
                    {"title": idea.title, "hooks": [idea.hook], "description": idea.script,
                     "copyright_note": idea.copyright_note}
                )

    def start_refresh(self, query: str | None = None) -> None:
        if self.refresh_worker is not None:
            return
        self.refresh_worker = TrendRefreshWorker(query, self)
        self.refresh_worker.succeeded.connect(self._refresh_succeeded)
        self.refresh_worker.error.connect(self._failed)
        self.refresh_worker.finished.connect(self._refresh_finished)
        self.refresh_worker.start()

    def search_clips(self) -> None:
        query = self.topic_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Нужна тема", "Введите тему или название произведения.")
            return
        if not settings.youtube_api_key:
            QMessageBox.information(self, "Нужен YouTube API", "Укажите YOUTUBE_API_KEY в .env для поиска реальных роликов.")
            return
        self.start_refresh(query)

    def _refresh_succeeded(self, trend_ids: list[int]) -> None:
        self.log_message.emit(f"Обновлено трендов: {len(trend_ids)}.")
        self.refresh()

    def _refresh_finished(self) -> None:
        if self.refresh_worker:
            self.refresh_worker.deleteLater()
        self.refresh_worker = None

    def generate_idea(self) -> None:
        if self.selected_trend_id is None or self.idea_worker is not None:
            return
        self.idea_button.setEnabled(False)
        self.idea_button.setText("AI готовит идею…")
        self.idea_worker = TrendIdeaWorker(self.selected_trend_id, self)
        self.idea_worker.succeeded.connect(self._idea_succeeded)
        self.idea_worker.error.connect(self._failed)
        self.idea_worker.finished.connect(self._idea_finished)
        self.idea_worker.start()

    def _idea_succeeded(self, idea_id: int, pack: dict) -> None:
        self._show_idea(pack)
        self.log_message.emit(f"Контент-идея #{idea_id} создана.")

    def _show_idea(self, pack: dict) -> None:
        hooks = "\n".join(f"• {item}" for item in pack.get("hooks", []))
        self.idea_view.setPlainText(
            f"{pack.get('title', '')}\n\n{hooks}\n\n{pack.get('description', '')}"
            f"\n\nПрава на материал: {pack.get('copyright_note', '')}"
        )

    def _idea_finished(self) -> None:
        if self.idea_worker:
            self.idea_worker.deleteLater()
        self.idea_worker = None
        self.idea_button.setText("Создать идею из выбранного тренда")
        self.idea_button.setEnabled(self.selected_trend_id is not None)

    def _failed(self, message: str) -> None:
        self.log_message.emit(f"Тренды: {message}")
        QMessageBox.critical(self, "Ошибка", message)

    def is_busy(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self.refresh_worker, self.idea_worker)
        )
