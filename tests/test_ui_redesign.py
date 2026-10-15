"""
Tests for the redesigned main window: filter chips, category summaries,
selection-aware Install button, double-click toggling, colored log, and the
install progress readout.

Run directly:
    venv\\Scripts\\python.exe tests\\test_ui_redesign.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.definitions import InstalledState
from core.version_resolvers import LatestInfo
from ui import main_window as mw
from ui.main_window import (
    COL_INSTALLED, COL_LATEST, COL_NAME, COL_STATUS, FILTER_ALL, FILTER_INSTALLED, FILTER_NEEDS,
    MainWindow, STATUS_NOT_INSTALLED, STATUS_UP_TO_DATE, STATUS_UPDATE,
)
from ui.workers import ResultStatus

app = QApplication(sys.argv)
results = {}

window = MainWindow()
if window.scan_worker is not None:
    window.scan_worker.wait()
    app.processEvents()

# Deterministic scan results, independent of the machine running the test.
keys = list(window.tree_items)
cat_of = {c.key: c.category for c in window.components}
installed_current, installed_outdated, missing = keys[0], keys[1], keys[2]
window._scan_results.clear()
window._initial_scan_done = True
for key in keys:
    window._on_component_scanned(key, InstalledState(installed=False), None)
window._on_component_scanned(installed_current, InstalledState(True, "2.0.0"), LatestInfo("2.0.0", "u", "f"))
window._on_component_scanned(installed_outdated, InstalledState(True, "1.0.0"), LatestInfo("2.0.0", "u", "f"))
window._on_select_none()

items = window.tree_items
results["columns_are_status_installed_latest"] = (
    items[installed_outdated].text(COL_STATUS) == STATUS_UPDATE
    and items[installed_outdated].text(COL_INSTALLED) == "1.0.0"
    and items[installed_outdated].text(COL_LATEST) == "2.0.0"
)
results["current_component_shows_up_to_date"] = items[installed_current].text(COL_STATUS) == STATUS_UP_TO_DATE
results["missing_component_shows_not_installed"] = items[missing].text(COL_STATUS) == STATUS_NOT_INSTALLED

# ---- filter chips
window._set_filter(FILTER_NEEDS)
results["needs_filter_hides_up_to_date"] = items[installed_current].isHidden() and not items[installed_outdated].isHidden()
results["needs_filter_shows_missing"] = not items[missing].isHidden()
window._set_filter(FILTER_INSTALLED)
results["installed_filter_hides_missing"] = items[missing].isHidden() and not items[installed_current].isHidden()
window._set_filter(FILTER_ALL)
results["all_filter_shows_everything"] = not any(i.isHidden() for i in items.values())
results["chip_state_follows_filter"] = window.filter_buttons[FILTER_ALL].isChecked() and not window.filter_buttons[FILTER_NEEDS].isChecked()

# search combines with the filter, and empty categories disappear
window.search_box.setText(items[installed_current].text(COL_NAME))
window._set_filter(FILTER_NEEDS)
results["search_and_filter_combine"] = all(i.isHidden() for i in items.values())
results["category_hidden_when_no_children_match"] = all(c.isHidden() for c in window.category_items.values())
window.search_box.setText("")
window._set_filter(FILTER_ALL)
results["clearing_search_restores_categories"] = not any(c.isHidden() for c in window.category_items.values())

# select-all respects what's visible
window._set_filter(FILTER_INSTALLED)
window._on_select_all()
checked = window._selected_keys()
results["select_all_only_checks_visible_rows"] = checked == {installed_current, installed_outdated}
window._set_filter(FILTER_ALL)
window._on_select_none()
results["select_none_clears_everything"] = not window._selected_keys()

# ---- category summary text
category_keys = [k for k in keys if cat_of[k] == cat_of[installed_outdated]]
cat_item = window.category_items[cat_of[installed_outdated]]
results["category_summary_counts_installed"] = f"of {len(category_keys)} installed" in cat_item.text(COL_STATUS)
results["category_summary_mentions_updates"] = "update" in cat_item.text(COL_STATUS)

# ---- Install button reflects the selection and the Dry run toggle
window._on_select_none()
results["install_disabled_with_nothing_selected"] = not window.install_btn.isEnabled()
items[missing].setCheckState(COL_NAME, Qt.CheckState.Checked)
items[installed_outdated].setCheckState(COL_NAME, Qt.CheckState.Checked)
results["install_button_shows_count"] = window.install_btn.text() == "Install 2 selected" and window.install_btn.isEnabled()
results["selection_label_shows_count"] = window.selection_label.text() == "2 selected"
window.dry_run_checkbox.setChecked(True)
results["install_button_says_dry_run"] = window.install_btn.text() == "Dry run 2 selected"
window.dry_run_checkbox.setChecked(False)

# ---- double-click toggles a leaf but leaves categories alone
items[missing].setCheckState(COL_NAME, Qt.CheckState.Unchecked)
window._on_tree_item_double_clicked(items[missing], COL_STATUS)
results["double_click_checks_row"] = items[missing].checkState(COL_NAME) == Qt.CheckState.Checked
window._on_tree_item_double_clicked(items[missing], COL_STATUS)
results["double_click_unchecks_row"] = items[missing].checkState(COL_NAME) == Qt.CheckState.Unchecked
before = cat_item.checkState(COL_NAME)
window._on_tree_item_double_clicked(cat_item, COL_NAME)
results["double_click_ignores_category_rows"] = cat_item.checkState(COL_NAME) == before

# ---- busy state: an install in flight blocks the Install button
class _FakeWorker:
    dry_run = True

    def isRunning(self):
        return True


window.install_worker = _FakeWorker()
window._update_selection_ui()
results["install_disabled_while_installing"] = not window.install_btn.isEnabled()
window.install_worker = None
window._update_selection_ui()
results["install_reenabled_when_idle"] = window.install_btn.isEnabled()

# ---- progress readout: overall = (done + current fraction) / total
window._install_total, window._install_done = 4, 1
window._set_overall_progress(0.5)
results["overall_progress_counts_finished_components"] = window.progress_bar.value() == 37
window._on_component_finished(missing, ResultStatus.FAILED, "")
results["finishing_a_component_advances_progress"] = window._install_done == 2 and window.progress_bar.value() == 50
window._set_selection_controls_visible(False)
results["selection_controls_hidden_while_busy"] = not window.select_all_btn.isVisibleTo(window) and not window.select_missing_btn.isVisibleTo(window)
window._set_selection_controls_visible(True)

# ---- log lines are colored by severity, and HTML in them is escaped
window.log_view.clear()
window._on_log_line("2026 - [FAIL] boom <b>x</b>")
window._on_log_line("2026 - [ OK ] fine")
html_out = window.log_view.toHtml()
results["failure_lines_colored_red"] = mw.theme.ERR.lower() in html_out.lower()
results["success_lines_colored_green"] = mw.theme.OK.lower() in html_out.lower()
results["log_text_is_escaped"] = "<b>x</b>" in window.log_view.toPlainText()

# ---- friendly component names
vc_names = [c.name for c in window.components if c.category == "VC++ Redistributables"]
results["vc_names_are_readable"] = "Visual C++ 2005 (x86)" in vc_names and len(set(vc_names)) == len(vc_names)
results["no_raw_keys_in_names"] = not any("_x" in n for n in vc_names)

window._save_settings = lambda: None
window.close()
for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
