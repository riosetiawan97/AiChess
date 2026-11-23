"""Unit test modul state (jalankan: py tests/test_state.py) — tanpa dependensi CV."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess

from chessbot import state


def test_startpos_roundtrip():
    board = chess.Board()
    matrix = state.board_to_matrix(board)
    assert matrix[0] == list("rnbqkbnr")
    assert matrix[7] == list("RNBQKBNR")
    assert state.matrix_to_placement(matrix) == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    assert state.matrix_to_fen(matrix) == chess.STARTING_FEN


def test_infer_simple_move():
    board = chess.Board()
    target = chess.Board()
    target.push_san("e4")
    move = state.infer_move(board, state.board_to_matrix(target))
    assert move == chess.Move.from_uci("e2e4"), move


def test_infer_castling():
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
    board = chess.Board(fen)
    target = chess.Board(fen)
    target.push_san("O-O")
    move = state.infer_move(board, state.board_to_matrix(target))
    assert move == chess.Move.from_uci("e1g1"), move


def test_infer_en_passant():
    fen = "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"
    board = chess.Board(fen)
    target = chess.Board(fen)
    target.push_san("exf6")
    move = state.infer_move(board, state.board_to_matrix(target))
    assert move == chess.Move.from_uci("e5f6"), move


def test_infer_promotion():
    fen = "8/P6k/8/8/8/8/7K/8 w - - 0 1"
    board = chess.Board(fen)
    target = chess.Board(fen)
    target.push_san("a8=Q")
    move = state.infer_move(board, state.board_to_matrix(target))
    assert move == chess.Move.from_uci("a7a8q"), move


def test_infer_no_match():
    board = chess.Board()
    bogus = state.board_to_matrix(chess.Board())
    bogus[4][4] = "Q"  # posisi mustahil dicapai satu langkah
    assert state.infer_move(board, bogus) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK  {}".format(fn.__name__))
    print("\nSemua {} test lulus.".format(len(fns)))
