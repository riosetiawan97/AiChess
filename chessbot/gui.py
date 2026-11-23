"""Panel kontrol GUI (Tkinter) — jalankan: py -m chessbot.gui

Semua alur jadi tombol: Kalibrasi -> Buat Template -> Tes Baca -> Start.
Kalibrasi dilakukan langsung di GUI: layar dibekukan fullscreen, klik
sudut kiri-atas lalu kanan-bawah papan (ESC untuk batal).

Penting: saat bot berjalan, jendela panel TIDAK BOLEH menutupi papan.
"""
import glob
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import chess
import cv2
import pyautogui  # noqa: F401 — import ini membuat proses DPI-aware (mapping klik 1:1)

from . import capture, mouse, state
from .config import PROJECT_ROOT, TEMPLATES_DIR, load_config, resolve_engine_path, save_config
from .engine import Engine
from .recognize import Recognizer


def fmt_score(score, color) -> str:
    """Format PovScore jadi teks singkat dari sudut pandang kita, mis. +0.35 / M3."""
    if score is None:
        return "?"
    pov = score.pov(color)
    if pov.is_mate():
        return "M{}".format(pov.mate())
    return "{:+.2f}".format(pov.score(mate_score=10000) / 100.0)


class BotThread(threading.Thread):
    """Loop capture->detect->engine->(advise|auto) di thread terpisah.

    Komunikasi ke GUI hanya lewat queue (thread-safe): ("log"|"suggest"|"stopped", teks).
    """

    def __init__(self, cfg: dict, opts: dict, out: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.cfg, self.opts, self.out, self.stop_event = cfg, opts, out, stop_event

    def emit(self, kind: str, payload=None):
        self.out.put((kind, payload))

    def stable_matrix(self, recognizer):
        m1 = recognizer.matrix_from_image(capture.grab_board(self.cfg), self.cfg["white_bottom"])
        time.sleep(0.15)
        m2 = recognizer.matrix_from_image(capture.grab_board(self.cfg), self.cfg["white_bottom"])
        return m1 if m1 == m2 else None

    def save_debug(self, recognizer):
        """Simpan apa yang 'dilihat' bot: crop papan + grid + label hasil klasifikasi."""
        img = capture.grab_board(self.cfg).copy()
        squares = capture.split_squares(img)
        cell = img.shape[0] / 8.0
        for i in range(9):
            p = int(i * cell)
            cv2.line(img, (p, 0), (p, img.shape[0]), (0, 255, 0), 1)
            cv2.line(img, (0, p), (img.shape[1], p), (0, 255, 0), 1)
        for r in range(8):
            for c in range(8):
                label = recognizer.classify_square(squares[r][c])
                cv2.putText(img, label, (int(c * cell) + 4, int(r * cell) + 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        path = os.path.join(PROJECT_ROOT, "debug_desync.png")
        cv2.imwrite(path, img)
        return path

    def run(self):
        o = self.opts
        our_color = chess.WHITE if o["color"] == "w" else chess.BLACK
        board = chess.Board()
        try:
            recognizer = Recognizer()
            engine = Engine(resolve_engine_path(self.cfg), elo=o["elo"])
        except Exception as e:
            self.emit("log", "Gagal start: {}".format(e))
            self.emit("stopped")
            return

        self.emit("log", "Bot berjalan — mode {}, kita main {}.".format(
            o["mode"], "PUTIH" if our_color else "HITAM"))
        last_hint_fen = None
        desync_count = 0
        try:
            while not self.stop_event.is_set() and not board.is_game_over():
                matrix = self.stable_matrix(recognizer)
                if matrix is None:
                    self.stop_event.wait(0.4)
                    continue

                internal = state.board_to_matrix(board)
                if matrix == internal:
                    desync_count = 0
                if matrix != internal:
                    move = state.infer_move(board, matrix)
                    if move is not None:
                        desync_count = 0
                        san = board.san(move)
                        board.push(move)
                        self.emit("log", "Terdeteksi: {}".format(san))
                    else:
                        desync_count += 1
                        if desync_count <= 3 or desync_count % 10 == 0:
                            diffs = state.diff_squares(state.board_to_matrix(board), matrix)
                            detail = ", ".join(
                                "{}: {}→{}".format(sq, a, b) for sq, a, b in diffs[:8])
                            if len(diffs) > 8:
                                detail += " (+{} lagi)".format(len(diffs) - 8)
                            self.emit("log", "! Tidak sinkron, {} kotak beda: {}".format(
                                len(diffs), detail))
                        if desync_count == 3:
                            path = self.save_debug(recognizer)
                            self.emit("log", "Snapshot pandangan bot tersimpan: {}".format(
                                os.path.basename(path)))
                            self.emit("log", "Banyak kotak beda biasanya = papan BERGESER "
                                             "sejak kalibrasi (layout situs berubah). "
                                             "STOP lalu Kalibrasi ulang (tombol 1).")
                elif board.turn == our_color and board.fen() != last_hint_fen:
                    move, score = engine.evaluate(board, o["movetime"])
                    if move is None:
                        break
                    text = "{}   {}".format(board.san(move), fmt_score(score, our_color))
                    self.emit("suggest", text)
                    if o["mode"] == "auto":
                        self.emit("log", ">> Menjalankan: {}".format(text))
                        mouse.execute_move(move, self.cfg)
                    else:
                        self.emit("log", ">> Saran: {}".format(text))
                    last_hint_fen = board.fen()

                self.stop_event.wait(0.6)

            if board.is_game_over():
                self.emit("suggest", "Selesai  {}".format(board.result()))
                self.emit("log", "Game selesai: {}".format(board.result()))
        except Exception as e:
            self.emit("log", "Error: {!r}".format(e))
        finally:
            engine.close()
            self.emit("stopped")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.bot = None

        root.title("AiChess — Panel Kontrol")
        root.attributes("-topmost", True)  # tetap di atas, tapi jangan tutupi papan
        root.resizable(False, False)

        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(root, padding=10)
        main.grid(sticky="nsew")

        # --- Status kalibrasi/template/engine ---
        self.status_var = tk.StringVar()
        ttk.Label(main, textvariable=self.status_var, foreground="#555").grid(
            row=0, column=0, columnspan=4, sticky="w", **pad)

        # --- Tombol persiapan ---
        prep = ttk.LabelFrame(main, text="Persiapan (urut, sekali saja)", padding=6)
        prep.grid(row=1, column=0, columnspan=4, sticky="ew", **pad)
        ttk.Button(prep, text="1. Kalibrasi Papan", command=self.calibrate).grid(row=0, column=0, **pad)
        ttk.Button(prep, text="2. Buat Template", command=self.build_templates).grid(row=0, column=1, **pad)
        ttk.Button(prep, text="3. Tes Baca Papan", command=self.test_read).grid(row=0, column=2, **pad)

        # --- Opsi ---
        opts = ttk.LabelFrame(main, text="Opsi", padding=6)
        opts.grid(row=2, column=0, columnspan=4, sticky="ew", **pad)

        self.color_var = tk.StringVar(value="w")
        ttk.Label(opts, text="Warna kita:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Radiobutton(opts, text="Putih", variable=self.color_var, value="w").grid(row=0, column=1)
        ttk.Radiobutton(opts, text="Hitam", variable=self.color_var, value="b").grid(row=0, column=2)

        self.mode_var = tk.StringVar(value="advise")
        ttk.Label(opts, text="Mode:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Radiobutton(opts, text="Advise (saran saja)", variable=self.mode_var,
                        value="advise").grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(opts, text="Auto (mouse jalan sendiri)", variable=self.mode_var,
                        value="auto").grid(row=2, column=1, columnspan=2, sticky="w")

        ttk.Label(opts, text="Waktu pikir (dtk):").grid(row=3, column=0, sticky="w", **pad)
        self.movetime_var = tk.StringVar(value="1.0")
        ttk.Spinbox(opts, from_=0.1, to=10.0, increment=0.1, width=6,
                    textvariable=self.movetime_var).grid(row=3, column=1, sticky="w")

        ttk.Label(opts, text="Batas Elo (kosong = full):").grid(row=4, column=0, sticky="w", **pad)
        self.elo_var = tk.StringVar(value="")
        ttk.Entry(opts, width=8, textvariable=self.elo_var).grid(row=4, column=1, sticky="w")

        # --- Start/Stop ---
        run = ttk.Frame(main)
        run.grid(row=3, column=0, columnspan=4, sticky="ew", **pad)
        self.start_btn = ttk.Button(run, text="▶  START", command=self.start)
        self.start_btn.grid(row=0, column=0, **pad)
        self.stop_btn = ttk.Button(run, text="■  STOP", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, **pad)

        # --- Saran langkah (besar) ---
        self.suggest_var = tk.StringVar(value="—")
        tk.Label(main, textvariable=self.suggest_var, font=("Segoe UI", 26, "bold"),
                 fg="#1a7f37").grid(row=4, column=0, columnspan=4, **pad)

        # --- Log ---
        self.log_box = tk.Text(main, width=52, height=10, state="disabled",
                               font=("Consolas", 9))
        self.log_box.grid(row=5, column=0, columnspan=4, **pad)

        self.refresh_status()
        self.log("Selamat datang. Buka papan catur di layar, lalu ikuti tombol 1-2-3.")
        self.log("Saat bot jalan, jangan tutupi papan dengan jendela ini.")
        root.after(100, self.poll)

    # ------------------------------------------------------------------ util
    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def refresh_status(self):
        cfg = load_config()
        parts = []
        if cfg["board"]:
            b = cfg["board"]
            parts.append("Kalibrasi ✓ ({},{} ukuran {})".format(b["left"], b["top"], b["size"]))
        else:
            parts.append("Kalibrasi ✗")
        n_templates = len(glob.glob(os.path.join(TEMPLATES_DIR, "*", "*.png")))
        parts.append("Template: {}".format(n_templates if n_templates else "✗"))
        parts.append("Engine {}".format("✓" if os.path.exists(resolve_engine_path(cfg)) else "✗"))
        self.status_var.set("   |   ".join(parts))

    def hide_capture(self, func):
        """Sembunyikan panel sesaat supaya tidak ikut ter-capture, lalu jalankan func."""
        self.root.withdraw()
        self.root.update()
        time.sleep(0.35)
        try:
            return func()
        finally:
            self.root.deiconify()

    # ----------------------------------------------------------- kalibrasi
    def calibrate(self):
        screen = self.hide_capture(capture.grab_screen)
        tmp_png = os.path.join(PROJECT_ROOT, "_calib_screen.png")
        cv2.imwrite(tmp_png, screen)

        top = tk.Toplevel(self.root)
        top.attributes("-fullscreen", True)
        top.attributes("-topmost", True)
        img = tk.PhotoImage(file=tmp_png)
        top._img = img  # cegah garbage-collect
        canvas = tk.Canvas(top, highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, anchor="nw", image=img)
        canvas.create_rectangle(0, 0, img.width(), 34, fill="#222")
        canvas.create_text(img.width() // 2, 17, fill="white", font=("Segoe UI", 12, "bold"),
                           text="Klik sudut KIRI-ATAS papan, lalu KANAN-BAWAH  (ESC = batal)")

        clicks = []

        def finish():
            top.destroy()
            os.remove(tmp_png)
            (x1, y1), (x2, y2) = clicks
            left, top_ = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            if w < 100 or h < 100:
                messagebox.showerror("Kalibrasi", "Area terlalu kecil — ulangi.")
                return
            if abs(w - h) > 0.03 * max(w, h):
                self.log("Peringatan: area tidak persegi ({}x{}).".format(w, h))
            size = round((w + h) / 2)
            white_bottom = messagebox.askyesno(
                "Orientasi", "Apakah bidak PUTIH ada di sisi BAWAH papan?")
            cfg = load_config()
            cfg["board"] = {"left": left, "top": top_, "size": size}
            cfg["white_bottom"] = white_bottom
            save_config(cfg)
            self.log("Kalibrasi tersimpan: left={} top={} size={} putih_bawah={}".format(
                left, top_, size, white_bottom))
            self.refresh_status()

        def on_click(e):
            clicks.append((e.x, e.y))
            canvas.create_oval(e.x - 6, e.y - 6, e.x + 6, e.y + 6, outline="red", width=3)
            if len(clicks) == 2:
                top.after(150, finish)

        def on_cancel(_e=None):
            top.destroy()
            os.remove(tmp_png)
            self.log("Kalibrasi dibatalkan.")

        canvas.bind("<Button-1>", on_click)
        top.bind("<Escape>", on_cancel)

    # ------------------------------------------------------------ template
    def build_templates(self):
        cfg = load_config()
        if not cfg["board"]:
            messagebox.showwarning("Template", "Kalibrasi dulu (tombol 1).")
            return
        if not messagebox.askokcancel(
                "Buat Template",
                "Pastikan papan sedang menampilkan POSISI AWAL lengkap.\nLanjutkan?"):
            return

        def do_build():
            from .recognize import label_to_dir
            matrix = state.board_to_matrix(chess.Board())
            squares = capture.split_squares(capture.grab_board(cfg))
            stamp = int(time.time())
            for r in range(8):
                for c in range(8):
                    label = matrix[r][c] if cfg["white_bottom"] else matrix[7 - r][7 - c]
                    out_dir = os.path.join(TEMPLATES_DIR, label_to_dir(label))
                    os.makedirs(out_dir, exist_ok=True)
                    cv2.imwrite(os.path.join(out_dir, "{}_{}{}.png".format(stamp, r, c)),
                                squares[r][c])

        self.hide_capture(do_build)
        self.log("64 template tersimpan. Lanjut tombol 3 untuk verifikasi.")
        self.refresh_status()

    def test_read(self):
        cfg = load_config()
        try:
            recognizer = Recognizer()
        except RuntimeError as e:
            messagebox.showwarning("Tes Baca", str(e))
            return
        matrix = self.hide_capture(
            lambda: recognizer.matrix_from_image(capture.grab_board(cfg), cfg["white_bottom"]))
        self.log("Hasil baca papan:")
        for row in matrix:
            self.log("   " + " ".join(row))
        try:
            self.log("FEN: " + state.matrix_to_fen(matrix))
        except ValueError as e:
            self.log("Posisi tidak valid sebagai FEN: {}".format(e))

    # ----------------------------------------------------------- start/stop
    def start(self):
        cfg = load_config()
        if not cfg["board"]:
            messagebox.showwarning("Start", "Kalibrasi dulu (tombol 1).")
            return
        if self.mode_var.get() == "auto":
            if not messagebox.askokcancel(
                    "Mode AUTO",
                    "Mouse akan bergerak sendiri.\n\nHanya gunakan pada papan yang "
                    "mengizinkan otomatisasi (GUI lokal, papan analisis, vs komputer). "
                    "Di game online vs manusia = cheating + ban.\n\nDarurat: banting "
                    "kursor ke pojok KIRI-ATAS layar.\n\nLanjutkan?"):
                return
        elo_text = self.elo_var.get().strip()
        try:
            opts = {
                "color": self.color_var.get(),
                "mode": self.mode_var.get(),
                "movetime": float(self.movetime_var.get()),
                "elo": int(elo_text) if elo_text else None,
            }
        except ValueError:
            messagebox.showerror("Opsi", "Waktu pikir / Elo tidak valid.")
            return

        self.stop_event.clear()
        self.bot = BotThread(cfg, opts, self.q, self.stop_event)
        self.bot.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.suggest_var.set("…")

    def stop(self):
        self.stop_event.set()
        self.log("Menghentikan bot...")

    # --------------------------------------------------------------- queue
    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "suggest":
                    self.suggest_var.set(payload)
                elif kind == "stopped":
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.log("Bot berhenti.")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
