"""
Main window for Runtime Forge.

Layout, top to bottom:
  - (only when not elevated) a slim banner with a one-click relaunch
  - toolbar: search, All / Needs action / Installed filter, profile picker, Rescan, Dry run, menu
  - the component tree, full width - it is the point of the app
  - a collapsible bottom pane: Log | PATH backups
  - an action bar: scan/install summary, progress, selection helpers, the Install button
"""

import ctypes
import html
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QEvent, QObject, QMimeData, Qt, QSettings, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStatusBar, QTabWidget, QTextEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from core import path_backup, profiles
from core.definitions import Component, InstalledState, build_components
from core.logger import setup_logging
from core.paths import get_bundle_dir, get_data_dir
from core.version_resolvers import LatestInfo, version_is_newer
from ui import theme
from ui.workers import AppUpdateCheck, InstallWorker, ResultStatus, ScanWorker, UninstallWorker

# Status-column text. Short on purpose: the version has its own columns, so a
# status never needs to be wider than a glyph and two words.
STATUS_CHECKING = "…   Checking"
STATUS_NOT_INSTALLED = "○   Not installed"
STATUS_UP_TO_DATE = "✓   Up to date"
STATUS_INSTALLED = "✓   Installed"
STATUS_UPDATE = "↑   Update available"
STATUS_INSTALLING = "⟳   Installing…"
STATUS_FAILED = "✗   Failed"
STATUS_SKIPPED = "–   Skipped"

FILTER_ALL, FILTER_NEEDS, FILTER_INSTALLED = "all", "needs", "installed"

KOFI_URL = "https://ko-fi.com/xechostormx"

COL_NAME, COL_STATUS, COL_INSTALLED, COL_LATEST = 0, 1, 2, 3


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def build_app_stylesheet() -> str:
    assets = get_bundle_dir() / "assets"
    return theme.build_stylesheet(
        check_icon=(assets / "check.png").as_posix(),
        dash_icon=(assets / "dash.png").as_posix(),
        chevron_right=(assets / "chevron_right.png").as_posix(),
        chevron_down=(assets / "chevron_down.png").as_posix(),
    )


