"""Validasi FEN (python-chess), sinkronisasi state papan, dan pemilihan langkah.

Mode:
- hybrid   : FEN dari Vision LLM divalidasi lalu Stockfish menghitung langkah.
- pure_llm : langkah UCI dari Vision LLM dipakai jika legal; kalau tidak,
             (opsional) jatuh ke Stockfish.
"""
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import chess
import chess.engine

import config


class InvalidPosition(ValueError):
    pass


# ---------------------------------------------------------------------------
# Validasi FEN
# ---------------------------------------------------------------------------
def board_from_fen(fen: str) -> chess.Board:
    """Bangun chess.Board dari FEN Vision LLM dan pastikan sah secara aturan.

    Field yang sering salah dibaca (hak rokade, en passant) dibersihkan dulu
    agar FEN yang penempatannya benar tidak ditolak hanya karena metadata.
    """
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise InvalidPosition("FEN tidak bisa di-parse: {} ({})".format(fen, e))

    board.castling_rights = board.clean_castling_rights()
    if board.ep_square is not None and not board.has_legal_en_passant():
        board.ep_square = None

    status = board.status()
    if status != chess.STATUS_VALID:
        reasons = [name for name, flag in _STATUS_FLAGS if status & flag]
        raise InvalidPosition("Posisi ilegal ({}): {}".format(", ".join(reasons), board.fen()))
    return board


_STATUS_FLAGS = [
    ("tanpa raja putih", chess.STATUS_NO_WHITE_KING),
    ("tanpa raja hitam", chess.STATUS_NO_BLACK_KING),
    ("raja lebih dari satu", chess.STATUS_TOO_MANY_KINGS),
    ("pion putih > 8", chess.STATUS_TOO_MANY_WHITE_PAWNS),
    ("pion hitam > 8", chess.STATUS_TOO_MANY_BLACK_PAWNS),
    ("pion di rank 1/8", chess.STATUS_PAWNS_ON_BACKRANK),
    ("bidak putih > 16", chess.STATUS_TOO_MANY_WHITE_PIECES),
    ("bidak hitam > 16", chess.STATUS_TOO_MANY_BLACK_PIECES),
    ("hak rokade salah", chess.STATUS_BAD_CASTLING_RIGHTS),
    ("en passant salah", chess.STATUS_INVALID_EP_SQUARE),
    ("raja lawan sedang di-skak (bukan giliran)", chess.STATUS_OPPOSITE_CHECK),
    ("skak dari terlalu banyak bidak", chess.STATUS_TOO_MANY_CHECKERS),
    ("skak mustahil", chess.STATUS_IMPOSSIBLE_CHECK),
]


def placement(board: chess.Board) -> str:
    return board.board_fen()


# ---------------------------------------------------------------------------
# Sinkronisasi dengan state yang kita lacak sendiri
# ---------------------------------------------------------------------------
SAME = "same"            # layar = posisi yang sudah kita ketahui
ONE_MOVE = "one_move"    # layar = posisi lama + tepat satu langkah legal
RESYNC = "resync"        # tidak nyambung -> percaya hasil vision


def reconcile(known: Optional[chess.Board], seen_placement: str) -> Tuple[str, Optional[chess.Move]]:
    """Cocokkan penempatan bidak dari layar dengan board yang kita lacak.

    Jika layar = ``known`` + satu langkah legal, kita tahu langkah lawan secara
    pasti (termasuk rokade/en passant/promosi) dan giliran tidak perlu ditebak
    dari gambar. Ini juga menyaring kesalahan baca LLM yang kecil.
    """
    if known is None:
        return RESYNC, None
    if placement(known) == seen_placement:
        return SAME, None
    for move in known.legal_moves:
        known.push(move)
        match = placement(known) == seen_placement
        known.pop()
        if match:
            return ONE_MOVE, move
    return RESYNC, None


# ---------------------------------------------------------------------------
# Stockfish
# ---------------------------------------------------------------------------
class Stockfish:
    def __init__(self, path: str = None):
        path = path or config.STOCKFISH_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(
                "Stockfish tidak ditemukan di {}. Unduh dari https://stockfishchess.org/download/ "
                "lalu taruh di folder stockfish/ atau ubah STOCKFISH_PATH di config.py.".format(path)
            )
        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self._opt("Threads", config.ENGINE_THREADS)
        self._opt("Hash", config.ENGINE_HASH_MB)
        if config.ENGINE_ELO:
            self._opt("UCI_LimitStrength", True)
            self._opt("UCI_Elo", int(config.ENGINE_ELO))
        else:
            self._opt("Skill Level", int(config.ENGINE_SKILL_LEVEL))

    def _opt(self, name, value):
        if name in self.engine.options:
            self.engine.configure({name: value})

    def best_move(self, board: chess.Board, movetime: float = None):
        info = self.engine.analyse(board, chess.engine.Limit(time=movetime or config.ENGINE_MOVETIME))
        pv = info.get("pv") or []
        move = pv[0] if pv else self.engine.play(board, chess.engine.Limit(time=0.1)).move
        return move, info.get("score")

    def close(self):
        try:
            self.engine.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Keputusan
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    move: Optional[chess.Move]
    source: str           # "stockfish" / "llm" / "stockfish-fallback" / "none"
    score: str = ""
    note: str = ""


def parse_uci(board: chess.Board, uci: Optional[str]) -> Optional[chess.Move]:
    """Ubah string UCI dari LLM jadi Move legal, atau None jika ilegal/rusak."""
    if not uci:
        return None
    raw = uci.strip().replace(" ", "")
    try:
        move = chess.Move.from_uci(raw.lower().replace("-", ""))
    except ValueError:
        try:
            move = board.parse_san(raw)  # LLM kadang memberi SAN (Nf3)
        except ValueError:
            return None
    # Promosi tanpa huruf bidak -> default ratu
    if move not in board.legal_moves and move.promotion is None:
        promo = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
        if promo in board.legal_moves:
            move = promo
    return move if move in board.legal_moves else None


class DecisionEngine:
    def __init__(self, mode: str = None):
        self.mode = mode or config.DECISION_MODE
        if self.mode not in ("hybrid", "pure_llm"):
            raise ValueError("DECISION_MODE harus 'hybrid' atau 'pure_llm'")
        self.stockfish = None
        if self.mode == "hybrid" or config.PURE_LLM_FALLBACK_TO_ENGINE:
            try:
                self.stockfish = Stockfish()
            except FileNotFoundError:
                if self.mode == "hybrid":
                    raise

    @property
    def needs_llm_move(self) -> bool:
        return self.mode == "pure_llm"

    def decide(self, board: chess.Board, llm_move_uci: Optional[str] = None) -> Decision:
        if board.is_game_over():
            return Decision(None, "none", note="Game selesai: " + board.result())

        if self.mode == "pure_llm":
            move = parse_uci(board, llm_move_uci)
            if move is not None:
                return Decision(move, "llm")
            note = "Langkah LLM '{}' ilegal".format(llm_move_uci)
            if self.stockfish is None:
                return Decision(None, "none", note=note)
            move, score = self.stockfish.best_move(board)
            return Decision(move, "stockfish-fallback", str(score), note)

        move, score = self.stockfish.best_move(board)
        return Decision(move, "stockfish", str(score))

    def close(self):
        if self.stockfish:
            self.stockfish.close()
