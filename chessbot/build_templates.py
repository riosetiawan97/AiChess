"""Buat template bidak dari posisi yang DIKETAHUI — py -m chessbot.build_templates

Default: papan di layar harus menampilkan POSISI AWAL. Karena posisi awal
mengandung 12 jenis bidak sekaligus kotak kosong terang & gelap, satu kali
capture langsung menghasilkan template lengkap.

Akurasi kurang? Tambah sampel dari posisi lain yang diketahui:
    py -m chessbot.build_templates --fen "<FEN posisi di layar>"
Template baru DITAMBAHKAN, tidak menimpa yang lama.
"""
import argparse
import os
import time

import chess
import cv2

from . import capture, state
from .config import TEMPLATES_DIR, load_config
from .recognize import label_to_dir


def main():
    parser = argparse.ArgumentParser(description="Ekstrak template bidak dari posisi diketahui")
    parser.add_argument("--fen", default=chess.STARTING_FEN,
                        help="FEN posisi yang sedang tampil di layar (default: posisi awal)")
    args = parser.parse_args()

    cfg = load_config()
    matrix = state.board_to_matrix(chess.Board(args.fen))  # label tiap kotak
    board_img = capture.grab_board(cfg)
    squares = capture.split_squares(board_img)

    stamp = int(time.time())
    count = 0
    for r in range(8):  # r = baris gambar (0 = atas)
        for c in range(8):
            # Petakan posisi gambar -> kotak papan sesuai orientasi
            if cfg["white_bottom"]:
                label = matrix[r][c]
            else:
                label = matrix[7 - r][7 - c]
            out_dir = os.path.join(TEMPLATES_DIR, label_to_dir(label))
            os.makedirs(out_dir, exist_ok=True)
            filename = "{}_{}{}.png".format(stamp, r, c)
            cv2.imwrite(os.path.join(out_dir, filename), squares[r][c])
            count += 1

    print("Tersimpan {} template ke {}".format(count, TEMPLATES_DIR))
    print("Uji hasilnya dengan: py -m chessbot.read_board")


if __name__ == "__main__":
    main()
