"""UCI -> koordinat piksel layar -> gerakan mouse (drag atau click-and-click).

Keamanan:
- pyautogui.FAILSAFE: banting kursor ke salah satu POJOK layar untuk abort.
- ``stop_event`` (threading.Event) dicek di setiap langkah kecil gerakan,
  sehingga hotkey kill-switch dari main.py menghentikan gerakan seketika.
"""
import math
import random
import threading
import time
from typing import Optional, Tuple

import chess
import pyautogui

import config

pyautogui.FAILSAFE = config.PYAUTOGUI_FAILSAFE
pyautogui.PAUSE = 0.0


class MoveAborted(RuntimeError):
    pass


def square_to_cell(square: chess.Square, white_bottom: bool) -> Tuple[int, int]:
    """(col, row) kotak pada layar; row 0 = baris paling atas gambar."""
    f, r = chess.square_file(square), chess.square_rank(square)
    return (f, 7 - r) if white_bottom else (7 - f, r)


def cell_center(col: float, row: float, roi: dict) -> Tuple[float, float]:
    cw, ch = roi["width"] / 8.0, roi["height"] / 8.0
    return roi["left"] + (col + 0.5) * cw, roi["top"] + (row + 0.5) * ch


def square_to_pixel(square: chess.Square, roi: dict, white_bottom: bool,
                    jitter: float = 0.0) -> Tuple[int, int]:
    col, row = square_to_cell(square, white_bottom)
    x, y = cell_center(col, row, roi)
    if jitter:
        x += random.uniform(-jitter, jitter) * roi["width"] / 8.0
        y += random.uniform(-jitter, jitter) * roi["height"] / 8.0
    return int(round(x)), int(round(y))


def uci_to_pixels(uci: str, roi: dict, white_bottom: bool, jitter: float = 0.0):
    move = chess.Move.from_uci(uci)
    return (square_to_pixel(move.from_square, roi, white_bottom, jitter),
            square_to_pixel(move.to_square, roi, white_bottom, jitter))


class MouseController:
    def __init__(self, roi: dict = None, white_bottom: bool = True,
                 stop_event: Optional[threading.Event] = None, style: str = None):
        self.roi = dict(roi or config.BOARD_ROI)
        self.white_bottom = white_bottom
        self.stop_event = stop_event or threading.Event()
        self.style = style or config.MOUSE_STYLE
        self._button_down = False

    # -- primitive yang bisa dibatalkan ------------------------------------
    def _check(self):
        if self.stop_event.is_set():
            self.release()
            raise MoveAborted("Dihentikan oleh kill-switch")

    def _sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            self._check()
            time.sleep(min(0.02, max(0.0, end - time.time())))

    def _glide(self, x: int, y: int, duration: float = None):
        """Gerak halus (ease-in-out) dari posisi sekarang ke (x, y)."""
        if duration is None:
            duration = random.uniform(*config.MOUSE_MOVE_DURATION)
        x0, y0 = pyautogui.position()
        steps = max(2, int(duration * config.MOUSE_STEPS_PER_SECOND))
        for i in range(1, steps + 1):
            self._check()
            t = i / float(steps)
            e = 0.5 - 0.5 * math.cos(math.pi * t)
            pyautogui.moveTo(x0 + (x - x0) * e, y0 + (y - y0) * e, _pause=False)
            time.sleep(duration / steps)

    def release(self):
        if self._button_down:
            try:
                pyautogui.mouseUp(_pause=False)
            except Exception:
                pass
            self._button_down = False

    # -- aksi tingkat tinggi -----------------------------------------------
    def execute(self, move: chess.Move):
        j = config.MOUSE_JITTER
        x1, y1 = square_to_pixel(move.from_square, self.roi, self.white_bottom, j)
        x2, y2 = square_to_pixel(move.to_square, self.roi, self.white_bottom, j)

        self._glide(x1, y1)
        self._sleep(random.uniform(0.05, 0.12))
        try:
            if self.style == "drag":
                pyautogui.mouseDown(_pause=False)
                self._button_down = True
                # Geser kecil dulu: beberapa papan web baru mengenali drag
                # setelah ada gerakan kecil sesudah mouseDown.
                self._sleep(random.uniform(0.06, 0.12))
                self._glide(x1 + random.randint(-3, 3), y1 + random.randint(-3, 3), 0.04)
                self._glide(x2, y2)
                self._sleep(random.uniform(0.03, 0.08))
                pyautogui.mouseUp(_pause=False)
                self._button_down = False
            else:  # click-and-click
                pyautogui.click(_pause=False)
                self._sleep(random.uniform(0.08, 0.2))
                self._glide(x2, y2)
                pyautogui.click(_pause=False)
        finally:
            self.release()

        if move.promotion:
            self._promote(move)
        if config.PARK_CURSOR:
            self.park()

    def _promote(self, move: chess.Move):
        """Klik pilihan di popup promosi (muncul di kolom kotak tujuan)."""
        symbol = chess.piece_symbol(move.promotion)
        offset = config.PROMOTION_POPUP_OFFSETS.get(symbol, 0)
        col, row = square_to_cell(move.to_square, self.white_bottom)
        direction = 1 if row == 0 else -1   # popup memanjang ke tengah papan
        x, y = cell_center(col, row + direction * offset, self.roi)
        self._sleep(0.35)
        self._glide(int(x), int(y), 0.15)
        pyautogui.click(_pause=False)

    def park(self):
        """Pindahkan kursor ke luar papan agar tidak menutupi bidak/hover effect."""
        r = self.roi
        screen_w, screen_h = pyautogui.size()
        x = r["left"] + r["width"] + 40
        if x >= screen_w - 5:
            x = max(5, r["left"] - 40)
        y = min(screen_h - 5, max(5, r["top"] + r["height"] // 2))
        self._glide(int(x), int(y), 0.15)
