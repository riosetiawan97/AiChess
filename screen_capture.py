"""Screenshot area papan (mss) + konversi ke PNG/base64 + deteksi perubahan frame."""
import base64
import hashlib
import io
from typing import Optional

import mss
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config


class ScreenCapture:
    """Wrapper mss yang dipakai ulang (lebih cepat daripada membuka mss tiap frame)."""

    def __init__(self, roi: Optional[dict] = None):
        self.roi = dict(roi or config.BOARD_ROI)
        self._sct = mss.mss()

    def grab(self) -> np.ndarray:
        """Ambil area papan sebagai array RGB (H, W, 3) uint8."""
        shot = self._sct.grab(self.roi)
        # mss memberi BGRA -> ambil 3 channel lalu balik ke RGB
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return arr[:, :, 2::-1].copy()

    def grab_full_screen(self, monitor_index: int = 0) -> np.ndarray:
        """Screenshot seluruh desktop (dipakai saat kalibrasi)."""
        shot = self._sct.grab(self._sct.monitors[monitor_index])
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return arr[:, :, 2::-1].copy()

    def close(self) -> None:
        self._sct.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# Deteksi perubahan frame
# ---------------------------------------------------------------------------
def fingerprint(img: np.ndarray, size: int = 64) -> np.ndarray:
    """Thumbnail grayscale kecil — murah dibandingkan & kebal noise kecil."""
    gray = Image.fromarray(img).convert("L").resize((size, size), Image.BILINEAR)
    return np.asarray(gray, dtype=np.float32)


def frame_hash(img: np.ndarray) -> str:
    """Hash persis dari thumbnail (cepat untuk cek "sama persis")."""
    return hashlib.md5(fingerprint(img).astype(np.uint8).tobytes()).hexdigest()


def frame_diff(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    """Rata-rata selisih absolut piksel (0-255) antara dua fingerprint."""
    if a is None or b is None:
        return 255.0
    return float(np.mean(np.abs(a - b)))


def wait_for_stable(cap: ScreenCapture, frames: int = None, threshold: float = None,
                    interval: float = 0.12, timeout: float = 5.0, stop_event=None):
    """Capture sampai N frame berturut-turut nyaris identik (animasi selesai).

    Mengembalikan (img, fingerprint) frame terakhir, atau frame terakhir yang
    didapat jika timeout.
    """
    import time

    frames = frames or config.STABLE_FRAMES
    threshold = config.STABLE_THRESHOLD if threshold is None else threshold
    deadline = time.time() + timeout
    img = cap.grab()
    fp = fingerprint(img)
    stable = 1
    while stable < frames and time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)
        img2 = cap.grab()
        fp2 = fingerprint(img2)
        stable = stable + 1 if frame_diff(fp, fp2) <= threshold else 1
        img, fp = img2, fp2
    return img, fp


# ---------------------------------------------------------------------------
# Siapkan gambar untuk Vision LLM
# ---------------------------------------------------------------------------
def annotate_coordinates(img: Image.Image, white_bottom: bool) -> Image.Image:
    """Tambah margin berlabel file (a-h) & rank (1-8) supaya LLM tidak salah baris."""
    w, h = img.size
    margin = max(18, w // 28)
    canvas = Image.new("RGB", (w + margin, h + margin), (255, 255, 255))
    canvas.paste(img, (margin, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", int(margin * 0.7))
    except Exception:
        font = ImageFont.load_default()
    files = "abcdefgh" if white_bottom else "hgfedcba"
    ranks = "87654321" if white_bottom else "12345678"
    cell_w, cell_h = w / 8.0, h / 8.0
    for i in range(8):
        draw.text((margin + (i + 0.4) * cell_w, h + margin * 0.1), files[i], fill=(0, 0, 0), font=font)
        draw.text((margin * 0.25, (i + 0.35) * cell_h), ranks[i], fill=(0, 0, 0), font=font)
    return canvas


def to_png_bytes(img: np.ndarray, max_size: int = None, white_bottom: bool = True,
                 draw_coordinates: bool = None) -> bytes:
    max_size = max_size or config.VISION_IMAGE_MAX_SIZE
    draw_coordinates = config.VISION_DRAW_COORDINATES if draw_coordinates is None else draw_coordinates
    pil = Image.fromarray(img)
    if max(pil.size) > max_size:
        scale = max_size / float(max(pil.size))
        pil = pil.resize((int(pil.width * scale), int(pil.height * scale)), Image.LANCZOS)
    if draw_coordinates:
        pil = annotate_coordinates(pil, white_bottom)
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def to_base64_png(img: np.ndarray, **kwargs) -> str:
    return base64.b64encode(to_png_bytes(img, **kwargs)).decode("ascii")


def to_data_url(img: np.ndarray, **kwargs) -> str:
    return "data:image/png;base64," + to_base64_png(img, **kwargs)


def load_image(path: str) -> np.ndarray:
    """Baca file gambar (untuk tes offline tanpa layar)."""
    return np.asarray(Image.open(path).convert("RGB"))
