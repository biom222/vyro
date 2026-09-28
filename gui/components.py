from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def page_header(title: str, subtitle: str, action: QPushButton | None = None) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 4)
    text = QVBoxLayout()
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    description = QLabel(subtitle)
    description.setObjectName("pageSubtitle")
    description.setWordWrap(True)
    text.addWidget(heading)
    text.addWidget(description)
    layout.addLayout(text, 1)
    if action is not None:
        layout.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)
    return widget
