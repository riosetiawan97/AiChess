"""Loop utama: capture -> recognize -> infer move -> Stockfish -> (advise|auto).

    py -m chessbot.main --color w                  # mode advise (default, aman)
    py -m chessbot.main --color b --mode auto      # mouse bergerak sendiri

Desain penting:
- Internal chess.Board adalah "sumber kebenaran". Layar hanya dipakai untuk
  MENDETEKSI langkah (diff matriks + pencocokan langkah legal), sehingga
  castling rights & en passant selalu akurat tanpa perlu dibaca dari gambar.
- Di mode auto pun langkah kita sendiri dideteksi balik dari layar sebelum
  di-push — sekaligus verifikasi bahwa drag mouse benar-benar berhasil.

PERINGATAN: mode auto hanya untuk papan yang mengizinkan otomatisasi
(GUI lokal, papan analisis, vs komputer, riset). Dipakai di game online
melawan manusia = cheating + pelanggaran ToS + ban.
"""
import argparse
import time

import chess

from . import mouse, state
from .config import load_config
from .engine import open_engine
from .recognize import Recognizer


def stable_matrix(recognizer, cfg, gap: float = 0.15):
    """Baca papan dua kali; terima hanya jika identik (hindari frame animasi)."""
    from . import capture

    m1 = recognizer.matrix_from_image(capture.grab_board(cfg), cfg["white_bottom"])
    time.sleep(gap)
    m2 = recognizer.matrix_from_image(capture.grab_board(cfg), cfg["white_bottom"])
    return m1 if m1 == m2 else None


def main():
    parser = argparse.ArgumentParser(description="Chess bot loop")
    parser.add_argument("--color", choices=["w", "b"], default="w", help="Warna kita")
    parser.add_argument("--mode", choices=["advise", "auto"], default="advise",
                        help="advise: hanya menampilkan langkah; auto: gerakkan mouse")
    parser.add_argument("--fen", default=chess.STARTING_FEN, help="Posisi awal game")
    parser.add_argument("--movetime", type=float, default=1.0, help="Waktu pikir engine (detik)")
    parser.add_argument("--elo", type=int, default=None, help="Batasi kekuatan engine (mis. 1500)")
    parser.add_argument("--skill", type=int, default=20, help="Skill Level 0-20 (dipakai jika --elo kosong)")
    parser.add_argument("--interval", type=float, default=0.7, help="Jeda polling (detik)")
    parser.add_argument("--style", choices=["drag", "click"], default="drag")
    args = parser.parse_args()

    cfg = load_config()
    our_color = chess.WHITE if args.color == "w" else chess.BLACK
    board = chess.Board(args.fen)
    recognizer = Recognizer()
    engine = open_engine(cfg, skill_level=args.skill, elo=args.elo)

    if args.mode == "auto":
        print("MODE AUTO — pastikan target papan mengizinkan otomatisasi.")
        print("Darurat: banting kursor ke pojok kiri-atas layar untuk abort.\n")

    last_advised_fen = None
    last_auto_fen = None
    print("Berjalan. Ctrl+C untuk berhenti.\n")
    try:
        while not board.is_game_over():
            matrix = stable_matrix(recognizer, cfg)
            if matrix is None:
                time.sleep(args.interval)
                continue

            if matrix != state.board_to_matrix(board):
                # Papan di layar berubah -> cari langkah legal yang cocok
                move = state.infer_move(board, matrix)
                if move is not None:
                    print("Terdeteksi: {} ({})".format(board.san(move), move.uci()))
                    board.push(move)
                else:
                    print("! Papan tidak cocok dengan langkah legal mana pun "
                          "(salah baca CV / out of sync). Menunggu frame berikut...")
            elif board.turn == our_color:
                fen = board.fen()
                if args.mode == "advise":
                    if fen != last_advised_fen:
                        move, score = engine.evaluate(board, args.movetime)
                        print(">> Saran: {} ({})  eval: {}".format(
                            board.san(move), move.uci(), score))
                        last_advised_fen = fen
                elif fen != last_auto_fen:
                    move = engine.best_move(board, args.movetime)
                    print(">> Menjalankan: {} ({})".format(board.san(move), move.uci()))
                    mouse.execute_move(move, cfg, style=args.style)
                    last_auto_fen = fen  # jangan ulangi drag untuk posisi sama
                    # push TIDAK dilakukan di sini — loop akan mendeteksinya
                    # dari layar (sekaligus verifikasi drag berhasil)

            time.sleep(args.interval)

        print("\nGame selesai: {}".format(board.result()))
    except KeyboardInterrupt:
        print("\nDihentikan.")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
