"""Deliverable #3 — uji integrasi Stockfish TANPA computer vision.

Matriks 8x8 dummy -> FEN -> Stockfish -> best move + evaluasi.

    py -m chessbot.engine_demo [--movetime 1.0]
"""
import argparse

import chess

from . import state
from .config import load_config
from .engine import open_engine

# Posisi Italian Game setelah 1.e4 e5 2.Nf3 Nc6 3.Bc4 — giliran hitam.
# Ini contoh "output modul piece recognition" dalam bentuk matriks 8x8.
DUMMY_MATRIX = [
    ["r", ".", "b", "q", "k", "b", "n", "r"],
    ["p", "p", "p", "p", ".", "p", "p", "p"],
    [".", ".", "n", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", "p", ".", ".", "."],
    [".", ".", "B", ".", "P", ".", ".", "."],
    [".", ".", ".", ".", ".", "N", ".", "."],
    ["P", "P", "P", "P", ".", "P", "P", "P"],
    ["R", "N", "B", "Q", "K", ".", ".", "R"],
]


def main():
    parser = argparse.ArgumentParser(description="Demo matriks dummy -> FEN -> Stockfish")
    parser.add_argument("--movetime", type=float, default=1.0)
    args = parser.parse_args()

    print("Matriks dummy (seolah-olah hasil piece recognition):")
    for row in DUMMY_MATRIX:
        print("  " + " ".join(row))

    fen = state.matrix_to_fen(DUMMY_MATRIX, turn="b", castling="KQkq", fullmove=3)
    print("\nFEN: " + fen)

    board = chess.Board(fen)
    with open_engine(load_config()) as engine:
        move, score = engine.evaluate(board, args.movetime)
        print("Best move Stockfish : {} ({})".format(board.san(move), move.uci()))
        print("Evaluasi            : {}".format(score))
    print("\nIntegrasi matriks -> FEN -> Stockfish BERHASIL.")


if __name__ == "__main__":
    main()
