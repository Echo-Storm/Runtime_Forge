"""
Runtime Forge's visual theme: two palettes (dark, light) and one stylesheet
builder.

Everything color-related lives here so the window code only refers to
semantic names (palette.ACCENT, palette.OK, ...) and the QSS below is the
single place that decides what a button, a tree row or a scrollbar looks
like. `palette` is whichever scheme is active; set_scheme() swaps it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    BG: str             # window
    SURFACE: str        # panels, tree, inputs
    SURFACE_ALT: str    # hover rows
    RAISED: str         # buttons, combos
    RAISED_HOVER: str
    RAISED_PRESSED: str
    BORDER: str
    BORDER_STRONG: str
    TEXT: str
    TEXT_DIM: str
    TEXT_FAINT: str
    ACCENT: str
    ACCENT_DIM: str     # primary button / checked boxes
    ACCENT_BG: str      # selected row, active chip
    PRIMARY_HOVER: str
    PRIMARY_TEXT: str
    OK: str
    WARN: str
    ORANGE: str
    ERR: str
    BANNER_BG: str
    BANNER_BORDER: str
    BANNER_TEXT: str
    DANGER_BG: str
    DANGER_BORDER: str
    DANGER_TEXT: str
    DANGER_HOVER: str
    LOG_BG: str
    SCROLL_HOVER: str


DARK = Palette(
    name="dark",
    BG="#14171b", SURFACE="#1b1f24", SURFACE_ALT="#20252b",
    RAISED="#262c33", RAISED_HOVER="#2f3640", RAISED_PRESSED="#38414c",
    BORDER="#2c333b", BORDER_STRONG="#3a424c",
    TEXT="#d3d8de", TEXT_DIM="#8b939d", TEXT_FAINT="#5d6570",
    ACCENT="#5aa9f2", ACCENT_DIM="#245a8d", ACCENT_BG="#17304a",
    PRIMARY_HOVER="#2d6ca8", PRIMARY_TEXT="#ffffff",
    OK="#5fc48a", WARN="#e0b04f", ORANGE="#e58f4a", ERR="#e26d6d",
    BANNER_BG="#2a2417", BANNER_BORDER="#5d4c22", BANNER_TEXT="#e0b04f",
    DANGER_BG="#3d1f22", DANGER_BORDER="#8a3f43", DANGER_TEXT="#f0a3a3", DANGER_HOVER="#4d2629",
    LOG_BG="#101316", SCROLL_HOVER="#4c5662",
)

LIGHT = Palette(
    name="light",
    BG="#eef1f5", SURFACE="#ffffff", SURFACE_ALT="#f1f4f8",
    RAISED="#f7f9fb", RAISED_HOVER="#e9eef4", RAISED_PRESSED="#dde5ee",
    BORDER="#d8dee6", BORDER_STRONG="#bfc8d3",
    TEXT="#1d2630", TEXT_DIM="#55606c", TEXT_FAINT="#9aa4af",
    ACCENT="#1a73d9", ACCENT_DIM="#1a73d9", ACCENT_BG="#dbeafd",
    PRIMARY_HOVER="#155fb5", PRIMARY_TEXT="#ffffff",
    OK="#1b8a50", WARN="#a36200", ORANGE="#c2540a", ERR="#c02f2f",
    BANNER_BG="#fff4d6", BANNER_BORDER="#e3c36b", BANNER_TEXT="#7a5200",
    DANGER_BG="#fde8e8", DANGER_BORDER="#e09090", DANGER_TEXT="#a32727", DANGER_HOVER="#fbd5d5",
    LOG_BG="#f6f8fa", SCROLL_HOVER="#a9b4c0",
)

SCHEMES = {"dark": DARK, "light": LIGHT}

# The active palette. Read it at use time (`theme.palette.OK`), never copy
# its values into module-level names, or a theme switch won't reach them.
palette: Palette = DARK


def set_scheme(name: str) -> Palette:
    global palette
    palette = SCHEMES.get(name, DARK)
    return palette


FONT_UI = '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", "Courier New", monospace'

# What each status "kind" is drawn with (see ui.main_window._set_status).
STATUS_COLOR_FIELD = {
    "checking": "TEXT_DIM",
    "missing": "TEXT_DIM",
    "ok": "OK",
    "update": "WARN",
    "busy": "ACCENT",
    "fail": "ERR",
    "skip": "TEXT_DIM",
    "warn": "ORANGE",
}


def status_color(kind: str) -> str:
    return getattr(palette, STATUS_COLOR_FIELD.get(kind, "TEXT_DIM"))


def build_stylesheet(check_icon: str = "", dash_icon: str = "", chevron_right: str = "", chevron_down: str = "") -> str:
    """`check_icon` / `dash_icon`: white PNGs drawn inside checked / partly-checked boxes;
    `chevron_*`: the tree's expand / collapse arrows."""
    p = palette
    return f"""
* {{
    outline: none;
}}

QMainWindow, QWidget {{
    background-color: {p.BG};
    color: {p.TEXT};
    font-family: {FONT_UI};
    font-size: 10pt;
}}

QDialog, QMessageBox, QInputDialog {{
    background-color: {p.BG};
    color: {p.TEXT};
}}

QToolTip {{
    background-color: {p.RAISED};
    color: {p.TEXT};
    border: 1px solid {p.BORDER_STRONG};
    padding: 4px 6px;
}}

/* ---- toolbar / panels -------------------------------------------- */

QFrame#toolbar {{
    background-color: transparent;
}}

QFrame#banner {{
    background-color: {p.BANNER_BG};
    border: 1px solid {p.BANNER_BORDER};
    border-radius: 6px;
}}
QFrame#banner QLabel {{
    background: transparent;
    color: {p.BANNER_TEXT};
}}

QFrame#actionBar {{
    background-color: {p.SURFACE};
    border: 1px solid {p.BORDER};
    border-radius: 8px;
}}
QFrame#actionBar QLabel {{
    background: transparent;
}}

QLabel#summaryLabel {{
    color: {p.TEXT_DIM};
}}
QLabel#selectionLabel {{
    color: {p.TEXT};
    font-weight: 600;
}}
QLabel#emptyLabel {{
    color: {p.TEXT_DIM};
    background: transparent;
}}
QLabel#detailsLabel {{
    background-color: {p.SURFACE};
}}
QLabel#fieldLabel {{
    color: {p.TEXT_DIM};
    background: transparent;
}}

/* ---- buttons ------------------------------------------------------ */

QPushButton, QToolButton {{
    background-color: {p.RAISED};
    border: 1px solid {p.BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 14px;
    color: {p.TEXT};
    min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{
    background-color: {p.RAISED_HOVER};
    border-color: {p.ACCENT};
}}
QPushButton:pressed, QToolButton:pressed {{
    background-color: {p.RAISED_PRESSED};
}}
QPushButton:disabled, QToolButton:disabled {{
    background-color: {p.SURFACE};
    color: {p.TEXT_FAINT};
    border-color: {p.BORDER};
}}
QToolButton::menu-indicator {{
    image: none;
    width: 0px;
}}

QPushButton#primaryBtn {{
    background-color: {p.ACCENT_DIM};
    border: 1px solid {p.ACCENT};
    color: {p.PRIMARY_TEXT};
    font-weight: 600;
    padding: 8px 22px;
}}
QPushButton#primaryBtn:hover {{
    background-color: {p.PRIMARY_HOVER};
}}
QPushButton#primaryBtn:disabled {{
    background-color: {p.SURFACE};
    border-color: {p.BORDER};
    color: {p.TEXT_FAINT};
}}

QPushButton#dangerBtn {{
    background-color: {p.DANGER_BG};
    border-color: {p.DANGER_BORDER};
    color: {p.DANGER_TEXT};
}}
QPushButton#dangerBtn:hover {{
    background-color: {p.DANGER_HOVER};
}}

QPushButton#linkBtn {{
    background: transparent;
    border: none;
    color: {p.TEXT_DIM};
    padding: 0 6px;
    font-size: 8pt;
}}
QPushButton#linkBtn:hover {{
    color: {p.ACCENT};
}}

QPushButton#miniBtn {{
    padding: 3px 10px;
    min-height: 16px;
    font-size: 9pt;
}}

/* the All / Needs action / Installed filter */
QPushButton#chip {{
    background-color: transparent;
    border: 1px solid {p.BORDER_STRONG};
    border-radius: 14px;
    padding: 4px 12px;
    color: {p.TEXT_DIM};
    min-height: 18px;
}}
QPushButton#chip:hover {{
    border-color: {p.ACCENT};
    color: {p.TEXT};
}}
QPushButton#chip:checked {{
    background-color: {p.ACCENT_BG};
    border-color: {p.ACCENT};
    color: {p.ACCENT};
    font-weight: 600;
}}

/* ---- inputs ------------------------------------------------------- */

QLineEdit {{
    background-color: {p.SURFACE};
    border: 1px solid {p.BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 10px;
    color: {p.TEXT};
    min-height: 20px;
    selection-background-color: {p.ACCENT_DIM};
    selection-color: #ffffff;
}}
QLineEdit:focus {{
    border-color: {p.ACCENT};
}}

QComboBox {{
    background-color: {p.RAISED};
    border: 1px solid {p.BORDER_STRONG};
    border-radius: 6px;
    padding: 5px 10px;
    color: {p.TEXT};
    min-height: 20px;
}}
QComboBox:hover, QComboBox:focus {{
    border-color: {p.ACCENT};
}}
QComboBox:disabled {{
    color: {p.TEXT_FAINT};
    background-color: {p.SURFACE};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.RAISED};
    border: 1px solid {p.BORDER_STRONG};
    selection-background-color: {p.ACCENT_DIM};
    selection-color: #ffffff;
    color: {p.TEXT};
}}

QCheckBox {{
    color: {p.TEXT};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator, QTreeView::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.BORDER_STRONG};
    border-radius: 4px;
    background-color: {p.SURFACE};
}}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{
    border-color: {p.ACCENT};
}}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{
    background-color: {p.ACCENT_DIM};
    border-color: {p.ACCENT};
    image: url({check_icon});
}}
QTreeView::indicator:indeterminate {{
    background-color: {p.ACCENT_DIM};
    border-color: {p.ACCENT};
    image: url({dash_icon});
}}

/* ---- the component tree -------------------------------------------- */

QTreeWidget {{
    background-color: {p.SURFACE};
    alternate-background-color: {p.SURFACE};
    border: 1px solid {p.BORDER};
    border-radius: 8px;
    color: {p.TEXT};
    show-decoration-selected: 0;
}}
QTreeWidget::item {{
    padding: 5px 4px;
    border: none;
}}
QTreeWidget::item:hover {{
    background-color: {p.SURFACE_ALT};
}}
QTreeWidget::item:selected {{
    background-color: {p.ACCENT_BG};
    color: {p.TEXT};
}}
QTreeView::branch {{
    background: transparent;
    border-image: none;
    image: none;
}}
QTreeView::branch:selected {{
    background-color: {p.ACCENT_BG};
    image: none;
    border-image: none;
}}
QTreeView::branch:closed:has-children {{
    image: url({chevron_right});
}}
QTreeView::branch:open:has-children {{
    image: url({chevron_down});
}}
QTreeView::branch:selected:closed:has-children {{
    image: url({chevron_right});
}}
QTreeView::branch:selected:open:has-children {{
    image: url({chevron_down});
}}

QHeaderView::section {{
    background-color: {p.SURFACE};
    color: {p.TEXT_DIM};
    padding: 8px 8px;
    border: none;
    border-bottom: 1px solid {p.BORDER_STRONG};
    font-weight: 600;
    font-size: 9pt;
}}

/* ---- log / tabs ----------------------------------------------------- */

QTextEdit#logView {{
    background-color: {p.LOG_BG};
    border: none;
    border-radius: 0 0 8px 8px;
    color: {p.TEXT_DIM};
    font-family: {FONT_MONO};
    font-size: 9pt;
    padding: 6px;
}}

QTabWidget::pane {{
    border: 1px solid {p.BORDER};
    border-radius: 8px;
    background-color: {p.SURFACE};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {p.TEXT_DIM};
    padding: 7px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
}}
QTabBar::tab:hover {{
    color: {p.TEXT};
}}
QTabBar::tab:selected {{
    color: {p.ACCENT};
    border-bottom: 2px solid {p.ACCENT};
}}
QWidget#tabPage {{
    background-color: {p.SURFACE};
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
    background-color: {p.BG};
    border: 1px solid {p.BORDER};
    border-radius: 5px;
    text-align: center;
    color: {p.TEXT};
    min-height: 16px;
    max-height: 16px;
}}
QProgressBar::chunk {{
    background-color: {p.ACCENT};
    border-radius: 4px;
}}

QStatusBar {{
    background-color: {p.BG};
    color: {p.TEXT_DIM};
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
    background-color: {p.BORDER_STRONG};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {p.SCROLL_HOVER};
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
    background-color: {p.BORDER_STRONG};
    border-radius: 4px;
    min-width: 30px;
}}

QMenu {{
    background-color: {p.RAISED};
    border: 1px solid {p.BORDER_STRONG};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 5px;
    color: {p.TEXT};
}}
QMenu::item:selected {{
    background-color: {p.ACCENT_DIM};
    color: #ffffff;
}}
QMenu::item:disabled {{
    color: {p.TEXT_FAINT};
}}
QMenu::separator {{
    height: 1px;
    background: {p.BORDER_STRONG};
    margin: 5px 8px;
}}
"""
