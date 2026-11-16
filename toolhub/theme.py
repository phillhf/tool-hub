"""Farben und Schriften für helles und dunkles Design."""
import tkinter.font as tkfont
import zlib

try:
    import winreg
except ImportError:
    winreg = None

LIGHT = {
    "bg": "#f1f0ec", "panel": "#fbfaf8", "line": "#d9d6cf", "text": "#16171a", "muted": "#5f6268",
    "faint": "#8f9197", "hover": "#e7e5df", "input": "#e9e7e2",
    "primary_bg": "#16171a", "primary_fg": "#ffffff", "primary_hover": "#383a40",
    "second_bg": "#fbfaf8", "second_hover": "#ebe9e4", "select_bg": "#16171a", "select_fg": "#ffffff",
    "track": "#e2dfd8", "bar": "#6d4ee0",
    "update": ("#8a5a00", "#fbefd2"), "ok": ("#17703a", "#dcf2e2"), "install": ("#1d55b8", "#e0eafc"),
    "busy": ("#5b3cc4", "#ebe5fc"), "error": ("#b42318", "#fde4e1"), "private": ("#5f6268", "#e9e7e2"),
    "banner_bg": "#e0eafc", "banner_fg": "#1d55b8",
}
DARK = {
    "bg": "#0f1012", "panel": "#15161a", "line": "#2b2d33", "text": "#f1f1f2", "muted": "#a2a4aa",
    "faint": "#6c6e75", "hover": "#1e2025", "input": "#0a0b0d",
    "primary_bg": "#f1f1f2", "primary_fg": "#111214", "primary_hover": "#cfd0d3",
    "second_bg": "#15161a", "second_hover": "#22242a", "select_bg": "#f1f1f2", "select_fg": "#111214",
    "track": "#2b2d33", "bar": "#9b7bff",
    "update": ("#f2b33d", "#2b2210"), "ok": ("#4ccb76", "#10261a"), "install": ("#6aa8ff", "#0f1d33"),
    "busy": ("#b49aff", "#211a37"), "error": ("#ff8078", "#341515"), "private": ("#a2a4aa", "#1e2025"),
    "banner_bg": "#0f1d33", "banner_fg": "#9cc4ff",
}
TOOL_COLORS = ["#2f6fed", "#e5533d", "#8b5cf6", "#f0a020", "#14a38b", "#e0457b", "#5cb83f", "#3b8ec4",
               "#d9661f", "#7a62d6"]


def system_is_dark():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def palette(mode):
    dark = system_is_dark() if mode == "auto" else mode == "dark"
    colors = dict(DARK if dark else LIGHT)
    colors["dark"] = dark
    return colors


def tool_color(name):
    return TOOL_COLORS[zlib.crc32(name.lower().encode()) % len(TOOL_COLORS)]


class Fonts:
    def __init__(self, root):
        families = set(tkfont.families(root))
        ui = "Segoe UI" if "Segoe UI" in families else "TkDefaultFont"
        bold = "Segoe UI Semibold" if "Segoe UI Semibold" in families else ui
        mono = next((f for f in ("Cascadia Mono", "Consolas") if f in families), "TkFixedFont")
        self.icons = "Segoe Fluent Icons" if "Segoe Fluent Icons" in families else (
            "Segoe MDL2 Assets" if "Segoe MDL2 Assets" in families else None)
        self.brand = (bold, 15)
        self.title = (bold, 13)
        self.row_title = (bold, 11)
        self.text = (ui, 10)
        self.small = (ui, 9)
        self.label = (mono, 8)
        self.label_bold = (mono, 8, "bold")
        self.button = (mono, 9, "bold")
        self.version = (mono, 10)
        self.initials = (bold, 15)
