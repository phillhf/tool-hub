"""Schlanke, selbst gezeichnete Bedienelemente – flach wie in einem Launcher, ohne Web-Oberfläche."""
import tkinter as tk


class FlatButton(tk.Label):
    """Knopf aus einem Label: primary (gefüllt), secondary (Rahmen), ghost (nur Text)."""

    def __init__(self, master, t, fonts, text, command=None, kind="secondary", width=None, font=None, **kw):
        self.t, self.kind, self.command = t, kind, command
        self.enabled = command is not None
        super().__init__(master, text=text, font=font or fonts.button, cursor="hand2" if self.enabled else "",
                         padx=kw.pop("padx", 14), pady=kw.pop("pady", 7), width=width or 0,
                         highlightthickness=1, bd=0, **kw)
        self._paint(False)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _colors(self, hover):
        t = self.t
        if not self.enabled:
            return t["faint"], t["panel"], t["line"]
        if self.kind == "primary":
            bg = t["primary_hover"] if hover else t["primary_bg"]
            return t["primary_fg"], bg, bg
        if self.kind == "selected":
            return t["select_fg"], t["select_bg"], t["select_bg"]
        if self.kind == "ghost":
            return (t["text"] if hover else t["muted"]), self.master.cget("bg"), self.master.cget("bg")
        return t["text"], (t["second_hover"] if hover else t["second_bg"]), t["line"]

    def _paint(self, hover):
        fg, bg, border = self._colors(hover)
        self.configure(fg=fg, bg=bg, highlightbackground=border, highlightcolor=border)

    def _click(self, event):
        if self.enabled and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()


class Pill(tk.Label):
    def __init__(self, master, t, fonts, text, tone):
        fg, bg = t[tone]
        super().__init__(master, text=text.upper(), font=fonts.label_bold, fg=fg, bg=bg, padx=6, pady=1,
                         highlightthickness=1, highlightbackground=fg)


class Link(tk.Label):
    def __init__(self, master, t, fonts, text, command, font=None):
        super().__init__(master, text=text, font=font or fonts.label, fg=t["muted"], bg=master.cget("bg"),
                         cursor="hand2")
        self.bind("<Enter>", lambda e: self.configure(fg=t["text"]))
        self.bind("<Leave>", lambda e: self.configure(fg=t["muted"]))
        self.bind("<ButtonRelease-1>", lambda e: command())


def rounded(canvas, x1, y1, x2, y2, r, **kw):
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
              x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


class ToolIcon(tk.Canvas):
    """Farbige Kachel mit Anfangsbuchstaben – kein Bild-Download, kein Speicherhunger."""

    def __init__(self, master, fonts, title, color, size=52):
        super().__init__(master, width=size, height=size, bg=master.cget("bg"), highlightthickness=0, bd=0)
        rounded(self, 1, 1, size - 1, size - 1, size // 4, fill=color, outline=color)
        self.create_text(size / 2, size / 2 + 1, text=initials_of(title), fill="#ffffff",
                         font=fonts.initials if size >= 44 else (fonts.initials[0], 11))


def initials_of(title):
    """„Music Renamer“ → MR, „OpenRisk“ → OR, „OCRDMS“ → OC, „Canio“ → Ca."""
    words = [w for w in title.replace("-", " ").split() if w]
    if len(words) > 1:
        return (words[0][0] + words[1][0]).upper()
    capitals = [c for c in title if c.isupper()]
    if len(capitals) >= 2:
        return "".join(capitals[:2])
    return title[:2].title()


class Bar(tk.Canvas):
    """Fortschrittsbalken; percent=None läuft als Lauflicht."""

    def __init__(self, master, t, width=200, height=4):
        super().__init__(master, width=width, height=height, bg=t["track"], highlightthickness=0, bd=0)
        self.t, self.h = t, height
        self.fill = self.create_rectangle(0, 0, 0, height, fill=t["bar"], width=0)
        self._phase, self._job = 0, None
        self.bind("<Configure>", lambda e: self._draw())
        self.percent = 0

    def set(self, percent):
        self.percent = percent
        if percent is None and self._job is None:
            self._animate()
        self._draw()

    def _draw(self):
        width = self.winfo_width()
        if self.percent is None:
            seg = width * 0.3
            x = (self._phase % 100) / 100 * (width + seg) - seg
            self.coords(self.fill, x, 0, x + seg, self.h)
        else:
            self.coords(self.fill, 0, 0, width * self.percent / 100, self.h)

    def _animate(self):
        if self.percent is not None or not self.winfo_exists():
            self._job = None
            return
        self._phase += 2
        self._draw()
        self._job = self.after(30, self._animate)
