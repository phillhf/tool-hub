"""Symbol im Infobereich (Taskleiste) über die Win32-API – ohne Zusatzpakete und ohne eigenen Thread.

Das Symbol hat einen eigenen Thread mit eigener Nachrichtenschleife. Rückrufe aus Windows dürfen nicht in der
Ereignisschleife von tkinter landen (das bringt Python zum Absturz); sie gehen über schedule() an die Oberfläche.
"""
import ctypes
import sys
import threading
from ctypes import wintypes

CLASS = "ToolHubTray"
WM_TRAY = 0x8001
WM_SHOW = 0x8002
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
NIN_BALLOONUSERCLICK = 0x0405
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x01
IMAGE_ICON = 1
LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x10, 0x40
WM_CLOSE, WM_DESTROY = 0x0010, 0x0002
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


def _libs():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.LPVOID]
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    return user32, shell32, kernel32


def signal_running():
    """Läuft Tool-Hub schon? Dann dessen Fenster nach vorne holen und True liefern."""
    if sys.platform != "win32":
        return False
    user32, _, _ = _libs()
    hwnd = user32.FindWindowW(CLASS, None)
    if hwnd:
        user32.PostMessageW(hwnd, WM_SHOW, 0, 0)
        return True
    return False


class Tray:
    def __init__(self, icon_path, tip, menu, on_click, schedule):
        """menu: Liste aus (Text, Funktion) oder None als Trennlinie. schedule(fn) übergibt fn an die Oberfläche."""
        self.ok = False
        self.hwnd = None
        self.hicon = None
        self.menu, self.on_click, self.schedule = menu, on_click, schedule
        self.user32, self.shell32, self.kernel32 = _libs()
        self._proc = WNDPROC(self._wndproc)  # Referenz halten, sonst räumt Python den Rückruf weg
        self._ready = threading.Event()
        threading.Thread(target=self._run, args=(icon_path, tip), name="tray", daemon=True).start()
        self._ready.wait(5)

    def _run(self, icon_path, tip):
        try:
            instance = self.kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._proc
            wc.hInstance = instance
            wc.lpszClassName = CLASS
            self.user32.RegisterClassW(ctypes.byref(wc))
            self.hwnd = self.user32.CreateWindowExW(0, CLASS, "Tool-Hub", 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                return
            self.hicon = self.user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            self.nid = NOTIFYICONDATAW()
            self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            self.nid.hWnd = self.hwnd
            self.nid.uID = 1
            self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            self.nid.uCallbackMessage = WM_TRAY
            self.nid.hIcon = self.hicon
            self.nid.szTip = tip[:127]
            self.ok = bool(self.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid)))
        finally:
            self._ready.set()
        msg = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, NIN_BALLOONUSERCLICK):
                self.schedule(self.on_click)
            elif event == WM_RBUTTONUP:
                self._popup()
            return 0
        if msg == WM_SHOW:
            self.schedule(self.on_click)
            return 0
        if msg == WM_CLOSE:
            if self.ok:
                self.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
                self.ok = False
            self.user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup(self):
        menu = self.user32.CreatePopupMenu()
        actions = {}
        for index, item in enumerate(self.menu, start=1):
            if item is None:
                self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                actions[index] = item[1]
                self.user32.AppendMenuW(menu, MF_STRING, index, item[0])
        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        self.user32.SetForegroundWindow(self.hwnd)
        chosen = self.user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y, 0, self.hwnd, None)
        self.user32.PostMessageW(self.hwnd, 0, 0, 0)
        self.user32.DestroyMenu(menu)
        if chosen in actions:
            self.schedule(actions[chosen])

    def notify(self, title, text):
        if not self.ok:
            return
        self.nid.uFlags = NIF_INFO
        self.nid.szInfoTitle = title[:63]
        self.nid.szInfo = text[:255]
        self.nid.dwInfoFlags = NIIF_INFO
        self.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def close(self):
        """Symbol entfernen und den Thread beenden (das erledigt der Thread selbst)."""
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.hwnd = None
