"""
Main window for AIO Runtime Installer.
Steel/blue dark theme.
"""

import ctypes
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QCheckBox,
    QProgressBar, QMessageBox, QHeaderView, QFrame, QStatusBar,
    QTextEdit, QSizePolicy, QAbstractItemView, QComboBox, QInputDialog,
    QFileDialog,
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor

from core import path_backup, profiles
from core.definitions import Component, InstalledState, build_components
from core.logger import setup_logging
from core.paths import get_app_dir
from core.version_resolvers import LatestInfo, version_is_newer
from ui.workers import InstallWorker, ResultStatus, ScanWorker

STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #1a1d21;
    color: #c0c4c9;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
}

QLabel#titleLabel {
    color: #5b9bd5;
    font-size: 11pt;
    font-weight: bold;
}

QLabel#warnLabel {
    color: #d5a05b;
    font-weight: bold;
    padding: 4px 10px;
    background-color: #2a241a;
    border: 1px solid #6a5a30;
    border-radius: 3px;
}

QPushButton {
    background-color: #262b31;
    border: 1px solid #3d444c;
    border-radius: 3px;
    padding: 6px 14px;
    color: #c0c4c9;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #323942;
    border-color: #5b9bd5;
}

QPushButton:pressed {
    background-color: #3d444c;
}

QPushButton:disabled {
    background-color: #202327;
    color: #5a5f66;
    border-color: #2c3036;
}

QPushButton#installBtn {
    background-color: #1e3a5a;
    border-color: #5b9bd5;
    color: #7cb8f0;
    font-weight: bold;
    padding: 8px 20px;
}

QPushButton#installBtn:hover {
    background-color: #2a4a70;
}

QPushButton#installBtn:disabled {
    background-color: #202327;
    border-color: #303540;
    color: #505050;
}

QPushButton#cancelBtn {
    background-color: #4a2020;
    border-color: #a04040;
    color: #d08080;
}

QPushButton#cancelBtn:hover {
    background-color: #5a2828;
}

QTreeWidget {
    background-color: #1e2226;
    alternate-background-color: #22262b;
    border: 1px solid #333941;
    color: #c0c4c9;
    selection-background-color: #2a4a70;
}

QTreeWidget::item {
    padding: 3px;
}

QTreeWidget::item:selected {
    background-color: #2a4a70;
}

QHeaderView::section {
    background-color: #262b31;
    color: #5b9bd5;
    padding: 6px;
    border: none;
    border-bottom: 2px solid #5b9bd5;
    font-weight: bold;
}

QProgressBar {
    background-color: #202327;
    border: 1px solid #333941;
    border-radius: 3px;
    height: 18px;
    text-align: center;
    color: #c0c4c9;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2a5a8a, stop:1 #5b9bd5);
    border-radius: 2px;
}

QTextEdit {
    background-color: #16181b;
    border: 1px solid #2a2e33;
    color: #8a8f96;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9pt;
}

QCheckBox {
    color: #a0a4a9;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #4a4a4a;
    border-radius: 2px;
    background-color: #202327;
}

QCheckBox::indicator:checked {
    background-color: #5b9bd5;
    border-color: #5b9bd5;
}

QStatusBar {
    background-color: #1a1d21;
    border-top: 1px solid #2a2e33;
    color: #5b9bd5;
}

