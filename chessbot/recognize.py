"""Pengenalan bidak per kotak dengan template matching sederhana.

Metode: setiap kotak dinormalisasi (grayscale, resize, zero-mean, unit-norm)
lalu dibandingkan dengan semua template memakai korelasi silang ternormalisasi
(ZNCC). Label dengan skor tertinggi menang. Sederhana tapi sangat efektif
untuk papan digital yang render-nya konsisten.

Template dibuat sekali dengan: py -m chessbot.build_templates
"""
import glob
import os
from typing import List, Tuple

import cv2
import numpy as np

from .config import TEMPLATES_DIR

TEMPLATE_SIZE = 64

# Nama folder aman untuk filesystem Windows (case-insensitive)
_LABEL_TO_DIR = {
    "P": "wP", "N": "wN", "B": "wB", "R": "wR", "Q": "wQ", "K": "wK",
    "p": "bP", "n": "bN", "b": "bB", "r": "bR", "q": "bQ", "k": "bK",
    ".": "empty",
}
_DIR_TO_LABEL = {v: k for k, v in _LABEL_TO_DIR.items()}


def label_to_dir(label: str) -> str:
    return _LABEL_TO_DIR[label]


def normalize(img: np.ndarray) -> np.ndarray:
    """Ubah crop kotak menjadi vektor fitur yang tahan perbedaan brightness."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (TEMPLATE_SIZE, TEMPLATE_SIZE)).astype(np.float32)
    vec = gray.flatten()
    vec -= vec.mean()
    norm = np.linalg.norm(vec)
    return vec / (norm + 1e-6)


class Recognizer:
    def __init__(self, templates_dir: str = TEMPLATES_DIR):
        self.templates: List[Tuple[np.ndarray, str]] = []
        for dir_name, label in _DIR_TO_LABEL.items():
            for path in glob.glob(os.path.join(templates_dir, dir_name, "*.png")):
                img = cv2.imread(path)
                if img is not None:
                    self.templates.append((normalize(img), label))
        if not self.templates:
            raise RuntimeError(
                "Tidak ada template di {}. Jalankan dulu: "
                "py -m chessbot.build_templates".format(templates_dir)
            )

    def classify_square(self, square_img: np.ndarray) -> str:
        # Kotak kosong bertema polos nyaris tanpa variasi pixel; setelah
        # zero-mean vektornya cuma noise dan korelasinya jadi tidak bermakna.
        # Deteksi langsung sebagai kosong sebelum template matching.
        gray = cv2.cvtColor(square_img, cv2.COLOR_BGR2GRAY)
        if float(gray.std()) < 2.5:
            return "."
        vec = normalize(square_img)
        best_label, best_score = ".", -2.0
        for tvec, label in self.templates:
            score = float(np.dot(vec, tvec))
            if score > best_score:
                best_score, best_label = score, label
        return best_label

    def matrix_from_image(self, board_img: np.ndarray, white_bottom: bool = True):
        """Klasifikasikan 64 kotak, hasil dalam orientasi standar (row 0 = rank 8)."""
        from .capture import split_squares

        squares = split_squares(board_img)
        matrix = [[self.classify_square(squares[r][c]) for c in range(8)] for r in range(8)]
        if not white_bottom:
            # Papan di layar terbalik (kita main hitam) -> putar 180 derajat
            matrix = [list(reversed(row)) for row in reversed(matrix)]
        return matrix
