from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPalette
from PyQt6.QtWidgets import QSizePolicy, QWidget


class PreviewCanvas(QWidget):
    """Paint decoded frames and edit overlays without a native video child window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image = QImage()
        self.vertical = True
        self.crop_position = 0.5
        self.caption = ""
        self.text_position = "bottom"
        self.font_size = 64
        self.font_color = "white"
        self.output_width = 1920
        self.message = "Добавьте видео\nПервый кадр появится здесь"

    def set_image(self, image: QImage) -> None:
        if not image.isNull():
            self.image = image
            self.update()

    def clear(self) -> None:
        self.image = QImage()
        self.message = "Загрузка видео…"
        self.update()

    def source_rect(self) -> QRectF:
        rect = QRectF(self.image.rect())
        if self.vertical and not rect.isEmpty():
            width = min(rect.width(), rect.height() * 9 / 16)
            height = min(rect.height(), rect.width() * 16 / 9)
            rect = QRectF((rect.width() - width) * self.crop_position,
                          (rect.height() - height) / 2, width, height)
        return rect

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.image.isNull():
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        source = self.source_rect()
        scale = min((self.width() - 24) / source.width(), (self.height() - 24) / source.height())
        target = QRectF(0, 0, source.width() * scale, source.height() * scale)
        target.moveCenter(QRectF(self.rect()).center())
        painter.drawImage(target, self.image, source)
        if not self.caption:
            return
        # Use output-space coordinates so the overlay tracks the exported dimensions.
        output_width = 1080 if self.vertical else self.output_width
        output_scale = target.width() / output_width
        font = QFont("Arial")
        font.setBold(True)
        font.setPixelSize(max(1, round(self.font_size * output_scale)))
        path = QPainterPath()
        path.addText(0, 0, font, self.caption)
        bounds = path.boundingRect()
        x = target.center().x() - bounds.width() / 2 - bounds.left()
        y_top = {
            "top": target.top() + target.height() * 0.10,
            "center": target.center().y() - bounds.height() / 2,
            "bottom": target.bottom() - target.height() * 0.12 - bounds.height(),
        }[self.text_position]
        painter.setClipRect(target)
        painter.translate(x, y_top - bounds.top())
        painter.setPen(QPen(QColor("#d9000000"), max(1, 8 * output_scale)))
        painter.setBrush(QColor(self.font_color))
        painter.drawPath(path)
