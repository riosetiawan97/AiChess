"""Vision-Action Chess Agent — loop utama.

    python main.py                       # jalan sesuai config.py
    python main.py --color black         # kita main hitam
    python main.py --mode pure_llm       # langkah langsung dari Vision LLM
    python main.py --provider ollama     # pakai Vision LLM lokal
    python main.py --dry-run             # hanya tampilkan langkah, mouse diam
    python main.py --once                # baca papan sekali lalu keluar
    python main.py --image papan.png     # tes vision dari file gambar

Hotkey: Ctrl+Shift+Q / ESC = berhenti total, F8 = pause/resume.
Fail-safe pyautogui: banting kursor ke pojok layar.

Siklus: screenshot -> (berubah?) -> tunggu stabil -> Vision LLM -> validasi
python-chess -> sinkronisasi dengan state -> keputusan -> gerak mouse.
"""
import argparse
import random
import sys
import threading
import time
from typing import Optional

import chess
import requests

import config
import decision_engine as de
import screen_capture as sc
from vision_reader import VisionError, VisionReader

try:  # Windows console default cp1252 -> paksa UTF-8 agar log tidak crash
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg: str) -> None:
    print("[{}] {}".format(time.strftime("%H:%M:%S"), msg), flush=True)


# ---------------------------------------------------------------------------
# Kill-switch & pause
# ---------------------------------------------------------------------------
class Hotkeys:
    def __init__(self, stop_event: threading.Event, pause_event: threading.Event):
        self.stop_event, self.pause_event = stop_event, pause_event
        self._listeners = []

    def start(self):
        try:
            from pynput import keyboard
        except ImportError:
            log("pynput tidak terpasang — hotkey nonaktif (fail-safe pojok layar tetap aktif)")
            return
        hk = keyboard.GlobalHotKeys({
            config.KILL_HOTKEY: self.kill,
            config.PAUSE_HOTKEY: self.toggle_pause,
        })
        hk.daemon = True
        hk.start()
        self._listeners.append(hk)
        if config.KILL_ON_ESC:
            def on_press(key):
                if key == keyboard.Key.esc:
                    self.kill()
            esc = keyboard.Listener(on_press=on_press)
            esc.daemon = True
            esc.start()
            self._listeners.append(esc)

    def kill(self):
        if not self.stop_event.is_set():
            self.stop_event.set()
            log("KILL-SWITCH ditekan — menghentikan agent.")

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            log("Lanjut (resume).")
        else:
            self.pause_event.set()
            log("PAUSE — tekan F8 lagi untuk lanjut.")

    def stop(self):
        for l in self._listeners:
            try:
                l.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class ChessAgent:
    def __init__(self, dry_run: bool = False):
        self.color = chess.WHITE if config.PLAYER_COLOR == "white" else chess.BLACK
        self.white_bottom = config.white_at_bottom()
        self.dry_run = dry_run
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

        self.cap = sc.ScreenCapture(config.BOARD_ROI)
        self.vision = VisionReader()
        self.decider = de.DecisionEngine()
        self.mouse = None
        if not dry_run:
            from mouse_controller import MouseController
            self.mouse = MouseController(config.BOARD_ROI, self.white_bottom, self.stop_event)

        self.known: Optional[chess.Board] = None       # state yang kita lacak
        self.before_our_move: Optional[str] = None     # placement sebelum langkah kita
        self.our_last_move: Optional[chess.Move] = None
        self.move_attempts = 0
        self.last_fp = None
        self.last_llm_move: Optional[str] = None

    # -- Vision + validasi dengan retry ------------------------------------
    def read_position(self, img):
        """Kembalikan (board_valid, vision_result) atau (None, None) setelah retry habis."""
        feedback = None
        hint = None
        if self.known is not None:
            hint = "w" if self.known.turn == chess.WHITE else "b"
        for attempt in range(1, config.VISION_RETRIES + 1):
            if self.stop_event.is_set():
                return None, None
            try:
                res = self.vision.read(img, self.white_bottom, config.PLAYER_COLOR,
                                       include_move=self.decider.needs_llm_move,
                                       hint_side=hint, feedback=feedback)
            except (VisionError, ValueError) as e:
                log("Vision gagal (percobaan {}): {}".format(attempt, e))
                res = None
            except Exception as e:  # timeout jaringan, dsb.
                log("Error jaringan (percobaan {}): {}".format(attempt, e))
                res = None

            if res is not None:
                log("Vision: {} | giliran={} conf={:.2f} ({:.1f}s){}".format(
                    res.fen, res.side_to_move, res.confidence, res.latency,
                    " | " + res.notes if res.notes else ""))
                if res.pieces_in_motion:
                    feedback = "Ada bidak yang masih bergerak; baca ulang."
                elif res.confidence < config.MIN_CONFIDENCE:
                    feedback = "Keyakinan rendah ({:.2f}); periksa setiap kotak lagi.".format(res.confidence)
                else:
                    try:
                        board = de.board_from_fen(res.fen)
                        return board, res
                    except de.InvalidPosition as e:
                        feedback = str(e)
                        log("FEN ditolak python-chess: {}".format(e))
                if attempt == config.VISION_RETRIES and res.confidence >= 0.2 and not res.pieces_in_motion:
                    # Percobaan terakhir: terima jika FEN tetap valid walau conf rendah
                    try:
                        return de.board_from_fen(res.fen), res
                    except de.InvalidPosition:
                        pass

            time.sleep(config.RETRY_DELAY)  # tunggu animasi selesai
            img, _ = sc.wait_for_stable(self.cap, stop_event=self.stop_event)
        return None, None

    # -- Sinkronisasi state ------------------------------------------------
    def sync(self, seen: chess.Board, res, img) -> bool:
        """Perbarui self.known dari papan yang terlihat. False = abaikan frame ini."""
        status, move = de.reconcile(self.known, seen.board_fen())
        if status == de.SAME:
            if self.before_our_move is not None:
                log("Langkah kita {} terkonfirmasi di layar.".format(self.our_last_move.uci()))
                self.before_our_move = None
                self.move_attempts = 0
            return True
        if status == de.ONE_MOVE:
            who = "Lawan" if self.known.turn != self.color else "Kita (manual)"
            log("{} melangkah: {} ({})".format(who, self.known.san(move), move.uci()))
            self.known.push(move)
            self.before_our_move = None
            self.move_attempts = 0
            return True

        # RESYNC: layar tidak cocok dengan state yang dilacak.
        if self.before_our_move is not None and seen.board_fen() == self.before_our_move:
            log("Langkah kita {} tidak masuk di layar — akan dicoba lagi.".format(self.our_last_move.uci()))
            self.known.pop()
            self.before_our_move = None
            self.move_attempts += 1
            if self.move_attempts >= 3:
                log("Gagal 3x mengeksekusi langkah. Cek kalibrasi / MOUSE_STYLE. Agent di-pause.")
                self.pause_event.set()
                return False
            return True

        if self.known is not None:
            # Konfirmasi dengan pembacaan kedua agar salah baca LLM tidak merusak state
            log("Posisi tidak nyambung dengan state — konfirmasi pembacaan kedua...")
            seen2, res2 = self.read_position(img)
            if seen2 is None or seen2.board_fen() != seen.board_fen():
                log("Pembacaan tidak konsisten — frame diabaikan.")
                return False
            res = res2
        seen.turn = chess.WHITE if res.side_to_move == "w" else chess.BLACK
        seen.castling_rights = seen.clean_castling_rights()
        self.known = seen
        self.before_our_move = None
        self.last_llm_move = res.best_move_uci
        log("State disinkronkan ulang: {}".format(self.known.fen()))
        return True

    # -- Eksekusi ----------------------------------------------------------
    def maybe_move(self, res) -> None:
        if self.known is None or self.known.turn != self.color or self.before_our_move:
            return
        if self.known.is_game_over():
            log("Game selesai: {}".format(self.known.result()))
            return
        llm_move = res.best_move_uci if res is not None else None
        decision = self.decider.decide(self.known, llm_move)
        if decision.move is None:
            log("Tidak ada langkah: {}".format(decision.note))
            return
        log("Langkah terbaik [{}]: {} ({}) {}{}".format(
            decision.source, self.known.san(decision.move), decision.move.uci(),
            decision.score, " — " + decision.note if decision.note else ""))

        if self.dry_run:
            log("(dry-run) mouse tidak digerakkan.")
            self.known.push(decision.move)  # anggap kita sudah jalan
            return

        time.sleep(random.uniform(*config.MOVE_DELAY_RANGE))
        if self.stop_event.is_set() or self.pause_event.is_set():
            return
        self.before_our_move = self.known.board_fen()
        self.our_last_move = decision.move
        self.mouse.execute(decision.move)
        self.known.push(decision.move)

    # -- Loop --------------------------------------------------------------
    def step(self, force: bool = False) -> None:
        img = self.cap.grab()
        fp = sc.fingerprint(img)
        if not force and sc.frame_diff(fp, self.last_fp) < config.CHANGE_THRESHOLD:
            return  # papan tidak berubah -> tidak memanggil API
        img, fp = sc.wait_for_stable(self.cap, stop_event=self.stop_event)
        seen, res = self.read_position(img)
        self.last_fp = fp  # tandai frame ini sudah diproses (hemat API)
        if seen is None:
            log("Gagal membaca posisi valid setelah {} percobaan.".format(config.VISION_RETRIES))
            return
        if self.sync(seen, res, img):
            self.maybe_move(res)
            if self.before_our_move is not None:
                # tunggu layar menampilkan langkah kita sebelum frame berikutnya
                time.sleep(0.3)

    def run(self, once: bool = False) -> None:
        hotkeys = Hotkeys(self.stop_event, self.pause_event)
        hotkeys.start()
        log("Agent jalan | warna={} | mode={} | provider={} ({}) | papan={} | putih di {}".format(
            config.PLAYER_COLOR, self.decider.mode, self.vision.s["provider"], self.vision.s["model"],
            config.BOARD_ROI, "bawah" if self.white_bottom else "atas"))
        log("Stop: {} / ESC | Pause: {} | Fail-safe: kursor ke pojok layar".format(
            config.KILL_HOTKEY, config.PAUSE_HOTKEY))
        try:
            first = True
            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    time.sleep(0.2)
                    self.last_fp = None  # setelah resume, baca ulang
                    continue
                try:
                    self.step(force=first)
                except Exception as e:
                    if type(e).__name__ in ("MoveAborted", "FailSafeException"):
                        log("Gerakan mouse dibatalkan: {}".format(e))
                        self.stop_event.set()
                        break
                    raise
                first = False
                if once:
                    break
                time.sleep(config.POLL_INTERVAL)
        except KeyboardInterrupt:
            log("Ctrl+C — berhenti.")
        finally:
            hotkeys.stop()
            if self.mouse:
                self.mouse.release()
            self.decider.close()
            self.cap.close()
            log("Selesai. Total panggilan Vision API: {}".format(self.vision.calls))


