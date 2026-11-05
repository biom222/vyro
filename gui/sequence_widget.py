"""Ordered project clips and an optional background music track."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget, QFormLayout,
)
from gui.worker import AudioImportWorker


class SequenceWidget(QWidget):
    add_requested = pyqtSignal()
    preview_requested = pyqtSignal()
    effect_preview_requested = pyqtSignal()
    changed = pyqtSignal()
    selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.clips: list[dict] = []
        self.primary_id: int | None = None
        self.music_path = ""
        self.music_import_worker: AudioImportWorker | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)
        controls = QHBoxLayout()
        self.buttons = {}
        for label, handler in (("Добавить клип", self.add_requested.emit),
                               ("Просмотр сборки", self.preview_requested.emit),
                               ("Выше", lambda: self.move_selected(-1)),
                               ("Ниже", lambda: self.move_selected(1)),
                               ("Убрать", self.remove_selected)):
            button = QPushButton(label)
            self.buttons[label] = button
            if label == "Просмотр сборки":
                button.setToolTip("Просмотр исходных обрезок по порядку. Для эффектов используйте «Просмотр с эффектами».")
            if label == "Убрать":
                self.remove_button = button
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        root.addLayout(controls)
        self.effect_preview_button = QPushButton("Просмотр с эффектами")
        self.effect_preview_button.setToolTip("Подготовить просмотр переходов, музыки и слоёв. Первый запуск займёт время.")
        self.effect_preview_button.clicked.connect(self.effect_preview_requested.emit)
        controls.addWidget(self.effect_preview_button)
        self.table = QTableView()
        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["Клип", "Начало", "Конец", "Длительность"])
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(80)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self._select_row(current.row()))
        root.addWidget(self.table, 1)
        self.properties = QWidget()
        details = QVBoxLayout(self.properties)
        details.setContentsMargins(8, 8, 8, 8)
        self.selection_label = QLabel("Выберите клип в сборке")
        self.selection_label.setWordWrap(True)
        details.addWidget(self.selection_label)
        detail = QFormLayout()
        detail.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.start_spin = QDoubleSpinBox()
        self.end_spin = QDoubleSpinBox()
        for spin in (self.start_spin, self.end_spin):
            spin.setRange(0, 600)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setSuffix(" сек.")
            spin.valueChanged.connect(self._trim_changed)
        detail.addRow("Начало в исходнике", self.start_spin)
        detail.addRow("Конец в исходнике", self.end_spin)
        self.transition = QComboBox()
        self.transition.addItem("Склейка", "cut")
        self.transition.addItem("Растворение", "dissolve")
        self.transition.currentIndexChanged.connect(self.changed.emit)
        detail.addRow("Переходы между клипами", self.transition)
        self.transition_duration = QDoubleSpinBox()
        self.transition_duration.setRange(0.1, 2.0)
        self.transition_duration.setValue(0.5)
        self.transition_duration.setSingleStep(0.1)
        self.transition_duration.setSuffix(" сек.")
        self.transition_duration.valueChanged.connect(self.changed.emit)
        detail.addRow("Длительность перехода", self.transition_duration)
        self.music_button = QPushButton("Музыка…")
        self.music_button.clicked.connect(self.choose_music)
        detail.addRow("Музыка сборки", self.music_button)
        self.music_label = QLabel("Без музыки")
        self.music_label.setObjectName("muted")
        self.music_label.setWordWrap(True)
        detail.addRow(self.music_label)
        clear = QPushButton("Убрать музыку")
        clear.clicked.connect(lambda: self.set_music(""))
        detail.addRow(clear)
        self.music_volume = QDoubleSpinBox()
        self.music_volume.setRange(0, 100)
        self.music_volume.setValue(25)
        self.music_volume.setSuffix(" %")
        self.music_volume.valueChanged.connect(self.changed.emit)
        detail.addRow("Громкость музыки", self.music_volume)
        details.addLayout(detail)
        details.addStretch()
        self.transition.currentIndexChanged.connect(self._transition_state)
        self._transition_state()
        self._select_row(-1)

    def set_clips(self, primary_id: int, clips: list[dict], music_path: str = "", music_volume: float = 0.25,
                  transition: str = "cut", transition_duration: float = 0.5,
                  selected_index: int = 0) -> None:
        self.primary_id = primary_id
        self.clips = [dict(clip) for clip in clips]
        self.music_path = music_path
        self.music_label.setText(Path(music_path).name if music_path else "Без музыки")
        self.music_volume.blockSignals(True)
        self.music_volume.setValue(round(music_volume * 100))
        self.music_volume.blockSignals(False)
        self.transition.blockSignals(True)
        self.transition.setCurrentIndex(max(0, self.transition.findData(transition)))
        self.transition.blockSignals(False)
        self._transition_state()
        self.transition_duration.blockSignals(True)
        self.transition_duration.setValue(transition_duration)
        self.transition_duration.blockSignals(False)
        self._refresh(selected_index)

    def add_video(self, video_id: int, path: str, duration: float) -> None:
        self.clips.append({"video_id": video_id, "name": Path(path).name,
                           "duration": duration, "start_time": 0.0, "end_time": duration})
        self._refresh(len(self.clips) - 1)
        self.changed.emit()

    def _refresh(self, selected_row: int) -> None:
        self.model.setRowCount(0)
        for clip in self.clips:
            start, end = clip["start_time"], clip["end_time"]
            items = [QStandardItem(str(value)) for value in
                     (clip["name"], f"{start:.2f}", f"{end:.2f}", f"{end - start:.2f} сек.")]
            items[0].setToolTip(f"Видео #{clip['video_id']}")
            self.model.appendRow(items)
        if self.clips:
            row = max(0, min(selected_row, len(self.clips) - 1))
            self.table.setCurrentIndex(self.model.index(row, 0))
            self.table.selectRow(row)
        else:
            self._select_row(-1)

    def _select_row(self, row: int) -> None:
        active = 0 <= row < len(self.clips)
        self.selection_label.setText(f"Клип {row + 1}: {self.clips[row]['name']}" if active else "Выберите клип в сборке")
        removable = active and self.clips[row]["video_id"] != self.primary_id
        self.remove_button.setEnabled(removable)
        self.remove_button.setToolTip("Убрать из сборки (Delete); файл останется в медиатеке" if removable else "Основной клип проекта нельзя убрать")
        for label in ("Добавить клип", "Просмотр сборки"):
            self.buttons[label].setEnabled(bool(self.clips))
            self.buttons[label].setToolTip("Сначала добавьте видео" if not self.clips else
                "Добавить исходник в текущую сборку" if label == "Добавить клип" else
                "Просмотр обрезок по порядку; переходы и слои — через просмотр с эффектами")
        self.buttons["Выше"].setEnabled(active and row > 0)
        self.buttons["Ниже"].setEnabled(active and row < len(self.clips)-1)
        self.effect_preview_button.setEnabled(bool(self.clips))
        for spin in (self.start_spin, self.end_spin):
            spin.setEnabled(active)
        if active:
            clip = self.clips[row]
            self.start_spin.blockSignals(True)
            self.end_spin.blockSignals(True)
            self.start_spin.setMaximum(clip["duration"])
            self.end_spin.setMaximum(clip["duration"])
            self.start_spin.setValue(clip["start_time"])
            self.end_spin.setValue(clip["end_time"])
            self.start_spin.blockSignals(False)
            self.end_spin.blockSignals(False)
            self.selected.emit(row)

    def _transition_state(self) -> None:
        self.transition_duration.setEnabled(self.transition.currentData() == "dissolve")
        self.transition_duration.setToolTip("Длительность общая для всех переходов" if self.transition_duration.isEnabled() else "Доступно для растворения")

    def _trim_changed(self) -> None:
        row = self.table.currentIndex().row()
        if not 0 <= row < len(self.clips):
            return
        start, end = self.start_spin.value(), self.end_spin.value()
        if end - start < 0.1:
            return
        clip = self.clips[row]
        clip["start_time"], clip["end_time"] = start, end
        for column, value in ((1, f"{start:.2f}"), (2, f"{end:.2f}"),
                              (3, f"{end - start:.2f} сек.")):
            self.model.item(row, column).setText(value)
        self.changed.emit()

    def set_selected_range(self, start: float, end: float) -> None:
        row = self.table.currentIndex().row()
        if not 0 <= row < len(self.clips) or end - start < 0.1:
            return
        clip = self.clips[row]
        if end > clip["duration"] + 0.05:
            return
        clip["start_time"], clip["end_time"] = start, min(end, clip["duration"])
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.start_spin.setValue(start)
        self.end_spin.setValue(min(end, clip["duration"]))
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)
        self.model.item(row, 1).setText(f"{start:.2f}")
        self.model.item(row, 2).setText(f"{end:.2f}")
        self.model.item(row, 3).setText(f"{end-start:.2f} сек.")
        self.changed.emit()

    def move_selected(self, offset: int) -> None:
        row = self.table.currentIndex().row()
        destination = row + offset
        if not 0 <= row < len(self.clips) or not 0 <= destination < len(self.clips):
            return
        self.clips[row], self.clips[destination] = self.clips[destination], self.clips[row]
        self._refresh(destination)
        self.changed.emit()

    def remove_selected(self) -> None:
        row = self.table.currentIndex().row()
        if not 0 <= row < len(self.clips) or self.clips[row]["video_id"] == self.primary_id:
            return
        self.clips.pop(row)
        self._refresh(max(0, row - 1))
        self.changed.emit()

    def choose_music(self) -> None:
        if self.music_import_worker is not None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите аудиофайл", "", "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)")
        if path:
            self.music_label.setText("Копирование музыки…")
            self.music_button.setEnabled(False)
            worker = AudioImportWorker(path, self)
            self.music_import_worker = worker
            worker.progress.connect(lambda percent: self.music_label.setText(f"Копирование музыки… {percent}%"))
            worker.succeeded.connect(self.set_music)
            worker.error.connect(self._music_import_failed)
            worker.finished.connect(self._music_import_finished)
            worker.start()

    def _music_import_failed(self, message: str) -> None:
        self.music_label.setText(Path(self.music_path).name if self.music_path else "Без музыки")
        QMessageBox.warning(self, "Музыка не добавлена", message)

    def _music_import_finished(self) -> None:
        worker = self.music_import_worker
        self.music_import_worker = None
        self.music_button.setEnabled(True)
        if worker:
            worker.deleteLater()

    def is_busy(self) -> bool:
        return self.music_import_worker is not None and self.music_import_worker.isRunning()

    def set_effect_preview_active(self, active: bool) -> None:
        self.effect_preview_button.setText(
            "Вернуться к исходникам" if active else "Просмотр с эффектами"
        )

    def set_music(self, path: str) -> None:
        self.music_path = path
        self.music_label.setText(Path(path).name if path else "Без музыки")
        self.changed.emit()

    def render_params(self) -> dict:
        return {"clips": [{key: clip[key] for key in ("video_id", "start_time", "end_time")}
                          for clip in self.clips], "music_path": self.music_path,
                "music_volume": self.music_volume.value() / 100,
                "transition": self.transition.currentData(),
                "transition_duration": self.transition_duration.value()}
