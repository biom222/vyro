from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF, QPalette
from PyQt6.QtWidgets import QWidget
from gui.theme import ACCENT


class TimelineWidget(QWidget):
    """Single-clip editing timeline with draggable in/out handles and playhead."""

    position_changed = pyqtSignal(float)
    range_changed = pyqtSignal(float, float)

    LABEL_WIDTH = 92
    RULER_HEIGHT = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(178)
        self.setMaximumHeight(210)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Обрезка активного клипа")
        self.duration = 0.0
        self.position = 0.0
        self.start_time = 0.0
        self.end_time = 0.0
        self.clip_name = "Видео не добавлено"
        self.overlay_text = ""
        self._drag_mode: str | None = None

    def set_media(self, duration: float, name: str) -> None:
        self.duration = max(0.0, duration)
        self.position = 0.0
        self.start_time = 0.0
        self.end_time = self.duration
        self.clip_name = name
        self.update()

    def set_position(self, seconds: float, emit: bool = False) -> None:
        self.position = min(max(seconds, 0.0), self.duration)
        self.update()
        if emit:
            self.position_changed.emit(self.position)

    def set_range(self, start: float, end: float, emit: bool = False) -> None:
        if self.duration <= 0:
            return
        gap = min(0.1, self.duration)
        start = min(max(start, 0.0), self.duration - gap)
        end = min(max(end, start + gap), self.duration)
        self.start_time, self.end_time = start, end
        self.update()
        if emit:
            self.range_changed.emit(start, end)

    def set_overlay_text(self, text: str) -> None:
        self.overlay_text = text.strip()
        self.update()

    def _content_width(self) -> float:
        return max(1.0, self.width() - self.LABEL_WIDTH - 18)

    def _x_for_time(self, seconds: float) -> float:
        if self.duration <= 0:
            return float(self.LABEL_WIDTH)
        return self.LABEL_WIDTH + seconds / self.duration * self._content_width()

    def _time_for_x(self, x: float) -> float:
        ratio = (x - self.LABEL_WIDTH) / self._content_width()
        return min(max(ratio, 0.0), 1.0) * self.duration

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        surface = palette.color(QPalette.ColorRole.Base)
        control = palette.color(QPalette.ColorRole.Button)
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Window))

        track_x = self.LABEL_WIDTH
        track_w = self._content_width()
        video_y, video_h = 43, 58
        text_y, text_h = 112, 38

        painter.fillRect(QRectF(0, 0, self.LABEL_WIDTH - 1, self.height()), surface)
        painter.setPen(muted)
        painter.setFont(self.font())
        painter.drawText(QRectF(12, video_y, 70, video_h), Qt.AlignmentFlag.AlignVCenter, "Видео")
        painter.drawText(QRectF(12, text_y, 70, text_h), Qt.AlignmentFlag.AlignVCenter, "Текст")

        painter.fillRect(QRectF(track_x, video_y, track_w, video_h), surface)
        painter.fillRect(QRectF(track_x, text_y, track_w, text_h), surface)

        if self.duration > 0:
            tick_count = max(2, int(track_w // 85))
            painter.setPen(muted)
            for index in range(tick_count + 1):
                seconds = self.duration * index / tick_count
                x = self._x_for_time(seconds)
                painter.drawLine(QPointF(x, 20), QPointF(x, self.RULER_HEIGHT))
                label = self._format_time(seconds)
                painter.drawText(QRectF(x - 25, 1, 50, 17), Qt.AlignmentFlag.AlignCenter, label)

            start_x = self._x_for_time(self.start_time)
            end_x = self._x_for_time(self.end_time)
            clip_rect = QRectF(start_x, video_y + 3, max(4.0, end_x - start_x), video_h - 6)
            painter.setBrush(control)
            painter.setPen(QPen(QColor(ACCENT), 1))
            painter.drawRect(clip_rect)
            painter.setPen(text)
            painter.drawText(
                clip_rect.adjusted(13, 0, -13, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(self.clip_name, Qt.TextElideMode.ElideRight, max(0, int(clip_rect.width() - 26))),
            )

            for x in (start_x, end_x):
                painter.fillRect(QRectF(x - 4, video_y + 1, 8, video_h - 2), QColor(ACCENT))
                painter.setPen(text)
                painter.drawLine(QPointF(x, video_y + 19), QPointF(x, video_y + 39))

            if self.overlay_text:
                text_rect = QRectF(start_x, text_y + 3, max(4.0, end_x - start_x), text_h - 6)
                painter.setBrush(control)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(text_rect)
                painter.setPen(text)
                painter.drawText(
                    text_rect.adjusted(10, 0, -8, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    painter.fontMetrics().elidedText("T  " + self.overlay_text, Qt.TextElideMode.ElideRight, max(0, int(text_rect.width() - 18))),
                )

            play_x = self._x_for_time(self.position)
            painter.setPen(QPen(QColor(ACCENT), 2))
            painter.drawLine(QPointF(play_x, 24), QPointF(play_x, self.height() - 8))
            painter.setBrush(QColor(ACCENT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(
                QPolygonF([QPointF(play_x - 6, 24), QPointF(play_x + 6, 24), QPointF(play_x, 33)])
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.duration <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        x = event.position().x()
        on_clip = 43 <= event.position().y() <= 101
        if on_clip and abs(x - self._x_for_time(self.start_time)) <= 10:
            self._drag_mode = "start"
        elif on_clip and abs(x - self._x_for_time(self.end_time)) <= 10:
            self._drag_mode = "end"
        else:
            self._drag_mode = "playhead"
        self._apply_drag(x)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_mode:
            self._apply_drag(event.position().x())
            return
        x = event.position().x()
        near_handle = any(
            abs(x - self._x_for_time(value)) <= 10
            for value in (self.start_time, self.end_time)
        )
        self.setCursor(
            Qt.CursorShape.SizeHorCursor if near_handle else Qt.CursorShape.PointingHandCursor
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_mode = None

    def _apply_drag(self, x: float) -> None:
        value = self._time_for_x(x)
        if self._drag_mode == "start":
            self.start_time = max(0.0, min(value, self.end_time - min(0.1, self.duration)))
            self.range_changed.emit(self.start_time, self.end_time)
        elif self._drag_mode == "end":
            self.end_time = min(self.duration, max(value, self.start_time + min(0.1, self.duration)))
            self.range_changed.emit(self.start_time, self.end_time)
        else:
            self.position = value
            self.position_changed.emit(value)
        self.update()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0.0, seconds)
        return f"{int(total // 60)}:{total % 60:04.1f}"


class CompositionTimeline(QWidget):
    """A selectable overview in output time; editing stays in the existing models."""

    selected = pyqtSignal(str, int)
    seek_requested = pyqtSignal(float)
    LABEL_WIDTH = 86

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(136)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Шкала сборки: клипы, титры, видеослои и музыка")
        self.duration = 0.0
        self.position = 0.0
        self.items = []
        self.selection = ("video", 0)
        self.overlap = 0.0
        self.rows = [("video", -1, "Видео"), ("title", -1, "Титры"),
                     ("overlay", -1, "Видеослои"), ("music", -1, "Музыка")]

    def set_project(self, clips, titles, overlays, music, transition, overlap):
        self.items = []
        self.rows = [("video", -1, "Видео")]
        for kind, layers, label in (("title", titles, "Титр"), ("overlay", overlays, "Слой")):
            self.rows.extend((kind, index, f"{label} {index+1}") for index in range(len(layers)))
            if not layers:
                self.rows.append((kind, -1, label))
        self.rows.append(("music", -1, "Музыка"))
        self.setFixedHeight(36 + len(self.rows) * 25)
        self.overlap = overlap if transition == "dissolve" else 0.0
        offset = 0.0
        for index, clip in enumerate(clips):
            length = max(0.0, clip["end_time"] - clip["start_time"])
            self.items.append(("video", index, offset, offset + length, clip["name"]))
            offset += length - (self.overlap if index < len(clips) - 1 else 0)
        self.duration = max(0.0, offset)
        for kind, layers in (("title", titles), ("overlay", overlays)):
            for index, layer in enumerate(layers):
                self.items.append((kind, index, layer["start"], layer["end"],
                                   layer.get("text", f"Слой {index + 1}")))
        if music and self.duration:
            self.items.append(("music", 0, 0.0, self.duration, "Музыка"))
        self.update()

    def _x_for_time(self, seconds):
        return self.LABEL_WIDTH + seconds / max(0.001, self.duration) * max(1, self.width() - self.LABEL_WIDTH - 12)

    def item_rect(self, item):
        kind, _, start, end, _ = item
        row = next(index for index, (row_kind, row_index, _) in enumerate(self.rows)
                   if row_kind == kind and (row_index == item[1] or row_index == -1))
        return QRectF(self._x_for_time(start), 25 + row * 25,
                      max(3, self._x_for_time(end) - self._x_for_time(start)), 21)

    def set_position(self, seconds):
        self.position = min(max(0.0, seconds), self.duration)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Base))
        painter.setPen(muted)
        for index, (_, _, label) in enumerate(self.rows):
            painter.drawText(QRectF(6, 25 + index * 25, 76, 21), Qt.AlignmentFlag.AlignVCenter, label)
        if not self.duration:
            painter.drawText(self.rect().adjusted(self.LABEL_WIDTH, 0, 0, 0), Qt.AlignmentFlag.AlignCenter,
                             "Добавьте видео — здесь появится сборка")
            return
        ticks = max(2, (self.width() - self.LABEL_WIDTH) // 100)
        for index in range(ticks + 1):
            seconds = self.duration * index / ticks
            x = self._x_for_time(seconds)
            painter.drawText(QRectF(x - 24, 0, 48, 20), Qt.AlignmentFlag.AlignCenter,
                             TimelineWidget._format_time(seconds))
        for item in self.items:
            kind, index, start, end, label = item
            rect = self.item_rect(item)
            selected = (kind, index) == self.selection
            painter.fillRect(rect, QColor(ACCENT) if selected else palette.color(QPalette.ColorRole.Button))
            painter.setPen(palette.color(QPalette.ColorRole.Mid))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
            painter.drawLine(rect.topRight(), rect.bottomRight())
            label_rect = rect.adjusted(5, 0, -4, 0)
            if kind == "video" and index > 0 and self.overlap:
                transition = QRectF(rect.left(), rect.top(), max(2, self._x_for_time(start + self.overlap)-rect.left()), rect.height())
                painter.fillRect(transition, QColor(ACCENT))
                painter.setPen(text)
                painter.drawLine(transition.bottomLeft(), transition.topRight())
                label_rect.setLeft(transition.right() + 4)
            painter.setPen(text)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(0, int(label_rect.width()))))
        x = self._x_for_time(self.position)
        painter.setPen(QPen(QColor(ACCENT), 2))
        painter.drawLine(QPointF(x, 20), QPointF(x, self.height()-4))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.duration:
            return
        self.setFocus()
        point = event.position()
        for item in reversed(self.items):
            if self.item_rect(item).contains(point):
                self.selection = item[:2]
                self.selected.emit(*self.selection)
                self.update()
                return
        if point.x() >= self.LABEL_WIDTH:
            seconds = (point.x() - self.LABEL_WIDTH) / max(1, self.width() - self.LABEL_WIDTH - 12) * self.duration
            self.seek_requested.emit(min(self.duration, max(0, seconds)))
