"""Renders the main window (after a real scan) to a PNG for the README and visual checks.

    venv\Scripts\python.exe tools\screenshot.py out.png [options]

    --width N --height N     window size (default 1180x780)
    --theme dark|light       force a theme (default: whatever the settings say)
    --expand "A,B"           expand only these categories, collapse the rest
    --select KEY             highlight a component so the Details tab shows it
    --no-banner              hide the "not running as administrator" banner

The theme and window settings go to a throw-away data folder, so running this
never changes your real settings.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("RUNTIME_FORGE_DATA_DIR", tempfile.mkdtemp(prefix="rf_shot_"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path("screenshot.png")
    width, height = int(_opt("--width", 1180)), int(_opt("--height", 780))

    app = QApplication(sys.argv)
    window = MainWindow()
    window._save_settings = lambda: None  # don't persist the screenshot's geometry
    if _opt("--theme"):
        window._set_theme_pref(_opt("--theme"))
    window.resize(width, height)
    window.show()
    deadline = time.time() + 90
    while window.scan_worker is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)

    if "--no-banner" in sys.argv and hasattr(window, "banner"):
        window.banner.hide()
    if _opt("--expand"):
        wanted = {c.strip() for c in _opt("--expand").split(",")}
        for name, cat_item in window.category_items.items():
            cat_item.setExpanded(name in wanted)
    if _opt("--select"):
        item = window.tree_items[_opt("--select")]
        window.tree.setCurrentItem(item)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    window.tree.verticalScrollBar().setValue(0)
    app.processEvents()
    window.grab().save(str(out))
    print(f"saved {out} ({width}x{height})")
    window.close()


if __name__ == "__main__":
    main()
