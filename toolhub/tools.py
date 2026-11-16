"""Welche Tools es gibt, welche installiert sind und was man mit ihnen tun kann."""
import glob
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import SELF_REPO, registry, winrun

SETUP_RE = re.compile(r"^(?P<prefix>.+?)-Setup-v?(?P<version>\d+(?:\.\d+)*)\.exe$", re.IGNORECASE)
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
# Einträge im Startmenü oder Installationsordner, die das Tool nicht öffnen
NOT_A_START = ("deinstall", "uninstall", "beenden", "stopp", "protokoll", "konfiguration", "update",
               "zertifikat", "passwort", "einrichten", "import", "hilfe", "readme", "lizenz", "license")
INNO_ERRORS = {
    1: "Das Setup konnte nicht starten.",
    3: "Das Setup wurde unerwartet unterbrochen.",
    4: "Das Setup ist mit einem schweren Fehler abgebrochen.",
    5: "Die Installation ist fehlgeschlagen.",
    6: "Das Setup wurde von außen beendet.",
    7: "Die Vorbereitung der Installation ist fehlgeschlagen.",
    8: "Die Vorbereitung der Installation ist fehlgeschlagen, ein Neustart ist nötig.",
}


class ActionCancelled(Exception):
    pass


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower().replace("ö", "oe").replace("ä", "ae").replace("ü", "ue"))


def parse_version(text):
    return tuple(int(n) for n in re.findall(r"\d+", text or "")) or (0,)


def is_newer(latest, installed):
    a, b = parse_version(latest), parse_version(installed)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def strip_version(name):
    return re.sub(r"\s+(version\s+)?v?\d+(\.\d+)*\s*$", "", name, flags=re.IGNORECASE)


@dataclass
class Tool:
    repo: str
    title: str
    description: str
    private: bool
    html_url: str
    latest: str
    asset: dict
    prefix: str
    installed: registry.Installed | None = None
    extra_installs: list = field(default_factory=list)

    @property
    def update_available(self):
        return bool(self.installed) and is_newer(self.latest, self.installed.version)


def pick_setup(repo, assets):
    """Das Windows-Setup eines Releases; passt der Dateiname zum Repo, gewinnt es."""
    candidates = []
    for asset in assets or []:
        match = SETUP_RE.match(asset.get("name", ""))
        if match:
            candidates.append((match.group("prefix"), asset))
    if not candidates:
        return None, None
    key = norm(repo)
    for prefix, asset in candidates:
        if norm(prefix) == key:
            return prefix, asset
    for prefix, asset in candidates:
        if norm(prefix).startswith(key) or key.startswith(norm(prefix)):
            return prefix, asset
    return candidates[0]


def make_title(repo, prefix):
    """„Music-Renamer“ → „Music Renamer“; „LogistikMap“ aus Repo logistik-map → „Logistik Map“."""
    if not re.search(r"[-_ ]", prefix) and norm(prefix) == norm(repo) and re.search(r"[-_]", repo):
        return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]+", repo))
    return re.sub(r"[-_]+", " ", prefix)


RECHECK_SECONDS = 6 * 3600


def _still_without_setup(seen, pushed_at, now=None):
    """Repo ohne Setup überspringen – aber nur bis zum nächsten Push und höchstens 6 Stunden lang.

    Ein Release kann auch ohne Push dazukommen (z. B. von Hand oder per Workflow für einen alten Tag)."""
    if not isinstance(seen, dict) or seen.get("pushed_at") != pushed_at:
        return False
    return (now or time.time()) - seen.get("checked", 0) < RECHECK_SECONDS


def discover(api, no_setup):
    """Liefert (Tools, Release des Tool-Hub selbst). no_setup merkt sich Repos ohne Setup bis zum nächsten Push."""
    repos = [r for r in api.repos() if not r.get("archived")]
    own = None
    todo = []
    for repo in repos:
        name = repo["name"]
        if name.lower() == SELF_REPO:
            own = repo
        elif not _still_without_setup(no_setup.get(name), repo.get("pushed_at")):
            todo.append(repo)

    def fetch(repo):
        return repo, api.latest_release(repo["name"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, todo))
        own_release = pool.submit(api.latest_release, own["name"]).result() if own else None

    tools = []
    for repo, release in results:
        name = repo["name"]
        prefix, asset = pick_setup(name, (release or {}).get("assets"))
        if not asset:
            no_setup[name] = {"pushed_at": repo.get("pushed_at"), "checked": time.time()}
            continue
        no_setup.pop(name, None)
        tools.append(Tool(
            repo=name,
            title=make_title(name, prefix),
            description=repo.get("description") or "",
            private=bool(repo.get("private")),
            html_url=repo.get("html_url", ""),
            latest=(release.get("tag_name") or "").lstrip("vV"),
            asset={k: asset.get(k) for k in ("name", "url", "digest", "size")},
            prefix=prefix,
        ))
    tools.sort(key=lambda t: t.title.lower())
    return tools, own_release


def match_installed(tool, entries, learned_key=None):
    """Ordnet die installierten Einträge einem Tool zu. Liefert (Haupteintrag, weitere Installationen)."""
    if learned_key:
        for entry in entries:
            if entry.key == learned_key:
                return entry, [e for e in _hits(tool, entries) if e is not entry]
    hits = _hits(tool, entries)
    if not hits:
        return None, []
    keys = {norm(tool.repo), norm(tool.prefix)}
    hits.sort(key=lambda e: norm(strip_version(e.name)) not in keys)
    return hits[0], hits[1:]


