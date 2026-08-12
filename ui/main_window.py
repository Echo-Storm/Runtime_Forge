"""
Main window for Runtime Forge.
Steel/blue dark theme.
"""

import ctypes
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QCheckBox,
    QProgressBar, QMessageBox, QHeaderView, QFrame, QStatusBar,
    QTextEdit, QSizePolicy, QAbstractItemView, QComboBox, QInputDialog,
    QFileDialog, QLineEdit, QMenu,
)
from PyQt6.QtCore import Qt, QSettings, QUrl
from PyQt6.QtGui import QColor, QDesktopServices

from core import path_backup, profiles
from core.definitions import Component, InstalledState, build_components
from core.logger import setup_logging
from core.paths import get_app_dir
from core.version_resolvers import LatestInfo, version_is_newer
from ui.workers import InstallWorker, ResultStatus, ScanWorker, UninstallWorker

STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #1a1d21;
    color: #c0c4c9;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
}

QDialog, QMessageBox, QInputDialog {
    background-color: #1a1d21;
    color: #c0c4c9;
}

QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {
    color: #c0c4c9;
}

QLabel#titleLabel {
    color: #5b9bd5;
    font-size: 15pt;
    font-weight: bold;
    letter-spacing: 1px;
}

QFrame#titleRule {
    background-color: #5b9bd5;
    max-height: 2px;
    border: none;
}

QFrame#sectionPanel {
    background-color: #1e2226;
    border: 1px solid #2a2e33;
    border-radius: 6px;
}

QLabel#sectionLabel {
    color: #5b9bd5;
    font-weight: bold;
    font-size: 8pt;
    letter-spacing: 1px;
}

QLabel#fieldLabel {
    color: #8a8f96;
}

QFrame#warnLabel {
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

QTreeWidget::item:hover {
    background-color: #262b31;
}

QComboBox {
    background-color: #262b31;
    border: 1px solid #3d444c;
    border-radius: 3px;
    padding: 5px 10px;
    color: #c0c4c9;
    min-height: 20px;
}

QComboBox:hover, QComboBox:focus {
    border-color: #5b9bd5;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox QAbstractItemView {
    background-color: #262b31;
    border: 1px solid #3d444c;
    selection-background-color: #2a4a70;
    color: #c0c4c9;
    outline: none;
}

QLineEdit {
    background-color: #202327;
    border: 1px solid #3d444c;
    border-radius: 3px;
    padding: 5px 8px;
    color: #c0c4c9;
    min-height: 20px;
}

