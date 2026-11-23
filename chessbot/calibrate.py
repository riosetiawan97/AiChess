"""Tool kalibrasi papan — jalankan sekali: py -m chessbot.calibrate

Cara pakai:
1. Buka papan catur di layar (jangan tertutup jendela lain).
2. Jalankan tool ini. Screenshot layar akan muncul di jendela OpenCV.
3. Klik sudut KIRI-ATAS papan, lalu sudut KANAN-BAWAH papan
   (tepat di pojok area 8x8, tanpa koordinat/label di pinggir).
4. Jawab pertanyaan orientasi di terminal. Koordinat tersimpan ke config.json
   dan preview grid tersimpan ke calibration_preview.png untuk dicek.
"""
import argparse

import cv2

from . import capture
from .config import PROJECT_ROOT, load_config, save_config

MAX_DISPLAY_WIDTH = 1400


def main():
    parser = argparse.ArgumentParser(description="Kalibrasi posisi papan di layar")
    parser.add_argument("--monitor", type=int, default=1, help="Index monitor mss (default 1)")
    args = parser.parse_args()

    screen = capture.grab_screen(args.monitor)
    h, w = screen.shape[:2]
    scale = min(1.0, MAX_DISPLAY_WIDTH / w)
    display = cv2.resize(screen, (int(w * scale), int(h * scale))) if scale < 1.0 else screen.copy()

    clicks = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 2:
            clicks.append((int(x / scale), int(y / scale)))
            cv2.circle(display, (x, y), 6, (0, 0, 255), -1)
            cv2.imshow("Kalibrasi", display)

    print("Klik sudut KIRI-ATAS papan, lalu sudut KANAN-BAWAH. (ESC untuk batal)")
    cv2.imshow("Kalibrasi", display)
    cv2.setMouseCallback("Kalibrasi", on_mouse)
    while len(clicks) < 2:
        if cv2.waitKey(50) == 27:
            print("Dibatalkan.")
            cv2.destroyAllWindows()
            return
    cv2.destroyAllWindows()

    (x1, y1), (x2, y2) = clicks
    left, top = min(x1, x2), min(y1, y2)
    width, height = abs(x2 - x1), abs(y2 - y1)
    if width < 100 or height < 100:
        print("Area terlalu kecil ({}x{}). Ulangi kalibrasi.".format(width, height))
        return
    if abs(width - height) > 0.03 * max(width, height):
        print("Peringatan: area tidak persegi ({}x{}) — pastikan klik tepat di pojok.".format(width, height))
    size = round((width + height) / 2)

    ans = input("Apakah bidak PUTIH ada di sisi bawah papan? [Y/n] ").strip().lower()
    white_bottom = ans not in ("n", "no", "tidak")

    cfg = load_config()
    cfg["board"] = {"left": left, "top": top, "size": size}
    cfg["white_bottom"] = white_bottom
    save_config(cfg)

    # Simpan preview grid supaya user bisa verifikasi hasil kalibrasi
    board_img = capture.grab_board(cfg)
    cell = size / 8.0
    for i in range(9):
        p = int(i * cell)
        cv2.line(board_img, (p, 0), (p, size), (0, 255, 0), 1)
        cv2.line(board_img, (0, p), (size, p), (0, 255, 0), 1)
    preview_path = PROJECT_ROOT + "/calibration_preview.png"
    cv2.imwrite(preview_path, board_img)

    print("Tersimpan: board = left={}, top={}, size={}, white_bottom={}".format(
        left, top, size, white_bottom))
    print("Cek {} — garis hijau harus pas di batas kotak.".format(preview_path))


if __name__ == "__main__":
    main()
