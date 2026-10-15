"""
Tests for the light/dark theme, follow-Windows, drag-and-drop profile import,
the log toolbar and the app-update notice.

Run directly:
    venv\\Scripts\\python.exe tests\\test_theme_and_extras.py
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from core import http_cache
from core.definitions import InstalledState
from core.version_resolvers import LatestInfo
from ui import theme
from ui.main_window import COL_NAME, COL_STATUS, MainWindow
from ui.workers import AppUpdateCheck

app = QApplication(sys.argv)
results = {}


# ---- palette sanity: valid colors, readable contrast in BOTH schemes
def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


for scheme in theme.SCHEMES.values():
    fields = {k: v for k, v in vars(scheme).items() if k != "name"}
    results[f"{scheme.name}_all_fields_are_hex_colors"] = all(re.fullmatch(r"#[0-9a-fA-F]{6}", v) for v in fields.values())
    results[f"{scheme.name}_body_text_contrast_7_to_1"] = contrast(scheme.TEXT, scheme.BG) >= 7 and contrast(scheme.TEXT, scheme.SURFACE) >= 7
    results[f"{scheme.name}_dim_text_readable_on_surface"] = contrast(scheme.TEXT_DIM, scheme.SURFACE) >= 4.5
    results[f"{scheme.name}_status_colors_readable_on_surface"] = all(
        contrast(getattr(scheme, c), scheme.SURFACE) >= 3.5 for c in ("OK", "WARN", "ORANGE", "ERR", "ACCENT")
    )
    results[f"{scheme.name}_primary_button_text_readable"] = contrast(scheme.PRIMARY_TEXT, scheme.ACCENT_DIM) >= 4.5
    results[f"{scheme.name}_banner_text_readable"] = contrast(scheme.BANNER_TEXT, scheme.BANNER_BG) >= 4.5
    results[f"{scheme.name}_danger_text_readable"] = contrast(scheme.DANGER_TEXT, scheme.DANGER_BG) >= 4.5

results["stylesheet_follows_active_palette"] = (
    theme.set_scheme("light").BG in theme.build_stylesheet() and theme.set_scheme("dark").BG in theme.build_stylesheet()
    and theme.LIGHT.BG not in theme.build_stylesheet()
)
results["unknown_scheme_falls_back_to_dark"] = theme.set_scheme("nonsense").name == "dark"

# ---- the window
window = MainWindow()
if window.scan_worker is not None:
    window.scan_worker.wait()
    app.processEvents()
window._save_settings = lambda: None
key = next(iter(window.tree_items))
window._on_component_scanned(key, InstalledState(True, "1.0"), LatestInfo("2.0", "u", "f"))
item = window.tree_items[key]

window._set_theme_pref("dark")
dark_status = item.foreground(COL_STATUS).color().name()
dark_sheet = QApplication.instance().styleSheet()
window._set_theme_pref("light")
light_status = item.foreground(COL_STATUS).color().name()
results["switching_to_light_changes_the_stylesheet"] = QApplication.instance().styleSheet() != dark_sheet and theme.LIGHT.BG in QApplication.instance().styleSheet()
results["switching_theme_recolors_row_status"] = dark_status != light_status and light_status.lower() == theme.LIGHT.WARN.lower()
results["light_pref_is_saved"] = window.settings.value("theme") == "light"
results["theme_menu_has_three_choices"] = set(window.theme_actions) == {"system", "dark", "light"}
window.tree.setCurrentItem(item)
results["details_use_the_active_palette"] = theme.LIGHT.TEXT.lower() in window.details_label.text().lower()
window._on_log_line("x - [FAIL] boom")
results["log_lines_use_the_active_palette"] = theme.LIGHT.ERR.lower() in window.log_view.toHtml().lower()
window._set_theme_pref("dark")
results["switching_back_restores_dark"] = theme.palette.name == "dark" and item.foreground(COL_STATUS).color().name().lower() == theme.DARK.WARN.lower()


# ---- follow Windows
class _Hints:
    def __init__(self, scheme):
        self._scheme = scheme

    def colorScheme(self):
        return self._scheme


real_hints = QGuiApplication.styleHints
try:
    QGuiApplication.styleHints = staticmethod(lambda: _Hints(Qt.ColorScheme.Light))
    window._theme_pref = "system"
    results["system_pref_follows_windows_light"] = window._resolve_scheme() == "light"
    window._on_system_scheme_changed()
    results["system_scheme_change_applies_live"] = theme.palette.name == "light"
    QGuiApplication.styleHints = staticmethod(lambda: _Hints(Qt.ColorScheme.Dark))
    window._on_system_scheme_changed()
    results["system_scheme_change_back_to_dark"] = theme.palette.name == "dark"
    window._theme_pref = "light"
    results["explicit_choice_beats_windows"] = window._resolve_scheme() == "light"
    window._on_system_scheme_changed()  # ignored while an explicit choice is active
    results["explicit_choice_ignores_system_changes"] = theme.palette.name == "dark"
    window._theme_pref = "dark"
    window._apply_theme()
finally:
    QGuiApplication.styleHints = real_hints


# ---- drag and drop a profile
tmp = Path(tempfile.mkdtemp(prefix="rf_dnd_"))
profile_path = tmp / "dropped.json"
profile_path.write_text(json.dumps({"name": "Dropped Profile", "component_keys": [key], "created": "2026-01-01T00:00:00"}))


class _Mime:
    def __init__(self, paths):
        from PyQt6.QtCore import QUrl
        self._urls = [QUrl.fromLocalFile(str(p)) for p in paths]

    def hasUrls(self):
        return bool(self._urls)

    def urls(self):
        return self._urls


class _Event:
    def __init__(self, paths):
        self._mime = _Mime(paths)
        self.accepted = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True


good, bad = _Event([profile_path]), _Event([tmp / "notes.txt"])
window.dragEnterEvent(good)
window.dragEnterEvent(bad)
results["drag_accepts_a_json_file"] = good.accepted
results["drag_rejects_other_files"] = not bad.accepted
window.dropEvent(_Event([profile_path]))
results["drop_imports_the_profile"] = window.profile_combo.findText("Dropped Profile") >= 0 and window._selected_keys() == {key}
from core import profiles
profiles.delete_profile(window.app_dir, "Dropped Profile")
window._refresh_profile_combo()

# ---- log toolbar
window.log_view.clear()
window._on_log_line("hello log")
window.log_copy_btn.click()
results["log_copy_puts_text_on_clipboard"] = "hello log" in QApplication.clipboard().text()
window.log_clear_btn.click()
results["log_clear_empties_the_view"] = window.log_view.toPlainText() == ""

# ---- app update notice
class _Resp:
    def __init__(self, tag):
        self._tag = tag
        self.ok = True

    def raise_for_status(self):
        pass

    def json(self):
        return {"tag_name": self._tag, "html_url": "https://example.test/release"}


def run_check(current, tag=None, raises=False):
    found = []
    real_get = http_cache.get
    try:
        def fake_get(*a, **k):
            if raises:
                raise OSError("offline")
            return _Resp(tag)
        http_cache.get = fake_get
        # workers.py imported the module, so patching its attribute is enough
        worker = AppUpdateCheck(current)
        worker.update_found.connect(lambda v, u: found.append((v, u)))
        worker.run()
    finally:
        http_cache.get = real_get
    return found


results["update_check_reports_newer_release"] = run_check("0.2.0", "v0.3.0") == [("0.3.0", "https://example.test/release")]
results["update_check_silent_when_current"] = run_check("0.3.0", "v0.3.0") == []
results["update_check_silent_when_ahead"] = run_check("0.4.0", "v0.3.0") == []
results["update_check_silent_when_offline"] = run_check("0.2.0", raises=True) == []

window._on_app_update_found("9.9.9", "https://example.test/r")
results["update_notice_shows_version"] = window.update_btn.isVisibleTo(window.status_bar) and "9.9.9" in window.update_btn.text()
window._on_check_updates_toggled(False)
results["turning_updates_off_hides_notice_and_saves"] = (not window.update_btn.isVisibleTo(window.status_bar)) and window.settings.value("check_app_updates", True, type=bool) is False
window._on_check_updates_toggled(True)
results["source_checkout_never_checks"] = window._update_check is None or not getattr(sys, "frozen", False)
window.settings.setValue("check_app_updates", True)

window.close()
for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
