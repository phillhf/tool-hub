"""Oberfläche: eine Karte je Tool mit Installieren, Starten, Aktualisieren und Deinstallieren."""
import logging
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import APP_NAME, OWNER, SELF_REPO, __version__, config, github, registry, secret, tools, winrun

TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
log = logging.getLogger("toolhub")

BG = "#f3f4f6"
CARD = "#ffffff"
BORDER = "#d9dce1"
MUTED = "#5f6670"
ACCENT = "#1f6feb"
GOOD = "#1a7f37"
WARN = "#9a6700"


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "installer"))
    return os.path.join(base, name)


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} {__version__}")
        root.geometry("860x640")
        root.minsize(680, 420)
        root.configure(bg=BG)
        try:
            root.iconbitmap(resource("app.ico"))
        except tk.TclError:
            pass

        self.settings = config.load("settings.json", {})
        self.learned = config.load("learned.json", {})
        self.cache = config.load("cache.json", {})
        self.no_setup = self.cache.setdefault("no_setup", {})
        self.api = github.Api(secret.load_token(), cache=self.cache.setdefault("http", {}))
        self.tools = []
        self.own_release = None
        self.busy = False
        self.events = queue.Queue()
        self.silent_install = tk.BooleanVar(value=self.settings.get("silent_install", False))

        self._build()
        root.after(100, self._poll)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self.refresh()

    # ---------- Aufbau

    def _build(self):
        style = ttk.Style()
        style.configure("Accent.TButton", foreground=ACCENT)

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text=APP_NAME, font=("Segoe UI Semibold", 18), bg=BG).pack(side="left")
        tk.Label(top, text=f"  Tools von github.com/{OWNER}", font=("Segoe UI", 10), fg=MUTED, bg=BG).pack(side="left", pady=(6, 0))
        self.update_all_btn = ttk.Button(top, text="Alle aktualisieren", command=self.update_all)
        self.update_all_btn.pack(side="right")
        self.refresh_btn = ttk.Button(top, text="Neu laden", command=self.refresh)
        self.refresh_btn.pack(side="right", padx=6)

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 8))
        self.token_label = tk.Label(bar, bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.token_label.pack(side="left")
        ttk.Button(bar, text="Private Tools freischalten …", command=self.token_dialog).pack(side="left", padx=8)
        ttk.Checkbutton(bar, text="Neue Tools ohne Assistent installieren", variable=self.silent_install,
                        command=self._save_settings).pack(side="right")
        self._show_token_state()

        self.banner = tk.Frame(self.root, bg="#ddf4ff", highlightbackground="#54aeff", highlightthickness=1)
        self.banner_label = tk.Label(self.banner, bg="#ddf4ff", font=("Segoe UI", 10))
        self.banner_label.pack(side="left", padx=10, pady=6)
        ttk.Button(self.banner, text="Jetzt aktualisieren", command=self.self_update).pack(side="right", padx=8, pady=4)

        holder = tk.Frame(self.root, bg=BG)
        holder.pack(fill="both", expand=True, padx=(16, 4))
        self.canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.list = tk.Frame(self.canvas, bg=BG)
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.root.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=16, pady=8)
        self.status = tk.Label(foot, text="", bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9))
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(foot, length=220, mode="determinate")
        self.progress.pack(side="right")

    def _show_token_state(self):
        if self.api.token:
            self.token_label.config(text="🔓 Private Tools sind freigeschaltet.", fg=GOOD)
        else:
            self.token_label.config(text="🔒 Nur öffentliche Tools – private brauchen einen Token.", fg=MUTED)

    def _save_settings(self):
        self.settings["silent_install"] = self.silent_install.get()
        config.save("settings.json", self.settings)

    # ---------- Hintergrundarbeit

    def _poll(self):
        try:
            while True:
                fn, arg = self.events.get_nowait()
                fn(arg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _post(self, fn, arg=None):
        self.events.put((fn, arg))

    def _background(self, work, done):
        def run():
            try:
                result = work()
            except tools.ActionCancelled as exc:
                self._post(self._finish_cancelled, exc)
            except Exception as exc:  # noqa: BLE001 – jeder Fehler gehört in die Oberfläche
                log.exception("Fehler")
                self._post(self._finish_error, exc)
            else:
                self._post(done, result)
        threading.Thread(target=run, daemon=True).start()

    def _set_busy(self, busy, text=""):
        self.busy = busy
        for button in (self.refresh_btn, self.update_all_btn):
            button.state(["disabled"] if busy else ["!disabled"])
        self.status.config(text=text)
        if not busy:
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
        self._render()

    def _progress(self, text, percent=None):
        def show(_):
            self.status.config(text=text)
            if percent is None:
                if self.progress["mode"] != "indeterminate":
                    self.progress.config(mode="indeterminate")
                    self.progress.start(12)
            else:
                self.progress.stop()
                self.progress.config(mode="determinate", value=percent)
        self._post(show)

    def _finish_error(self, exc):
        self._set_busy(False, "")
        self._attach_installed()
        self._render()
        messagebox.showerror(APP_NAME, str(exc) or exc.__class__.__name__, parent=self.root)

    def _finish_cancelled(self, exc):
        self._set_busy(False, str(exc))
        self._attach_installed()
        self._render()

    def _save_cache(self):
        try:
            config.save("cache.json", self.cache)
            config.save("learned.json", self.learned)
        except OSError:
            log.exception("Speichern fehlgeschlagen")

    # ---------- Daten

    def refresh(self):
        if self.busy:
            return
        self._set_busy(True, "Suche nach Tools …")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.api.offline = False
        self._background(lambda: tools.discover(self.api, self.no_setup), self._loaded)

    def _loaded(self, result):
        self.tools, self.own_release = result
        self._save_cache()
        self._attach_installed()
        updates = sum(t.update_available for t in self.tools)
        text = f"{len(self.tools)} Tools gefunden"
        if updates:
            text += f", {updates} Update{'s' if updates > 1 else ''} verfügbar"
        if self.api.offline:
            text += " (offline – zuletzt geladener Stand)"
        self._set_busy(False, text + ".")
        self._show_self_update()

    def _attach_installed(self):
        entries = registry.entries()
        for tool in self.tools:
            tool.installed, tool.extra_installs = tools.match_installed(tool, entries, self.learned.get(tool.repo))

    def _own_setup(self):
        if not self.own_release:
            return None
        latest = (self.own_release.get("tag_name") or "").lstrip("vV")
        if not tools.is_newer(latest, __version__):
            return None
        _, asset = tools.pick_setup(SELF_REPO, self.own_release.get("assets"))
        return (latest, asset) if asset else None

    def _show_self_update(self):
        own = self._own_setup()
        if own and getattr(sys, "frozen", False):
            self.banner_label.config(text=f"{APP_NAME} {own[0]} ist verfügbar (installiert: {__version__}).")
            self.banner.pack(fill="x", padx=16, pady=(0, 8), before=self.canvas.master)
        else:
            self.banner.pack_forget()

    # ---------- Darstellung

    def _render(self):
        for child in self.list.winfo_children():
            child.destroy()
        if not self.tools:
            tk.Label(self.list, text="Noch keine Tools geladen." if not self.busy else "",
                     bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(pady=40)
            return
        for tool in self.tools:
            self._card(tool)

    def _card(self, tool):
        card = tk.Frame(self.list, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=4, padx=(0, 8))
        text = tk.Frame(card, bg=CARD)
        text.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        head = tk.Frame(text, bg=CARD)
        head.pack(anchor="w")
        tk.Label(head, text=tool.title, font=("Segoe UI Semibold", 12), bg=CARD).pack(side="left")
        if tool.private:
            tk.Label(head, text=" 🔒 privat", font=("Segoe UI", 9), fg=MUTED, bg=CARD).pack(side="left")
        if tool.description:
            tk.Label(text, text=tool.description, font=("Segoe UI", 9), fg=MUTED, bg=CARD,
                     anchor="w", justify="left", wraplength=430).pack(anchor="w", pady=(2, 0))

        if tool.installed and tool.update_available:
            line, color = f"Installiert: {tool.installed.version}  →  Neu: {tool.latest}", WARN
        elif tool.installed:
            line, color = f"Installiert: {tool.installed.version}  ·  aktuell", GOOD
        else:
            line, color = f"Nicht installiert  ·  Version {tool.latest}", MUTED
        if tool.extra_installs:
            line += f"  ·  {len(tool.extra_installs)} weitere Installation(en)"
        tk.Label(text, text=line, font=("Segoe UI", 9), fg=color, bg=CARD).pack(anchor="w", pady=(4, 0))

        buttons = tk.Frame(card, bg=CARD)
        buttons.pack(side="right", padx=12, pady=10)
        state = ["disabled"] if self.busy else ["!disabled"]

        def button(label, command, style="TButton"):
            b = ttk.Button(buttons, text=label, command=command, style=style, width=14)
            b.state(state)
            b.pack(side="left", padx=3)

        if tool.installed:
            button("Starten", lambda: self.start(tool), "Accent.TButton")
            if tool.update_available:
                button("Aktualisieren", lambda: self.update(tool))
            more = ttk.Menubutton(buttons, text="⋯", width=3)
            menu = tk.Menu(more, tearoff=False)
            menu.add_command(label="Deinstallieren", command=lambda: self.uninstall(tool))
            menu.add_command(label="Neu installieren", command=lambda: self.update(tool))
            menu.add_command(label="Ordner öffnen", command=lambda: self.open_folder(tool))
            menu.add_separator()
            menu.add_command(label="Auf GitHub ansehen", command=lambda: webbrowser.open(tool.html_url))
            more["menu"] = menu
            more.state(state)
            more.pack(side="left", padx=3)
        else:
            button("Installieren", lambda: self.install(tool), "Accent.TButton")
            link = ttk.Button(buttons, text="GitHub", width=8, command=lambda: webbrowser.open(tool.html_url))
            link.pack(side="left", padx=3)

    # ---------- Aktionen

    def _action(self, work, done_text):
        folder = config.downloads_dir()

        def run():
            work(folder)
            return done_text

        def done(text):
            self._save_cache()
            self._attach_installed()
            self._set_busy(False, text)

        self._background(run, done)

    def install(self, tool):
        if self.busy:
            return
        silent = self.silent_install.get()
        self._set_busy(True, f"{tool.title} wird installiert …")
        self._action(lambda folder: tools.install(self.api, tool, folder, silent, self.learned, self._progress),
                     f"{tool.title} {tool.latest} ist installiert.")

    def update(self, tool):
        if self.busy:
            return
        self._set_busy(True, f"{tool.title} wird aktualisiert …")
        self._action(lambda folder: tools.install(self.api, tool, folder, True, self.learned, self._progress),
                     f"{tool.title} ist jetzt auf Version {tool.latest}.")

    def update_all(self):
        pending = [t for t in self.tools if t.update_available]
        if self.busy or not pending:
            if not pending:
                self.status.config(text="Alle installierten Tools sind aktuell.")
            return
        names = "\n".join(f"  • {t.title} {t.installed.version} → {t.latest}" for t in pending)
        if not messagebox.askyesno(APP_NAME, f"Diese Tools aktualisieren?\n\n{names}", parent=self.root):
            return
        self._set_busy(True, "Aktualisiere …")

        def work(folder):
            failed = []
            for tool in pending:
                try:
                    tools.install(self.api, tool, folder, True, self.learned, self._progress)
                except tools.ActionCancelled:
                    failed.append(f"{tool.title}: abgebrochen")
                except Exception as exc:  # noqa: BLE001
                    log.exception("Update %s", tool.repo)
                    failed.append(f"{tool.title}: {exc}")
            if failed:
                raise RuntimeError("Nicht alle Updates haben geklappt:\n\n" + "\n".join(failed))

        self._action(work, f"{len(pending)} Tool(s) aktualisiert.")

    def uninstall(self, tool):
        if self.busy or not tool.installed:
            return
        if not messagebox.askyesno(
                APP_NAME, f"{tool.installed.name} deinstallieren?\n\nOrdner: {tool.installed.location}\n\n"
                          "Eigene Daten und Einstellungen des Tools bleiben erhalten.", parent=self.root):
            return
        self._set_busy(True, f"{tool.title} wird deinstalliert …")
        self._action(lambda folder: tools.uninstall(tool, self.learned, self._progress),
                     f"{tool.title} ist deinstalliert.")

    def start(self, tool):
        try:
            tools.start(tool)
            self.status.config(text=f"{tool.title} wird gestartet …")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)

    def open_folder(self, tool):
        location = tool.installed.location if tool.installed else ""
        if location and os.path.isdir(location):
            os.startfile(location)
        else:
            messagebox.showinfo(APP_NAME, "Der Installationsordner ist nicht bekannt.", parent=self.root)

    def self_update(self):
        own = self._own_setup()
        if not own or self.busy:
            return
        latest, asset = own
        self._set_busy(True, f"Lade {APP_NAME} {latest} …")

        def work():
            asset_info = {k: asset.get(k) for k in ("name", "url", "digest", "size")}
            return self.api.download(asset_info, config.downloads_dir(),
                                     lambda p: self._progress(f"Lade {APP_NAME} {latest} …", p))

        def done(path):
            winrun.start_detached(path, [*tools.SILENT, "/RESTARTAPP=1"])
            self._close()

        self._background(work, done)

    # ---------- Token

    def token_dialog(self):
        TokenDialog(self)

    def set_token(self, token):
        self.api.token = token or None
        self.no_setup.clear()
        self._show_token_state()
        self.refresh()

    def _close(self):
        self._save_cache()
        self.root.destroy()


class TokenDialog:
    def __init__(self, app):
        self.app = app
        win = self.win = tk.Toplevel(app.root)
        win.title("Private Tools freischalten")
        win.configure(bg=BG)
        win.transient(app.root)
        win.resizable(False, False)
        pad = {"padx": 16, "anchor": "w"}
        tk.Label(win, text="GitHub-Token für private Tools", font=("Segoe UI Semibold", 12), bg=BG).pack(pady=(14, 6), **pad)
        steps = (
            "1.  Auf GitHub einen „Fine-grained token“ erstellen (Knopf unten).\n"
            f"2.  Resource owner: {OWNER}  ·  Ablaufdatum wählen.\n"
            "3.  Repository access: „Only select repositories“ und die privaten Tools auswählen.\n"
            "4.  Permissions → Repository → Contents: „Read-only“.\n"
            "5.  Token erzeugen, kopieren und hier einfügen.\n\n"
            "Der Token wird in der Windows-Anmeldeinformationsverwaltung gespeichert\n"
            "und nur an api.github.com gesendet. Er kann nur lesen, nichts ändern."
        )
        tk.Label(win, text=steps, justify="left", bg=BG, font=("Segoe UI", 9)).pack(**pad)
        ttk.Button(win, text="Token auf GitHub erstellen …", command=lambda: webbrowser.open(TOKEN_URL)).pack(pady=8, **pad)
        self.entry = ttk.Entry(win, show="•", width=64)
        self.entry.pack(padx=16, fill="x")
        self.info = tk.Label(win, text="Gespeichert ist ein Token." if app.api.token else "Noch kein Token gespeichert.",
                             bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.info.pack(pady=(4, 0), **pad)
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=16, pady=14)
        self.save_btn = ttk.Button(row, text="Prüfen und speichern", command=self.save)
        self.save_btn.pack(side="right")
        ttk.Button(row, text="Schließen", command=win.destroy).pack(side="right", padx=6)
        if app.api.token:
            ttk.Button(row, text="Token entfernen", command=self.remove).pack(side="left")
        self.entry.focus_set()
        win.bind("<Return>", lambda e: self.save())
        win.grab_set()

    def save(self):
        token = self.entry.get().strip()
        if not token:
            return
        self.save_btn.state(["disabled"])
        self.info.config(text="Prüfe Token …", fg=MUTED)

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
        self.save_btn.state(["!disabled"])
        if not ok:
            self.info.config(text=detail, fg="#cf222e")
            return
        try:
            secret.save_token(token)
        except OSError as exc:
            self.info.config(text=f"Speichern fehlgeschlagen: {exc}", fg="#cf222e")
            return
        self.win.destroy()
        self.app.set_token(token)
        self.app.status.config(text=f"Token von {detail} gespeichert, private Tools werden geladen …")

    def remove(self):
        try:
            secret.delete_token()
        except OSError as exc:
            self.info.config(text=str(exc), fg="#cf222e")
            return
        self.win.destroy()
        self.app.set_token(None)


def main():
    logging.basicConfig(filename=os.path.join(config.data_dir(), "toolhub.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
