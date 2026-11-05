"""Open existing local files in the platform file manager without invoking a shell."""
from pathlib import Path
import subprocess
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox


def reveal_file(value, parent=None) -> bool:
    if not value or not Path(value).is_file():
        QMessageBox.warning(parent, "Файл недоступен", "Файл не найден. Восстановите исходник или повторите экспорт.")
        return False
    path = Path(value).resolve()
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", f"/select,{path}"], shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)], shell=False)
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))):
            raise OSError("File manager unavailable")
    except OSError:
        QMessageBox.warning(parent, "Папка не открыта", f"Откройте папку вручную:\n{path.parent}")
        return False
    return True
