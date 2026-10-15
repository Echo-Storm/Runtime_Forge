"""Renders the main window (after a real scan) to a PNG for docs/visual checks.

    venv\Scripts\python.exe tools\screenshot.py [out.png] [--width 1180 --height 780]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0] if args else "screenshot.png")
    width = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 1180
    height = int(sys.argv[sys.argv.index("--height") + 1]) if "--height" in sys.argv else 780

    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(width, height)
    window.show()
    deadline = time.time() + 60
    while window.scan_worker is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    if "--no-banner" in sys.argv and hasattr(window, "banner"):
        window.banner.hide()
        app.processEvents()
    window.grab().save(str(out))
    window._save_settings = lambda: None  # don't persist the screenshot's geometry
    print(f"saved {out} ({width}x{height})")
    window.close()


if __name__ == "__main__":
    main()
