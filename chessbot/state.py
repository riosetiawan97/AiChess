"""Representasi state papan: matriks 8x8 <-> FEN, dan inferensi langkah.

Konvensi matriks: list 8x8 berisi karakter bidak ('P','n','.', dst.)
dengan row 0 = rank 8 dan col 0 = file a (orientasi standar, TIDAK
tergantung orientasi papan di layar).
"""
from typing import List, Optional

import chess

Matrix = List[List[str]]


def board_to_matrix(board: chess.Board) -> Matrix:
    """Konversi chess.Board menjadi matriks 8x8."""
    matrix = []
    for rank in range(7, -1, -1):  # rank 8 -> 1
        row = []
        for file in range(8):  # file a -> h
            piece = board.piece_at(chess.square(file, rank))
            row.append(piece.symbol() if piece else ".")
        matrix.append(row)
    return matrix


def matrix_to_placement(matrix: Matrix) -> str:
    """Bagian pertama FEN (penempatan bidak) dari matriks 8x8."""
    ranks = []
    for row in matrix:
        rank_str = ""
        empty = 0
        for cell in row:
            if cell == ".":
                empty += 1
            else:
                if empty:
                    rank_str += str(empty)
                    empty = 0
                rank_str += cell
        if empty:
            rank_str += str(empty)
        ranks.append(rank_str)
    return "/".join(ranks)


def matrix_to_fen(
    matrix: Matrix,
    turn: str = "w",
    castling: str = "KQkq",
    en_passant: str = "-",
    halfmove: int = 0,
    fullmove: int = 1,
) -> str:
    """FEN lengkap dari matriks + info tambahan.

    Catatan: castling/en passant tidak bisa dibaca dari satu gambar saja.
    Untuk permainan penuh gunakan infer_move() yang men-tracking otomatis.
    """
    fen = "{} {} {} {} {} {}".format(
        matrix_to_placement(matrix), turn, castling, en_passant, halfmove, fullmove
    )
    # Validasi — melempar ValueError jika FEN tidak masuk akal
    chess.Board(fen)
    return fen


def square_name(row: int, col: int) -> str:
    """Nama kotak (mis. 'e2') dari indeks matriks (row 0 = rank 8)."""
    return chr(ord("a") + col) + str(8 - row)


def diff_squares(m1: Matrix, m2: Matrix):
    """Daftar (kotak, isi_m1, isi_m2) untuk semua kotak yang berbeda."""
    return [
        (square_name(r, c), m1[r][c], m2[r][c])
        for r in range(8)
        for c in range(8)
        if m1[r][c] != m2[r][c]
    ]


def infer_move(board: chess.Board, new_matrix: Matrix) -> Optional[chess.Move]:
    """Cari langkah legal pada `board` yang menghasilkan `new_matrix`.

    Ini kunci orkestrasi: karena kita mencoba langkah LEGAL satu per satu,
    rokade, en passant, dan promosi terdeteksi dengan benar, dan internal
    board otomatis menyimpan hak rokade / target en passant untuk FEN.
    """
    for move in board.legal_moves:
        board.push(move)
        match = board_to_matrix(board) == new_matrix
        board.pop()
        if match:
            return move
    return None
