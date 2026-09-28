"""Shared flat desktop theme for widgets and painted editor surfaces."""
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QAction, QColor, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QAbstractButton, QApplication, QStyle, QTableView

ACCENT = "#d97706"


def set_flat_icon(target, standard_pixmap):
    """Draw small desktop action icons with a transparent background."""
    target.setProperty("standardPixmap", standard_pixmap.value)
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QApplication.palette().color(QPalette.ColorRole.Text), 1.7))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if standard_pixmap == QStyle.StandardPixmap.SP_DialogOpenButton:
        path = QPainterPath()
        path.moveTo(2, 6)
        path.lineTo(7, 6)
        path.lineTo(9, 8)
        path.lineTo(18, 8)
        path.lineTo(16, 16)
        path.lineTo(2, 16)
        path.closeSubpath()
        painter.drawPath(path)
    elif standard_pixmap == QStyle.StandardPixmap.SP_DialogSaveButton:
        painter.drawRect(QRectF(3, 2, 14, 16))
        painter.drawRect(QRectF(6, 2, 8, 5))
        painter.drawRect(QRectF(6, 12, 8, 6))
    elif standard_pixmap in (QStyle.StandardPixmap.SP_MediaPlay, QStyle.StandardPixmap.SP_MediaPause):
        if standard_pixmap == QStyle.StandardPixmap.SP_MediaPlay:
            painter.drawPolygon(QPolygonF([QPointF(5, 3), QPointF(16, 10), QPointF(5, 17)]))
        else:
            painter.drawRect(QRectF(5, 3, 3, 14))
            painter.drawRect(QRectF(12, 3, 3, 14))
    elif standard_pixmap in (QStyle.StandardPixmap.SP_MediaSkipBackward,
                             QStyle.StandardPixmap.SP_MediaSkipForward):
        backward = standard_pixmap == QStyle.StandardPixmap.SP_MediaSkipBackward
        painter.drawLine(3 if backward else 17, 3, 3 if backward else 17, 17)
        if backward:
            painter.drawPolygon(QPolygonF([QPointF(16, 3), QPointF(5, 10), QPointF(16, 17)]))
        else:
            painter.drawPolygon(QPolygonF([QPointF(4, 3), QPointF(15, 10), QPointF(4, 17)]))
    elif standard_pixmap == QStyle.StandardPixmap.SP_FileDialogDetailedView:
        for y in (4, 9, 14):
            painter.drawRect(QRectF(3, y, 2, 2))
            painter.drawLine(8, y + 1, 17, y + 1)
    painter.end()
    target.setIcon(QIcon(pixmap))


def apply_theme(window, light=False):
    app = QApplication.instance()
    app.setStyle("Fusion")
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if sys.platform == "win32":
        font.setFamily("Segoe UI")
    elif sys.platform == "darwin":
        font.setFamily("SF Pro Text")
    else:
        font.setFamily("Cantarell")
    font.setPixelSize(12)
    app.setFont(font)
    bg, surface, text = ("#f5f5f5", "#ffffff", "#1a1a1a") if light else ("#1a1a1a", "#242424", "#e5e5e5")
    muted = "#707070" if light else "#8a8a8a"
    control = "#e5e5e5" if light else "#333333"
    edge = "#cccccc" if light else "#444444"
    palette = QPalette()
    roles = {"Window": bg, "Base": surface, "AlternateBase": bg, "WindowText": text,
             "Text": text, "Button": control, "ButtonText": text, "Highlight": ACCENT,
             "HighlightedText": "#ffffff", "PlaceholderText": muted, "Mid": edge,
             "ToolTipBase": surface, "ToolTipText": text}
    for role, value in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(muted))
    app.setPalette(palette)
    for target in window.findChildren(QAction) + window.findChildren(QAbstractButton):
        icon_id = target.property("standardPixmap")
        if icon_id is not None:
            set_flat_icon(target, QStyle.StandardPixmap(icon_id))
    for table in window.findChildren(QTableView):
        table.setShowGrid(False)
    window.setStyleSheet(f"""QWidget {{ color: {text}; font-size: 12px; }}
QMainWindow, QStackedWidget, QScrollArea {{ background: {bg}; }}
QFrame, QScrollArea, QDockWidget, QToolBar {{ border: 0; }}
QLabel {{ background: transparent; }}
QLabel#pageTitle, QLabel#sectionTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#pageSubtitle, QLabel#muted, QLabel#panelEyebrow {{ color: {muted}; }}
QLabel#panelEyebrow {{ font-size: 11px; padding: 2px; }}
QLabel#contextBanner {{ background: {surface}; padding: 6px; }}
QFrame#mediaBin, QFrame#inspectorPanel, QFrame#previewPanel, QFrame#timelinePanel {{ background: {surface}; }}
QPushButton, QToolButton {{ background: {control}; border: 0; border-radius: 2px; padding: 4px 8px; min-height: 20px; }}
QPushButton:hover, QToolButton:hover {{ background: {edge}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {ACCENT}; color: white; }}
QPushButton#primaryButton {{ background: {ACCENT}; color: white; }}
QPushButton:disabled, QToolButton:disabled {{ color: {muted}; background: {bg}; }}
QPushButton#transportButton, QPushButton#playButton {{ padding: 2px; min-height: 18px; }}
QLineEdit, QTextEdit, QAbstractSpinBox, QComboBox {{ background: {surface}; border: 1px solid {edge}; border-radius: 2px; padding: 3px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QTextEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QAbstractItemView {{ background: {surface}; alternate-background-color: {bg}; border: 0; selection-background-color: {ACCENT}; selection-color: white; }}
QAbstractItemView::item {{ padding: 3px; }}
QHeaderView::section {{ background: {control}; color: {text}; border: 0; padding: 5px; }}
QGroupBox {{ border: 0; background: {surface}; margin-top: 16px; padding: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 0; font-weight: 600; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: {surface}; padding: 6px 10px; color: {muted}; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {ACCENT}; }}
QProgressBar {{ border: 0; border-radius: 0; background: {control}; text-align: center; min-height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QSplitter::handle {{ background: {bg}; width: 5px; height: 5px; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QMenuBar, QMenu, QToolBar, QStatusBar {{ background: {surface}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::item {{ padding: 5px 24px; }}
QToolBar {{ spacing: 3px; padding: 3px; }}
QScrollBar:vertical {{ background: {bg}; width: 10px; }}
QScrollBar:horizontal {{ background: {bg}; height: 10px; }}
QScrollBar::handle {{ background: {edge}; border-radius: 0; min-width: 20px; min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {edge}; }}
""")
    window.editor_workspace.timeline.update()
    window.editor_workspace.canvas.update()