def analyze_image(path: str) -> None:
    """Tes offline: baca gambar papan dari file, validasi, dan beri langkah."""
    img = sc.load_image(path)
    vision = VisionReader()
    decider = de.DecisionEngine()
    try:
        res = vision.read(img, config.white_at_bottom(), config.PLAYER_COLOR,
                          include_move=decider.needs_llm_move)
        log("FEN Vision : {}".format(res.fen))
        log("Giliran    : {} | confidence {:.2f} | {}".format(res.side_to_move, res.confidence, res.notes))
        board = de.board_from_fen(res.fen)
        log("FEN valid  : {}".format(board.fen()))
        print(board)
        d = decider.decide(board, res.best_move_uci)
        if d.move:
            log("Langkah [{}]: {} ({}) {}".format(d.source, board.san(d.move), d.move.uci(), d.score))
        else:
            log("Tidak ada langkah: {}".format(d.note))
    except de.InvalidPosition as e:
        log("FEN tidak valid: {}".format(e))
    except requests.RequestException as e:
        log("Gagal menghubungi Vision LLM: {}".format(e))
    finally:
        decider.close()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Vision-Action Chess Agent")
    p.add_argument("--color", choices=["white", "black"], help="warna kita (default: config)")
    p.add_argument("--bottom", choices=["auto", "white", "black"], help="warna di bawah layar")
    p.add_argument("--mode", choices=["hybrid", "pure_llm"], help="mode keputusan")
    p.add_argument("--provider", choices=sorted(config.VISION_PROVIDERS), help="preset Vision LLM")
    p.add_argument("--model", help="override nama model")
    p.add_argument("--style", choices=["drag", "click"], help="gaya gerakan mouse")
    p.add_argument("--dry-run", action="store_true", help="jangan gerakkan mouse")
    p.add_argument("--once", action="store_true", help="baca sekali lalu keluar")
    p.add_argument("--image", help="analisis file gambar papan (tanpa layar/mouse)")
    p.add_argument("--debug-images", action="store_true", help="simpan gambar yang dikirim ke LLM")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    if a.color:
        config.PLAYER_COLOR = a.color
    if a.bottom:
        config.BOARD_BOTTOM = a.bottom
    if a.mode:
        config.DECISION_MODE = a.mode
    if a.provider:
        config.VISION_PROVIDER = a.provider
    if a.model:
        config.VISION_MODEL_OVERRIDE = a.model
    if a.style:
        config.MOUSE_STYLE = a.style
    if a.debug_images:
        config.SAVE_DEBUG_IMAGES = True

    try:
        if a.image:
            analyze_image(a.image)
            return 0
        ChessAgent(dry_run=a.dry_run or a.once).run(once=a.once)
        return 0
    except (VisionError, FileNotFoundError, ValueError) as e:
        log("ERROR: {}".format(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
