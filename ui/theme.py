"""
Runtime Forge's visual theme: one palette, one stylesheet.

Everything color-related lives here so the window code only refers to
semantic names (ACCENT, OK, WARN...) and the QSS below is the single place
that decides what a button, a tree row or a scrollbar looks like.
"""

# --- palette -------------------------------------------------------------
BG = "#14171b"            # window
SURFACE = "#1b1f24"       # panels, tree, inputs
SURFACE_ALT = "#20252b"   # alternating rows, hover
RAISED = "#262c33"        # buttons
BORDER = "#2c333b"
BORDER_STRONG = "#3a424c"
TEXT = "#d3d8de"
TEXT_DIM = "#8b939d"
TEXT_FAINT = "#5d6570"
ACCENT = "#5aa9f2"
ACCENT_DIM = "#245a8d"
ACCENT_BG = "#17304a"
OK = "#5fc48a"
WARN = "#e0b04f"
ORANGE = "#e58f4a"
ERR = "#e26d6d"

# status-column colors (kept under their old names for the window code)
COLOR_NOT_INSTALLED = TEXT_DIM
COLOR_INSTALLED = OK
COLOR_UPDATE_AVAILABLE = WARN
COLOR_INSTALLING = ACCENT
COLOR_FAILED = ERR
COLOR_SKIPPED = TEXT_DIM
COLOR_PATH_WARNING = ORANGE

FONT_UI = '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", "Courier New", monospace'


def build_stylesheet(check_icon: str = "", dash_icon: str = "") -> str:
    """`check_icon` / `dash_icon`: white PNGs drawn inside checked / partly-checked boxes."""
    return f"""
* {{
    outline: none;
}}

QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 10pt;
}}

QDialog, QMessageBox, QInputDialog {{
    background-color: {BG};
    color: {TEXT};
}}

QToolTip {{
    background-color: {RAISED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 4px 6px;
}}

/* ---- toolbar / panels -------------------------------------------- */

QFrame#toolbar {{
    background-color: transparent;
}}

QFrame#banner {{
    background-color: #2a2417;
    border: 1px solid #5d4c22;
    border-radius: 6px;
}}
QFrame#banner QLabel {{
    background: transparent;
    color: {WARN};
}}

QFrame#actionBar {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#actionBar QLabel {{
    background: transparent;
}}

QLabel#summaryLabel {{
    color: {TEXT_DIM};
}}
QLabel#selectionLabel {{
    color: {TEXT};
    font-weight: 600;
}}
QLabel#fieldLabel {{
    color: {TEXT_DIM};
    background: transparent;
}}

/* ---- buttons ------------------------------------------------------ */

QPushButton, QToolButton {{
    background-color: {RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT};
    min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{
    background-color: #2f3640;
    border-color: {ACCENT};
}}
QPushButton:pressed, QToolButton:pressed {{
    background-color: #38414c;
}}
QPushButton:disabled, QToolButton:disabled {{
    background-color: {SURFACE};
    color: {TEXT_FAINT};
    border-color: {BORDER};
}}
QToolButton::menu-indicator {{
    image: none;
    width: 0px;
}}

QPushButton#primaryBtn {{
    background-color: {ACCENT_DIM};
    border: 1px solid {ACCENT};
    color: #ffffff;
    font-weight: 600;
    padding: 8px 22px;
}}
QPushButton#primaryBtn:hover {{
    background-color: #2d6ca8;
}}
QPushButton#primaryBtn:disabled {{
    background-color: {SURFACE};
    border-color: {BORDER};
    color: {TEXT_FAINT};
}}

QPushButton#dangerBtn {{
    background-color: #3d1f22;
    border-color: #8a3f43;
    color: #f0a3a3;
}}
QPushButton#dangerBtn:hover {{
    background-color: #4d2629;
}}

QPushButton#linkBtn {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    padding: 0 6px;
    font-size: 8pt;
}}
QPushButton#linkBtn:hover {{
    color: {ACCENT};
}}

/* the All / Needs action / Installed filter */
QPushButton#chip {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 4px 12px;
    color: {TEXT_DIM};
    min-height: 18px;
}}
QPushButton#chip:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}
QPushButton#chip:checked {{
    background-color: {ACCENT_BG};
    border-color: {ACCENT};
    color: {ACCENT};
    font-weight: 600;
}}

/* ---- inputs ------------------------------------------------------- */

QLineEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT};
    min-height: 20px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QComboBox {{
    background-color: {RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT};
    min-height: 20px;
}}
QComboBox:hover, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox:disabled {{
    color: {TEXT_FAINT};
    background-color: {SURFACE};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {RAISED};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_DIM};
    color: {TEXT};
}}

QCheckBox {{
    color: {TEXT};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator, QTreeView::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background-color: {SURFACE};
}}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: url({check_icon});
}}
QTreeView::indicator:indeterminate {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
    image: url({dash_icon});
}}

/* ---- the component tree -------------------------------------------- */

QTreeWidget {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT};
    show-decoration-selected: 0;
}}
QTreeWidget::item {{
    padding: 5px 4px;
    border: none;
}}
QTreeWidget::item:hover {{
    background-color: {SURFACE_ALT};
}}
QTreeWidget::item:selected {{
    background-color: {ACCENT_BG};
    color: {TEXT};
}}
QTreeView::branch {{
    background: transparent;
}}

QHeaderView::section {{
    background-color: {SURFACE};
    color: {TEXT_DIM};
    padding: 8px 8px;
    border: none;
    border-bottom: 1px solid {BORDER_STRONG};
    font-weight: 600;
    font-size: 9pt;
}}

/* ---- log / tabs ----------------------------------------------------- */

QTextEdit#logView {{
    background-color: #101316;
    border: none;
    border-radius: 0 0 8px 8px;
    color: {TEXT_DIM};
    font-family: {FONT_MONO};
    font-size: 9pt;
    padding: 6px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background-color: {SURFACE};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 7px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QWidget#tabPage {{
    background-color: {SURFACE};
}}
QWidget#tabPage QLabel {{
    background: transparent;
}}

QSplitter::handle {{
    background: transparent;
    height: 8px;
}}

/* ---- progress / scrollbars / menus ----------------------------------- */

QProgressBar {{
    background-color: {BG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {TEXT};
    min-height: 16px;
    max-height: 16px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

QStatusBar {{
    background-color: {BG};
    color: {TEXT_DIM};
}}
QStatusBar::item {{
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER_STRONG};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: #4c5662;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background-color: {BORDER_STRONG};
    border-radius: 4px;
    min-width: 30px;
}}

QMenu {{
    background-color: {RAISED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 5px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background-color: {ACCENT_DIM};
}}
QMenu::item:disabled {{
    color: {TEXT_FAINT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER_STRONG};
    margin: 5px 8px;
}}
"""
