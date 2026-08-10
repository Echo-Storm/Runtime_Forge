#!/usr/bin/env python3
"""
AIO Runtime Installer - Entry point
"""

import sys
import os

app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# Qt6's Windows platform plugin already declares per-monitor-v2 DPI
# awareness itself before the first window is created (unlike Qt5, which
# needed a manual shcore.SetProcessDpiAwareness() pre-set to avoid blurry
# bitmap-stretching). Pre-setting it here as well made Windows reject Qt's
# own later call with "Access is denied" (harmless, but noisy) since a
# process's DPI awareness can only be set once — so leave it to Qt.

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