def _hits(tool, entries):
    keys = {norm(tool.repo), norm(tool.prefix)}
    return [e for e in entries if any(norm(strip_version(e.name)).startswith(k) for k in keys)]


def _exe_path(command):
    match = re.match(r'\s*"([^"]+)"|\s*(\S+)', command or "")
    return (match.group(1) or match.group(2)) if match else ""


def _start_files(folder, patterns):
    files = []
    for pattern in patterns:
        files.extend(glob.glob(os.path.join(glob.escape(folder), pattern)))
    return [f for f in files if not any(word in norm(os.path.basename(f)) for word in map(norm, NOT_A_START))]


def _start_menu_dirs():
    dirs = []
    for var in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(var)
        if base:
            dirs.append(os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs"))
    return dirs


def _rank(path, title):
    stem = norm(os.path.splitext(os.path.basename(path))[0])
    return (
        0 if ("oeffnen" in stem or "starten" in stem or stem == norm(title)) else 1,
        0 if path.lower().endswith(".url") else 1,
        len(stem),
    )


def start_target(entry, title, start_menu_dirs=None):
    """Was „Starten“ öffnet: Weblink, Verknüpfung oder Programm des installierten Tools."""
    location = entry.location.rstrip("\\/")
    if location and os.path.isdir(location):
        folders = [location, os.path.join(location, "setup")]
        links = [f for folder in folders for f in _start_files(folder, ("*.url", "*.lnk"))]
        if links:
            return min(links, key=lambda p: _rank(p, title))
    icon = re.sub(r",\s*-?\d+$", "", entry.icon.strip()).strip('"')
    if icon.lower().endswith(".exe") and not os.path.basename(icon).lower().startswith("unins") and os.path.isfile(icon):
        return icon
    key = norm(strip_version(entry.name)) or norm(title)
    menu = []
    for base in start_menu_dirs if start_menu_dirs is not None else _start_menu_dirs():
        for path in glob.glob(os.path.join(glob.escape(base), "**", "*.lnk"), recursive=True) + \
                glob.glob(os.path.join(glob.escape(base), "**", "*.url"), recursive=True):
            stem = norm(os.path.splitext(os.path.basename(path))[0])
            folder = norm(os.path.basename(os.path.dirname(path)))
            if (key in stem or folder == key) and not any(norm(w) in stem for w in NOT_A_START):
                menu.append(path)
    if menu:
        return min(menu, key=lambda p: _rank(p, title))
    if location and os.path.isdir(location):
        for pattern in ("*.bat", "*.exe"):
            found = [f for f in _start_files(location, (pattern,)) if not os.path.basename(f).lower().startswith("unins")]
            if len(found) == 1:
                return found[0]
    return None


# ---- Aktionen (laufen im Hintergrund-Thread)

def install(api, tool, folder, silent, learned, progress=lambda text, percent=None: None):
    progress(f"{tool.title}: lade {tool.asset['name']} …", 0)
    path = api.download(tool.asset, folder, lambda p: progress(f"{tool.title}: lade {tool.asset['name']} …", p))
    try:
        before = {e.key for e in registry.entries()}
        progress(f"{tool.title}: Setup läuft …", None)
        try:
            code = winrun.run_and_wait(path, SILENT if silent else [])
        except winrun.Cancelled as exc:
            raise ActionCancelled("Administratorrechte wurden nicht erteilt.") from exc
        if code == 2:
            raise ActionCancelled("Das Setup wurde abgebrochen.")
        if code:
            raise RuntimeError(INNO_ERRORS.get(code, f"Das Setup endete mit Fehlercode {code}."))
        new = [e for e in registry.entries() if e.key not in before]
        if new:
            matched, _ = match_installed(tool, new)
            learned[tool.repo] = (matched or new[0]).key
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def uninstall(tool, learned, progress=lambda text, percent=None: None, wait=120):
    entry = tool.installed
    exe = _exe_path(entry.uninstall)
    if not exe or not os.path.isfile(exe):
        raise RuntimeError("Das Deinstallationsprogramm wurde nicht gefunden.")
    progress(f"{tool.title}: wird deinstalliert …", None)
    try:
        code = winrun.run_and_wait(exe, SILENT)
    except winrun.Cancelled as exc:
        raise ActionCancelled("Administratorrechte wurden nicht erteilt.") from exc
    if code:
        raise RuntimeError(f"Die Deinstallation endete mit Fehlercode {code}.")
    # Das Inno-Deinstallationsprogramm läuft als Kopie weiter: warten, bis der Eintrag weg ist
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if all(e.key != entry.key for e in registry.entries()):
            learned.pop(tool.repo, None)
            return
        time.sleep(1)
    raise RuntimeError("Die Deinstallation ist nicht fertig geworden.")


def start(tool):
    target = start_target(tool.installed, tool.title)
    if not target:
        raise RuntimeError("Für dieses Tool ist kein Startpunkt bekannt. Über „Ordner“ lässt sich der "
                           "Installationsordner öffnen.")
    os.startfile(target)
