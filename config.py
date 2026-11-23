"""Konfigurasi pusat Vision-Action Chess Agent.

Semua nilai bisa diubah langsung di file ini. Nilai yang sering berubah
(ROI papan hasil kalibrasi, API key) dibaca dari file/env terpisah supaya
tidak ikut ter-commit:

- ``calibration.json``  -> ditulis oleh ``python calibrate.py`` (ROI papan)
- environment variable  -> API key (OPENAI_API_KEY, GEMINI_API_KEY, ...)
"""
import ctypes
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_PATH = os.path.join(PROJECT_ROOT, "calibration.json")
DEBUG_DIR = os.path.join(PROJECT_ROOT, "debug")


# ---------------------------------------------------------------------------
# DPI awareness (WAJIB di Windows dengan scaling 125%/150%)
# ---------------------------------------------------------------------------
# Tanpa ini, mss memakai piksel fisik sedangkan pyautogui memakai piksel
# "logis", sehingga klik meleset. Dipanggil saat config di-import, yaitu
# sebelum modul lain menyentuh layar.
def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()


# ---------------------------------------------------------------------------
# 1. Area papan (ROI) — koordinat piksel layar
# ---------------------------------------------------------------------------
# left/top = sudut kiri-atas papan, width/height = ukuran papan (8 kotak).
# Jalankan `python calibrate.py` untuk mengisi ini otomatis ke calibration.json.
BOARD_ROI = {"left": 0, "top": 0, "width": 800, "height": 800}

# Orientasi papan di layar. "auto" = ikut PLAYER_COLOR (kebanyakan situs
# menaruh warna kita di bawah). Isi "white" / "black" untuk memaksa.
BOARD_BOTTOM = "auto"

# Warna kita: "white" atau "black"
PLAYER_COLOR = "white"


# ---------------------------------------------------------------------------
# 2. Vision LLM (semua lewat API OpenAI-compatible /chat/completions)
# ---------------------------------------------------------------------------
# Pilih salah satu preset di VISION_PROVIDERS, atau set env AICHESS_PROVIDER.
VISION_PROVIDER = os.environ.get("AICHESS_PROVIDER", "openai")

VISION_PROVIDERS = {
    # Cloud — OpenAI
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    # Cloud — Google Gemini (endpoint kompatibel OpenAI)
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",
        "api_key_env": "GEMINI_API_KEY",
        # dipakai bergiliran jika model utama sibuk (503) / tidak tersedia (404)
        "fallback_models": ["gemini-flash-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"],
    },
    # Cloud — OpenRouter / provider OpenAI-compatible lain
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    # Lokal — Ollama (`ollama pull qwen2.5vl:7b`), tanpa API key
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5vl:7b",
        "api_key_env": None,
        "timeout": 240.0,       # model lokal lebih lambat, apalagi saat pertama dimuat
    },
}

# Override cepat lewat env tanpa mengubah preset
VISION_MODEL_OVERRIDE = os.environ.get("AICHESS_MODEL")          # mis. "gpt-4.1"
VISION_BASE_URL_OVERRIDE = os.environ.get("AICHESS_BASE_URL")    # mis. LM Studio

VISION_TIMEOUT = 90.0          # detik per request
VISION_BUSY_RETRIES = 2        # retry per model jika server sibuk (429/503)
VISION_BUSY_BACKOFF = 2.0      # detik, dikalikan nomor percobaan
VISION_TEMPERATURE = 0.0
VISION_MAX_TOKENS = 4000       # model "thinking" butuh ruang lebih
# "json_schema" (structured output ketat) atau "json_object" (lebih kompatibel).
# Jika server menolak json_schema, vision_reader otomatis turun ke json_object.
VISION_RESPONSE_FORMAT = "json_schema"
# Gambar diperkecil sebelum dikirim (hemat token). Papan 8x8 cukup ~768 px.
VISION_IMAGE_MAX_SIZE = 768
# Tambahkan label koordinat a-h / 1-8 di tepi gambar -> akurasi FEN naik.
VISION_DRAW_COORDINATES = True


# ---------------------------------------------------------------------------
# 3. Mesin keputusan
# ---------------------------------------------------------------------------
# "hybrid"   : Vision LLM -> FEN -> validasi python-chess -> Stockfish (disarankan)
# "pure_llm" : Vision LLM langsung memberi langkah UCI, divalidasi python-chess
DECISION_MODE = "hybrid"

STOCKFISH_PATH = os.path.join(PROJECT_ROOT, "stockfish", "stockfish.exe")
ENGINE_MOVETIME = 0.8          # detik pikir Stockfish per langkah
ENGINE_SKILL_LEVEL = 20        # 0-20 (dipakai jika ENGINE_ELO = None)
ENGINE_ELO = None              # mis. 1500 untuk membatasi kekuatan
ENGINE_THREADS = 2
ENGINE_HASH_MB = 128
# Mode pure_llm: kalau langkah LLM ilegal, pakai Stockfish sebagai cadangan
PURE_LLM_FALLBACK_TO_ENGINE = True


