#!/usr/bin/env python3
"""
AIO Runtime Installer - Entry point
"""

import sys
import os

app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# Must happen before QApplication is constructed. Qt6 enables its own
# high-DPI scaling by default, but on Windows the *process* also needs to
# declare itself DPI-aware (via shcore) so the OS doesn't fall back to
# blurry bitmap-stretching before Qt's platform plugin gets a chance to set
# it — a plain `python.exe` process has no manifest declaring this itself.
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # Windows 7/8 fallback
        except (AttributeError, OSError):
            pass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication
from ui import MainWindow


def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("AIO Runtime Installer")
    app.setOrganizationName("EchoStorm")

    icon_path = os.path.join(app_dir, "assets", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