QScrollBar:vertical {
    background-color: #1a1d21;
    width: 12px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #333941;
    border-radius: 4px;
    min-height: 30px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #454c56;
}
"""

STATUS_NOT_INSTALLED = "Not installed"
COLOR_NOT_INSTALLED = "#8a8f96"
COLOR_INSTALLED = "#6bbf6b"
COLOR_UPDATE_AVAILABLE = "#d5c05b"
COLOR_INSTALLING = "#5b9bd5"
COLOR_FAILED = "#d56b6b"
COLOR_SKIPPED = "#8a8f96"
COLOR_PATH_WARNING = "#e0954a"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


class MainWindow(QMainWindow):
    APP_NAME = "AIO Runtime Installer"
    APP_VERSION = "1.0.0"

    def __init__(self):
        super().__init__()

        self.app_dir = get_app_dir()
        self.logger = setup_logging(self.app_dir)
        self.logger.status(f"{self.APP_NAME} v{self.APP_VERSION} starting")

        self.components = build_components()
        self.component_by_key = {c.key: c for c in self.components}
        self.tree_items: dict[str, QTreeWidgetItem] = {}

        self.scan_worker: Optional[ScanWorker] = None
        self.install_worker: Optional[InstallWorker] = None

        self._profiles_cache: List[profiles.Profile] = []
        self._applying_profile = False
        self._active_profile_name: Optional[str] = None
        self._scan_results: dict[str, tuple] = {}
        # Auto-select-missing/outdated is a sensible default only when
        # nothing has been chosen yet. After the first scan, later Rescans
        # must never touch checkbox state on their own — a user who
        # deliberately unchecked something, then clicked Rescan (a normal,
        # expected action) would otherwise find it silently re-checked with
        # no warning. "Select Missing/Outdated" stays available to reapply
        # this deliberately.
        self._initial_scan_done = False
        self._path_backups_cache: List[path_backup.PathBackup] = []

        settings_path = str(self.app_dir / "AIORuntimeInstaller.ini")
        self.settings = QSettings(settings_path, QSettings.Format.IniFormat)

        self.setStyleSheet(STYLE_SHEET)
        self._setup_ui()
        self._load_settings()
        self._populate_tree()
        profiles.ensure_default_profile(self.app_dir, self.components)
        self._refresh_profile_combo()
        self._refresh_path_backup_combo()
        self._start_scan()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setWindowTitle(f"{self.APP_NAME} v{self.APP_VERSION}")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel("AIO RUNTIME INSTALLER")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        if not _is_admin():
            warn = QLabel(
                "Not running as administrator — most installs will fail. "
                "Re-launch this app elevated (right-click → Run as administrator)."
            )
            warn.setObjectName("warnLabel")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # --- Toolbar ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._on_select_all)
        toolbar.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(self._on_select_none)
        toolbar.addWidget(self.select_none_btn)

        self.select_missing_btn = QPushButton("Select Missing/Outdated")
        self.select_missing_btn.setToolTip("Check everything not installed, plus anything with an update available")
        self.select_missing_btn.clicked.connect(self._on_select_not_installed)
        toolbar.addWidget(self.select_missing_btn)

        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self._start_scan)
        toolbar.addWidget(self.rescan_btn)

        toolbar.addStretch()

        self.dry_run_checkbox = QCheckBox("Dry Run")
        self.dry_run_checkbox.setToolTip("Preview every action (including what it would download) without installing or writing anything")
        toolbar.addWidget(self.dry_run_checkbox)

        layout.addLayout(toolbar)

        # --- Profiles ---
        profile_bar = QHBoxLayout()
        profile_bar.setSpacing(8)

        profile_bar.addWidget(QLabel("Profile:"))

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.setToolTip("A saved selection preset — pick one to check exactly those components")
        self.profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        profile_bar.addWidget(self.profile_combo)

        self.profile_save_as_btn = QPushButton("Save As...")
        self.profile_save_as_btn.setToolTip("Save the current checkbox selection as a new named profile")
        self.profile_save_as_btn.clicked.connect(self._on_save_profile_as)
        profile_bar.addWidget(self.profile_save_as_btn)

        self.profile_update_btn = QPushButton("Update")
        self.profile_update_btn.setToolTip("Overwrite the selected profile with the current checkbox selection")
        self.profile_update_btn.clicked.connect(self._on_update_profile)
        profile_bar.addWidget(self.profile_update_btn)

        self.profile_delete_btn = QPushButton("Delete")
        self.profile_delete_btn.clicked.connect(self._on_delete_profile)
        profile_bar.addWidget(self.profile_delete_btn)

        profile_bar.addStretch()

        self.profile_export_btn = QPushButton("Export...")
        self.profile_export_btn.setToolTip("Save the selected profile to a file — carry it to another machine")
        self.profile_export_btn.clicked.connect(self._on_export_profile)
        profile_bar.addWidget(self.profile_export_btn)

        self.profile_import_btn = QPushButton("Import...")
        self.profile_import_btn.setToolTip("Load a profile file exported from another machine")
        self.profile_import_btn.clicked.connect(self._on_import_profile)
        profile_bar.addWidget(self.profile_import_btn)

        layout.addLayout(profile_bar)

        # --- PATH Backups ---
        path_bar = QHBoxLayout()
        path_bar.setSpacing(8)

        path_bar.addWidget(QLabel("PATH Backups:"))

        self.path_backup_combo = QComboBox()
        self.path_backup_combo.setMinimumWidth(320)
        self.path_backup_combo.setToolTip(
            "One snapshot per real install run — a safety net in case PATH ever gets mangled, "
            "separate from each install's own \"set PATH correctly\" flags"
        )
        path_bar.addWidget(self.path_backup_combo)

        self.path_backup_restore_btn = QPushButton("Restore...")
        self.path_backup_restore_btn.setToolTip("Preview and optionally roll PATH back to this snapshot")
        self.path_backup_restore_btn.clicked.connect(self._on_restore_path_backup)
        path_bar.addWidget(self.path_backup_restore_btn)

        path_bar.addStretch()

        layout.addLayout(path_bar)

        # --- Tree ---
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Component", "Status", "Installed Version", "Latest Version"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        layout.addWidget(self.tree, stretch=3)

        # --- Log pane ---
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(140)
        self.log_view.setPlaceholderText("Log output...")
        layout.addWidget(self.log_view, stretch=1)

        # --- Bottom bar ---
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        self.summary_label = QLabel("Scanning...")
        bottom_bar.addWidget(self.summary_label)

        bottom_bar.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(220)
        self.progress_bar.setVisible(False)
        bottom_bar.addWidget(self.progress_bar)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setVisible(False)
        bottom_bar.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install Selected")
        self.install_btn.setObjectName("installBtn")
        self.install_btn.clicked.connect(self._on_install_clicked)
        self.install_btn.setEnabled(False)
        bottom_bar.addWidget(self.install_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #333941; max-height: 1px;")
        layout.addWidget(sep)
        layout.addLayout(bottom_bar)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.resize(980, 720)

    def _populate_tree(self):
        categories: dict[str, QTreeWidgetItem] = {}
        for component in self.components:
            cat_item = categories.get(component.category)
            if cat_item is None:
                cat_item = QTreeWidgetItem(self.tree, [component.category, "", "", ""])
                cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                cat_item.setCheckState(0, Qt.CheckState.Unchecked)
                font = cat_item.font(0)
                font.setBold(True)
                cat_item.setFont(0, font)
                categories[component.category] = cat_item

            leaf = QTreeWidgetItem(cat_item, [component.name, "Checking...", "", ""])
            leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.CheckState.Unchecked)
            leaf.setData(0, Qt.ItemDataRole.UserRole, component.key)
            leaf.setForeground(1, self._color(COLOR_NOT_INSTALLED))
            self.tree_items[component.key] = leaf

        self.tree.expandAll()

    def _color(self, hex_str: str):
        return QColor(hex_str)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        dry_run = self.settings.value("dry_run", False, type=bool)
        self.dry_run_checkbox.setChecked(dry_run)

    def _save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("dry_run", self.dry_run_checkbox.isChecked())

    def closeEvent(self, event):
        self._save_settings()
        if self.install_worker and self.install_worker.isRunning():
            reply = QMessageBox.question(
                self, "Install in Progress", "An install is running. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.install_worker.request_cancel()
            self.install_worker.wait(5000)
        event.accept()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _start_scan(self):
        self.rescan_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.summary_label.setText("Scanning installed components...")
        self._scan_results.clear()
        for key, item in self.tree_items.items():
            item.setText(1, "Checking...")
            item.setForeground(1, self._color(COLOR_NOT_INSTALLED))

        self.scan_worker = ScanWorker(self.components, self)
        self.scan_worker.component_scanned.connect(self._on_component_scanned)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.start()

    @staticmethod
    def _has_update(state: InstalledState, latest: Optional[LatestInfo]) -> bool:
        return bool(state.installed and latest is not None and version_is_newer(latest.version, state.version or ""))

    def _on_component_scanned(self, key: str, state: InstalledState, latest: Optional[LatestInfo]):
        item = self.tree_items.get(key)
        if item is None:
            return
        self._scan_results[key] = (state, latest)

        has_update = self._has_update(state, latest)

        if state.installed:
            if has_update:
                item.setText(1, f"Installed (v{state.version}) → v{latest.version} available")
                item.setForeground(1, self._color(COLOR_UPDATE_AVAILABLE))
            else:
                item.setText(1, state.version and f"Installed (v{state.version})" or "Installed")
                item.setForeground(1, self._color(COLOR_INSTALLED))
        else:
            item.setText(1, STATUS_NOT_INSTALLED)
            item.setForeground(1, self._color(COLOR_NOT_INSTALLED))

        item.setText(2, state.version or "-")
        item.setText(3, latest.version if latest is not None else "-")

        # Pre-select anything that's missing entirely, or that has a real
        # update available — the whole point of surfacing "update available"
        # is for Install Selected to actually be able to act on it. Only on
        # the very first scan, though — see _initial_scan_done.
        if not self._initial_scan_done and (not state.installed or has_update):
            item.setCheckState(0, Qt.CheckState.Checked)

    def _on_scan_finished(self):
        self._initial_scan_done = True
        self.rescan_btn.setEnabled(True)
        self.install_btn.setEnabled(True)
        not_installed = sum(1 for state, _ in self._scan_results.values() if not state.installed)
        updates_available = sum(1 for state, latest in self._scan_results.values() if self._has_update(state, latest))

        msg = f"Scan complete — {not_installed} of {len(self.components)} not installed"
        if updates_available:
            msg += f", {updates_available} update(s) available"
        self.summary_label.setText(msg)
        self.logger.status(f"Scan complete ({not_installed} not installed, {updates_available} updates available)")

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _set_all_checkstate(self, state: Qt.CheckState):
        for item in self.tree_items.values():
            item.setCheckState(0, state)

    def _on_select_all(self):
        self._set_all_checkstate(Qt.CheckState.Checked)

    def _on_select_none(self):
        self._set_all_checkstate(Qt.CheckState.Unchecked)

    def _on_select_not_installed(self):
        # Reads the cached scan results rather than calling is_installed()
        # again here — several of those checks (git/node/cmake/pwsh) shell
        # out to the real exe with a 15s timeout each, which would freeze
        # the UI thread if run synchronously from a button click instead of
        # ScanWorker's background thread.
        for key, item in self.tree_items.items():
            state, latest = self._scan_results.get(key, (InstalledState(installed=False), None))
            needs_action = not state.installed or self._has_update(state, latest)
            item.setCheckState(0, Qt.CheckState.Checked if needs_action else Qt.CheckState.Unchecked)

    def _selected_keys(self) -> set[str]:
        return {key for key, item in self.tree_items.items() if item.checkState(0) == Qt.CheckState.Checked}

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        # Any manual checkbox edit invalidates "this matches a saved
        # profile" — reset the combo to Custom rather than silently implying
        # the current selection still matches whatever was last loaded.
        # _active_profile_name deliberately does NOT get cleared here: it's
        # what "Update" saves back to, and the whole point of Update is
        # "I loaded a profile, tweaked the selection, now save that back" —
        # if editing cleared it too, Update would go permanently disabled
        # the instant you made the one edit you actually wanted to save.
        if column != 0 or self._applying_profile:
            return
        if self.profile_combo.currentIndex() != 0:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(0)
            self.profile_combo.blockSignals(False)
            self._update_profile_buttons_enabled()

    def _refresh_profile_combo(self, select_name: Optional[str] = None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("— Custom (unsaved) —")
        self._profiles_cache = profiles.list_profiles(self.app_dir)
        for profile in self._profiles_cache:
            self.profile_combo.addItem(profile.name)
        if select_name:
            idx = self.profile_combo.findText(select_name)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._update_profile_buttons_enabled()

    def _current_profile_name(self) -> Optional[str]:
        """The profile literally shown in the combo right now — None while
        it reads "Custom" (i.e. the tree no longer matches anything saved).
        Used by Delete/Export, which act on a specific saved profile."""
        idx = self.profile_combo.currentIndex()
        return self.profile_combo.currentText() if idx > 0 else None

    def _update_profile_buttons_enabled(self):
        self.profile_update_btn.setEnabled(self._active_profile_name is not None)
        has_selected = self._current_profile_name() is not None
        self.profile_delete_btn.setEnabled(has_selected)
        self.profile_export_btn.setEnabled(has_selected)

    def _on_profile_combo_changed(self, index: int):
        name = self._current_profile_name()
        if name is not None:
            self._active_profile_name = name
        self._update_profile_buttons_enabled()
        if name is None:
            return
        profile = next((p for p in self._profiles_cache if p.name == name), None)
        if profile is None:
            return
        self._apply_profile(profile)

    def _apply_profile(self, profile: profiles.Profile):
        """Checks exactly this profile's component_keys in the tree.
        Callers must set self._active_profile_name themselves first if the
        profile should become the active one — this only touches the tree.

        Split out from _on_profile_combo_changed so Import can call it
        directly: _refresh_profile_combo() blocks the combo's signals
        internally (so selecting the newly-imported item in the dropdown
        doesn't recurse), which means currentIndexChanged never fires and
        this logic would otherwise never run for an imported profile — the
        combo would visibly show it "selected" while the tree silently kept
        whatever was checked before the import.
        """
        keys = set(profile.component_keys)
        self._applying_profile = True
        for key, item in self.tree_items.items():
            item.setCheckState(0, Qt.CheckState.Checked if key in keys else Qt.CheckState.Unchecked)
        self._applying_profile = False

        unknown = keys - set(self.tree_items.keys())
        msg = f"Loaded profile '{profile.name}' — {len(keys)} component(s) selected"
        if unknown:
            msg += f" ({len(unknown)} no longer exist and were skipped)"
        self.status_bar.showMessage(msg, 5000)

    def _on_save_profile_as(self):
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        name = name.strip()
        if not ok or not name:
            return
        self._write_profile(name)

    def _on_update_profile(self):
        # Targets _active_profile_name (survives edits), not
        # _current_profile_name() (resets to Custom on the first edit) —
        # otherwise "load a profile, tweak it, click Update" could never
        # work, since the tweak itself disables the button.
        if self._active_profile_name:
            self._write_profile(self._active_profile_name)

    def _write_profile(self, name: str):
        selected = sorted(self._selected_keys())
        profile = profiles.Profile(name=name, component_keys=selected, created=datetime.now().isoformat(timespec="seconds"))
        if profiles.save_profile(self.app_dir, profile) is None:
            QMessageBox.warning(self, "Save Failed", f"Could not save profile '{name}' — check the name and try again.")
            return
        self._active_profile_name = name
        self._refresh_profile_combo(select_name=name)
        self.status_bar.showMessage(f"Saved profile '{name}' ({len(selected)} component(s))", 5000)

    def _on_delete_profile(self):
        name = self._current_profile_name()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        profiles.delete_profile(self.app_dir, name)
        if self._active_profile_name == name:
            self._active_profile_name = None
        self._refresh_profile_combo()
        self.status_bar.showMessage(f"Deleted profile '{name}'", 5000)

    def _on_export_profile(self):
        name = self._current_profile_name()
        if not name:
            return
        profile = next((p for p in self._profiles_cache if p.name == name), None)
        if not profile:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export Profile", f"{name}.json", "JSON Files (*.json)")
        if not dest:
            return
        if profiles.export_profile(profile, Path(dest)):
            self.status_bar.showMessage(f"Exported to {dest}", 5000)
        else:
            QMessageBox.warning(self, "Export Failed", "Could not write the profile file.")

    def _on_import_profile(self):
        src, _ = QFileDialog.getOpenFileName(self, "Import Profile", "", "JSON Files (*.json)")
        if not src:
            return
        profile = profiles.load_profile(Path(src))
        if not profile:
            QMessageBox.warning(self, "Import Failed", "That file isn't a valid profile.")
            return
        if profiles.save_profile(self.app_dir, profile) is None:
            QMessageBox.warning(self, "Import Failed", f"Could not save imported profile '{profile.name}'.")
            return
        self._refresh_profile_combo(select_name=profile.name)
        # _refresh_profile_combo blocks the combo's signals while it runs,
        # so currentIndexChanged never fires here — apply the import to the
        # tree explicitly instead of relying on that signal path. Also
        # re-run the button-enabled check: _refresh_profile_combo already
        # called it once internally, but that was before _active_profile_name
        # below was set, so the Update button could be left stale (disabled)
        # if there wasn't already an active profile beforehand.
        self._active_profile_name = profile.name
        self._update_profile_buttons_enabled()
        self._apply_profile(profile)
        self.status_bar.showMessage(f"Imported profile '{profile.name}' ({len(profile.component_keys)} component(s))", 5000)

    # ------------------------------------------------------------------
    # PATH backups
    # ------------------------------------------------------------------

    def _refresh_path_backup_combo(self):
        self.path_backup_combo.clear()
        self._path_backups_cache = path_backup.list_backups(self.app_dir)
        if not self._path_backups_cache:
            self.path_backup_combo.addItem("(no backups yet)")
            self.path_backup_restore_btn.setEnabled(False)
            return
        for backup in self._path_backups_cache:
            self.path_backup_combo.addItem(f"{backup.timestamp} — {backup.reason}")
        self.path_backup_restore_btn.setEnabled(True)

    def _on_restore_path_backup(self):
        idx = self.path_backup_combo.currentIndex()
        if idx < 0 or idx >= len(self._path_backups_cache):
            return
        backup = self._path_backups_cache[idx]

        current_machine, current_user = path_backup.read_current_path()

        preview = (
            f"Restore PATH to the snapshot from {backup.timestamp}?\n"
            f"({backup.reason})\n\n"
            f"This will overwrite the CURRENT machine + user PATH values.\n"
            f"A fresh backup of the current PATH is taken automatically first, "
            f"so this itself can be undone.\n\n"
            f"Current machine PATH ({len(current_machine)} chars) vs "
            f"snapshot ({len(backup.machine_path)} chars)\n"
            f"Current user PATH ({len(current_user)} chars) vs "
            f"snapshot ({len(backup.user_path)} chars)"
        )
        reply = QMessageBox.question(
            self, "Restore PATH Backup", preview,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        path_backup.create_backup(self.app_dir, f"before restoring {backup.timestamp}")
        if path_backup.restore_backup(backup):
            self._refresh_path_backup_combo()
            QMessageBox.information(
                self, "PATH Restored",
                "PATH has been restored and the change broadcast to running processes.\n"
                "Some already-open windows (terminals especially) may still need to be "
                "restarted to pick it up.",
            )
        else:
            QMessageBox.warning(
                self, "Restore Failed",
                "Could not write PATH to the registry — this needs to run elevated.",
            )

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def _on_install_clicked(self):
        selected = self._selected_keys()
        if not selected:
            QMessageBox.information(self, "Nothing Selected", "Check at least one component to install.")
            return

        dry_run = self.dry_run_checkbox.isChecked()
        if not dry_run:
            reply = QMessageBox.question(
                self, "Confirm Install",
                f"Install {len(selected)} selected component(s)? This will download and run installers, "
                "and may modify the registry, PATH, and System32.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.install_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_view.clear()

        self.install_worker = InstallWorker(self.components, selected, dry_run, self)
        self.install_worker.component_started.connect(self._on_component_started)
        self.install_worker.component_progress.connect(self._on_component_progress)
        self.install_worker.component_finished.connect(self._on_component_finished)
        self.install_worker.log_line.connect(self._on_log_line)
        self.install_worker.all_finished.connect(self._on_all_finished)
        self.install_worker.start()

    def _on_cancel_clicked(self):
        if self.install_worker:
            self.install_worker.request_cancel()
            self.status_bar.showMessage("Cancelling after current component finishes...")

    def _on_component_started(self, key: str):
        item = self.tree_items.get(key)
        if item:
            item.setText(1, "Installing...")
            item.setForeground(1, self._color(COLOR_INSTALLING))
        component = self.component_by_key.get(key)
        if component:
            self.status_bar.showMessage(f"Installing {component.name}...")

    def _on_component_progress(self, key: str, message: str, fraction: float):
        self.progress_bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        self.status_bar.showMessage(message)

    def _on_component_finished(self, key: str, status: ResultStatus, warning: str):
        item = self.tree_items.get(key)
        if item is None:
            return
        if status == ResultStatus.INSTALLED and warning:
            item.setText(1, f"Installed — {warning}")
            item.setForeground(1, self._color(COLOR_PATH_WARNING))
        elif status == ResultStatus.INSTALLED:
            item.setText(1, "Installed")
            item.setForeground(1, self._color(COLOR_INSTALLED))
        elif status == ResultStatus.SKIPPED:
            item.setText(1, "Skipped (already installed)")
            item.setForeground(1, self._color(COLOR_SKIPPED))
        else:
            item.setText(1, "Failed")
            item.setForeground(1, self._color(COLOR_FAILED))

    def _on_log_line(self, line: str):
        self.log_view.append(line)

    def _on_all_finished(self, installed: int, skipped: int, failed: int):
        self.install_worker = None
        self.install_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self.status_bar.clearMessage()
        self.summary_label.setText(f"Done — Installed: {installed}  Skipped: {skipped}  Failed: {failed}")
        if not self.dry_run_checkbox.isChecked():
            self._refresh_path_backup_combo()  # a real run just created a new one

        QMessageBox.information(
            self, "Install Complete",
            f"Installed: {installed}\nSkipped (already present): {skipped}\nFailed: {failed}\n\n"
            f"Log saved to: {self.logger.log_file}",
        )