QLineEdit:focus {
    border-color: #5b9bd5;
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

QCheckBox::indicator:hover {
    border-color: #5b9bd5;
}

QCheckBox:disabled {
    color: #5a5f66;
}

QCheckBox::indicator:disabled {
    background-color: #16181b;
    border-color: #2c3036;
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

KOFI_URL = "https://ko-fi.com/xechostormx"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


class MainWindow(QMainWindow):
    APP_NAME = "Runtime Forge"
    APP_VERSION = "0.1.0"

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
        self.uninstall_worker: Optional[UninstallWorker] = None

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
        self._last_scan_time: Optional[datetime] = None

        settings_path = str(self.app_dir / "RuntimeForge.ini")
        self.settings = QSettings(settings_path, QSettings.Format.IniFormat)

        # Applied at the QApplication level, not just this window - a
        # QMessageBox/QInputDialog is a separate top-level window that does
        # NOT inherit a stylesheet set only on MainWindow, so confirmation
        # dialogs (profile overwrite, PATH restore, etc.) would otherwise
        # render in plain unthemed Windows chrome against this dark UI.
        QApplication.instance().setStyleSheet(STYLE_SHEET)
        self._setup_ui()
        self._load_settings()
        self._populate_tree()
        profiles.ensure_default_profile(self.app_dir, self.components)
        path_backup.ensure_first_run_backup(self.app_dir)
        self._refresh_profile_combo()
        self._refresh_path_backup_combo()
        self._start_scan()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    @staticmethod
    def _make_section(title: str, content: QVBoxLayout) -> QFrame:
        """Wraps a column of controls in a bordered, labeled panel so
        related controls (bulk-select, profiles, PATH backups) read as
        distinct sections instead of a flat stack of same-weight rows."""
        frame = QFrame()
        frame.setObjectName("sectionPanel")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionLabel")
        inner.addWidget(label)
        inner.addLayout(content)
        return frame

    @staticmethod
    def _button_row(*widgets) -> QHBoxLayout:
        """A row of same-weight controls (e.g. Save As / Update) - used to
        pair short buttons side by side in the narrow left sidebar instead
        of each claiming its own full-width row."""
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in widgets:
            row.addWidget(w)
        return row

    def _setup_ui(self):
        self.setWindowTitle(f"{self.APP_NAME} v{self.APP_VERSION}")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("RUNTIME FORGE")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        title_rule = QFrame()
        title_rule.setObjectName("titleRule")
        title_rule.setFixedHeight(2)
        layout.addWidget(title_rule)

        if not _is_admin():
            warn_frame = QFrame()
            warn_frame.setObjectName("warnLabel")
            warn_layout = QHBoxLayout(warn_frame)
            warn_layout.setContentsMargins(10, 4, 10, 4)
            warn_layout.setSpacing(12)

            warn_text = QLabel("Not running as administrator — most installs will fail.")
            warn_text.setWordWrap(True)
            warn_layout.addWidget(warn_text, stretch=1)

            relaunch_btn = QPushButton("Relaunch as Administrator")
            relaunch_btn.setToolTip("Re-opens this app elevated via UAC, then closes this window")
            relaunch_btn.clicked.connect(self._relaunch_elevated)
            warn_layout.addWidget(relaunch_btn)

            layout.addWidget(warn_frame)

        # === Left sidebar (controls) / right side (the component tree) ===
        # The components are the actual point of this app - they were
        # previously squeezed under three full-width control panels,
        # leaving the tree a small fraction of the window. Controls now
        # live in a fixed-width left sidebar (same shape as the sibling
        # apps' own left-panel convention - see Echo Audio Converter's
        # `leftPanel`), freeing the right side entirely for the tree.
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(12)

        # --- Selection ---
        selection_col = QVBoxLayout()
        selection_col.setSpacing(8)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._on_select_all)

        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(self._on_select_none)

        selection_col.addLayout(self._button_row(self.select_all_btn, self.select_none_btn))

        self.select_missing_btn = QPushButton("Select Missing/Outdated")
        self.select_missing_btn.setToolTip("Check everything not installed, plus anything with an update available")
        self.select_missing_btn.clicked.connect(self._on_select_not_installed)
        selection_col.addWidget(self.select_missing_btn)

        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self._start_scan)
        selection_col.addWidget(self.rescan_btn)

        self.dry_run_checkbox = QCheckBox("Dry Run")
        self.dry_run_checkbox.setToolTip("Preview every action (including what it would download) without installing or writing anything")
        selection_col.addWidget(self.dry_run_checkbox)

        left_panel.addWidget(self._make_section("SELECTION", selection_col))

        # --- Profiles ---
        profile_col = QVBoxLayout()
        profile_col.setSpacing(8)

        profile_field_label = QLabel("Active:")
        profile_field_label.setObjectName("fieldLabel")
        profile_col.addWidget(profile_field_label)

        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.profile_combo.setToolTip("A saved selection preset — pick one to check exactly those components")
        self.profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        profile_col.addWidget(self.profile_combo)

        self.profile_save_as_btn = QPushButton("Save As...")
        self.profile_save_as_btn.setToolTip("Save the current checkbox selection as a new named profile")
        self.profile_save_as_btn.clicked.connect(self._on_save_profile_as)

        self.profile_update_btn = QPushButton("Update")
        self.profile_update_btn.setToolTip("Overwrite the selected profile with the current checkbox selection")
        self.profile_update_btn.clicked.connect(self._on_update_profile)

        profile_col.addLayout(self._button_row(self.profile_save_as_btn, self.profile_update_btn))

        self.profile_delete_btn = QPushButton("Delete")
        self.profile_delete_btn.clicked.connect(self._on_delete_profile)
        profile_col.addWidget(self.profile_delete_btn)

        self.profile_export_btn = QPushButton("Export...")
        self.profile_export_btn.setToolTip("Save the selected profile to a file — carry it to another machine")
        self.profile_export_btn.clicked.connect(self._on_export_profile)

        self.profile_import_btn = QPushButton("Import...")
        self.profile_import_btn.setToolTip("Load a profile file exported from another machine")
        self.profile_import_btn.clicked.connect(self._on_import_profile)

        profile_col.addLayout(self._button_row(self.profile_export_btn, self.profile_import_btn))

        left_panel.addWidget(self._make_section("PROFILES", profile_col))

        # --- PATH Backups ---
        path_col = QVBoxLayout()
        path_col.setSpacing(8)

        path_field_label = QLabel("Snapshot:")
        path_field_label.setObjectName("fieldLabel")
        path_col.addWidget(path_field_label)

        self.path_backup_combo = QComboBox()
        self.path_backup_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path_backup_combo.setToolTip(
            "One snapshot per real install run — a safety net in case PATH ever gets mangled, "
            "separate from each install's own \"set PATH correctly\" flags"
        )
        path_col.addWidget(self.path_backup_combo)

        self.path_backup_restore_btn = QPushButton("Restore...")
        self.path_backup_restore_btn.setToolTip("Preview and optionally roll PATH back to this snapshot")
        self.path_backup_restore_btn.clicked.connect(self._on_restore_path_backup)

        self.path_backup_now_btn = QPushButton("Backup Now")
        self.path_backup_now_btn.setToolTip(
            "Snapshot PATH right now, without installing anything — installs only back it up "
            "automatically when Dry Run is off"
        )
        self.path_backup_now_btn.clicked.connect(self._on_backup_path_now)

        path_col.addLayout(self._button_row(self.path_backup_restore_btn, self.path_backup_now_btn))

        left_panel.addWidget(self._make_section("PATH BACKUPS", path_col))

        left_panel.addStretch()

        left_widget = QWidget()
        left_widget.setObjectName("leftPanel")
        left_widget.setLayout(left_panel)
        left_widget.setFixedWidth(300)
        content_layout.addWidget(left_widget)

        # --- Right: the component tree - the actual point of the app ---
        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)

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
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        tree_toolbar = QHBoxLayout()
        tree_toolbar.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter components...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        tree_toolbar.addWidget(self.search_box, stretch=1)

        self.collapse_all_btn = QPushButton("Collapse All")
        self.collapse_all_btn.clicked.connect(self.tree.collapseAll)
        tree_toolbar.addWidget(self.collapse_all_btn)

        self.expand_all_btn = QPushButton("Expand All")
        self.expand_all_btn.clicked.connect(self.tree.expandAll)
        tree_toolbar.addWidget(self.expand_all_btn)

        self.export_report_btn = QPushButton("Export Report...")
        self.export_report_btn.setToolTip("Save the full scan (every component's installed/latest version) to a text file")
        self.export_report_btn.clicked.connect(self._on_export_report)
        tree_toolbar.addWidget(self.export_report_btn)

        right_panel.addLayout(tree_toolbar)
        right_panel.addWidget(self.tree, stretch=3)

        # --- Log pane ---
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(140)
        self.log_view.setPlaceholderText("Log output...")
        right_panel.addWidget(self.log_view, stretch=1)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        content_layout.addWidget(right_widget, stretch=1)

        layout.addLayout(content_layout, stretch=1)

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

        # Ko-fi donate link — permanent widget, far right, same unobtrusive
        # placement as the sibling apps (Echo Audio Converter, TorBox Manager).
        kofi_btn = QPushButton("♥  donate")
        kofi_btn.setFlat(True)
        kofi_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        kofi_btn.setToolTip("Support development on Ko-fi")
        kofi_btn.setStyleSheet(f"""
            QPushButton {{
                color: {COLOR_NOT_INSTALLED};
                font-size: 8pt;
                border: none;
                background: transparent;
                padding: 0 6px;
            }}
            QPushButton:hover {{
                color: {COLOR_INSTALLING};
            }}
        """)
        kofi_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KOFI_URL)))
        self.status_bar.addPermanentWidget(kofi_btn)

        # Wider than tall now - the 300px control sidebar plus a properly
        # roomy tree (the actual point of the app) needs width, not height,
        # unlike the old top-to-bottom stacked layout.
        self.resize(1180, 760)

    def _relaunch_elevated(self):
        """Re-launches this exact process elevated via a real UAC prompt,
        then quits this instance - only quits if the prompt was actually
        accepted (ShellExecuteW's return value is > 32 on success; a
        cancelled/denied prompt returns an error code, in which case this
        window is left running untouched rather than quitting for nothing).
        Handles both the frozen exe (no separate script argument needed)
        and running from source (python.exe needs the script path passed
        as its own argument)."""
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = ""
        else:
            exe = sys.executable
            params = f'"{os.path.abspath(sys.argv[0])}"'
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if result > 32:
            QApplication.quit()
        else:
            QMessageBox.information(
                self, "Elevation Cancelled",
                "The elevated relaunch was cancelled or failed - this window will stay open as-is.",
            )

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
            if not self.install_worker.wait(5000):
                # request_cancel() only stops the *next* component from
                # starting - the current one's blocking subprocess.run()/
                # msiexec call can't be interrupted from here. Destroying a
                # still-running QThread (which closing the window would do)
                # is undefined behavior in Qt - can crash on exit - and
                # would orphan whatever installer subprocess is mid-flight,
                # so block for real completion instead of proceeding after
                # an arbitrary timeout.
                QMessageBox.information(
                    self, "Finishing Up",
                    "The current component can't be interrupted mid-install - "
                    "waiting for it to finish before closing (nothing new will start).",
                )
                self.install_worker.wait()
        if self.scan_worker and self.scan_worker.isRunning():
            reply = QMessageBox.question(
                self, "Scan in Progress", "A scan is still running. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            # ScanWorker has no cancellation mechanism (it's read-only
            # network calls) - same crash risk as above if the window closes
            # out from under it, so wait for real completion here too.
            if not self.scan_worker.wait(5000):
                QMessageBox.information(
                    self, "Finishing Up", "Waiting for the current scan to finish before closing.",
                )
                self.scan_worker.wait()
        if self.uninstall_worker and self.uninstall_worker.isRunning():
            reply = QMessageBox.question(
                self, "Uninstall in Progress", "An uninstall is running. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            # Same reasoning as install_worker above - can't be
            # interrupted mid-command, so wait for real completion rather
            # than risk destroying a live QThread.
            if not self.uninstall_worker.wait(5000):
                QMessageBox.information(
                    self, "Finishing Up",
                    "The current uninstall can't be interrupted - waiting for it to finish before closing.",
                )
                self.uninstall_worker.wait()
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
        self.scan_worker = None
        self._initial_scan_done = True
        self.rescan_btn.setEnabled(True)
        self.install_btn.setEnabled(True)
        not_installed = sum(1 for state, _ in self._scan_results.values() if not state.installed)
        updates_available = sum(1 for state, latest in self._scan_results.values() if self._has_update(state, latest))

        self._last_scan_time = datetime.now()
        msg = f"Scan complete — {not_installed} of {len(self.components)} not installed"
        if updates_available:
            msg += f", {updates_available} update(s) available"
        msg += f"  ·  Last scanned: {self._last_scan_time.strftime('%b %d, %Y · %I:%M %p')}"
        self.summary_label.setText(msg)
        self.logger.status(f"Scan complete ({not_installed} not installed, {updates_available} updates available)")

    # ------------------------------------------------------------------
    # Tree display (search filter, context menu)
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str):
        query = text.strip().lower()
        for item in self.tree_items.values():
            item.setHidden(bool(query) and query not in item.text(0).lower())

        # A category row stays visible if any of its children matched (or
        # if the search is empty) - otherwise a matching leaf would be
        # orphaned under a hidden parent and never actually show up.
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            if not query:
                cat_item.setHidden(False)
                continue
            any_visible_child = any(
                not cat_item.child(j).isHidden() for j in range(cat_item.childCount())
            )
            cat_item.setHidden(not any_visible_child)

        if query:
            self.tree.expandAll()

    def _on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or item.parent() is None:
            return  # empty space, or a category row (categories have no parent)

        key = item.data(0, Qt.ItemDataRole.UserRole)
        component = self.component_by_key.get(key)
        if component is None:
            return
        result = self._scan_results.get(key)
        state = result[0] if result else None

        menu = QMenu(self)

        if state is not None and state.installed and component.path_entry is not None:
            open_action = menu.addAction("Open Install Location")
            open_action.triggered.connect(lambda: self._open_install_location(component))

        if state is not None and state.version:
            copy_action = menu.addAction("Copy Version")
            copy_action.triggered.connect(lambda: QApplication.clipboard().setText(state.version))

        if state is not None and state.installed and component.uninstall is not None:
            menu.addSeparator()
            uninstall_action = menu.addAction("Uninstall...")
            uninstall_action.triggered.connect(lambda: self._on_uninstall_component(component))

        if menu.isEmpty():
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_uninstall_component(self, component: Component):
        if self.install_worker is not None or self.uninstall_worker is not None or \
                (self.scan_worker is not None and self.scan_worker.isRunning()):
            QMessageBox.information(self, "Busy", "Wait for the current install/uninstall/scan to finish first.")
            return

        dry_run = self.dry_run_checkbox.isChecked()
        reply = QMessageBox.question(
            self, "Uninstall",
            f"Uninstall {component.name}?\n\n" + (
                "Dry Run is on — this will only log what would run, nothing will actually change."
                if dry_run else
                "This runs the real uninstall command for this component. It is not something "
                "this app can undo afterward."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.install_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.status_bar.showMessage(f"Uninstalling {component.name}...")

        self.uninstall_worker = UninstallWorker(component, dry_run, self)
        self.uninstall_worker.log_line.connect(self._on_log_line)
        self.uninstall_worker.finished_uninstall.connect(self._on_uninstall_finished)
        self.uninstall_worker.start()

    def _on_uninstall_finished(self, key: str, success: bool):
        self.uninstall_worker = None
        self.install_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        self.status_bar.clearMessage()

        component = self.component_by_key.get(key)
        item = self.tree_items.get(key)
        if component is None or item is None:
            return

        if not success:
            QMessageBox.warning(self, "Uninstall Failed", f"Could not uninstall {component.name} — check the log for details.")
            return

        if self.dry_run_checkbox.isChecked():
            self.status_bar.showMessage(f"Dry run: would have uninstalled {component.name}", 5000)
            return

        # Re-verify against real system state, same discipline every
        # install already follows — "uninstalled" means "confirmed no
        # longer present," not just "the command exited 0."
        try:
            state = component.is_installed()
        except Exception:
            state = InstalledState(installed=False)

        previous_latest = self._scan_results.get(key, (None, None))[1]
        self._scan_results[key] = (state, previous_latest)

        if state.installed:
            item.setText(1, f"Installed (v{state.version})" if state.version else "Installed")
            item.setForeground(1, self._color(COLOR_INSTALLED))
            QMessageBox.information(
                self, "Still Installed",
                f"{component.name}'s uninstall command completed, but it still appears installed — "
                f"it may need a restart to finish, or the removal wasn't fully complete.",
            )
        else:
            item.setText(1, STATUS_NOT_INSTALLED)
            item.setForeground(1, self._color(COLOR_NOT_INSTALLED))
            item.setText(2, "-")
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self.status_bar.showMessage(f"{component.name} uninstalled", 5000)

    @staticmethod
    def _open_install_location(component: Component):
        if component.path_entry is None:
            return
        try:
            entry = component.path_entry()
        except Exception:
            entry = None
        if entry is None or not entry.is_dir():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(entry)))

    def _on_export_report(self):
        if not self._scan_results:
            QMessageBox.information(self, "No Scan Data", "Run a scan first before exporting a report.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export System Report",
            f"RuntimeForge_Report_{datetime.now():%Y%m%d_%H%M%S}.txt",
            "Text Files (*.txt)",
        )
        if not dest:
            return

        lines = [
            f"{self.APP_NAME} System Report",
            f"Generated: {datetime.now().strftime('%b %d, %Y · %I:%M %p')}",
            "",
        ]
        current_category = None
        # Iterated in registry order, which is already grouped by category
        # (build_components() adds every component of one category before
        # moving to the next) - same grouping the tree itself relies on.
        for component in self.components:
            if component.category != current_category:
                current_category = component.category
                lines.append(f"== {current_category} ==")
            result = self._scan_results.get(component.key)
            if result is None:
                lines.append(f"  {component.name}: not scanned")
                continue
            state, latest = result
            if state.installed:
                status = f"Installed (v{state.version})" if state.version else "Installed"
                if self._has_update(state, latest):
                    status += f" -> v{latest.version} available"
            else:
                status = "Not installed"
            lines.append(f"  {component.name}: {status}")

        try:
            Path(dest).write_text("\n".join(lines), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", f"Could not write the report: {e}")
            return
        self.status_bar.showMessage(f"Report exported to {dest}", 5000)

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
        # Case-insensitive: profile names become filenames, and Windows
        # filenames are case-insensitive - "basic" and "Basic" are the same
        # file on disk, so a naive case-sensitive check here would miss a
        # collision that save_profile() below would silently clobber anyway.
        existing = next((p for p in self._profiles_cache if p.name.lower() == name.lower()), None)
        if existing is not None:
            reply = QMessageBox.question(
                self, "Overwrite Profile",
                f"A profile named '{existing.name}' already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
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

    @staticmethod
    def _format_backup_timestamp(iso_str: str) -> str:
        """Backups are identified internally by their raw ISO timestamp
        string (used for cache-selection matching, filenames, etc) - this
        is purely a display-layer formatter for the combo/dialog text, not
        a change to that identity."""
        try:
            return datetime.fromisoformat(iso_str).strftime("%b %d, %Y · %I:%M %p")
        except ValueError:
            return iso_str

    def _refresh_path_backup_combo(self, select_timestamp: Optional[str] = None):
        """Repopulates the PATH-backup dropdown. By default, re-selects
        whichever backup was already selected (by timestamp identity)
        rather than resetting to the newest entry - otherwise an unrelated
        action elsewhere (an install run finishing, which creates its own
        new backup) would silently swap out a backup the user had
        deliberately selected to review or restore. Pass select_timestamp
        to select a specific entry instead (e.g. one just created by
        Backup Now)."""
        if select_timestamp is None:
            current = self._selected_path_backup()
            select_timestamp = current.timestamp if current else None

        self.path_backup_combo.clear()
        self._path_backups_cache = path_backup.list_backups(self.app_dir)
        if not self._path_backups_cache:
            self.path_backup_combo.addItem("(no backups yet)")
            self.path_backup_restore_btn.setEnabled(False)
            return
        for backup in self._path_backups_cache:
            self.path_backup_combo.addItem(f"{self._format_backup_timestamp(backup.timestamp)} — {backup.reason}")
        self.path_backup_restore_btn.setEnabled(True)

        if select_timestamp is not None:
            for i, backup in enumerate(self._path_backups_cache):
                if backup.timestamp == select_timestamp:
                    self.path_backup_combo.setCurrentIndex(i)
                    break

    def _selected_path_backup(self) -> Optional[path_backup.PathBackup]:
        idx = self.path_backup_combo.currentIndex()
        if 0 <= idx < len(self._path_backups_cache):
            return self._path_backups_cache[idx]
        return None

    def _on_backup_path_now(self):
        backup_path = path_backup.create_backup(self.app_dir, "manual backup")
        if backup_path:
            new_backups = path_backup.list_backups(self.app_dir)
            new_timestamp = new_backups[0].timestamp if new_backups else None
            self._refresh_path_backup_combo(select_timestamp=new_timestamp)
            QMessageBox.information(
                self, "PATH Backed Up",
                f"Current machine + user PATH saved to {backup_path.name}.",
            )
        else:
            QMessageBox.warning(
                self, "Backup Failed",
                "Could not read the current machine PATH from the registry, so no backup was made.",
            )

    def _on_restore_path_backup(self):
        backup = self._selected_path_backup()
        if backup is None:
            return

        current_machine, current_user = path_backup.read_current_path()

        preview = (
            f"Restore PATH to the snapshot from {self._format_backup_timestamp(backup.timestamp)}?\n"
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
        # Refresh regardless of outcome below - the safety backup above was
        # just written to disk either way, and leaving the combo stale
        # would contradict the dialog's own claim that it "is taken
        # automatically first" if the user then goes looking for it.
        self._refresh_path_backup_combo(select_timestamp=backup.timestamp)
        if path_backup.restore_backup(backup):
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
