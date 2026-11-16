"""Liest die von Inno Setup angelegten Einträge unter „Apps & Features“."""
from dataclasses import dataclass

try:
    import winreg
except ImportError:  # nicht Windows: keine installierten Tools
    winreg = None

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass(frozen=True)
class Installed:
    key: str
    name: str
    version: str
    location: str
    icon: str
    uninstall: str
    machine_wide: bool = False


def _value(key, name):
    try:
        return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return ""


def entries():
    if winreg is None:
        return []
    views = [
        (winreg.HKEY_CURRENT_USER, 0, False),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, True),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, True),
    ]
    found, seen = [], set()
    for hive, view, machine in views:
        try:
            root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if not sub.lower().endswith("_is1") or (machine, sub) in seen:
                    continue
                try:
                    with winreg.OpenKey(root, sub) as key:
                        entry = Installed(sub, _value(key, "DisplayName"), _value(key, "DisplayVersion"),
                                          _value(key, "InstallLocation"), _value(key, "DisplayIcon"),
                                          _value(key, "UninstallString"), machine)
                except OSError:
                    continue
                if entry.name:
                    seen.add((machine, sub))
                    found.append(entry)
    return found
