"""Integrasi Stockfish via protokol UCI (python-chess)."""
import os
from typing import Optional

import chess
import chess.engine

from .config import resolve_engine_path


class Engine:
    """Wrapper tipis di atas chess.engine.SimpleEngine."""

    def __init__(
        self,
        path: str,
        skill_level: int = 20,
        elo: Optional[int] = None,
        threads: int = 2,
        hash_mb: int = 128,
    ):
        if not os.path.exists(path):
            raise FileNotFoundError(
                "Stockfish tidak ditemukan di: {}\n"
                "Unduh dari https://stockfishchess.org/download/ lalu taruh "
                "binary-nya di folder stockfish/ (atau ubah engine_path di "
                "config.json).".format(path)
            )
        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self._configure("Threads", threads)
        self._configure("Hash", hash_mb)
        if elo is not None:
            # Batasi kekuatan supaya langkah lebih "manusiawi"
            self._configure("UCI_LimitStrength", True)
            self._configure("UCI_Elo", elo)
        else:
            self._configure("Skill Level", skill_level)

    def _configure(self, name: str, value) -> None:
        if name in self.engine.options:
            self.engine.configure({name: value})

    def best_move(self, board: chess.Board, movetime: float = 1.0) -> chess.Move:
        result = self.engine.play(board, chess.engine.Limit(time=movetime))
        return result.move

    def evaluate(self, board: chess.Board, movetime: float = 1.0):
        """Kembalikan (best_move, skor dari sudut pandang pemain yang jalan)."""
        info = self.engine.analyse(board, chess.engine.Limit(time=movetime))
        pv = info.get("pv")
        move = pv[0] if pv else None
        return move, info.get("score")

    def close(self) -> None:
        self.engine.quit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_engine(cfg: dict, **kwargs) -> Engine:
    return Engine(resolve_engine_path(cfg), **kwargs)
