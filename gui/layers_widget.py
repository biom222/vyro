from __future__ import annotations

from copy import deepcopy

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableView,
    QVBoxLayout, QWidget,
)


class LayersWidget(QWidget):
    """Edit independent timed title layers and their animation keyframes."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers: list[dict] = []
        self.duration = 0.0
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Титры (до 8 слоёв)"))
        title_row.addStretch()
        add = QPushButton("Добавить титр")
        add.clicked.connect(self.add_title)
        title_row.addWidget(add)
        remove = QPushButton("Удалить")
        remove.clicked.connect(self.remove_selected)
        title_row.addWidget(remove)
        root.addLayout(title_row)

        self.table = QTableView()
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Текст", "Начало", "Конец"])
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(65)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(lambda current, _: self._select_layer(current.row()))
        root.addWidget(self.table, 1)

        form = QFormLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Текст титра")
        self.text.textChanged.connect(self._layer_changed)
        form.addRow("Текст", self.text)
        time_row = QHBoxLayout()
        self.start = self._time_spin()
        self.end = self._time_spin()
        self.start.valueChanged.connect(self._layer_changed)
        self.end.valueChanged.connect(self._layer_changed)
        time_row.addWidget(QLabel("От"))
        time_row.addWidget(self.start)
        time_row.addWidget(QLabel("До"))
        time_row.addWidget(self.end)
        self.size = QSpinBox()
        self.size.setRange(16, 160)
        self.size.setValue(64)
        self.size.valueChanged.connect(self._layer_changed)
        time_row.addWidget(QLabel("Размер"))
        time_row.addWidget(self.size)
        self.color = QComboBox()
        for label, value in (("Белый", "white"), ("Жёлтый", "yellow"), ("Голубой", "#69c0ff")):
            self.color.addItem(label, value)
        self.color.currentIndexChanged.connect(self._layer_changed)
        time_row.addWidget(self.color)
        form.addRow("Время", time_row)
        root.addLayout(form)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Ключевые кадры: время, положение и прозрачность"))
        key_row.addStretch()
        add_key = QPushButton("Добавить кадр")
        add_key.clicked.connect(self.add_keyframe)
        key_row.addWidget(add_key)
        remove_key = QPushButton("Удалить кадр")
        remove_key.clicked.connect(self.remove_keyframe)
        key_row.addWidget(remove_key)
        root.addLayout(key_row)
        self.key_table = QTableView()
        self.key_model = QStandardItemModel(0, 4, self)
        self.key_model.setHorizontalHeaderLabels(["Сек.", "X %", "Y %", "Непрозр. %"])
        self.key_table.setModel(self.key_model)
        self.key_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.key_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.key_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.key_table.verticalHeader().hide()
        self.key_table.setShowGrid(False)
        self.key_table.setMinimumHeight(65)
        self.key_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.key_table.selectionModel().currentRowChanged.connect(lambda current, _: self._select_keyframe(current.row()))
        root.addWidget(self.key_table, 1)

        values = QHBoxLayout()
        self.key_time = self._time_spin()
        self.key_x = self._percent_spin(50)
        self.key_y = self._percent_spin(80)
        self.key_opacity = self._percent_spin(100)
        for label, spin in (("Время", self.key_time), ("X", self.key_x),
                            ("Y", self.key_y), ("Непрозрачность", self.key_opacity)):
            values.addWidget(QLabel(label))
            values.addWidget(spin)
            spin.valueChanged.connect(self._keyframe_changed)
        values.addStretch()
        root.addLayout(values)
        self._select_layer(-1)

    @staticmethod
    def _time_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 3600)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setSuffix(" сек.")
        return spin

    @staticmethod
    def _percent_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(value)
        spin.setSuffix(" %")
        return spin

    def set_duration(self, duration: float) -> None:
        was_loading = self._loading
        self._loading = True
        self.duration = max(0.0, float(duration))
        if self.duration < 0.1:
            self.layers.clear()
        else:
            for layer in self.layers:
                layer["end"] = min(layer["end"], self.duration)
                layer["start"] = min(layer["start"], max(0.0, layer["end"] - 0.1))
                for key in layer["keyframes"]:
                    key["time"] = min(layer["end"], max(layer["start"], key["time"]))
                layer["keyframes"] = self._deduplicate_keys(layer["keyframes"])
        for spin in (self.start, self.end, self.key_time):
            spin.setMaximum(max(0.0, self.duration))
        self._loading = was_loading

    def set_layers(self, layers: list[dict], duration: float) -> None:
        self._loading = True
        self.set_duration(duration)
        self.layers = deepcopy(layers) if isinstance(layers, list) else []
        self._refresh_layers(0)
        self._loading = False

    def export_layers(self) -> list[dict]:
        return deepcopy(self.layers)

    def add_title(self) -> None:
        if self.duration < 0.1 or len(self.layers) >= 8:
            return
        end = self.duration
        fade = min(0.3, end / 4)
        self.layers.append({"text": "Новый титр", "start": 0.0, "end": end,
                            "font_size": 64, "color": "white", "keyframes": [
            {"time": 0.0, "x": 0.5, "y": 0.8, "opacity": 0.0},
            {"time": fade, "x": 0.5, "y": 0.8, "opacity": 1.0},
            {"time": end - fade, "x": 0.5, "y": 0.8, "opacity": 1.0},
            {"time": end, "x": 0.5, "y": 0.8, "opacity": 0.0},
        ]})
        self._refresh_layers(len(self.layers) - 1)
        self.changed.emit()

    def remove_selected(self) -> None:
        row = self.table.currentIndex().row()
        if 0 <= row < len(self.layers):
            self.layers.pop(row)
            self._refresh_layers(max(0, row - 1))
            self.changed.emit()

    def _refresh_layers(self, selected: int) -> None:
        self.model.setRowCount(0)
        for layer in self.layers:
            self.model.appendRow([QStandardItem(str(value)) for value in (
                layer.get("text", ""), f"{layer.get('start', 0):.2f}", f"{layer.get('end', 0):.2f}")])
        if self.layers:
            self.table.selectRow(max(0, min(selected, len(self.layers) - 1)))
        else:
            self._select_layer(-1)

    def _select_layer(self, row: int) -> None:
        active = 0 <= row < len(self.layers)
        was_loading = self._loading
        self._loading = True
        for widget in (self.text, self.start, self.end, self.size, self.color, self.key_table,
                       self.key_time, self.key_x, self.key_y, self.key_opacity):
            widget.setEnabled(active)
        if active:
            layer = self.layers[row]
            self.text.setText(str(layer.get("text", "")))
            self.start.setValue(float(layer.get("start", 0)))
            self.end.setValue(float(layer.get("end", self.duration)))
            self.size.setValue(int(layer.get("font_size", 64)))
            self.color.setCurrentIndex(max(0, self.color.findData(layer.get("color", "white"))))
        self._refresh_keys(0)
        self._loading = was_loading

    def _layer_changed(self) -> None:
        row = self.table.currentIndex().row()
        if self._loading or not 0 <= row < len(self.layers) or self.end.value() - self.start.value() < 0.1:
            return
        layer = self.layers[row]
        old_start, old_end = layer["start"], layer["end"]
        layer.update(text=self.text.text(), start=self.start.value(), end=self.end.value(),
                     font_size=self.size.value(), color=self.color.currentData())
        if old_start != layer["start"] or old_end != layer["end"]:
            for key in layer["keyframes"]:
                key["time"] = min(layer["end"], max(layer["start"], key["time"]))
            layer["keyframes"] = self._deduplicate_keys(layer["keyframes"])
            self._refresh_keys(0)
        self.model.item(row, 0).setText(layer["text"])
        self.model.item(row, 1).setText(f"{layer['start']:.2f}")
        self.model.item(row, 2).setText(f"{layer['end']:.2f}")
        self.changed.emit()

    @staticmethod
    def _deduplicate_keys(keys: list[dict]) -> list[dict]:
        ordered = sorted(keys, key=lambda key: key["time"])
        return [key for index, key in enumerate(ordered)
                if index == 0 or key["time"] - ordered[index - 1]["time"] >= 0.001]

    def _refresh_keys(self, selected: int) -> None:
        self.key_model.setRowCount(0)
        row = self.table.currentIndex().row()
        if not 0 <= row < len(self.layers):
            return
        for key in self.layers[row]["keyframes"]:
            self.key_model.appendRow([QStandardItem(str(value)) for value in (
                f"{key['time']:.2f}", round(key["x"] * 100), round(key["y"] * 100),
                round(key["opacity"] * 100))])
        if self.key_model.rowCount():
            self.key_table.selectRow(min(selected, self.key_model.rowCount() - 1))

    def _select_keyframe(self, row: int) -> None:
        layer_row = self.table.currentIndex().row()
        if not 0 <= layer_row < len(self.layers):
            return
        keys = self.layers[layer_row]["keyframes"]
        if not 0 <= row < len(keys):
            return
        key = keys[row]
        was_loading = self._loading
        self._loading = True
        self.key_time.setRange(self.layers[layer_row]["start"], self.layers[layer_row]["end"])
        self.key_time.setValue(key["time"])
        self.key_x.setValue(round(key["x"] * 100))
        self.key_y.setValue(round(key["y"] * 100))
        self.key_opacity.setValue(round(key["opacity"] * 100))
        self._loading = was_loading

    def add_keyframe(self) -> None:
        row = self.table.currentIndex().row()
        if not 0 <= row < len(self.layers):
            return
        layer = self.layers[row]
        keys = layer["keyframes"]
        if len(keys) >= 20:
            return
        time = self.key_time.value()
        if any(abs(key["time"] - time) < 0.001 for key in keys):
            return
        keys.append({"time": time, "x": self.key_x.value() / 100,
                     "y": self.key_y.value() / 100, "opacity": self.key_opacity.value() / 100})
        keys.sort(key=lambda key: key["time"])
        self._refresh_keys(next(index for index, key in enumerate(keys) if key["time"] == time))
        self.changed.emit()

    def remove_keyframe(self) -> None:
        layer_row, key_row = self.table.currentIndex().row(), self.key_table.currentIndex().row()
        if not 0 <= layer_row < len(self.layers):
            return
        keys = self.layers[layer_row]["keyframes"]
        if 0 <= key_row < len(keys) and len(keys) > 1:
            keys.pop(key_row)
            self._refresh_keys(max(0, key_row - 1))
            self.changed.emit()

    def _keyframe_changed(self) -> None:
        layer_row, key_row = self.table.currentIndex().row(), self.key_table.currentIndex().row()
        if self._loading or not 0 <= layer_row < len(self.layers):
            return
        keys = self.layers[layer_row]["keyframes"]
        if not 0 <= key_row < len(keys):
            return
        time = self.key_time.value()
        if any(index != key_row and abs(key["time"] - time) < 0.001 for index, key in enumerate(keys)):
            return
        keys[key_row].update(time=time, x=self.key_x.value() / 100,
                             y=self.key_y.value() / 100, opacity=self.key_opacity.value() / 100)
        keys.sort(key=lambda key: key["time"])
        self._refresh_keys(next(index for index, key in enumerate(keys) if key["time"] == time))
        self.changed.emit()
