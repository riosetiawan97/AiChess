"""Tes Vision-Action Chess Agent tanpa API key & tanpa menggerakkan mouse.

    python tests/test_agent.py

Vision LLM diganti server HTTP palsu (OpenAI-compatible) di localhost.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["AICHESS_TEST_KEY"] = "dummy"

import chess
import numpy as np

import config
import decision_engine as de
import mouse_controller as mc
import screen_capture as sc
import vision_reader as vr

ROI = {"left": 100, "top": 200, "width": 800, "height": 800}


# ---------------------------------------------------------------------------
# Server Vision palsu
# ---------------------------------------------------------------------------
class FakeLLM(BaseHTTPRequestHandler):
    replies = []          # antrean JSON jawaban
    requests = []         # payload yang diterima
    reject_schema = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.requests.append(body)
        rf = body.get("response_format") or {}
        if FakeLLM.reject_schema and rf.get("type") == "json_schema":
            self._send(400, {"error": "json_schema not supported"})
            return
        data = FakeLLM.replies.pop(0) if FakeLLM.replies else {}
        content = "```json\n" + json.dumps(data) + "\n```"  # uji parser code-fence
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def start_fake_server():
    srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    config.VISION_PROVIDERS["fake"] = {
        "base_url": "http://127.0.0.1:{}/v1".format(srv.server_port),
        "model": "fake-vision",
        "api_key_env": "AICHESS_TEST_KEY",
    }
    config.VISION_PROVIDER = "fake"
    return srv


def reply(fen, side="w", conf=0.95, move=None, motion=False):
    board = chess.Board(fen)
    ranks = []
    for r in range(7, -1, -1):
        ranks.append("".join(str(board.piece_at(chess.square(f, r)) or ".") for f in range(8)))
    d = {"ranks": ranks, "fen": fen, "side_to_move": side, "confidence": conf,
         "pieces_in_motion": motion, "notes": ""}
    if move:
        d["best_move_uci"] = move
    return d


# ---------------------------------------------------------------------------
# Tes unit
# ---------------------------------------------------------------------------
def test_square_mapping():
    # Putih di bawah: a1 kiri-bawah, h8 kanan-atas (kotak 100 px)
    assert mc.square_to_pixel(chess.A1, ROI, True) == (150, 950)
    assert mc.square_to_pixel(chess.H8, ROI, True) == (850, 250)
    assert mc.square_to_pixel(chess.E2, ROI, True) == (550, 850)
    # Hitam di bawah: papan dibalik
    assert mc.square_to_pixel(chess.A1, ROI, False) == (850, 250)
    assert mc.square_to_pixel(chess.H8, ROI, False) == (150, 950)
    assert mc.uci_to_pixels("g1f3", ROI, True) == ((750, 950), (650, 750))


def test_board_from_fen_valid_and_cleaned():
    # Hak rokade "KQkq" salah karena benteng h1 sudah pergi -> dibersihkan, bukan ditolak
    b = de.board_from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBN1 w KQkq - 0 1")
    assert not b.has_kingside_castling_rights(chess.WHITE)
    assert b.has_queenside_castling_rights(chess.WHITE)


def test_board_from_fen_invalid():
    for bad in ["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQ1BNR w - - 0 1",   # tanpa raja putih
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP w - - 0 1",            # rank kurang
                "Pnbqkbnr/pppppppp/8/8/8/8/1PPPPPPP/RNBQKBNR w - - 0 1"]:  # pion di rank 8
        try:
            de.board_from_fen(bad)
        except de.InvalidPosition:
            continue
        raise AssertionError("seharusnya ditolak: " + bad)


def test_reconcile():
    known = chess.Board()
    assert de.reconcile(known, known.board_fen()) == (de.SAME, None)
    after = chess.Board()
    after.push_uci("e2e4")
    assert de.reconcile(known, after.board_fen()) == (de.ONE_MOVE, chess.Move.from_uci("e2e4"))
    # Rokade dikenali sebagai satu langkah
    k = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    a = k.copy()
    a.push_uci("e1g1")
    assert de.reconcile(k, a.board_fen()) == (de.ONE_MOVE, chess.Move.from_uci("e1g1"))
    status, _ = de.reconcile(known, "8/8/8/8/8/8/8/K6k")
    assert status == de.RESYNC


def test_parse_uci():
    b = chess.Board()
    assert de.parse_uci(b, "g1f3") == chess.Move.from_uci("g1f3")
    assert de.parse_uci(b, "Nf3") == chess.Move.from_uci("g1f3")   # SAN diterima
    assert de.parse_uci(b, "e2e5") is None                         # ilegal
    assert de.parse_uci(b, "zzz") is None
    p = chess.Board("8/4P3/8/8/8/8/k7/4K3 w - - 0 1")
    assert de.parse_uci(p, "e7e8") == chess.Move.from_uci("e7e8q")  # promosi default ratu


def test_ranks_to_placement():
    ranks = ["rnbqkbnr", "pppppppp", "........", "........",
             "....P...", "........", "PPPP.PPP", "RNBQKBNR"]
    assert vr.ranks_to_placement(ranks) == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR"
    assert vr.ranks_to_placement(["abc"] * 8) is None
    # ranks mengoreksi FEN yang salah hitung angka
    res = vr.VisionReader._to_result({"ranks": ranks, "fen": "rnbqkbnr/ppp/8 b KQkq e3 0 1",
                                      "side_to_move": "b", "confidence": 0.9}, 0.1)
    assert res.fen == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    assert de.board_from_fen(res.fen).ep_square is None  # ep tanpa capture legal dibuang


def test_frame_diff_and_png():
    a = np.zeros((400, 400, 3), np.uint8)
    b = a.copy()
    b[50:100, 50:100] = 255
    fa, fb = sc.fingerprint(a), sc.fingerprint(b)
    assert sc.frame_diff(fa, fa) == 0.0
    assert sc.frame_diff(fa, fb) > config.CHANGE_THRESHOLD
    assert sc.frame_hash(a) != sc.frame_hash(b)
    png = sc.to_png_bytes(a, max_size=256)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert sc.to_data_url(a).startswith("data:image/png;base64,")


def test_screen_capture_real():
    with sc.ScreenCapture({"left": 0, "top": 0, "width": 200, "height": 150}) as cap:
        img = cap.grab()
    assert img.shape == (150, 200, 3) and img.dtype == np.uint8


def test_vision_reader_http_and_fallback():
    FakeLLM.requests.clear()
    FakeLLM.reject_schema = True
    FakeLLM.replies = [reply(chess.STARTING_FEN, move="e2e4")]
    reader = vr.VisionReader()
    res = reader.read(np.zeros((300, 300, 3), np.uint8), True, "white", include_move=True)
    FakeLLM.reject_schema = False
    assert res.fen == chess.STARTING_FEN and res.best_move_uci == "e2e4"
    # json_schema ditolak (400) -> otomatis turun ke json_object
    assert [r.get("response_format", {}).get("type") for r in FakeLLM.requests] == ["json_schema", "json_object"]
    content = FakeLLM.requests[-1]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert FakeLLM.requests[-1]["model"] == "fake-vision"


def test_stockfish_hybrid():
    d = de.DecisionEngine("hybrid")
    try:
        # Mat dalam 1: Qh5xf7#
        b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
        dec = d.decide(b)
        assert dec.source == "stockfish" and dec.move.uci() == "h5f7", dec
    finally:
        d.close()


def test_pure_llm_validation():
    d = de.DecisionEngine("pure_llm")
    try:
        b = chess.Board()
        assert d.decide(b, "e2e4").source == "llm"
        dec = d.decide(b, "e2e5")  # ilegal -> cadangan Stockfish
        assert dec.source == "stockfish-fallback" and dec.move in b.legal_moves
    finally:
        d.close()


def test_agent_loop_dry_run():
    """Simulasi 1 game pendek: start -> kita jalan -> lawan jalan -> kita jalan."""
    import main as agent_main

    config.PLAYER_COLOR = "white"
    config.DECISION_MODE = "hybrid"
    config.MOVE_DELAY_RANGE = (0, 0)
    config.RETRY_DELAY = 0.01
    agent = agent_main.ChessAgent(dry_run=True)
    screen = {"v": 10}  # nilai piksel = "versi" tampilan layar
    agent.cap.grab = lambda: np.full((400, 400, 3), screen["v"], np.uint8)
    try:
        # 1) posisi awal, FEN pertama ilegal (raja hilang) -> retry -> valid
        no_king = {"ranks": ["rnbqkbnr", "pppppppp"] + ["........"] * 4 + ["PPPPPPPP", "RNBQ.BNR"],
                   "fen": "", "side_to_move": "w", "confidence": 0.9, "pieces_in_motion": False, "notes": ""}
        FakeLLM.replies = [no_king, reply(chess.STARTING_FEN)]
        agent.step(force=True)
        assert agent.known is not None and len(agent.known.move_stack) == 1, agent.known
        our_first = agent.known.move_stack[0]
        # 2) layar menampilkan langkah kita + balasan lawan
        b = chess.Board()
        b.push(our_first)
        reply_move = next(iter(b.legal_moves))
        b.push(reply_move)
        FakeLLM.replies = [reply(b.fen(), side="w")]
        screen["v"] = 120
        agent.step()
        assert agent.known.move_stack[1] == reply_move
        assert len(agent.known.move_stack) == 3 and agent.known.turn == chess.BLACK
        # 3) frame tidak berubah -> TIDAK ada panggilan API
        calls = agent.vision.calls
        agent.step()
        agent.step()
        assert agent.vision.calls == calls
    finally:
        agent.decider.close()
        agent.cap.close()


def run():
    srv = start_fake_server()
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", name, "->", e)
    srv.shutdown()
    print("\n{}/{} lulus".format(len(tests) - failed, len(tests)))
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
