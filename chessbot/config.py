"""Load/save konfigurasi proyek (config.json di root proyek)."""
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")

DEFAULTS = {
    # Diisi oleh chessbot.calibrate: {"left": int, "top": int, "size": int}
    "board": None,
    # True jika bidak putih ada di sisi bawah papan pada layar
    "white_bottom": True,
    # Path ke binary Stockfish (relatif terhadap root proyek atau absolut)
    "engine_path": "stockfish/stockfish.exe",
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def resolve_engine_path(cfg: dict) -> str:
    path = cfg.get("engine_path", DEFAULTS["engine_path"])
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    return path
