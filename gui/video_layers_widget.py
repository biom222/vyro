from __future__ import annotations

from copy import deepcopy

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QTableView, QVBoxLayout, QWidget,
)


class VideoLayersWidget(QWidget):
    """Project-local picture-in-picture tracks above the primary sequence."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers: list[dict] = []
        self.duration = 0.0
        self.sources: dict[int, dict] = {}
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Видеослои (до 4, без звука)"))
        self.source = QComboBox()
        self.source.setMinimumWidth(150)
        self.source.setMaximumWidth(380)
        self.source.currentIndexChanged.connect(self._layer_changed)
        controls.addWidget(self.source)
        controls.addStretch(1)
        add = QPushButton("Добавить слой")
        add.clicked.connect(self.add_layer)
        controls.addWidget(add)
        remove = QPushButton("Удалить")
        remove.clicked.connect(self.remove_selected)
        controls.addWidget(remove)
        root.addLayout(controls)

        self.table = QTableView()
        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["Источник", "На шкале", "До", "Ширина"])
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(lambda current, _: self._select_row(current.row()))
        root.addWidget(self.table, 1)

        form = QFormLayout()
        time_row = QHBoxLayout()
        self.start = self._spin(0, 3600, 0.1, " сек.")
        self.end = self._spin(0, 3600, 0.1, " сек.")
        self.source_start = self._spin(0, 3600, 0.1, " сек.")
        for label, spin in (("От", self.start), ("До", self.end), ("Исходник с", self.source_start)):
            time_row.addWidget(QLabel(label))
            time_row.addWidget(spin)
            spin.valueChanged.connect(self._layer_changed)
        form.addRow("Время", time_row)
        geometry = QHBoxLayout()
        self.x = self._spin(0, 100, 1, " %")
        self.y = self._spin(0, 100, 1, " %")
        self.width = self._spin(10, 100, 1, " %")
        self.opacity = self._spin(0, 100, 1, " %")
        for label, spin in (("X", self.x), ("Y", self.y), ("Ширина", self.width),
                            ("Непрозрачность", self.opacity)):
            geometry.addWidget(QLabel(label))
            geometry.addWidget(spin)
            spin.valueChanged.connect(self._layer_changed)
        geometry.addStretch()
        form.addRow("Геометрия", geometry)
        root.addLayout(form)
        root.addWidget(QLabel("Положение задаётся в процентах свободного пространства кадра."))
        self._select_row(-1)

    @staticmethod
    def _spin(low: float, high: float, step: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(2 if step < 1 else 0)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setFixedWidth(116 if step < 1 else 80)
        return spin

    def set_sources(self, clips: list[dict], duration: float) -> None:
        self._loading = True
        self.duration = max(0.0, float(duration))
        self.sources = {int(clip["video_id"]): clip for clip in clips}
        previous = self.source.currentData()
        self.source.clear()
        for video_id, clip in self.sources.items():
            self.source.addItem(str(clip["name"]), video_id)
        if previous in self.sources:
            self.source.setCurrentIndex(self.source.findData(previous))
        for spin in (self.start, self.end):
            spin.setMaximum(self.duration)
        if self.duration < 0.1:
            self.layers.clear()
        else:
            for layer in self.layers:
                layer["end"] = min(layer["end"], self.duration)
                layer["start"] = min(layer["start"], max(0, layer["end"] - 0.1))
        self._refresh(max(0, self.table.currentIndex().row()))
        self._loading = False

    def set_layers(self, layers: list[dict], clips: list[dict], duration: float) -> None:
        self.layers = deepcopy(layers) if isinstance(layers, list) else []
        self.set_sources(clips, duration)

    def export_layers(self) -> list[dict]:
        return deepcopy(self.layers)

    def add_layer(self) -> None:
        video_id = self.source.currentData()
        if video_id is None or self.duration < 0.1 or len(self.layers) >= 4:
            return
        clip = self.sources[video_id]
        end = min(2.0, self.duration, float(clip["duration"]))
        if end < 0.1:
            return
        self.layers.append({"video_id": video_id, "start": 0.0, "end": end,
                            "source_start": 0.0, "x": 0.5, "y": 0.05,
                            "width": 0.5, "opacity": 1.0})
        self._refresh(len(self.layers) - 1)
        self.changed.emit()

    def remove_selected(self) -> None:
        row = self.table.currentIndex().row()
        if 0 <= row < len(self.layers):
            self.layers.pop(row)
            self._refresh(max(0, row - 1))
            self.changed.emit()

    def _refresh(self, selected: int) -> None:
        self.model.setRowCount(0)
        for layer in self.layers:
            source = self.sources.get(layer["video_id"], {})
            self.model.appendRow([QStandardItem(str(value)) for value in (
                source.get("name", f"Видео #{layer['video_id']}"),
                f"{layer['start']:.2f}", f"{layer['end']:.2f}",
                f"{layer['width'] * 100:.0f}%")])
        if self.layers:
            self.table.selectRow(min(selected, len(self.layers) - 1))
        else:
            self._select_row(-1)

    def _select_row(self, row: int) -> None:
        active = 0 <= row < len(self.layers)
        was_loading = self._loading
        self._loading = True
        self.source.setEnabled(bool(self.sources))
        for widget in (self.start, self.end, self.source_start,
                       self.x, self.y, self.width, self.opacity):
            widget.setEnabled(active)
        if active:
            layer = self.layers[row]
            self.source.setCurrentIndex(max(0, self.source.findData(layer["video_id"])))
            self.start.setValue(layer["start"])
            self.end.setValue(layer["end"])
            self.source_start.setValue(layer["source_start"])
            self.x.setValue(layer["x"] * 100)
            self.y.setValue(layer["y"] * 100)
            self.width.setValue(layer["width"] * 100)
            self.opacity.setValue(layer["opacity"] * 100)
        self._loading = was_loading

    def _layer_changed(self) -> None:
        row = self.table.currentIndex().row()
        if self._loading or not 0 <= row < len(self.layers):
            return
        video_id = self.source.currentData()
        if video_id not in self.sources or self.end.value() - self.start.value() < 0.1:
            return
        if self.source_start.value() + self.end.value() - self.start.value() > self.sources[video_id]["duration"] + 0.05:
            return
        layer = self.layers[row]
        layer.update(video_id=video_id, start=self.start.value(), end=self.end.value(),
                     source_start=self.source_start.value(), x=self.x.value() / 100,
                     y=self.y.value() / 100, width=self.width.value() / 100,
                     opacity=self.opacity.value() / 100)
        self.model.item(row, 0).setText(self.sources[video_id]["name"])
        self.model.item(row, 1).setText(f"{layer['start']:.2f}")
        self.model.item(row, 2).setText(f"{layer['end']:.2f}")
        self.model.item(row, 3).setText(f"{layer['width'] * 100:.0f}%")
        self.changed.emit()
