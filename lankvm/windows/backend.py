from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Protocol

from ..events import KeyEvent, MouseButtonEvent, MouseMoveEvent, MouseWheelEvent
from ..screen import ScreenInfo
from . import win32


INJECTED_EXTRA_INFO = 0xC0D3C0D3


class LocalInputHandler(Protocol):
    def handle_mouse_move(self, event: MouseMoveEvent) -> bool: ...
    def handle_mouse_button(self, event: MouseButtonEvent) -> bool: ...
    def handle_mouse_wheel(self, event: MouseWheelEvent) -> bool: ...
    def handle_key_event(self, event: KeyEvent) -> bool: ...


class WindowsInputBackend:
    def __init__(self, handler: LocalInputHandler, logger: logging.Logger) -> None:
        self._handler = handler
        self._logger = logger
        self._thread = threading.Thread(target=self._hook_loop, name="lan-kvm-hooks", daemon=True)
        self._started = threading.Event()
        self._thread_id = 0
        self._mouse_hook = None
        self._keyboard_hook = None
        self._mouse_proc = win32.HOOKPROC(self._mouse_callback)
        self._keyboard_proc = win32.HOOKPROC(self._keyboard_callback)

    def start(self) -> None:
        self._thread.start()
        if not self._started.wait(timeout=5.0):
            raise RuntimeError("failed to start Windows low-level hooks")

    def stop(self) -> None:
        if self._thread_id:
            win32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        self._thread.join(timeout=2.0)

    def screen_info(self) -> ScreenInfo:
        return ScreenInfo(
            left=win32.GetSystemMetrics(win32.SM_XVIRTUALSCREEN),
            top=win32.GetSystemMetrics(win32.SM_YVIRTUALSCREEN),
            width=win32.GetSystemMetrics(win32.SM_CXVIRTUALSCREEN),
            height=win32.GetSystemMetrics(win32.SM_CYVIRTUALSCREEN),
        )

    def get_cursor_position(self) -> tuple[int, int]:
        point = win32.POINT()
        if not win32.GetCursorPos(ctypes.byref(point)):
            win32.raise_last_error("GetCursorPos failed")
        return point.x, point.y

    def set_cursor_position(self, x: int, y: int) -> None:
        if not win32.SetCursorPos(int(x), int(y)):
            win32.raise_last_error("SetCursorPos failed")

    def move_mouse_relative(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        input_item = win32.INPUT(
            type=win32.INPUT_MOUSE,
            mi=win32.MOUSEINPUT(
                dx=int(dx),
                dy=int(dy),
                mouseData=0,
                dwFlags=win32.MOUSEEVENTF_MOVE,
                time=0,
                dwExtraInfo=INJECTED_EXTRA_INFO,
            ),
        )
        self._send_inputs([input_item])

    def inject_mouse_button(self, button: str, is_down: bool) -> None:
        button = button.lower()
        mapping = {
            "left": (win32.MOUSEEVENTF_LEFTDOWN, win32.MOUSEEVENTF_LEFTUP, 0),
            "right": (win32.MOUSEEVENTF_RIGHTDOWN, win32.MOUSEEVENTF_RIGHTUP, 0),
            "middle": (win32.MOUSEEVENTF_MIDDLEDOWN, win32.MOUSEEVENTF_MIDDLEUP, 0),
            "x1": (win32.MOUSEEVENTF_XDOWN, win32.MOUSEEVENTF_XUP, win32.XBUTTON1),
            "x2": (win32.MOUSEEVENTF_XDOWN, win32.MOUSEEVENTF_XUP, win32.XBUTTON2),
        }
        if button not in mapping:
            return

        down_flag, up_flag, mouse_data = mapping[button]
        input_item = win32.INPUT(
            type=win32.INPUT_MOUSE,
            mi=win32.MOUSEINPUT(
                dx=0,
                dy=0,
                mouseData=mouse_data,
                dwFlags=down_flag if is_down else up_flag,
                time=0,
                dwExtraInfo=INJECTED_EXTRA_INFO,
            ),
        )
        self._send_inputs([input_item])

    def inject_mouse_wheel(self, delta: int) -> None:
        input_item = win32.INPUT(
            type=win32.INPUT_MOUSE,
            mi=win32.MOUSEINPUT(
                dx=0,
                dy=0,
                mouseData=int(delta),
                dwFlags=win32.MOUSEEVENTF_WHEEL,
                time=0,
                dwExtraInfo=INJECTED_EXTRA_INFO,
            ),
        )
        self._send_inputs([input_item])

    def inject_key(self, *, vk_code: int, scan_code: int, is_down: bool, flags: int) -> None:
        key_flags = 0
        if flags & win32.LLKHF_EXTENDED:
            key_flags |= win32.KEYEVENTF_EXTENDEDKEY
        if not is_down:
            key_flags |= win32.KEYEVENTF_KEYUP
        input_item = win32.INPUT(
            type=win32.INPUT_KEYBOARD,
            ki=win32.KEYBDINPUT(
                wVk=int(vk_code),
                wScan=int(scan_code),
                dwFlags=key_flags,
                time=0,
                dwExtraInfo=INJECTED_EXTRA_INFO,
            ),
        )
        self._send_inputs([input_item])

    def _send_inputs(self, items: list[win32.INPUT]) -> None:
        if not items:
            return
        array_type = win32.INPUT * len(items)
        sent = win32.SendInput(len(items), array_type(*items), ctypes.sizeof(win32.INPUT))
        if sent != len(items):
            win32.raise_last_error("SendInput failed")

    def _hook_loop(self) -> None:
        self._thread_id = win32.GetCurrentThreadId()
        module_handle = win32.GetModuleHandleW(None)
        self._mouse_hook = win32.SetWindowsHookExW(win32.WH_MOUSE_LL, self._mouse_proc, module_handle, 0)
        if not self._mouse_hook:
            win32.raise_last_error("SetWindowsHookExW(mouse) failed")

        self._keyboard_hook = win32.SetWindowsHookExW(win32.WH_KEYBOARD_LL, self._keyboard_proc, module_handle, 0)
        if not self._keyboard_hook:
            win32.raise_last_error("SetWindowsHookExW(keyboard) failed")

        self._started.set()
        self._logger.info("low-level hooks installed")

        message = win32.wintypes.MSG()
        try:
            while True:
                result = win32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    win32.raise_last_error("GetMessageW failed")
                win32.TranslateMessage(ctypes.byref(message))
                win32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._mouse_hook:
                win32.UnhookWindowsHookEx(self._mouse_hook)
                self._mouse_hook = None
            if self._keyboard_hook:
                win32.UnhookWindowsHookEx(self._keyboard_hook)
                self._keyboard_hook = None
            self._logger.info("low-level hooks removed")

    def _mouse_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return win32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)

        hook = ctypes.cast(l_param, ctypes.POINTER(win32.MSLLHOOKSTRUCT)).contents
        if hook.flags & (win32.LLMHF_INJECTED | win32.LLMHF_LOWER_IL_INJECTED):
            return win32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
        if hook.dwExtraInfo == INJECTED_EXTRA_INFO:
            return win32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)

        timestamp = time.monotonic()
        x = int(hook.pt.x)
        y = int(hook.pt.y)
        suppress = False
        message = int(w_param)

        if message == win32.WM_MOUSEMOVE:
            suppress = self._handler.handle_mouse_move(MouseMoveEvent(x=x, y=y, monotonic_time=timestamp))
        elif message in {
            win32.WM_LBUTTONDOWN,
            win32.WM_LBUTTONUP,
            win32.WM_RBUTTONDOWN,
            win32.WM_RBUTTONUP,
            win32.WM_MBUTTONDOWN,
            win32.WM_MBUTTONUP,
            win32.WM_XBUTTONDOWN,
            win32.WM_XBUTTONUP,
        }:
            button_name = _mouse_button_name(message, hook.mouseData)
            if button_name is not None:
                suppress = self._handler.handle_mouse_button(
                    MouseButtonEvent(
                        button=button_name,
                        is_down=message in {win32.WM_LBUTTONDOWN, win32.WM_RBUTTONDOWN, win32.WM_MBUTTONDOWN, win32.WM_XBUTTONDOWN},
                        x=x,
                        y=y,
                        monotonic_time=timestamp,
                    )
                )
        elif message == win32.WM_MOUSEWHEEL:
            delta = ctypes.c_short((hook.mouseData >> 16) & 0xFFFF).value
            suppress = self._handler.handle_mouse_wheel(MouseWheelEvent(delta=delta, x=x, y=y, monotonic_time=timestamp))

        if suppress:
            return 1
        return win32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)

    def _keyboard_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return win32.CallNextHookEx(self._keyboard_hook, n_code, w_param, l_param)

        hook = ctypes.cast(l_param, ctypes.POINTER(win32.KBDLLHOOKSTRUCT)).contents
        if hook.flags & (win32.LLKHF_INJECTED | win32.LLKHF_LOWER_IL_INJECTED):
            return win32.CallNextHookEx(self._keyboard_hook, n_code, w_param, l_param)
        if hook.dwExtraInfo == INJECTED_EXTRA_INFO:
            return win32.CallNextHookEx(self._keyboard_hook, n_code, w_param, l_param)

        message = int(w_param)
        if message not in {win32.WM_KEYDOWN, win32.WM_KEYUP, win32.WM_SYSKEYDOWN, win32.WM_SYSKEYUP}:
            return win32.CallNextHookEx(self._keyboard_hook, n_code, w_param, l_param)

        suppress = self._handler.handle_key_event(
            KeyEvent(
                vk_code=int(hook.vkCode),
                scan_code=int(hook.scanCode),
                flags=int(hook.flags),
                is_down=message in {win32.WM_KEYDOWN, win32.WM_SYSKEYDOWN},
                monotonic_time=time.monotonic(),
            )
        )
        if suppress:
            return 1
        return win32.CallNextHookEx(self._keyboard_hook, n_code, w_param, l_param)


def _mouse_button_name(message: int, mouse_data: int) -> str | None:
    if message in {win32.WM_LBUTTONDOWN, win32.WM_LBUTTONUP}:
        return "left"
    if message in {win32.WM_RBUTTONDOWN, win32.WM_RBUTTONUP}:
        return "right"
    if message in {win32.WM_MBUTTONDOWN, win32.WM_MBUTTONUP}:
        return "middle"
    if message in {win32.WM_XBUTTONDOWN, win32.WM_XBUTTONUP}:
        button = (mouse_data >> 16) & 0xFFFF
        if button == win32.XBUTTON1:
            return "x1"
        if button == win32.XBUTTON2:
            return "x2"
    return None
