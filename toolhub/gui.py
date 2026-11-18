"""Launcher-Oberfläche: Kacheln oder Tabelle, Filter, Suche, Fortschritt je Tool, Symbol im Infobereich."""
import collections
import ctypes
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import APP_NAME, OWNER, SELF_REPO, __version__, config, github, registry, secret, theme, tools, tray, winrun
from .widgets import Bar, FlatButton, Link, Pill, ToolIcon

TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
CHECK_EVERY_MS = 6 * 3600 * 1000
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]
FILTERS = [("all", "ALLE"), ("installed", "INSTALLIERT"), ("updates", "UPDATES"), ("missing", "NICHT INSTALLIERT")]
log = logging.getLogger("toolhub")


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "installer"))
    return os.path.join(base, name)


def german_date(iso):
    try:
        year, month, day = (int(x) for x in iso.split("-"))
        return f"{day}. {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return ""


def megabytes(n):
    return f"{n / 1048576:.0f} MB" if n >= 10 * 1048576 else f"{n / 1048576:.1f} MB".replace(".", ",")


class Job:
    def __init__(self, tool, kind):
        self.tool, self.kind = tool, kind
        self.phase, self.done, self.total = "queued", 0, 0
        self.cancel = threading.Event()


class App:
    def __init__(self, root, start_hidden=False):
        self.root = root
        root.title(APP_NAME)
        root.geometry(config.load("settings.json", {}).get("geometry", "1060x720"))
        root.minsize(560, 420)
        try:
            root.iconbitmap(default=resource("app.ico"))
        except tk.TclError:
            pass

        self._clean_downloads()
        self.settings = config.load("settings.json", {})
        self.settings.setdefault("theme", "auto")
        self.settings.setdefault("view", "grid")
        self.settings.setdefault("close_to_tray", True)
        self.learned = config.load("learned.json", {})
        self.cache = config.load("cache.json", {})
        self.no_setup = self.cache.setdefault("no_setup", {})
        self.api = github.Api(secret.load_token(), cache=self.cache.setdefault("http", {}))
        self.tools, self.own_release = [], None
        self.loading, self.load_error, self.last_check = False, "", None
        self.jobs, self.job = collections.deque(), None
        self.notified = set(self.settings.get("notified", []))
        self.filter = "all"
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._render())
        self.events = queue.Queue()
        self.fonts = theme.Fonts(root)
        self._columns = 0
        self._live = {}
        self.status_text = ""
        self._reload = False

        self.tray = None
        try:
            self.tray = tray.Tray(resource("app.ico"), APP_NAME, [
                ("Tool-Hub öffnen", self.show), ("Nach Updates suchen", self.refresh), None, ("Beenden", self.quit)],
                self.show, lambda fn: self._post(lambda _: fn()))
        except (OSError, AttributeError):
            log.exception("Infobereich nicht verfügbar")

        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._poll)
        root.after(60_000, self._tick)
        root.after(CHECK_EVERY_MS, self._periodic)
        if start_hidden and self.tray and self.tray.ok:
            root.withdraw()
        self.refresh()

    @staticmethod
    def _clean_downloads():
        """Reste früherer Downloads entfernen, z. B. das Setup der eigenen Aktualisierung."""
        folder = config.downloads_dir()
        for name in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass  # gerade in Benutzung – beim nächsten Start

    # ================= Aufbau

    def _build(self):
        for child in self.root.winfo_children():
            child.destroy()
        t = self.t = theme.palette(self.settings["theme"])
        f = self.fonts
        self.root.configure(bg=t["bg"])
        self._dark_titlebar(t["dark"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Hub.Vertical.TScrollbar", background=t["line"], troughcolor=t["bg"], bordercolor=t["bg"],
                        arrowcolor=t["muted"], lightcolor=t["line"], darkcolor=t["line"], gripcount=0)
        style.map("Hub.Vertical.TScrollbar", background=[("active", t["faint"])])

        # Kopfzeile
        head = tk.Frame(self.root, bg=t["panel"])
        head.pack(fill="x")
        tk.Frame(self.root, bg=t["line"], height=1).pack(fill="x")
        tk.Label(head, text="TOOL-HUB", font=f.brand, bg=t["panel"], fg=t["text"]).pack(side="left", padx=(20, 14), pady=10)
        tk.Frame(head, bg=t["line"], width=1).pack(side="left", fill="y")
        tk.Label(head, text=" LAUNCHER ", font=f.label_bold, bg=t["select_bg"], fg=t["select_fg"]).pack(side="left", padx=(14, 8))
        tk.Label(head, text=f"GITHUB.COM/{OWNER.upper()}", font=f.label, bg=t["panel"], fg=t["muted"]).pack(side="left")

        def head_button(text, command, font=None):
            tk.Frame(head, bg=t["line"], width=1).pack(side="right", fill="y")
            b = FlatButton(head, t, f, text, command, kind="ghost", font=font, padx=14, pady=10)
            b.configure(highlightthickness=0)
            b.pack(side="right")
            return b

        icon = f.icons
        head_button("" if icon else "⚙", self._settings_menu, (icon, 12) if icon else None)
        self.refresh_btn = head_button("" if icon else "⟳", self.refresh, (icon, 12) if icon else None)
        tk.Frame(head, bg=t["line"], width=1).pack(side="right", fill="y")
        views = tk.Frame(head, bg=t["panel"])
        views.pack(side="right", padx=12)
        for key, label in (("grid", "RASTER"), ("table", "TABELLE")):
            FlatButton(views, t, f, label, lambda k=key: self._set_view(k),
                       kind="selected" if self.settings["view"] == key else "ghost", padx=8, pady=2,
                       font=f.label_bold).pack(side="left", padx=2)

        # Hinweis auf neue Tool-Hub-Version
        self.banner = tk.Frame(self.root, bg=t["banner_bg"])
        self.banner_label = tk.Label(self.banner, bg=t["banner_bg"], fg=t["banner_fg"], font=f.small)
        self.banner_label.pack(side="left", padx=20, pady=6)
        self.banner_btn = FlatButton(self.banner, t, f, "AKTUALISIEREN UND NEU STARTEN", self.self_update,
                                     kind="primary", pady=3)
        self.banner_btn.pack(side="right", padx=20, pady=5)

        # Filter, Suche, Alle aktualisieren
        bar = tk.Frame(self.root, bg=t["bg"])
        bar.pack(fill="x", padx=20, pady=(16, 10))
        self.bar = bar
        self.filter_frame = tk.Frame(bar, bg=t["line"])
        self.filter_frame.pack(side="left")
        self.update_all_holder = tk.Frame(bar, bg=t["bg"])
        self.update_all_holder.pack(side="right")
        self.search_row = tk.Frame(self.root, bg=t["bg"])
        search = self.search_box = tk.Frame(self.root, bg=t["input"], highlightthickness=1, highlightbackground=t["line"])
        search.pack(in_=bar, side="right", padx=10)
        self._narrow = False
        tk.Label(search, text="" if icon else "⌕", font=(icon, 10) if icon else f.text, bg=t["input"],
                 fg=t["faint"]).pack(side="left", padx=(8, 0))
        entry = tk.Entry(search, textvariable=self.search, width=22, font=f.text, bg=t["input"], fg=t["text"],
                         insertbackground=t["text"], relief="flat", bd=0)
        entry.pack(side="left", padx=8, pady=6)
        self.root.bind("<Control-f>", lambda e: entry.focus_set())
        entry.bind("<Escape>", lambda e: self.search.set(""))

        # Liste
        holder = tk.Frame(self.root, bg=t["bg"])
        holder.pack(fill="both", expand=True, padx=(20, 6))
        self.canvas = tk.Canvas(holder, bg=t["bg"], highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview, style="Hub.Vertical.TScrollbar")
        self.list = tk.Frame(self.canvas, bg=t["bg"])
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self.canvas.bind("<Configure>", self._resized)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y", padx=(6, 0))
        self.root.bind_all("<MouseWheel>", self._wheel)

        # Fußzeile
        tk.Frame(self.root, bg=t["line"], height=1).pack(fill="x")
        foot = tk.Frame(self.root, bg=t["panel"])
        foot.pack(fill="x")
        self.foot_left = tk.Label(foot, font=f.label, bg=t["panel"], fg=t["faint"], anchor="w")
        self.foot_left.pack(side="left", padx=20, pady=7)
        tk.Label(foot, text="WINDOWS", font=f.label, bg=t["panel"], fg=t["faint"]).pack(side="right", padx=(10, 20))
        self.token_link = Link(foot, t, f, "", self.token_dialog)
        self.token_link.pack(side="right", padx=10)
        Link(foot, t, f, "GITHUB ↗", lambda: webbrowser.open(f"https://github.com/{OWNER}")).pack(side="right", padx=10)
        self._render()

    def _dark_titlebar(self, dark):
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass

    def _wheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is not None and str(widget).startswith(str(self.canvas)):
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _resized(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        narrow = self.root.winfo_width() < 900
        if narrow != self._narrow:
            # Schmales Fenster: Suche in eine eigene Zeile, damit die Filter Platz haben
            self._narrow = narrow
            self.search_box.pack_forget()
            if narrow:
                self.search_row.pack(fill="x", padx=20, pady=(0, 10), after=self.bar)
                self.search_box.pack(in_=self.search_row, side="left", fill="x", expand=True)
            else:
                self.search_row.pack_forget()
                self.search_box.pack(in_=self.bar, side="right", padx=10, after=self.update_all_holder)
        if self.settings["view"] == "grid" and self._grid_columns(event.width) != self._columns:
            self._render()

    @staticmethod
    def _grid_columns(width):
        return max(1, min(4, width // 330))

    # ================= Hintergrund

    def _poll(self):
        try:
            while True:
                fn, arg = self.events.get_nowait()
                fn(arg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _post(self, fn, arg=None):
        self.events.put((fn, arg))

    def _thread(self, work, done, failed):
        def run():
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 – jeder Fehler gehört in die Oberfläche
                if not isinstance(exc, tools.ActionCancelled):
                    log.exception("Fehler")
                self._post(failed, exc)
            else:
                self._post(done, result)
        threading.Thread(target=run, daemon=True).start()

    def _save(self):
        try:
            config.save("cache.json", self.cache)
            config.save("learned.json", self.learned)
            self.settings["notified"] = sorted(self.notified)
            config.save("settings.json", self.settings)
        except OSError:
            log.exception("Speichern fehlgeschlagen")

    # ================= Daten laden

    def refresh(self, quiet=False):
        if self.loading:
            self._reload = True  # z. B. neuer Token während des Ladens: danach noch einmal
            return
        if self.job:
            return
        self.loading, self.load_error = True, ""
        self.api.offline = False
        if not quiet:
            self.no_setup.clear()  # von Hand neu laden: auch Repos ohne Setup sofort neu prüfen
            self.status_text = "SUCHE NACH TOOLS …"
            self._update_chrome()
            if not self.tools:
                self._render()
        self._thread(lambda: tools.discover(self.api, self.no_setup), self._loaded, self._load_failed)

    def _again(self):
        if self._reload:
            self._reload = False
            self.refresh()
            return True
        return False

    def _loaded(self, result):
        self.loading = False
        if self._again():
            return
        self.tools, self.own_release = result
        self.last_check = time.time()
        self.status_text = "OFFLINE · ZULETZT GELADENER STAND" if self.api.offline else ""
        self._attach_installed()
        self._save()
        self._render()
        self._notify_updates()

    def _load_failed(self, exc):
        self.loading = False
        if self._again():
            return
        self.load_error = str(exc)
        self.status_text = ""
        self._render()

    def _attach_installed(self):
        entries = registry.entries()
        for tool in self.tools:
            tool.installed, tool.extra_installs = tools.match_installed(tool, entries, self.learned.get(tool.repo))

    def _periodic(self):
        self.refresh(quiet=True)
        self.root.after(CHECK_EVERY_MS, self._periodic)

    def _tick(self):
        self._update_chrome()
        self.root.after(60_000, self._tick)

    def _notify_updates(self):
        current = {f"{t.repo}@{t.latest}" for t in self.tools if t.update_available}
        new = current - self.notified
        self.notified = current
        self._save()
        if new and self.tray and not self.root.winfo_viewable():
            names = ", ".join(t.title for t in self.tools if f"{t.repo}@{t.latest}" in new)
            self.tray.notify(f"{len(new)} Update{'s' if len(new) > 1 else ''} verfügbar", names)

    # ================= Darstellung

    def _counts(self):
        return {
            "all": len(self.tools),
            "installed": sum(1 for t in self.tools if t.installed),
            "updates": sum(1 for t in self.tools if t.update_available),
            "missing": sum(1 for t in self.tools if not t.installed),
        }

    def _visible(self):
        term = self.search.get().strip().lower()
        keep = {
            "all": lambda t: True,
            "installed": lambda t: t.installed,
            "updates": lambda t: t.update_available,
            "missing": lambda t: not t.installed,
        }[self.filter]
        return [t for t in self.tools if keep(t) and (not term or term in f"{t.title} {t.repo} {t.description}".lower())]

    def _update_chrome(self):
        t, f = self.t, self.fonts
        counts = self._counts()
        for child in self.filter_frame.winfo_children():
            child.destroy()
        for key, label in FILTERS:
            selected = key == self.filter
            cell = tk.Frame(self.filter_frame, bg=t["select_bg"] if selected else t["bg"], cursor="hand2")
            cell.pack(side="left", padx=(0 if key == "all" else 1, 0), pady=1)
            fg = t["select_fg"] if selected else t["muted"]
            parts = [tk.Label(cell, text=label, font=f.label_bold, bg=cell["bg"], fg=fg)]
            tone = t["update"][0] if key == "updates" and counts[key] and not selected else (fg if selected else t["faint"])
            parts.append(tk.Label(cell, text=str(counts[key]), font=f.label_bold, bg=cell["bg"], fg=tone))
            parts[0].pack(side="left", padx=(12, 6), pady=7)
            parts[1].pack(side="left", padx=(0, 12))
            for w in (cell, *parts):
                w.bind("<ButtonRelease-1>", lambda e, k=key: self._set_filter(k))
        for child in self.update_all_holder.winfo_children():
            child.destroy()
        pending = sum(1 for tool in self.tools if tool.update_available and not self._job_for(tool))
        FlatButton(self.update_all_holder, t, f, f"ALLE AKTUALISIEREN ({pending})",
                   self.update_all if pending else None, kind="primary" if pending else "secondary").pack()

        if self.loading:
            left = self.status_text or "SUCHE NACH TOOLS …"
        elif self.last_check:
            minutes = int((time.time() - self.last_check) // 60)
            left = "ZULETZT GEPRÜFT " + ("GERADE EBEN" if minutes < 1 else f"VOR {minutes} MIN" if minutes < 120
                                         else f"VOR {minutes // 60} STD")
            if self.status_text:
                left += " · " + self.status_text
        else:
            left = self.status_text
        self.foot_left.configure(text=f"{left}   ·   TOOL-HUB {__version__}")
        self.token_link.configure(text="🔓 PRIVATE TOOLS FREIGESCHALTET" if self.api.token
                                  else "🔒 PRIVATE TOOLS FREISCHALTEN …")
        own = self._own_setup()
        if own and getattr(sys, "frozen", False):
            self.banner_label.configure(text=f"Tool-Hub {own[0]} ist da (installiert: {__version__}).")
            self.banner.pack(fill="x", after=self.root.winfo_children()[1])
        else:
            self.banner.pack_forget()

    def _render(self):
        if not hasattr(self, "list"):
            return
        self._update_chrome()
        self._live = {}
        for child in self.list.winfo_children():
            child.destroy()
        t, f = self.t, self.fonts
        visible = self._visible()
        if not visible:
            if self.loading:
                text = "Suche nach Tools …"
            elif self.load_error:
                text = self.load_error
            elif self.tools:
                text = "Keine Tools in dieser Ansicht."
            else:
                text = "Keine Tools gefunden."
            tk.Label(self.list, text=text, font=f.text, bg=t["bg"], fg=t["muted"]).pack(pady=60)
            if self.load_error:
                FlatButton(self.list, t, f, "ERNEUT VERSUCHEN", self.refresh).pack()
            return
        numbers = {tool.repo: i + 1 for i, tool in enumerate(self.tools)}
        if self.settings["view"] == "grid":
            self._columns = self._grid_columns(self.canvas.winfo_width() or 1000)
            for c in range(4):
                self.list.grid_columnconfigure(c, weight=1 if c < self._columns else 0, uniform="cards" if c < self._columns else "")
            for i, tool in enumerate(visible):
                card = self._card(tool, numbers[tool.repo])
                card.grid(row=i // self._columns, column=i % self._columns, sticky="nsew", padx=(0, 8), pady=(0, 8))
        else:
            self._columns = 0
            for c in range(4):
                self.list.grid_columnconfigure(c, weight=0, uniform="")
            self._table(visible)

    # ---- Kachel

    def _status(self, tool):
        job = self._job_for(tool)
        if job:
            if job.phase == "queued":
                return "In Warteschlange", "busy"
            return {"download": "Wird geladen …", "setup": "Wird installiert …",
                    "uninstall": "Wird deinstalliert …"}.get(job.phase, "Läuft …"), "busy"
        if tool.update_available:
            return "Update verfügbar", "update"
        if tool.installed:
            return "Installiert · aktuell", "ok"
        return "Bereit zur Installation", "install"

    def _version_line(self, tool):
        date = german_date(tool.published)
        if tool.update_available:
            text = f"{tool.installed.version} installiert → {tool.latest} veröffentlicht"
        else:
            text = f"Version {tool.latest}"
        if date:
            text += f" · {date}"
        if tool.extra_installs:
            text += f" · +{len(tool.extra_installs)} weitere Installation"
        return text

    def _primary(self, tool):
        if tool.update_available:
            return f"UPDATE AUF {tool.latest}", lambda: self._enqueue(tool, "update"), "primary"
        if tool.installed:
            return "ÖFFNEN", lambda: self.start(tool), "secondary"
        return "INSTALLIEREN", lambda: self._enqueue(tool, "install"), "primary"

    def _card(self, tool, number):
        t, f = self.t, self.fonts
        color = theme.tool_color(tool.repo)
        card = tk.Frame(self.list, bg=t["panel"], highlightthickness=1, highlightbackground=t["line"])
        top = tk.Frame(card, bg=t["panel"])
        top.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(top, text=f" {number:02d} ", font=f.label_bold, bg=color, fg="#ffffff").pack(side="left")
        if tool.private:
            tk.Label(top, text="  PRIVAT", font=f.label, bg=t["panel"], fg=t["faint"]).pack(side="left")
        Link(top, t, f, "GITHUB ↗", lambda: webbrowser.open(tool.html_url)).pack(side="right")
        tk.Frame(card, bg=t["line"], height=1).pack(fill="x", pady=(10, 0))

        body = tk.Frame(card, bg=t["panel"])
        body.pack(fill="both", expand=True, padx=16, pady=(14, 0))
        ToolIcon(body, f, tool.title, color).pack(side="left", anchor="n")
        text = tk.Frame(body, bg=t["panel"])
        text.pack(side="left", fill="x", expand=True, padx=(12, 0))
        tk.Label(text, text=tool.title, font=f.title, bg=t["panel"], fg=t["text"], anchor="w").pack(fill="x")
        description = tool.description if len(tool.description) <= 110 else tool.description[:107].rstrip() + " …"
        desc = tk.Label(text, text=description, font=f.small, bg=t["panel"], fg=t["muted"], anchor="nw",
                        justify="left", wraplength=220, height=3)
        desc.pack(fill="x")
        text.bind("<Configure>", lambda e: desc.configure(wraplength=max(120, e.width - 4)))

        label, tone = self._status(tool)
        status = tk.Frame(card, bg=t["panel"])
        status.pack(fill="x", padx=16, pady=(8, 0))
        Pill(status, t, f, label, tone).pack(side="left")
        tk.Label(card, text=self._version_line(tool), font=f.small, bg=t["panel"], fg=t["muted"], anchor="w"
                 ).pack(fill="x", padx=16, pady=(8, 0))

        actions = tk.Frame(card, bg=t["panel"])
        actions.pack(fill="x", padx=16, pady=(10, 16))
        self._actions(actions, tool)
        return card

    def _actions(self, parent, tool, compact=False):
        t, f = self.t, self.fonts
        job = self._job_for(tool)
        if job and job.phase != "queued":
            # Abbrechen geht nur während des Downloads; danach läuft das Setup selbst
            FlatButton(parent, t, f, "✕", (lambda: job.cancel.set()) if job.phase == "download" else None,
                       padx=10).pack(side="right", padx=(8, 0))
            line = tk.Frame(parent, bg=parent["bg"])
            line.pack(side="left", fill="x", expand=True)
            label = tk.Label(line, font=f.small, bg=parent["bg"], fg=t["text"], anchor="w", width=1)
            label.pack(fill="x")
            bar = Bar(line, t, width=60)
            bar.pack(fill="x", pady=(4, 0))
            self._live[tool.repo] = (label, bar, compact)
            self._paint_job(job)
            return
        if job:
            FlatButton(parent, t, f, "IN WARTESCHLANGE", None).pack(side="left", fill="x", expand=True)
            FlatButton(parent, t, f, "✕", lambda: self._dequeue(job), padx=10).pack(side="right", padx=(8, 0))
            return
        text, command, kind = self._primary(tool)
        FlatButton(parent, t, f, text, command, kind=kind, width=16 if compact else 0).pack(
            side="left", fill="x", expand=not compact)
        more = FlatButton(parent, t, f, "…", lambda: self._tool_menu(tool, more), padx=10)
        more.pack(side="right", padx=(8, 0))

    def _tool_menu(self, tool, widget):
        menu = self._menu()
        if tool.installed:
            menu.add_command(label="Öffnen", command=lambda: self.start(tool))
            menu.add_command(label="Ordner öffnen", command=lambda: self.open_folder(tool))
            menu.add_separator()
            menu.add_command(label="Neu installieren", command=lambda: self._enqueue(tool, "update"))
            menu.add_command(label="Deinstallieren …", command=lambda: self.uninstall(tool))
        else:
            menu.add_command(label="Installieren", command=lambda: self._enqueue(tool, "install"))
        menu.add_separator()
        menu.add_command(label="Release-Notizen", command=lambda: webbrowser.open(tool.release_url))
        menu.add_command(label="Auf GitHub ansehen", command=lambda: webbrowser.open(tool.html_url))
        menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def _menu(self):
        t = self.t
        return tk.Menu(self.root, tearoff=False, bg=t["panel"], fg=t["text"], activebackground=t["hover"],
                       activeforeground=t["text"], bd=1, relief="solid", font=self.fonts.text)

    # ---- Tabelle

    def _table(self, visible):
        t, f = self.t, self.fonts
        table = tk.Frame(self.list, bg=t["panel"], highlightthickness=1, highlightbackground=t["line"])
        table.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.list.grid_columnconfigure(0, weight=1)
        widths = (0, 24, 12, 12, 16, 0)
        heads = ("TOOL", "STATUS", "INSTALLIERT", "NEUESTE", "VERÖFFENTLICHT", "")
        for c, weight in enumerate((1, 0, 0, 0, 0, 0)):
            table.grid_columnconfigure(c, weight=weight)
        for c, text in enumerate(heads):
            tk.Label(table, text=text, font=f.label, bg=t["panel"], fg=t["faint"], anchor="w", width=widths[c] or None
                     ).grid(row=0, column=c, sticky="w", padx=(16 if c == 0 else 6, 6), pady=(12, 10))
        for r, tool in enumerate(visible, start=1):
            row = 2 * r
            tk.Frame(table, bg=t["line"], height=1).grid(row=row - 1, column=0, columnspan=6, sticky="ew")
            name = tk.Frame(table, bg=t["panel"])
            name.grid(row=row, column=0, sticky="w", padx=(16, 6), pady=10)
            ToolIcon(name, f, tool.title, theme.tool_color(tool.repo), size=34).pack(side="left")
            words = tk.Frame(name, bg=t["panel"])
            words.pack(side="left", padx=(10, 0))
            title = tool.title + ("  · privat" if tool.private else "")
            tk.Label(words, text=title, font=f.row_title, bg=t["panel"], fg=t["text"], anchor="w").pack(fill="x")
            short = tool.description if len(tool.description) <= 52 else tool.description[:50].rstrip() + " …"
            tk.Label(words, text=short, font=f.small, bg=t["panel"], fg=t["muted"], anchor="w").pack(fill="x")
            label, tone = self._status(tool)
            holder = tk.Frame(table, bg=t["panel"])
            holder.grid(row=row, column=1, sticky="w", padx=6)
            Pill(holder, t, f, label, tone).pack(side="left")
            installed = tool.installed.version if tool.installed else "—"
            tk.Label(table, text=installed, font=f.version, bg=t["panel"], fg=t["text"] if tool.installed else t["faint"],
                     anchor="w").grid(row=row, column=2, sticky="w", padx=6)
            tk.Label(table, text=tool.latest, font=f.version, bg=t["panel"],
                     fg=t["update"][0] if tool.update_available else t["text"], anchor="w"
                     ).grid(row=row, column=3, sticky="w", padx=6)
            tk.Label(table, text=german_date(tool.published), font=f.small, bg=t["panel"], fg=t["muted"], anchor="w"
                     ).grid(row=row, column=4, sticky="w", padx=6)
            actions = tk.Frame(table, bg=t["panel"], width=220, height=36)
            actions.grid(row=row, column=5, sticky="e", padx=(6, 16))
            actions.pack_propagate(False)
            self._actions(actions, tool, compact=True)

    # ================= Aufträge (eins nach dem anderen)

    def _job_for(self, tool):
        if self.job and self.job.tool.repo == tool.repo:
            return self.job
        return next((j for j in self.jobs if j.tool.repo == tool.repo), None)

    def _enqueue(self, tool, kind):
        if self._job_for(tool):
            return
        self.jobs.append(Job(tool, kind))
        self._next_job()
        self._render()

    def _dequeue(self, job):
        if job in self.jobs:
            self.jobs.remove(job)
            self._render()

    def _next_job(self):
        if self.job or not self.jobs:
            return
        job = self.job = self.jobs.popleft()
        job.phase = "start"
        silent = job.kind == "update" or self.settings.get("silent_install", False)
        folder = config.downloads_dir()

        def report(phase, done=None, total=None):
            self._post(self._job_progress, (job, phase, done, total))

        def work():
            if job.kind == "uninstall":
                tools.uninstall(job.tool, self.learned, report)
            else:
                tools.install(self.api, job.tool, folder, silent, self.learned, report, job.cancel.is_set)
            return job

        self._thread(work, self._job_done, lambda exc: self._job_failed((job, exc)))

    def _job_progress(self, args):
        job, phase, done, total = args
        changed = phase != job.phase
        job.phase = phase
        if done is not None:
            job.done, job.total = done, total or 0
        if changed:
            self._render()
        else:
            self._paint_job(job)

    def _paint_job(self, job):
        live = self._live.get(job.tool.repo)
        if not live or not live[0].winfo_exists():
            return
        label, bar, compact = live
        if job.phase == "download" and job.total:
            percent = min(100, job.done * 100 // job.total)
            label.configure(text=f"{percent} % von {megabytes(job.total)}" if compact else
                            f"Lade {megabytes(job.done)} von {megabytes(job.total)} · {percent} %")
            bar.set(percent)
        elif job.phase == "download":
            label.configure(text=f"Lade … {megabytes(job.done)}")
            bar.set(None)
        else:
            label.configure(text={"setup": "Setup läuft …" if compact else "Setup läuft – ggf. Windows-Rückfrage bestätigen",
                                  "uninstall": "Wird entfernt …"}.get(job.phase, "Bitte warten …"))
            bar.set(None)

    def _finish_job(self, job, message):
        self.job = None
        self._attach_installed()
        self._save()
        self.status_text = message.upper()
        self._render()
        self._next_job()

    def _job_done(self, job):
        verb = {"install": "ist installiert", "update": f"ist jetzt auf {job.tool.latest}",
                "uninstall": "ist deinstalliert"}[job.kind]
        self._finish_job(job, f"{job.tool.title} {verb}")

    def _job_failed(self, args):
        job, exc = args
        self._finish_job(job, f"{job.tool.title}: {exc}" if isinstance(exc, tools.ActionCancelled)
                         else f"{job.tool.title}: Fehler")
        if not isinstance(exc, tools.ActionCancelled):
            messagebox.showerror(APP_NAME, f"{job.tool.title}\n\n{exc}", parent=self.root)

    # ================= Aktionen

    def update_all(self):
        for tool in self.tools:
            if tool.update_available:
                self._enqueue(tool, "update")

    def uninstall(self, tool):
        if not tool.installed or self._job_for(tool):
            return
        if messagebox.askyesno(APP_NAME, f"{tool.installed.name} deinstallieren?\n\nOrdner: {tool.installed.location}"
                                         "\n\nEigene Daten und Einstellungen des Tools bleiben erhalten.",
                               parent=self.root):
            self._enqueue(tool, "uninstall")

    def start(self, tool):
        try:
            tools.start(tool)
            self.status_text = f"{tool.title} wird geöffnet".upper()
            self._update_chrome()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)

    def open_folder(self, tool):
        location = tool.installed.location if tool.installed else ""
        if location and os.path.isdir(location):
            os.startfile(location)
        else:
            messagebox.showinfo(APP_NAME, "Der Installationsordner ist nicht bekannt.", parent=self.root)

    def _own_setup(self):
        if not self.own_release:
            return None
        latest = (self.own_release.get("tag_name") or "").lstrip("vV")
        if not tools.is_newer(latest, __version__):
            return None
        _, asset = tools.pick_setup(SELF_REPO, self.own_release.get("assets"))
        return (latest, asset) if asset else None

    def self_update(self):
        own = self._own_setup()
        if not own or self.job:
            return
        latest, asset = own
        self.banner_label.configure(text=f"Lade Tool-Hub {latest} …")

        def work():
            info = {k: asset.get(k) for k in ("name", "url", "digest", "size")}
            return self.api.download(info, config.downloads_dir())

        def done(path):
            winrun.start_detached(path, [*tools.SILENT, "/RESTARTAPP=1"])
            self.quit()

        def failed(exc):
            self._update_chrome()
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)

        self._thread(work, done, failed)

    # ================= Einstellungen

    def _set_view(self, view):
        self.settings["view"] = view
        self._save()
        self._build()

    def _set_filter(self, key):
        self.filter = key
        self._render()

    def _set_theme(self, mode):
        self.settings["theme"] = mode
        self._save()
        self._build()

    def _toggle(self, key):
        self.settings[key] = not self.settings.get(key, False)
        self._save()

    def _settings_menu(self):
        menu = self._menu()
        design = self._menu()
        theme_var = tk.StringVar(value=self.settings["theme"])
        silent_var = tk.BooleanVar(value=self.settings.get("silent_install", False))
        tray_var = tk.BooleanVar(value=self.settings["close_to_tray"] and bool(self.tray and self.tray.ok))
        auto_var = tk.BooleanVar(value=self._autostart())
        self._menu_vars = (theme_var, silent_var, tray_var, auto_var)  # sonst räumt Python sie weg
        for mode, label in (("auto", "Wie Windows"), ("light", "Hell"), ("dark", "Dunkel")):
            design.add_radiobutton(label=label, command=lambda m=mode: self._set_theme(m),
                                   variable=theme_var, value=mode)
        menu.add_cascade(label="Design", menu=design)
        menu.add_checkbutton(label="Neue Tools ohne Assistent installieren",
                             variable=silent_var,
                             command=lambda: self._toggle("silent_install"))
        tray_ok = bool(self.tray and self.tray.ok)
        menu.add_checkbutton(label="Beim Schließen im Infobereich weiterlaufen",
                             variable=tray_var,
                             command=lambda: self._toggle("close_to_tray"),
                             state="normal" if tray_ok else "disabled")
        menu.add_checkbutton(label="Mit Windows starten (im Infobereich)", variable=auto_var,
                             command=self._toggle_autostart,
                             state="normal" if getattr(sys, "frozen", False) else "disabled")
        menu.add_separator()
        menu.add_command(label="Private Tools freischalten …", command=self.token_dialog)
        menu.add_command(label="Einstellungsordner öffnen", command=lambda: os.startfile(config.data_dir()))
        menu.add_separator()
        menu.add_command(label=f"Über Tool-Hub {__version__}",
                         command=lambda: webbrowser.open(f"https://github.com/{OWNER}/{SELF_REPO}"))
        x = self.root.winfo_rootx() + self.root.winfo_width() - 300
        menu.tk_popup(x, self.root.winfo_rooty() + 44)

    def _autostart(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return bool(winreg.QueryValueEx(key, APP_NAME)[0])
        except OSError:
            return False

    def _toggle_autostart(self):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if self._autostart():
                winreg.DeleteValue(key, APP_NAME)
            else:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --tray')

    # ================= Token

    def token_dialog(self):
        TokenDialog(self)

    def set_token(self, token):
        self.api.token = token or None
        self.no_setup.clear()
        self.tools = []
        self.refresh()

    # ================= Fenster

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def close(self):
        if self.tray and self.tray.ok and self.settings["close_to_tray"]:
            self._remember_geometry()
            self.root.withdraw()
            if not self.settings.get("tray_hint_shown"):
                self.settings["tray_hint_shown"] = True
                self._save()
                self.tray.notify(APP_NAME, "Läuft im Infobereich weiter und meldet neue Updates. "
                                           "Beenden über Rechtsklick auf das Symbol.")
            return
        self.quit()

    def quit(self):
        if self.job and not messagebox.askyesno(APP_NAME, "Es läuft noch eine Installation. Trotzdem beenden?",
                                                parent=self.root):
            return
        self._remember_geometry()
        self._save()
        if self.tray:
            self.tray.close()
        self.root.destroy()

    def _remember_geometry(self):
        if self.root.winfo_viewable() and self.root.state() == "normal":
            self.settings["geometry"] = self.root.geometry()


class TokenDialog:
    def __init__(self, app):
        self.app = app
        t, f = app.t, app.fonts
        win = self.win = tk.Toplevel(app.root, bg=t["panel"])
        win.title("Private Tools freischalten")
        win.transient(app.root)
        win.resizable(False, False)
        pad = {"padx": 24, "anchor": "w"}
        tk.Label(win, text="PRIVATE TOOLS FREISCHALTEN", font=f.label_bold, bg=t["panel"], fg=t["muted"]
                 ).pack(pady=(20, 4), **pad)
        tk.Label(win, text="GitHub-Token eintragen", font=f.title, bg=t["panel"], fg=t["text"]).pack(**pad)
        steps = (
            f"1.  Fine-grained token erstellen, Resource owner: {OWNER}, Ablaufdatum wählen.\n"
            "2.  Repository access: „All repositories“ – dann erscheinen neue private Tools\n"
            "     von selbst. Oder „Only select repositories“ und einzeln auswählen.\n"
            "3.  Permissions → Repository → Contents: „Read-only“.\n"
            "4.  Token erzeugen, kopieren und hier einfügen.\n\n"
            "Gespeichert wird er in der Windows-Anmeldeinformationsverwaltung und nur an\n"
            "api.github.com gesendet. Er kann nur lesen, nichts ändern."
        )
        tk.Label(win, text=steps, justify="left", bg=t["panel"], fg=t["muted"], font=f.small).pack(pady=(10, 12), **pad)
        FlatButton(win, t, f, "TOKEN AUF GITHUB ERSTELLEN ↗", lambda: webbrowser.open(TOKEN_URL)).pack(**pad)
        box = tk.Frame(win, bg=t["input"], highlightthickness=1, highlightbackground=t["line"])
        box.pack(padx=24, pady=(14, 0), fill="x")
        self.entry = tk.Entry(box, show="•", font=f.text, bg=t["input"], fg=t["text"], insertbackground=t["text"],
                              relief="flat", bd=0)
        self.entry.pack(fill="x", padx=10, pady=8)
        self.info = tk.Label(win, text="Ein Token ist gespeichert." if app.api.token else "Noch kein Token gespeichert.",
                             bg=t["panel"], fg=t["faint"], font=f.small)
        self.info.pack(pady=(6, 0), **pad)
        row = tk.Frame(win, bg=t["panel"])
        row.pack(fill="x", padx=24, pady=(16, 22))
        self.save_btn = FlatButton(row, t, f, "PRÜFEN UND SPEICHERN", self.save, kind="primary")
        self.save_btn.pack(side="right")
        FlatButton(row, t, f, "SCHLIESSEN", win.destroy).pack(side="right", padx=8)
        if app.api.token:
            FlatButton(row, t, f, "TOKEN ENTFERNEN", self.remove).pack(side="left")
        self.entry.focus_set()
        win.bind("<Return>", lambda e: self.save())
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()

    def save(self):
        token = self.entry.get().strip()
        if not token:
            return
        self.info.configure(text="Prüfe Token …", fg=self.app.t["faint"])

        def check():
            try:
                user = github.Api(token, cache={}).user()
                result = (True, (user or {}).get("login", ""))
            except Exception as exc:  # noqa: BLE001
                result = (False, str(exc))
            self.app._post(self._checked, (token, result))

        threading.Thread(target=check, daemon=True).start()

    def _checked(self, args):
        token, (ok, detail) = args
        if not self.win.winfo_exists():
            return
        if not ok:
            self.info.configure(text=detail, fg=self.app.t["error"][0])
            return
        try:
            secret.save_token(token)
        except OSError as exc:
            self.info.configure(text=f"Speichern fehlgeschlagen: {exc}", fg=self.app.t["error"][0])
            return
        self.win.destroy()
        self.app.set_token(token)

    def remove(self):
        try:
            secret.delete_token()
        except OSError as exc:
            self.info.configure(text=str(exc), fg=self.app.t["error"][0])
            return
        self.win.destroy()
        self.app.set_token(None)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(filename=os.path.join(config.data_dir(), "toolhub.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    if tray.signal_running():
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root, start_hidden="--tray" in argv)
    root.mainloop()
