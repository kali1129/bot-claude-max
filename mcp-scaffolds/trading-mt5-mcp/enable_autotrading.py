"""Toggle the MT5 AutoTrading button via Ctrl+E (Windows-only).

MT5 keeps the global "AutoTrading" toggle as an in-memory flag managed by
the GUI. The MetaTrader5 Python lib cannot flip it; we have to send
``Ctrl+E`` to the terminal window. We use AttachThreadInput so the foreground
steal is reliable (Windows blocks plain SetForegroundWindow).

Idempotent: checks via ``mt5.terminal_info().trade_allowed`` before and
after, so calling it twice doesn't toggle off an already-on state.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import time
from ctypes import wintypes

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("autotrading")

import MetaTrader5 as mt5  # noqa: E402

VK_CONTROL = 0x11
VK_E = 0x45
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1
SW_RESTORE = 9

DEFAULT_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)


# --- SendInput plumbing ---

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _INPUTunion(ctypes.Union):
    _fields_ = (("ki", KEYBDINPUT),)


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTunion))


def _send_key(vk: int, up: bool = False) -> None:
    flags = KEYEVENTF_KEYUP if up else 0
    inp = INPUT(type=INPUT_KEYBOARD,
                u=_INPUTunion(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags,
                                             time=0, dwExtraInfo=None)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _attach_and_focus(hwnd: int) -> None:
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    if fg_thread != target_thread:
        user32.AttachThreadInput(fg_thread, target_thread, True)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if fg_thread != target_thread:
        user32.AttachThreadInput(fg_thread, target_thread, False)


# --- public ---

def find_mt5_window(account_match: int | None = None):
    """Returns (hwnd, title) for the matching MT5 main window, or None."""
    matches = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
    )

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        # MT5 windows show titles like "<login> - <broker> - ... [SYM,TF]"
        # or "MetaTrader 5". Match both flavours.
        if "MetaTrader" not in title and "MT5" not in title:
            return True
        matches.append((hwnd, title))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    if not matches:
        return None
    if account_match is not None:
        for hwnd, title in matches:
            if str(account_match) in title:
                return (hwnd, title)
    return matches[0]


def enable(account_match: int | None = None,
           verify_path: str = DEFAULT_PATH) -> bool:
    """Returns True if AutoTrading is on after the call."""
    # 1. check current state
    if mt5.initialize(path=verify_path):
        info = mt5.terminal_info()
        already = bool(info.trade_allowed) if info else False
        mt5.shutdown()
        if already:
            log.info("AutoTrading already on")
            return True

    # 2. find window
    found = find_mt5_window(account_match=account_match)
    if not found:
        log.error("no MT5 window found")
        return False
    hwnd, title = found
    log.info("targeting MT5: %s", title)

    # 3. focus + Ctrl+E via SendInput
    _attach_and_focus(hwnd)
    time.sleep(0.4)
    _send_key(VK_CONTROL, up=False)
    time.sleep(0.05)
    _send_key(VK_E, up=False)
    time.sleep(0.05)
    _send_key(VK_E, up=True)
    time.sleep(0.05)
    _send_key(VK_CONTROL, up=True)
    time.sleep(1.0)

    # 4. verify
    if mt5.initialize(path=verify_path):
        info = mt5.terminal_info()
        ok = bool(info.trade_allowed) if info else False
        mt5.shutdown()
        if ok:
            log.info("AutoTrading enabled successfully")
            return True
    log.error("Ctrl+E delivered but AutoTrading still off — checking again in a sec")
    time.sleep(1.5)
    if mt5.initialize(path=verify_path):
        info = mt5.terminal_info()
        ok = bool(info.trade_allowed) if info else False
        mt5.shutdown()
        return ok
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None,
                    help="login number to match in window title")
    ap.add_argument("--path", default=os.environ.get("MT5_PATH", DEFAULT_PATH))
    args = ap.parse_args()
    return 0 if enable(args.account, args.path) else 2


if __name__ == "__main__":
    sys.exit(main())