class MainWindow(QMainWindow):
    APP_NAME = "Runtime Forge"
    APP_VERSION = "0.4.0"

    def __init__(self):
        super().__init__()

        self.app_dir = get_data_dir()  # user data (logs, settings, profiles, PATH backups)
        self.logger = setup_logging(self.app_dir)
        self.logger.status(f"{self.APP_NAME} v{self.APP_VERSION} starting")

        self.components = build_components()
        self.component_by_key = {c.key: c for c in self.components}
        self.tree_items: dict[str, QTreeWidgetItem] = {}
        self.category_items: dict[str, QTreeWidgetItem] = {}

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
        # no warning. "Select needed" stays available to reapply this
        # deliberately.
        self._initial_scan_done = False
        self._path_backups_cache: List[path_backup.PathBackup] = []
        self._last_scan_time: Optional[datetime] = None
        self._filter_mode = FILTER_ALL
        self._install_total = 0
        self._install_done = 0
        self._install_results: dict[str, ResultStatus] = {}
        self._update_check: Optional[AppUpdateCheck] = None

        settings_path = str(self.app_dir / "RuntimeForge.ini")
        self.settings = QSettings(settings_path, QSettings.Format.IniFormat)

        # Applied at the QApplication level, not just this window - a
        # QMessageBox/QInputDialog is a separate top-level window that does
        # NOT inherit a stylesheet set only on MainWindow, so confirmation
        # dialogs (profile overwrite, PATH restore, etc.) would otherwise
        # render in plain unthemed Windows chrome against this dark UI.
        self._theme_pref = self.settings.value("theme", "system")
        if self._theme_pref not in ("system", "dark", "light"):
            self._theme_pref = "system"
        theme.set_scheme(self._resolve_scheme())
        QApplication.instance().setStyleSheet(build_app_stylesheet())
        self._setup_ui()
        self._load_settings()
        self._populate_tree()
        profiles.ensure_default_profile(self.app_dir, self.components)
        path_backup.ensure_first_run_backup(self.app_dir)
        self._refresh_profile_combo()
        self._refresh_path_backup_combo()
        self._update_selection_ui()
        self._start_scan()
        self._start_update_check()
        self.tree.setFocus()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setWindowTitle(f"{self.APP_NAME} v{self.APP_VERSION}")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 8)
        root.setSpacing(10)

        if not _is_admin():
            root.addWidget(self._build_banner())

        root.addWidget(self._build_toolbar())

        # --- the tree and the bottom pane share a splitter so the log can
        # be dragged open (or shut) without losing the tree's space.
        self.tree = self._build_tree()
        self.bottom_tabs = self._build_bottom_tabs()

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.bottom_tabs)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([470, 210])
        root.addWidget(self.splitter, stretch=1)

        root.addWidget(self._build_action_bar())

        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self.status_bar)
        kofi_btn = QPushButton("♥  donate")
        kofi_btn.setObjectName("linkBtn")
        kofi_btn.setFlat(True)
        kofi_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        kofi_btn.setToolTip("Support development on Ko-fi")
        kofi_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KOFI_URL)))
        self.status_bar.addPermanentWidget(kofi_btn)

        # Appears only when a newer release exists (see _start_update_check).
        self.update_btn = QPushButton("")
        self.update_btn.setObjectName("linkBtn")
        self.update_btn.setFlat(True)
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setVisible(False)
        self.status_bar.addPermanentWidget(self.update_btn)

        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except AttributeError:
            pass  # Qt older than 6.5: no live scheme notifications

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search_box.setFocus)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._on_rescan_shortcut)

        self.setAcceptDrops(True)
        self.resize(1180, 780)

    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("banner")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(12)

        text = QLabel(
            "Not running as administrator — scanning, Dry Run and profiles work, "
            "but installers that write to Program Files or the registry will fail."
        )
        text.setWordWrap(True)
        layout.addWidget(text, stretch=1)

        relaunch_btn = QPushButton("Relaunch as administrator")
        relaunch_btn.setToolTip("Re-opens this app elevated via UAC, then closes this window")
        relaunch_btn.clicked.connect(self._relaunch_elevated)
        layout.addWidget(relaunch_btn)
        self.banner = banner
        return banner

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("toolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search components   (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumWidth(170)
        self.search_box.textChanged.connect(self._on_search_changed)
        row.addWidget(self.search_box, stretch=2)

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for mode, label, tip in (
            (FILTER_ALL, "All", "Show every component"),
            (FILTER_NEEDS, "Needs action", "Only what's missing or has an update available"),
            (FILTER_INSTALLED, "Installed", "Only what's already on this machine"),
        ):
            chip = QPushButton(label)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setToolTip(tip)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setChecked(mode == FILTER_ALL)
            chip.clicked.connect(lambda _checked=False, m=mode: self._set_filter(m))
            self.filter_group.addButton(chip)
            self.filter_buttons[mode] = chip
            row.addWidget(chip)

        row.addSpacing(10)

        profile_label = QLabel("Profile")
        profile_label.setObjectName("fieldLabel")
        row.addWidget(profile_label)

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.profile_combo.setToolTip("A saved selection preset — pick one to check exactly those components")
        self.profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        row.addWidget(self.profile_combo)

        self.profile_menu_btn = QToolButton()
        self.profile_menu_btn.setText("Manage")
        self.profile_menu_btn.setToolTip("Save, update, delete, import or export profiles")
        self.profile_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        profile_menu = QMenu(self.profile_menu_btn)
        self.profile_save_as_action = profile_menu.addAction("Save current selection as…")
        self.profile_update_action = profile_menu.addAction("Update this profile")
        self.profile_delete_action = profile_menu.addAction("Delete this profile")
        profile_menu.addSeparator()
        self.profile_export_action = profile_menu.addAction("Export…")
        self.profile_import_action = profile_menu.addAction("Import…")
        self.profile_save_as_action.triggered.connect(self._on_save_profile_as)
        self.profile_update_action.triggered.connect(self._on_update_profile)
        self.profile_delete_action.triggered.connect(self._on_delete_profile)
        self.profile_export_action.triggered.connect(self._on_export_profile)
        self.profile_import_action.triggered.connect(self._on_import_profile)
        self.profile_menu_btn.setMenu(profile_menu)
        row.addWidget(self.profile_menu_btn)

        row.addSpacing(10)

        self.rescan_btn = QPushButton("⟳  Rescan")
        self.rescan_btn.setToolTip("Re-check what's installed and look up the latest versions   (Ctrl+R)")
        self.rescan_btn.clicked.connect(self._start_scan)
        row.addWidget(self.rescan_btn)

        self.dry_run_checkbox = QCheckBox("Dry run")
        self.dry_run_checkbox.setToolTip(
            "Preview every action (including what it would download) without installing or writing anything"
        )
        self.dry_run_checkbox.toggled.connect(lambda _on: self._update_selection_ui())
        row.addWidget(self.dry_run_checkbox)

        self.menu_btn = QToolButton()
        self.menu_btn.setText("☰")
        self.menu_btn.setToolTip("More")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_btn)
        self.export_report_action = menu.addAction("Export system report…")
        menu.addSeparator()
        expand = menu.addAction("Expand all")
        collapse = menu.addAction("Collapse all")
        menu.addSeparator()
        theme_menu = menu.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for pref, label in (("system", "Follow Windows"), ("dark", "Dark"), ("light", "Light")):
            action = theme_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(pref == self._theme_pref)
            action.triggered.connect(lambda _checked=False, p=pref: self._set_theme_pref(p))
            self.theme_group.addAction(action)
            self.theme_actions[pref] = action
        self.check_updates_action = menu.addAction("Check for app updates")
        self.check_updates_action.setCheckable(True)
        self.check_updates_action.setChecked(self.settings.value("check_app_updates", True, type=bool))
        self.check_updates_action.toggled.connect(self._on_check_updates_toggled)
        menu.addSeparator()
        open_logs = menu.addAction("Open log folder")
        menu.addSeparator()
        donate = menu.addAction("♥  Support on Ko-fi")
        self.export_report_action.triggered.connect(self._on_export_report)
        expand.triggered.connect(lambda: self.tree.expandAll())
        collapse.triggered.connect(lambda: self.tree.collapseAll())
        open_logs.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.app_dir))))
        donate.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(KOFI_URL)))
        self.menu_btn.setMenu(menu)
        self.menu_btn.setAccessibleName("More options")
        self.profile_menu_btn.setAccessibleName("Manage profiles")
        self.profile_combo.setAccessibleName("Profile")
        self.search_box.setAccessibleName("Search components")
        row.addWidget(self.menu_btn)
        return bar

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["Component", "Status", "Installed", "Latest"])
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_INSTALLED, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_LATEST, QHeaderView.ResizeMode.Fixed)
        tree.setColumnWidth(COL_STATUS, 190)
        tree.setColumnWidth(COL_INSTALLED, 150)
        tree.setColumnWidth(COL_LATEST, 150)
        header.setMinimumSectionSize(90)
        tree.setIndentation(20)
        tree.setUniformRowHeights(True)
        tree.setAnimated(False)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setMouseTracking(True)
        tree.itemChanged.connect(self._on_tree_item_changed)
        tree.currentItemChanged.connect(lambda current, _previous: self._show_details(current))
        tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        # Shown over the tree when a search/filter leaves nothing to display.
        self.empty_label = QLabel("No components match your search or filter.", tree.viewport())
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setObjectName("emptyLabel")
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.empty_label.hide()
        self._viewport_filter = _ResizeFilter(lambda: self.empty_label.setGeometry(tree.viewport().rect()), tree)
        tree.viewport().installEventFilter(self._viewport_filter)
        return tree

    def _build_bottom_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setDocumentMode(False)

        # --- Details (what the selected row actually is) ---
        self.details_label = QLabel()
        self.details_label.setTextFormat(Qt.TextFormat.RichText)
        self.details_label.setWordWrap(True)
        self.details_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_label.setMargin(10)
        self.details_label.setObjectName("detailsLabel")
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        details_scroll.setWidget(self.details_label)
        self.details_tab_index = tabs.addTab(details_scroll, "Details")
        self._show_details(None)

        # --- Log ---
        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Install and scan output appears here.")

        log_page = QWidget()
        log_page.setObjectName("tabPage")
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        log_bar = QHBoxLayout()
        log_bar.setContentsMargins(8, 6, 8, 6)
        log_bar.setSpacing(6)
        log_bar.addStretch()
        self.log_copy_btn = QPushButton("Copy")
        self.log_clear_btn = QPushButton("Clear")
        self.log_open_btn = QPushButton("Open log file")
        for btn in (self.log_copy_btn, self.log_clear_btn, self.log_open_btn):
            btn.setObjectName("miniBtn")
            log_bar.addWidget(btn)
        self.log_copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))
        self.log_clear_btn.clicked.connect(self.log_view.clear)
        self.log_open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.logger.log_file)))
        )
        log_layout.addLayout(log_bar)
        log_layout.addWidget(self.log_view, stretch=1)
        self.log_tab_index = tabs.addTab(log_page, "Log")

        # --- PATH backups ---
        page = QWidget()
        page.setObjectName("tabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        blurb = QLabel(
            "A snapshot of the machine and user PATH is taken before every real install, "
            "so a bad PATH change can always be rolled back."
        )
        blurb.setObjectName("fieldLabel")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_backup_combo = QComboBox()
        self.path_backup_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path_backup_combo.setToolTip("One snapshot per real install run, plus any you take by hand")
        row.addWidget(self.path_backup_combo, stretch=1)

        self.path_backup_restore_btn = QPushButton("Restore…")
        self.path_backup_restore_btn.setToolTip("Preview and optionally roll PATH back to this snapshot")
        self.path_backup_restore_btn.clicked.connect(self._on_restore_path_backup)
        row.addWidget(self.path_backup_restore_btn)

        self.path_backup_now_btn = QPushButton("Back up now")
        self.path_backup_now_btn.setToolTip(
            "Snapshot PATH right now, without installing anything — installs only back it up "
            "automatically when Dry Run is off"
        )
        self.path_backup_now_btn.clicked.connect(self._on_backup_path_now)
        row.addWidget(self.path_backup_now_btn)
        layout.addLayout(row)
        layout.addStretch()
        tabs.addTab(page, "PATH backups")
        return tabs

    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("actionBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 12, 10)
        row.setSpacing(10)

        self.summary_label = QLabel("Scanning…")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.summary_label, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(240)
        self.progress_bar.setVisible(False)
        row.addWidget(self.progress_bar)

        self.select_missing_btn = QPushButton("Select needed")
        self.select_missing_btn.setToolTip(
            "Check everything missing or outdated. Optional extras (apps, Go, Rust, Ghidra...) are only "
            "checked when they're already installed and have an update."
        )
        self.select_missing_btn.clicked.connect(self._on_select_not_installed)
        row.addWidget(self.select_missing_btn)

        self.select_all_btn = QPushButton("All")
        self.select_all_btn.setToolTip("Check every component")
        self.select_all_btn.clicked.connect(self._on_select_all)
        row.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("None")
        self.select_none_btn.setToolTip("Uncheck everything")
        self.select_none_btn.clicked.connect(self._on_select_none)
        row.addWidget(self.select_none_btn)

        self.selection_label = QLabel("")
        self.selection_label.setObjectName("selectionLabel")
        row.addWidget(self.selection_label)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setVisible(False)
        row.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install")
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.clicked.connect(self._on_install_clicked)
        self.install_btn.setEnabled(False)
        row.addWidget(self.install_btn)
        return bar

    def _relaunch_elevated(self):
        """Re-launches this exact process elevated via a real UAC prompt,
        then quits this instance - only quits if the prompt was actually
        accepted (ShellExecuteW's return value is > 32 on success; a
        cancelled/denied prompt returns an error code, in which case this
        window is left running untouched rather than quitting for nothing).
        Handles both the frozen exe (no separate script argument needed)
        and running from source (python.exe needs the script path passed
        as its own argument)."""
        for worker in (self.install_worker, self.uninstall_worker, self.scan_worker):
            if worker is not None and worker.isRunning():
                # QApplication.quit() here would destroy a live QThread out
                # from under a running install/uninstall/scan - exactly the
                # crash/orphaned-subprocess risk closeEvent's own guards
                # exist to prevent (see closeEvent below). Relaunching isn't
                # urgent enough to justify that; just ask for the work to
                # finish first.
                QMessageBox.information(
                    self, "Busy",
                    "Wait for the current install/uninstall/scan to finish before relaunching as Administrator.",
                )
                return
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

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _resolve_scheme(self) -> str:
        """The palette to use: an explicit Dark/Light choice, or whatever
        Windows is set to (dark if it can't be determined)."""
        if self._theme_pref in ("dark", "light"):
            return self._theme_pref
        try:
            scheme = QGuiApplication.styleHints().colorScheme()
        except AttributeError:
            return "dark"
        return "light" if scheme == Qt.ColorScheme.Light else "dark"

    def _apply_theme(self):
        theme.set_scheme(self._resolve_scheme())
        QApplication.instance().setStyleSheet(build_app_stylesheet())
        self._restyle_items()
        self._show_details(self.tree.currentItem())

    def _restyle_items(self):
        """Recolors the per-item foregrounds (QSS can't reach those) after a theme switch."""
        p = theme.palette
        for item in self.tree_items.values():
            kind = item.data(COL_STATUS, Qt.ItemDataRole.UserRole) or "missing"
            item.setForeground(COL_STATUS, self._color(theme.status_color(kind)))
            item.setForeground(COL_INSTALLED, self._color(p.TEXT_DIM))
            latest_kind = item.data(COL_LATEST, Qt.ItemDataRole.UserRole) or "skip"
            item.setForeground(COL_LATEST, self._color(theme.status_color(latest_kind)))
        for cat_item in self.category_items.values():
            kind = cat_item.data(COL_STATUS, Qt.ItemDataRole.UserRole) or "skip"
            cat_item.setForeground(COL_STATUS, self._color(theme.status_color(kind)))

    # ------------------------------------------------------------------
    # App update notice
    # ------------------------------------------------------------------

    def _start_update_check(self):
        """Only the packaged app looks (a source checkout is its own updater),
        and only if the user hasn't switched it off in the menu."""
        packaged = getattr(sys, "frozen", False) or os.environ.get("RF_FORCE_UPDATE_CHECK") == "1"
        if not packaged or not self.check_updates_action.isChecked():
            return
        self._update_check = AppUpdateCheck(self.APP_VERSION, self)
        self._update_check.update_found.connect(self._on_app_update_found)
        self._update_check.start()

    def _on_app_update_found(self, version: str, url: str):
        self.update_btn.setText(f"⬆  v{version} available")
        self.update_btn.setToolTip("A newer Runtime Forge is out — open the release page")
        try:
            self.update_btn.clicked.disconnect()
        except TypeError:
            pass
        self.update_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url or "https://github.com/Echo-Storm/Runtime_Forge/releases")))
        self.update_btn.setVisible(True)

    def _on_check_updates_toggled(self, on: bool):
        self.settings.setValue("check_app_updates", on)
        if on:
            self._start_update_check()
        else:
            self.update_btn.setVisible(False)

    def _set_theme_pref(self, pref: str):
        self._theme_pref = pref
        self.settings.setValue("theme", pref)
        self._apply_theme()

    def _on_system_scheme_changed(self, *_args):
        if self._theme_pref == "system":
            self._apply_theme()

    # ------------------------------------------------------------------
    # Tree population / row presentation
    # ------------------------------------------------------------------

    @staticmethod
    def _color(hex_str: str) -> QColor:
        return QColor(hex_str)

    def _set_status(self, item: QTreeWidgetItem, text: str, kind: str):
        """`kind` (ok / update / missing / busy / fail / skip / warn / checking) is
        remembered on the item so a theme switch can recolor it."""
        item.setText(COL_STATUS, text)
        item.setData(COL_STATUS, Qt.ItemDataRole.UserRole, kind)
        item.setForeground(COL_STATUS, self._color(theme.status_color(kind)))

    def _populate_tree(self):
        for component in self.components:
            cat_item = self.category_items.get(component.category)
            if cat_item is None:
                cat_item = QTreeWidgetItem(self.tree, [component.category, "", "", ""])
                cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                cat_item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
                font = cat_item.font(COL_NAME)
                font.setBold(True)
                cat_item.setFont(COL_NAME, font)
                cat_item.setData(COL_STATUS, Qt.ItemDataRole.UserRole, "skip")
                cat_item.setForeground(COL_STATUS, self._color(theme.status_color("skip")))
                self.category_items[component.category] = cat_item

            leaf = QTreeWidgetItem(cat_item, [component.name, STATUS_CHECKING, "", ""])
            leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            leaf.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            leaf.setData(COL_NAME, Qt.ItemDataRole.UserRole, component.key)
            leaf.setToolTip(COL_NAME, f"{component.name}\n{component.category}")
            self._set_status(leaf, STATUS_CHECKING, "checking")
            leaf.setForeground(COL_INSTALLED, self._color(theme.palette.TEXT_DIM))
            leaf.setForeground(COL_LATEST, self._color(theme.palette.TEXT_DIM))
            self.tree_items[component.key] = leaf

        self.tree.expandAll()

    def _update_category_summaries(self):
        """The category rows double as a one-glance summary ("5 of 6 installed")."""
        for category, cat_item in self.category_items.items():
            keys = [c.key for c in self.components if c.category == category]
            scanned = [self._scan_results[k] for k in keys if k in self._scan_results]
            if len(scanned) < len(keys):
                cat_item.setText(COL_STATUS, "")
                continue
            installed = sum(1 for state, _ in scanned if state.installed)
            updates = sum(1 for state, latest in scanned if self._has_update(state, latest))
            text = f"{installed} of {len(keys)} installed"
            if updates:
                text += f"  ·  {updates} update{'s' if updates != 1 else ''}"
            cat_item.setText(COL_STATUS, text)
            kind = "update" if updates else "skip"
            cat_item.setData(COL_STATUS, Qt.ItemDataRole.UserRole, kind)
            cat_item.setForeground(COL_STATUS, self._color(theme.status_color(kind)))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("splitter")
        if splitter_state:
            self.splitter.restoreState(splitter_state)
        dry_run = self.settings.value("dry_run", False, type=bool)
        self.dry_run_checkbox.setChecked(dry_run)

    def _save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("dry_run", self.dry_run_checkbox.isChecked())

    def closeEvent(self, event):
        self._save_settings()
        if self._update_check is not None and self._update_check.isRunning():
            self._update_check.wait(3000)
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
    # Busy state / action bar
    # ------------------------------------------------------------------

    def _is_scanning(self) -> bool:
        return self.scan_worker is not None and self.scan_worker.isRunning()

    def _is_busy(self) -> bool:
        return self._is_scanning() or self.install_worker is not None or self.uninstall_worker is not None

    def _update_selection_ui(self):
        """The Install button always says exactly what it will do, and is
        disabled while there's nothing checked or something else is running."""
        count = len(self._selected_keys())
        dry = self.dry_run_checkbox.isChecked()
        self.selection_label.setText(f"{count} selected" if count else "")
        verb = "Dry run" if dry else "Install"
        self.install_btn.setText(f"{verb} {count} selected" if count else verb)
        self.install_btn.setEnabled(count > 0 and not self._is_busy())

    def _set_selection_controls_visible(self, visible: bool):
        """While an install runs the action bar's room goes to the progress
        readout, not to selection shortcuts that can't be used anyway."""
        for widget in (self.select_missing_btn, self.select_all_btn, self.select_none_btn, self.selection_label):
            widget.setVisible(visible)

    def _on_rescan_shortcut(self):
        if self.rescan_btn.isEnabled():
            self._start_scan()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _start_scan(self):
        self.rescan_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        # _scan_results is cleared below and re-populated incrementally as
        # ScanWorker's per-component signals arrive - clicking this mid-scan
        # would read that partial state and treat every not-yet-scanned
        # component as "not installed" (the _on_select_not_installed
        # default), wrongly checking things that are actually already
        # current.
        self.select_missing_btn.setEnabled(False)
        self.summary_label.setText("Scanning installed components…")
        self._scan_results.clear()
        for key, item in self.tree_items.items():
            self._set_status(item, STATUS_CHECKING, "checking")
        self._update_category_summaries()

        self.scan_worker = ScanWorker(self.components, self)
        self.scan_worker.component_scanned.connect(self._on_component_scanned)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.log_line.connect(self._on_log_line)
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
                self._set_status(item, STATUS_UPDATE, "update")
            elif latest is not None:
                self._set_status(item, STATUS_UP_TO_DATE, "ok")
            else:
                self._set_status(item, STATUS_INSTALLED, "ok")
        else:
            self._set_status(item, STATUS_NOT_INSTALLED, "missing")

        item.setText(COL_INSTALLED, state.version or "–")
        item.setText(COL_LATEST, latest.version if latest is not None else "–")
        item.setData(COL_LATEST, Qt.ItemDataRole.UserRole, "update" if has_update else "skip")
        item.setForeground(COL_LATEST, self._color(theme.status_color("update" if has_update else "skip")))
        item.setToolTip(COL_STATUS, (
            f"Installed {state.version}, latest {latest.version}" if has_update and state.version else item.text(COL_STATUS)
        ))

        # Pre-select anything that's missing entirely, or that has a real
        # update available — the whole point of surfacing "update available"
        # is for Install to actually be able to act on it. Only on the very
        # first scan, though — see _initial_scan_done.
        # Optional extras (apps, extra languages) are never pre-checked when
        # missing - only an update to one that's already installed is.
        component = self.component_by_key.get(key)
        wanted = (not state.installed and not (component and component.optional)) or has_update
        if not self._initial_scan_done and wanted:
            item.setCheckState(COL_NAME, Qt.CheckState.Checked)

        self._update_category_summaries()
        if self._filter_mode != FILTER_ALL:
            self._apply_filters()

    def _on_scan_finished(self):
        self.scan_worker = None
        self._initial_scan_done = True
        self.rescan_btn.setEnabled(True)
        self.select_missing_btn.setEnabled(True)
        self._update_selection_ui()

        not_installed = sum(1 for state, _ in self._scan_results.values() if not state.installed)
        updates_available = sum(1 for state, latest in self._scan_results.values() if self._has_update(state, latest))

        self._last_scan_time = datetime.now()
        parts = [f"{len(self.components) - not_installed} of {len(self.components)} installed"]
        if not_installed:
            parts.append(f"{not_installed} missing")
        if updates_available:
            parts.append(f"{updates_available} update{'s' if updates_available != 1 else ''} available")
        parts.append(f"scanned {self._last_scan_time.strftime('%I:%M %p').lstrip('0')}")
        self.summary_label.setText("  ·  ".join(parts))
        self.logger.status(f"Scan complete ({not_installed} not installed, {updates_available} updates available)")
        self._update_category_summaries()
        self._apply_filters()

    # ------------------------------------------------------------------
    # Search / filter / context menu
    # ------------------------------------------------------------------

    def _set_filter(self, mode: str):
        self._filter_mode = mode
        for m, button in self.filter_buttons.items():
            button.setChecked(m == mode)
        self._apply_filters()

    def _on_search_changed(self, text: str):
        self._apply_filters()

    def _passes_filter(self, key: str) -> bool:
        if self._filter_mode == FILTER_ALL:
            return True
        result = self._scan_results.get(key)
        if result is None:
            return True  # not scanned yet - never hide something we don't know about
        state, latest = result
        if self._filter_mode == FILTER_INSTALLED:
            return state.installed
        return (not state.installed) or self._has_update(state, latest)

    def _apply_filters(self):
        query = self.search_box.text().strip().lower()
        for key, item in self.tree_items.items():
            matches_text = not query or query in item.text(COL_NAME).lower()
            item.setHidden(not (matches_text and self._passes_filter(key)))

        # A category row stays visible only if at least one child does -
        # otherwise a matching leaf would be orphaned under a hidden parent.
        filtering = bool(query) or self._filter_mode != FILTER_ALL
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            if not filtering:
                cat_item.setHidden(False)
                continue
            any_visible = any(not cat_item.child(j).isHidden() for j in range(cat_item.childCount()))
            cat_item.setHidden(not any_visible)

        if filtering:
            self.tree.expandAll()
        any_leaf_visible = any(not item.isHidden() for item in self.tree_items.values())
        self.empty_label.setVisible(not any_leaf_visible)
        self.empty_label.setGeometry(self.tree.viewport().rect())

    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Double-clicking a row toggles it - a much bigger target than the checkbox."""
        if item.parent() is None:
            return  # category rows keep Qt's default expand/collapse
        item.setCheckState(
            COL_NAME,
            Qt.CheckState.Unchecked if item.checkState(COL_NAME) == Qt.CheckState.Checked else Qt.CheckState.Checked,
        )

    def _on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or item.parent() is None:
            return  # empty space, or a category row (categories have no parent)

        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        component = self.component_by_key.get(key)
        if component is None:
            return
        result = self._scan_results.get(key)
        state = result[0] if result else None

        menu = QMenu(self)

        latest = result[1] if result else None
        if state is not None and not self._is_busy():
            if not state.installed:
                menu.addAction("Install").triggered.connect(lambda: self._start_install({key}))
            elif self._has_update(state, latest):
                menu.addAction(f"Update to {latest.version}").triggered.connect(lambda: self._start_install({key}))
            else:
                menu.addAction("Reinstall").triggered.connect(lambda: self._start_install({key}, force=True))
            menu.addSeparator()

        if state is not None and state.installed and (component.location or component.path_entry) is not None:
            open_action = menu.addAction("Open install location")
            open_action.triggered.connect(lambda: self._open_install_location(component))

        if latest is not None and latest.url:
            menu.addAction("Copy download URL").triggered.connect(lambda: QApplication.clipboard().setText(latest.url))

        if state is not None and state.version:
            copy_action = menu.addAction("Copy version")
            copy_action.triggered.connect(lambda: QApplication.clipboard().setText(state.version))

        if state is not None and state.installed and component.uninstall is not None:
            menu.addSeparator()
            uninstall_action = menu.addAction("Uninstall…")
            uninstall_action.triggered.connect(lambda: self._on_uninstall_component(component))

        if menu.isEmpty():
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_uninstall_component(self, component: Component):
        if self._is_busy():
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
        self.status_bar.showMessage(f"Uninstalling {component.name}…")

        self.uninstall_worker = UninstallWorker(component, dry_run, self)
        self.uninstall_worker.log_line.connect(self._on_log_line)
        self.uninstall_worker.finished_uninstall.connect(self._on_uninstall_finished)
        self.uninstall_worker.start()

    def _on_uninstall_finished(self, key: str, success: bool):
        # Captured from the worker that actually ran, not read live off the
        # checkbox below - the user can toggle Dry Run while a real
        # uninstall is still in flight, and reading it live here would then
        # treat a real, completed removal as a no-op dry run and skip the
        # re-verification/tree-update block entirely.
        was_dry_run = self.uninstall_worker.dry_run if self.uninstall_worker else True
        self.uninstall_worker = None
        self.rescan_btn.setEnabled(True)
        self._update_selection_ui()
        self.status_bar.clearMessage()

        component = self.component_by_key.get(key)
        item = self.tree_items.get(key)
        if component is None or item is None:
            return

        if not success:
            QMessageBox.warning(self, "Uninstall Failed", f"Could not uninstall {component.name} — check the log for details.")
            return

        if was_dry_run:
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
            self._set_status(item, STATUS_INSTALLED, "ok")
            QMessageBox.information(
                self, "Still Installed",
                f"{component.name}'s uninstall command completed, but it still appears installed — "
                f"it may need a restart to finish, or the removal wasn't fully complete.",
            )
        else:
            self._set_status(item, STATUS_NOT_INSTALLED, "missing")
            item.setText(COL_INSTALLED, "–")
            item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            self.status_bar.showMessage(f"{component.name} uninstalled", 5000)
        self._update_category_summaries()

    @staticmethod
    def _open_install_location(component: Component):
        finder = component.location or component.path_entry
        if finder is None:
            return
        try:
            entry = finder()
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
        # Visible rows only: with a search or filter active, "All" means
        # "everything I'm looking at", not rows hidden out of view.
        for item in self.tree_items.values():
            if not item.isHidden():
                item.setCheckState(COL_NAME, state)

    def _on_select_all(self):
        self._set_all_checkstate(Qt.CheckState.Checked)

    def _on_select_none(self):
        for item in self.tree_items.values():
            item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)

    def _on_select_not_installed(self):
        # Reads the cached scan results rather than calling is_installed()
        # again here — several of those checks (git/node/cmake/pwsh) shell
        # out to the real exe with a 15s timeout each, which would freeze
        # the UI thread if run synchronously from a button click instead of
        # ScanWorker's background thread.
        for key, item in self.tree_items.items():
            state, latest = self._scan_results.get(key, (InstalledState(installed=False), None))
            component = self.component_by_key[key]
            needs_action = (not state.installed and not component.optional) or self._has_update(state, latest)
            item.setCheckState(COL_NAME, Qt.CheckState.Checked if needs_action else Qt.CheckState.Unchecked)

    def _selected_keys(self) -> set[str]:
        return {key for key, item in self.tree_items.items() if item.checkState(COL_NAME) == Qt.CheckState.Checked}

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != COL_NAME:
            return
        self._update_selection_ui()
        # Any manual checkbox edit invalidates "this matches a saved
        # profile" — reset the combo to Custom rather than silently implying
        # the current selection still matches whatever was last loaded.
        # _active_profile_name deliberately does NOT get cleared here: it's
        # what "Update" saves back to, and the whole point of Update is
        # "I loaded a profile, tweaked the selection, now save that back" —
        # if editing cleared it too, Update would go permanently disabled
        # the instant you made the one edit you actually wanted to save.
        if self._applying_profile:
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
        self.profile_update_action.setEnabled(self._active_profile_name is not None)
        has_selected = self._current_profile_name() is not None
        self.profile_delete_action.setEnabled(has_selected)
        self.profile_export_action.setEnabled(has_selected)

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
            item.setCheckState(COL_NAME, Qt.CheckState.Checked if key in keys else Qt.CheckState.Unchecked)
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
        self._import_profile_file(Path(src))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".json") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Drop a profile .json anywhere on the window to import it."""
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".json":
                self._import_profile_file(path)
                break

    def _import_profile_file(self, src: Path):
        profile = profiles.load_profile(src)
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
        # below was set, so the Update action could be left stale (disabled)
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
        Back up now)."""
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
        self._start_install(self._selected_keys())

    def _confirm_install(self, selected: set, dry_run: bool) -> bool:
        names = [c.name for c in self.components if c.key in selected]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Confirm Install")
        box.setText(f"Install {len(names)} component{'s' if len(names) != 1 else ''}?")
        box.setInformativeText(
            "This downloads each installer, verifies it, and runs it. It may change the registry, "
            "PATH and Program Files; a PATH backup is taken first."
        )
        box.setDetailedText("\n".join(f"•  {n}" for n in names))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _start_install(self, selected: set, force: bool = False):
        if not selected:
            QMessageBox.information(self, "Nothing Selected", "Check at least one component to install.")
            return
        if self._is_busy():
            QMessageBox.information(self, "Busy", "Wait for the current install/uninstall/scan to finish first.")
            return

        dry_run = self.dry_run_checkbox.isChecked()
        if not dry_run and not self._confirm_install(selected, dry_run):
            return

        self._install_total = len(selected)
        self._install_done = 0
        self._install_results = {}
        self._set_selection_controls_visible(False)
        self.install_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 of {self._install_total}")
        self.log_view.clear()
        self.bottom_tabs.setCurrentIndex(self.log_tab_index)

        self.install_worker = InstallWorker(self.components, selected, dry_run, self, force=force)
        self.install_worker.component_started.connect(self._on_component_started)
        self.install_worker.component_progress.connect(self._on_component_progress)
        self.install_worker.component_finished.connect(self._on_component_finished)
        self.install_worker.log_line.connect(self._on_log_line)
        self.install_worker.all_finished.connect(self._on_all_finished)
        self.install_worker.start()

    def _on_cancel_clicked(self):
        if self.install_worker:
            self.install_worker.request_cancel()
            self.status_bar.showMessage("Cancelling after the current component finishes…")

    def _set_overall_progress(self, fraction_of_current: float = 0.0):
        total = max(1, self._install_total)
        value = (self._install_done + max(0.0, min(1.0, fraction_of_current))) / total
        self.progress_bar.setValue(int(value * 100))
        shown = min(self._install_done + 1, total)
        self.progress_bar.setFormat(f"{shown} of {total}")

    def _on_component_started(self, key: str):
        item = self.tree_items.get(key)
        if item:
            self._set_status(item, STATUS_INSTALLING, "busy")
            self.tree.scrollToItem(item)
        component = self.component_by_key.get(key)
        if component:
            self.status_bar.showMessage(f"Installing {component.name}…")
            self.summary_label.setText(
                f"Installing {min(self._install_done + 1, self._install_total)} of {self._install_total}  ·  {component.name}"
            )
        self._set_overall_progress(0.0)

    def _on_component_progress(self, key: str, message: str, fraction: float):
        self._set_overall_progress(fraction)
        self.status_bar.showMessage(message)

    def _on_component_finished(self, key: str, status: ResultStatus, warning: str):
        self._install_done += 1
        self._install_results[key] = status
        self._set_overall_progress(0.0)
        item = self.tree_items.get(key)
        if item is None:
            return
        if status == ResultStatus.INSTALLED and warning:
            self._set_status(item, "⚠   Installed — not on PATH", "warn")
            item.setToolTip(COL_STATUS, warning)
        elif status == ResultStatus.INSTALLED:
            self._set_status(item, STATUS_INSTALLED, "ok")
        elif status == ResultStatus.SKIPPED:
            self._set_status(item, STATUS_SKIPPED, "skip")
            item.setToolTip(COL_STATUS, warning or "Already installed and current")
        else:
            self._set_status(item, STATUS_FAILED, "fail")
            item.setToolTip(COL_STATUS, "See the log for details")

        # Keep _scan_results (what the context menu and Export Report read)
        # in sync with what actually just happened - without this, a
        # component installed this run shows no "Uninstall"/"Open Install
        # Location" menu and Export Report still calls it "Not installed"
        # until the next full Rescan, since only ScanWorker's results ever
        # wrote into _scan_results before this.
        component = self.component_by_key.get(key)
        if component is not None and status in (ResultStatus.INSTALLED, ResultStatus.SKIPPED):
            try:
                state = component.is_installed()
            except Exception:
                state = InstalledState(installed=False)
            previous_latest = self._scan_results.get(key, (None, None))[1]
            self._scan_results[key] = (state, previous_latest)
            item.setText(COL_INSTALLED, state.version or "–")
            self._update_category_summaries()

    def _show_details(self, item: Optional[QTreeWidgetItem]):
        """Fills the Details tab for the highlighted row."""
        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole) if item is not None else None
        component = self.component_by_key.get(key) if key else None
        dim, text = theme.palette.TEXT_DIM, theme.palette.TEXT
        if component is None:
            if item is not None and item.parent() is None:
                body = f'<span style="color:{dim}">{html.escape(item.text(COL_NAME))} — {html.escape(item.text(COL_STATUS)) or "scanning…"}</span>'
            else:
                body = f'<span style="color:{dim}">Select a component to see what it is, where it lives and what version it would install.</span>'
            self.details_label.setText(body)
            return

        result = self._scan_results.get(key)
        state, latest = result if result else (None, None)
        rows = [("Category", component.category)]
        if state is None:
            rows.append(("Status", "Checking…"))
        elif state.installed:
            rows.append(("Installed", state.version or "yes (version unknown)"))
        else:
            rows.append(("Installed", "no"))
        if latest is not None:
            label = "Latest"
            value = latest.version
            if self._has_update(state, latest) if state else False:
                value += f'  <span style="color:{theme.palette.WARN}">(update available)</span>'
            rows.append((label, value))
            if latest.url:
                rows.append(("Downloads from", html.escape(latest.url)))
            if latest.sha256:
                rows.append(("SHA-256", f'<span style="font-family:Consolas">{latest.sha256}</span>'))
        finder = component.location or component.path_entry
        if finder is not None:
            try:
                entry = finder()
            except Exception:
                entry = None
            if entry is not None:
                rows.append(("Install location", html.escape(str(entry))))
        rows.append(("Can uninstall", "yes" if component.uninstall is not None else "no — Windows or other software may depend on it"))
        if component.optional:
            rows.append(("Optional", "never pre-checked by a scan or Select needed"))
        if component.note:
            rows.append(("Note", html.escape(component.note)))

        table = "".join(
            f'<tr><td style="color:{dim}; padding-right:18px; vertical-align:top">{k}</td>'
            f'<td style="color:{text}">{v if k in ("Installed", "Latest", "SHA-256") else v}</td></tr>'
            for k, v in rows
        )
        self.details_label.setText(
            f'<div style="font-size:12pt; font-weight:600; color:{text}">{html.escape(component.name)}</div>'
            f'<table cellspacing="4" style="margin-top:6px">{table}</table>'
        )

    @staticmethod
    def _log_colors():
        p = theme.palette
        return (
            ("[FAIL]", p.ERR), ("WARNING", p.WARN), ("[ OK ]", p.OK),
            ("[SKIP]", p.TEXT_FAINT), ("[ DRY]", p.ACCENT),
        )

    def _on_log_line(self, line: str):
        color = next((c for tag, c in self._log_colors() if tag in line), None)
        escaped = html.escape(line)
        self.log_view.append(f'<span style="color:{color}">{escaped}</span>' if color else escaped)

    def _on_all_finished(self, installed: int, skipped: int, failed: int):
        # Same "use what the worker actually ran with" reasoning as
        # _on_uninstall_finished above - reading the checkbox live here
        # would miss refreshing the combo if Dry Run got toggled on after a
        # real run (that already created a backup) started.
        was_dry_run = self.install_worker.dry_run if self.install_worker else True
        self.install_worker = None
        self.rescan_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self._set_selection_controls_visible(True)
        self.status_bar.clearMessage()
        self._update_selection_ui()
        self.summary_label.setText(f"Done  ·  {installed} installed  ·  {skipped} skipped  ·  {failed} failed")
        if not was_dry_run:
            self._refresh_path_backup_combo()  # a real run just created a new one

        failed_names = [
            self.component_by_key[k].name for k, st in self._install_results.items()
            if st == ResultStatus.FAILED and k in self.component_by_key
        ]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if failed else QMessageBox.Icon.Information)
        box.setWindowTitle("Install Complete" if not was_dry_run else "Dry Run Complete")
        box.setText(f"Installed: {installed}    Skipped: {skipped}    Failed: {failed}")
        extra = ("Failed:\n" + "\n".join(f"•  {n}" for n in failed_names) + "\n\n") if failed_names else ""
        box.setInformativeText(f"{extra}Log saved to:\n{self.logger.log_file}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        self._show_details(self.tree.currentItem())


class _ResizeFilter(QObject):
    """Calls `callback` whenever the watched widget is resized (used to keep
    the empty-state label covering the tree's viewport)."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self._callback()
        return False