# ---------------------------------------------------------------------------
# 4. Loop utama, deteksi perubahan & retry
# ---------------------------------------------------------------------------
POLL_INTERVAL = 0.35           # jeda antar-screenshot saat menunggu perubahan
CHANGE_THRESHOLD = 2.0         # rata-rata selisih piksel (0-255) dianggap "berubah"
STABLE_FRAMES = 2              # frame identik berturut-turut = animasi selesai
STABLE_THRESHOLD = 0.6         # selisih maksimum antar-frame agar dianggap stabil
VISION_RETRIES = 3             # retry jika FEN tidak valid / langkah ilegal
RETRY_DELAY = 0.5              # detik menunggu animasi sebelum capture ulang
MIN_CONFIDENCE = 0.5           # di bawah ini hasil vision dianggap meragukan
MOVE_DELAY_RANGE = (0.6, 1.5)  # jeda acak sebelum mengeksekusi langkah kita
SAVE_DEBUG_IMAGES = False      # simpan gambar yang dikirim ke LLM di folder debug/


# ---------------------------------------------------------------------------
# 5. Mouse
# ---------------------------------------------------------------------------
MOUSE_STYLE = "drag"           # "drag" atau "click" (click-and-click)
MOUSE_MOVE_DURATION = (0.15, 0.35)  # durasi gerak kursor (detik, acak)
MOUSE_JITTER = 0.12            # deviasi acak dari pusat kotak (fraksi ukuran kotak)
MOUSE_STEPS_PER_SECOND = 120   # resolusi gerakan (dicek kill-switch tiap langkah)
PARK_CURSOR = True             # pindahkan kursor keluar papan setelah melangkah
PROMOTION_PIECE = "q"          # bidak promosi default
# Posisi pilihan promosi pada popup, dihitung dalam "kotak" dari kotak tujuan
# ke arah tengah papan. Lichess/chess.com: q=0, n=1, r=2, b=3.
PROMOTION_POPUP_OFFSETS = {"q": 0, "n": 1, "r": 2, "b": 3}


# ---------------------------------------------------------------------------
# 6. Keamanan
# ---------------------------------------------------------------------------
PYAUTOGUI_FAILSAFE = True      # banting kursor ke pojok layar = abort
KILL_HOTKEY = "<ctrl>+<shift>+q"   # format pynput
PAUSE_HOTKEY = "<f8>"              # pause / resume
KILL_ON_ESC = True             # ESC juga menghentikan agent


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def load_calibration() -> None:
    """Timpa BOARD_ROI (dan opsi lain) dari calibration.json jika ada."""
    global BOARD_ROI, BOARD_BOTTOM, PLAYER_COLOR
    if not os.path.exists(CALIBRATION_PATH):
        return
    with open(CALIBRATION_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    BOARD_ROI = {k: int(data["board_roi"][k]) for k in ("left", "top", "width", "height")}
    BOARD_BOTTOM = data.get("board_bottom", BOARD_BOTTOM)
    PLAYER_COLOR = data.get("player_color", PLAYER_COLOR)


def save_calibration(roi: dict, board_bottom: str = None, player_color: str = None) -> None:
    data = {
        "board_roi": roi,
        "board_bottom": board_bottom or BOARD_BOTTOM,
        "player_color": player_color or PLAYER_COLOR,
    }
    with open(CALIBRATION_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def white_at_bottom() -> bool:
    if BOARD_BOTTOM in ("white", "black"):
        return BOARD_BOTTOM == "white"
    return PLAYER_COLOR == "white"


def vision_settings() -> dict:
    """Resolve preset provider + override env menjadi satu dict siap pakai."""
    if VISION_PROVIDER not in VISION_PROVIDERS:
        raise ValueError(
            "VISION_PROVIDER '{}' tidak dikenal. Pilihan: {}".format(
                VISION_PROVIDER, ", ".join(VISION_PROVIDERS)
            )
        )
    preset = dict(VISION_PROVIDERS[VISION_PROVIDER])
    if VISION_MODEL_OVERRIDE:
        preset["model"] = VISION_MODEL_OVERRIDE
    if VISION_BASE_URL_OVERRIDE:
        preset["base_url"] = VISION_BASE_URL_OVERRIDE
    key_env = preset.get("api_key_env")
    preset["api_key"] = os.environ.get(key_env, "") if key_env else ""
    preset["provider"] = VISION_PROVIDER
    return preset


load_calibration()
