from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import AppPreference, EditParams, SessionLocal, Video
from gui.worker import RenderWorker


class EditWidget(QFrame):
    render_completed = pyqtSignal(int, str, float)
    publish_requested = pyqtSignal()
    log_message = pyqtSignal(str)
    range_changed = pyqtSignal(float, float)
    overlay_changed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)
    render_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self.video_id: int | None = None
        self.output_path: str | None = None
        self.worker: RenderWorker | None = None
        self.sequence_provider = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        heading = QLabel("Инспектор")
        heading.setObjectName("sectionTitle")
        self.source_label = QLabel("Выберите клип в медиатеке")
        self.source_label.setObjectName("muted")
        self.source_label.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(self.source_label)

        tabs = QTabWidget()
        self.edit_tabs = tabs
        tabs.setDocumentMode(True)
        clip_tab = QWidget()
        clip_form = QFormLayout(clip_tab)
        clip_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        clip_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        clip_form.setSpacing(6)
        self.start_time = self._time_spinbox()
        self.end_time = self._time_spinbox()
        clip_form.addRow("Начало", self.start_time)
        clip_form.addRow("Конец", self.end_time)
        self.vertical_checkbox = QCheckBox("Вертикальный холст 9:16")
        self.vertical_checkbox.setChecked(True)
        clip_form.addRow("Формат", self.vertical_checkbox)
        self.crop_position = QSpinBox()
        self.crop_position.setRange(0, 100)
        self.crop_position.setValue(50)
        self.crop_position.setSuffix(" %")
        self.crop_position.setToolTip("0 — левый край, 50 — центр, 100 — правый край")
        clip_form.addRow("Смещение кадра", self.crop_position)
        self.vertical_checkbox.toggled.connect(self.crop_position.setEnabled)
        self.canvas_hint = QLabel("Ручное кадрирование · 1080×1920")
        self.canvas_hint.setObjectName("muted")
        self.canvas_hint.setWordWrap(True)
        clip_form.addRow("Экспорт", self.canvas_hint)

        text_tab = QWidget()
        text_form = QFormLayout(text_tab)
        text_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        text_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        text_form.setSpacing(6)
        self.subtitle_edit = QLineEdit()
        self.subtitle_edit.setMaxLength(500)
        self.subtitle_edit.setPlaceholderText("Введите текст поверх видео")
        self.text_position = QComboBox()
        self.text_position.addItem("Снизу", "bottom")
        self.text_position.addItem("По центру", "center")
        self.text_position.addItem("Сверху", "top")
        self.font_size = QSpinBox()
        self.font_size.setRange(24, 120)
        self.font_size.setValue(64)
        self.font_size.setSuffix(" px")
        self.font_color = QComboBox()
        self.font_color.addItem("Белый", "white")
        self.font_color.addItem("Жёлтый", "yellow")
        self.font_color.addItem("Голубой", "#69c0ff")
        text_form.addRow("Текст", self.subtitle_edit)
        self.auto_subtitles = QCheckBox("Субтитры из распознанной речи")
        self.auto_subtitles.setToolTip("Сначала распознайте речь в разделе AI-клипы")
        text_form.addRow("Речь", self.auto_subtitles)
        text_form.addRow("Положение", self.text_position)
        text_form.addRow("Размер", self.font_size)
        text_form.addRow("Цвет", self.font_color)
        tabs.addTab(clip_tab, "Клип")
        tabs.addTab(text_tab, "Текст")
        layout.addWidget(tabs)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Проект не экспортирован")
        layout.addWidget(self.progress)

        self.render_button = QPushButton("Экспортировать MP4")
        self.render_button.setObjectName("primaryButton")
        self.render_button.clicked.connect(self.start_render)
        layout.addWidget(self.render_button)

        result_row = QVBoxLayout()
        self.save_button = QPushButton("Сохранить как…")
        self.save_button.setObjectName("secondaryButton")
        self.save_button.clicked.connect(self.save_as)
        self.publish_button = QPushButton("Публикация →")
        self.publish_button.setObjectName("secondaryButton")
        self.publish_button.clicked.connect(self.publish_requested.emit)
        result_row.addWidget(self.save_button)
        result_row.addWidget(self.publish_button)
        layout.addLayout(result_row)
        layout.addStretch()

        self.save_button.setVisible(False)
        self.publish_button.setVisible(False)
        self.start_time.valueChanged.connect(self._emit_range)
        self.end_time.valueChanged.connect(self._emit_range)
        self.subtitle_edit.textChanged.connect(self.overlay_changed.emit)
        self.setEnabled(False)
        self.render_button.setEnabled(False)

    @staticmethod
    def _time_spinbox() -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(0.0, 600.0)
        widget.setDecimals(2)
        widget.setSingleStep(0.1)
        widget.setSuffix(" сек.")
        return widget

    def set_video(
        self,
        video_id: int,
        duration: float,
        width: int,
        height: int,
        source_path: str,
        display_name: str | None = None,
    ) -> None:
        self.video_id = video_id
        self.output_path = None
        self.subtitle_edit.clear()
        self.auto_subtitles.blockSignals(True)
        self.auto_subtitles.setChecked(False)
        self.auto_subtitles.blockSignals(False)
        self.crop_position.blockSignals(True)
        self.crop_position.setValue(50)
        self.crop_position.blockSignals(False)
        self.start_time.blockSignals(True)
        self.end_time.blockSignals(True)
        self.start_time.setMaximum(duration)
        self.end_time.setMaximum(duration)
        self.start_time.setValue(0.0)
        self.end_time.setValue(duration)
        self.start_time.blockSignals(False)
        self.end_time.blockSignals(False)
        self.source_label.setText(
            f"{display_name or Path(source_path).name}\n{duration:.1f} сек. · {width}×{height}"
        )
        self.progress.setValue(0)
        self.progress.setFormat("Готово к экспорту")
        self.save_button.setVisible(False)
        self.publish_button.setVisible(False)
        self.setEnabled(True)
        self.render_button.setEnabled(True)
        self.range_changed.emit(0.0, duration)

    def set_range(self, start: float, end: float) -> None:
        self.start_time.blockSignals(True)
        self.end_time.blockSignals(True)
        self.start_time.setValue(start)
        self.end_time.setValue(end)
        self.start_time.blockSignals(False)
        self.end_time.blockSignals(False)

    def _emit_range(self) -> None:
        self.range_changed.emit(self.start_time.value(), self.end_time.value())

    def start_render(self) -> None:
        if self.video_id is None or self.is_busy():
            return
        start = self.start_time.value()
        end = self.end_time.value()
        if end <= start:
            QMessageBox.warning(
                self,
                "Неверный диапазон",
                "Время окончания должно быть больше времени начала.",
            )
            return

        params = self.build_render_params()
        self.render_started.emit()
        with SessionLocal() as session:
            video = session.get(Video, self.video_id)
            if video is None:
                QMessageBox.critical(self, "Ошибка", "Видео отсутствует в базе данных.")
                return
            session.add(
                EditParams(
                    video_id=video.id,
                    start_time=params["start_time"],
                    end_time=params["end_time"],
                    is_vertical=params["is_vertical"],
                    subtitle_text=params["subtitle_text"],
                )
            )
            preference_key = f"editor.video.{video.id}"
            preference = session.get(AppPreference, preference_key)
            if preference is None:
                preference = AppPreference(key=preference_key)
                session.add(preference)
            preference.value_json = dict(params)
            session.commit()

        self.render_button.setEnabled(False)
        self.edit_tabs.setEnabled(False)
        self.busy_changed.emit(True)
        self.save_button.setVisible(False)
        self.publish_button.setVisible(False)
        self.progress.setValue(1)
        self.progress.setFormat("FFmpeg · %p%")
        self.log_message.emit(f"Экспорт видео #{self.video_id} запущен.")

        self.worker = RenderWorker(self.video_id, params, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.succeeded.connect(self._render_succeeded)
        self.worker.error.connect(self._render_failed)
        self.worker.finished.connect(self._render_finished)
        self.worker.start()

    def build_render_params(self) -> dict:
        """Build the same payload for final export and effect-aware preview."""
        params = self.current_params()
        if self.sequence_provider is not None:
            sequence = self.sequence_provider()
            if sequence["clips"]:
                params.update(sequence)
                primary = next((clip for clip in sequence["clips"] if clip["video_id"] == self.video_id), None)
                if primary is not None:
                    params["start_time"] = primary["start_time"]
                    params["end_time"] = primary["end_time"]
        return params

    def current_params(self) -> dict:
        """Return editable inspector state without starting an export."""
        return {
            "start_time": self.start_time.value(),
            "end_time": self.end_time.value(),
            "is_vertical": self.vertical_checkbox.isChecked(),
            "crop_position": self.crop_position.value() / 100,
            "subtitle_text": self.subtitle_edit.text().strip(),
            "auto_subtitles": self.auto_subtitles.isChecked(),
            "text_position": self.text_position.currentData(),
            "font_size": self.font_size.value(),
            "font_color": self.font_color.currentData(),
        }

    def _render_succeeded(self, output_path: str, duration: float) -> None:
        self.output_path = output_path
        self.progress.setValue(100)
        self.progress.setFormat("Экспорт готов · 100%")
        self.save_button.setVisible(True)
        self.publish_button.setVisible(True)
        self.log_message.emit(
            f"Экспорт завершён: {Path(output_path).name}, {duration:.1f} сек."
        )
        self.render_completed.emit(self.video_id or 0, output_path, duration)

    def _render_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.progress.setFormat("Ошибка экспорта")
        self.log_message.emit(f"Ошибка экспорта: {message}")
        QMessageBox.critical(self, "Ошибка обработки", message)

    def _render_finished(self) -> None:
        self.render_button.setEnabled(True)
        self.edit_tabs.setEnabled(True)
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is self.worker:
            self.worker = None
        self.busy_changed.emit(False)

    def save_as(self) -> None:
        if not self.output_path or not Path(self.output_path).is_file():
            QMessageBox.warning(self, "Файл недоступен", "Сначала экспортируйте видео.")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить готовое видео",
            Path(self.output_path).name,
            "MP4 video (*.mp4)",
        )
        if not destination:
            return
        target = Path(destination)
        if target.suffix.lower() != ".mp4":
            target = target.with_suffix(".mp4")
        try:
            shutil.copy2(self.output_path, target)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return
        self.log_message.emit(f"Копия сохранена: {target}")
        QMessageBox.information(self, "Сохранено", f"Видео сохранено:\n{target}")

    def is_busy(self) -> bool:
        return self.worker is not None
