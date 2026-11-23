"""Screen capture (mss) dan pemotongan gambar papan menjadi 64 kotak."""
import cv2
import mss
import numpy as np


def grab_screen(monitor_index: int = 1) -> np.ndarray:
    """Screenshot satu monitor penuh, dikembalikan sebagai gambar BGR."""
    with mss.mss() as sct:
        mon = sct.monitors[monitor_index]
        img = np.array(sct.grab(mon))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def grab_board(cfg: dict) -> np.ndarray:
    """Capture hanya area papan sesuai hasil kalibrasi."""
    b = cfg["board"]
    if b is None:
        raise RuntimeError(
            "Papan belum dikalibrasi. Jalankan: py -m chessbot.calibrate"
        )
    region = {"left": b["left"], "top": b["top"], "width": b["size"], "height": b["size"]}
    with mss.mss() as sct:
        img = np.array(sct.grab(region))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def split_squares(board_img: np.ndarray) -> list:
    """Potong gambar papan menjadi grid 8x8.

    Hasil diindeks [row][col] dengan row 0 = baris paling ATAS pada gambar
    (belum peduli orientasi putih/hitam — itu urusan recognize.py).
    """
    h, w = board_img.shape[:2]
    cell_h, cell_w = h / 8.0, w / 8.0
    squares = []
    for r in range(8):
        row = []
        for c in range(8):
            y0, y1 = int(r * cell_h), int((r + 1) * cell_h)
            x0, x1 = int(c * cell_w), int((c + 1) * cell_w)
            row.append(board_img[y0:y1, x0:x1])
        squares.append(row)
    return squares
