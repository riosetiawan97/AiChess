"""Kalibrasi bounding box papan catur di layar Windows.

    python calibrate.py                 # arahkan kursor ke 2 sudut papan + Enter
    python calibrate.py --roi 248 132 800 800   # isi manual (left top width height)
    python calibrate.py --check         # simpan screenshot ROI + grid untuk dicek

Hasil disimpan ke calibration.json dan otomatis dipakai config.py.
"""
import argparse
import os
import sys

import config
from PIL import Image, ImageDraw


def ask_point(label: str):
    import pyautogui
    input("  Arahkan kursor ke {} papan (tepi luar kotak), lalu tekan Enter di sini...".format(label))
    x, y = pyautogui.position()
    print("    -> ({}, {})".format(x, y))
    return x, y


def interactive():
    print("Kalibrasi papan. Buka papan catur di browser, jangan geser/zoom jendela setelah ini.")
    x1, y1 = ask_point("sudut KIRI-ATAS")
    x2, y2 = ask_point("sudut KANAN-BAWAH")
    left, top = min(x1, x2), min(y1, y2)
    w, h = abs(x2 - x1), abs(y2 - y1)
    if w < 80 or h < 80:
        sys.exit("Papan terlalu kecil ({}x{}). Ulangi kalibrasi.".format(w, h))
    if abs(w - h) > 0.05 * max(w, h):
        print("  Catatan: lebar {} dan tinggi {} beda >5% — papan biasanya persegi.".format(w, h))
    return {"left": left, "top": top, "width": w, "height": h}


def ask_choice(prompt: str, options, default: str) -> str:
    v = input("{} [{}] (default {}): ".format(prompt, "/".join(options), default)).strip().lower()
    return v if v in options else default


def check(path: str = None) -> str:
    """Simpan gambar ROI dengan grid 8x8 + nama kotak untuk verifikasi visual."""
    import screen_capture as sc

    with sc.ScreenCapture(config.BOARD_ROI) as cap:
        img = Image.fromarray(cap.grab())
    draw = ImageDraw.Draw(img)
    w, h = img.size
    wb = config.white_at_bottom()
    for i in range(9):
        draw.line([(i * w / 8, 0), (i * w / 8, h)], fill=(255, 0, 0), width=2)
        draw.line([(0, i * h / 8), (w, i * h / 8)], fill=(255, 0, 0), width=2)
    for row in range(8):
        for col in range(8):
            f = col if wb else 7 - col
            r = 7 - row if wb else row
            name = "abcdefgh"[f] + str(r + 1)
            draw.text((col * w / 8 + 4, row * h / 8 + 2), name, fill=(255, 0, 0))
    path = path or os.path.join(config.PROJECT_ROOT, "calibration_check.png")
    img.save(path)
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--roi", nargs=4, type=int, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"))
    p.add_argument("--color", choices=["white", "black"])
    p.add_argument("--bottom", choices=["auto", "white", "black"])
    p.add_argument("--check", action="store_true", help="hanya buat calibration_check.png")
    a = p.parse_args()

    if a.check:
        print("ROI sekarang:", config.BOARD_ROI)
        print("Gambar cek disimpan:", check())
        return

    roi = dict(zip(("left", "top", "width", "height"), a.roi)) if a.roi else interactive()
    color = a.color or (config.PLAYER_COLOR if a.roi else ask_choice("Warna kita", ["white", "black"], config.PLAYER_COLOR))
    bottom = a.bottom or (config.BOARD_BOTTOM if a.roi else ask_choice("Warna di bawah layar", ["auto", "white", "black"], "auto"))
    config.save_calibration(roi, bottom, color)
    config.load_calibration()
    print("Tersimpan ke {}: {}".format(config.CALIBRATION_PATH, roi))
    print("Gambar cek grid:", check())
    print("Buka gambar itu: garis merah harus pas di batas kotak dan nama kotak (a1, h8) benar.")


if __name__ == "__main__":
    main()
