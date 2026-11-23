"""Eksekusi langkah dengan mouse (pyautogui) — drag-and-drop atau click-click.

Pengaman: pyautogui.FAILSAFE aktif — banting kursor ke pojok KIRI-ATAS layar
untuk membatalkan gerakan kapan pun (melempar FailSafeException).
"""
import random
import time
from typing import Tuple

import chess
import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02


def square_to_point(square: chess.Square, cfg: dict) -> Tuple[float, float]:
    """Koordinat pixel tengah kotak (plus jitter kecil biar tidak robotik)."""
    b = cfg["board"]
    cell = b["size"] / 8.0
    file, rank = chess.square_file(square), chess.square_rank(square)
    if cfg["white_bottom"]:
        col, row = file, 7 - rank
    else:
        col, row = 7 - file, rank
    jitter = cell * 0.12
    x = b["left"] + (col + 0.5) * cell + random.uniform(-jitter, jitter)
    y = b["top"] + (row + 0.5) * cell + random.uniform(-jitter, jitter)
    return x, y


def execute_move(move: chess.Move, cfg: dict, style: str = "drag") -> None:
    x1, y1 = square_to_point(move.from_square, cfg)
    x2, y2 = square_to_point(move.to_square, cfg)

    pyautogui.moveTo(x1, y1, duration=random.uniform(0.15, 0.35), tween=pyautogui.easeOutQuad)
    time.sleep(random.uniform(0.05, 0.15))

    if style == "drag":
        pyautogui.mouseDown()
        # Jeda + geser kecil dulu: beberapa papan web butuh press terdaftar
        # sebelum gerakan besar, kalau tidak drag dianggap klik biasa.
        time.sleep(random.uniform(0.08, 0.15))
        pyautogui.moveTo(x1 + random.uniform(-3, 3), y1 + random.uniform(-3, 3), duration=0.05)
        pyautogui.moveTo(x2, y2, duration=random.uniform(0.2, 0.45), tween=pyautogui.easeInOutQuad)
        time.sleep(random.uniform(0.04, 0.1))
        pyautogui.mouseUp()
    else:  # click-click
        pyautogui.click()
        time.sleep(random.uniform(0.1, 0.25))
        pyautogui.moveTo(x2, y2, duration=random.uniform(0.15, 0.35), tween=pyautogui.easeOutQuad)
        pyautogui.click()

    if move.promotion:
        # Kebanyakan papan digital memunculkan popup promosi dengan RATU tepat
        # di kotak tujuan — klik sekali lagi untuk memilihnya. Promosi minor
        # (N/B/R) perlu penyesuaian per platform.
        time.sleep(0.4)
        px, py_ = square_to_point(move.to_square, cfg)
        pyautogui.click(px, py_)
