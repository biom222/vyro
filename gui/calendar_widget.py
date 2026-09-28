from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QDateTime, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QDateTimeEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.models import Post, SessionLocal, Video
from app.services.scheduler import schedule_post
from gui.components import page_header


class CalendarWidget(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(
            page_header(
                "Контент-календарь",
                "Планируйте публикации. Локальный планировщик отправит их в назначенное время.",
                refresh,
            )
        )

        body = QHBoxLayout()
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.selectionChanged.connect(self.refresh)
        body.addWidget(self.calendar, 1)

        right = QVBoxLayout()
        self.date_label = QLabel()
        self.date_label.setObjectName("sectionTitle")
        right.addWidget(self.date_label)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Видео", "Платформа", "Статус", "Время"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        right.addWidget(self.table, 1)

        schedule_row = QHBoxLayout()
        self.when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.schedule_button = QPushButton("Запланировать выбранное")
        self.schedule_button.clicked.connect(self.schedule_selected)
        schedule_row.addWidget(self.when, 1)
        schedule_row.addWidget(self.schedule_button)
        right.addLayout(schedule_row)
        body.addLayout(right, 2)
        layout.addLayout(body, 1)
        layout.addWidget(
            QLabel(
                "Чтобы запланировать новую публикацию, сначала создайте её в разделе «Публикация»."
            )
        )
        self.refresh()

    def refresh(self) -> None:
        selected = self.calendar.selectedDate().toPyDate()
        self.date_label.setText(f"Публикации · {selected.strftime('%d.%m.%Y')}")
        with SessionLocal() as session:
            posts = list(session.scalars(select(Post).order_by(Post.created_at.desc())))
            rows: list[tuple[Post, str]] = []
            for post in posts:
                relevant = post.scheduled_at or post.published_at or post.created_at
                if relevant.date() == selected:
                    video = session.get(Video, post.video_id)
                    rows.append((post, video.filename if video else "—"))
        self.table.setRowCount(len(rows))
        for row, (post, filename) in enumerate(rows):
            item = QTableWidgetItem(str(post.id))
            item.setData(Qt.ItemDataRole.UserRole, post.id)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(filename))
            self.table.setItem(row, 2, QTableWidgetItem(post.platform))
            self.table.setItem(row, 3, QTableWidgetItem(post.status))
            value = post.scheduled_at or post.published_at or post.created_at
            self.table.setItem(row, 4, QTableWidgetItem(value.strftime("%H:%M")))

    def schedule_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None:
            QMessageBox.information(self, "Выберите публикацию", "Выберите строку в таблице.")
            return
        post_id = int(item.data(Qt.ItemDataRole.UserRole))
        when: datetime = self.when.dateTime().toPyDateTime().astimezone()
        if when <= datetime.now().astimezone():
            QMessageBox.warning(self, "Неверное время", "Выберите время в будущем.")
            return
        try:
            schedule_post(post_id, when)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка планирования", str(exc))
            return
        self.log_message.emit(f"Публикация #{post_id} запланирована на {when:%d.%m.%Y %H:%M}.")
        self.calendar.setSelectedDate(self.when.date())
        self.refresh()

    def is_busy(self) -> bool:
        return False
