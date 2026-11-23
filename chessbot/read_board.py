"""Uji pipeline CV: capture -> recognize -> matriks + FEN. Tanpa engine, tanpa mouse.

    py -m chessbot.read_board [--turn w|b]
"""
import argparse

from . import capture, state
from .config import load_config
from .recognize import Recognizer


def main():
    parser = argparse.ArgumentParser(description="Baca papan dari layar dan cetak FEN")
    parser.add_argument("--turn", choices=["w", "b"], default="w", help="Giliran jalan (untuk FEN)")
    args = parser.parse_args()

    cfg = load_config()
    recognizer = Recognizer()
    board_img = capture.grab_board(cfg)
    matrix = recognizer.matrix_from_image(board_img, cfg["white_bottom"])

    print("Hasil pembacaan papan:")
    for row in matrix:
        print("  " + " ".join(row))
    try:
        fen = state.matrix_to_fen(matrix, turn=args.turn)
        print("\nFEN: " + fen)
    except ValueError as e:
        print("\nPosisi tidak valid sebagai FEN: {}".format(e))


if __name__ == "__main__":
    main()
