"""Kirim gambar papan ke Vision LLM dan ambil hasil terstruktur (JSON).

Semua provider (OpenAI, Gemini, OpenRouter, Ollama, LM Studio, ...) dipanggil
lewat endpoint OpenAI-compatible ``POST {base_url}/chat/completions``.
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import requests

import config
import screen_capture


@dataclass
class VisionResult:
    fen: str
    side_to_move: str                  # "w" / "b"
    confidence: float                  # 0.0 - 1.0
    notes: str = ""
    pieces_in_motion: bool = False     # ada bidak terpotong animasi / drag
    best_move_uci: Optional[str] = None  # hanya diisi di mode pure_llm
    raw: dict = field(default_factory=dict)
    latency: float = 0.0


class VisionError(RuntimeError):
    pass


def _schema(include_move: bool) -> dict:
    props = {
        "ranks": {
            "type": "array",
            "description": "8 string, rank 8 lalu turun ke rank 1. Tiap string tepat 8 karakter "
                           "dari file a ke h: KQRBNP putih, kqrbnp hitam, '.' kosong.",
            "items": {"type": "string"},
        },
        "fen": {"type": "string", "description": "FEN lengkap 6 field"},
        "side_to_move": {"type": "string", "enum": ["w", "b"]},
        "confidence": {"type": "number", "description": "0.0 sampai 1.0"},
        "pieces_in_motion": {"type": "boolean"},
        "notes": {"type": "string"},
    }
    required = ["ranks", "fen", "side_to_move", "confidence", "pieces_in_motion", "notes"]
    if include_move:
        props["best_move_uci"] = {"type": "string", "description": "Langkah terbaik UCI, mis. g1f3"}
        required.append("best_move_uci")
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def _prompt(white_bottom: bool, player_color: str, include_move: bool,
            hint_side: Optional[str], feedback: Optional[str]) -> str:
    orient = (
        "Putih berada di BAWAH gambar (rank 1 di bawah, file a di kiri)."
        if white_bottom else
        "Hitam berada di BAWAH gambar (rank 8 di bawah, file h di kiri) — papan dibalik."
    )
    lines = [
        "Kamu adalah pembaca papan catur yang sangat teliti.",
        "Gambar berisi papan catur digital 8x8 dengan label koordinat di tepi kiri dan bawah.",
        orient,
        "Tugas:",
        "1. Baca setiap kotak satu per satu. Isi `ranks` dengan 8 string (rank 8 -> rank 1), "
        "masing-masing tepat 8 karakter dari file a -> h. Huruf besar = putih, huruf kecil = hitam, "
        "'.' = kosong. K raja, Q ratu, R benteng, B gajah, N kuda, P pion.",
        "2. Susun `fen` lengkap (penempatan, giliran, hak rokade, en passant, halfmove, fullmove) "
        "yang konsisten dengan `ranks`. Hak rokade hanya jika raja/benteng masih di kotak awal.",
        "3. `side_to_move`: tebak dari highlight langkah terakhir (warna kotak asal/tujuan yang "
        "disorot). Jika tidak terlihat, isi '{}'.".format(hint_side or ("w" if player_color == "white" else "b")),
        "4. `confidence` 0-1 seberapa yakin pembacaanmu. `pieces_in_motion` = true jika ada bidak "
        "yang sedang bergerak/terpotong animasi/ditarik kursor. Tulis keraguan di `notes`.",
        "Periksa ulang: tepat satu raja putih dan satu raja hitam, maksimal 8 pion per warna, "
        "tidak ada pion di rank 1 atau 8.",
    ]
    if include_move:
        lines.append(
            "5. `best_move_uci`: langkah terbaik untuk pihak {} dalam notasi UCI (mis. e2e4, "
            "e7e8q untuk promosi). Harus legal pada posisi tersebut.".format(player_color)
        )
    if feedback:
        lines.append("PERHATIAN — percobaan sebelumnya salah: " + feedback)
    lines.append("Jawab HANYA dengan JSON sesuai skema, tanpa teks lain.")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Buang code fence ```json ... ``` jika model tetap menambahkannya
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise VisionError("Respons LLM bukan JSON: {!r}".format(text[:200]))
    return json.loads(text[start:end + 1])


def ranks_to_placement(ranks) -> Optional[str]:
    """['rnbqkbnr', 'pppppppp', '........', ...] -> bagian penempatan FEN."""
    if not isinstance(ranks, list) or len(ranks) != 8:
        return None
    out = []
    for row in ranks:
        row = str(row).replace(" ", "").replace("1", ".")
        if len(row) != 8 or any(c not in "KQRBNPkqrbnp." for c in row):
            return None
        s, empty = "", 0
        for c in row:
            if c == ".":
                empty += 1
            else:
                if empty:
                    s += str(empty)
                    empty = 0
                s += c
        out.append(s + (str(empty) if empty else ""))
    return "/".join(out)


class VisionReader:
    def __init__(self, settings: Optional[dict] = None):
        self.s = settings or config.vision_settings()
        if self.s.get("api_key_env") and not self.s.get("api_key"):
            raise VisionError(
                "API key kosong. Set environment variable {} (provider '{}'), atau ganti "
                "VISION_PROVIDER di config.py (mis. 'ollama' untuk lokal).".format(
                    self.s["api_key_env"], self.s["provider"]
                )
            )
        self.url = self.s["base_url"].rstrip("/") + "/chat/completions"
        self.response_format = config.VISION_RESPONSE_FORMAT
        self.session = requests.Session()
        self.calls = 0

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.s.get("api_key"):
            headers["Authorization"] = "Bearer " + self.s["api_key"]
        r = self.session.post(self.url, json=payload, headers=headers, timeout=self.s.get("timeout", config.VISION_TIMEOUT))
        if r.status_code >= 400:
            raise VisionError("HTTP {} dari {}: {}".format(r.status_code, self.url, r.text[:500]))
        return r.json()

    def read(self, img: np.ndarray, white_bottom: bool, player_color: str,
             include_move: bool = False, hint_side: Optional[str] = None,
             feedback: Optional[str] = None) -> VisionResult:
        data_url = screen_capture.to_data_url(img, white_bottom=white_bottom)
        if config.SAVE_DEBUG_IMAGES:
            os.makedirs(config.DEBUG_DIR, exist_ok=True)
            import base64
            path = os.path.join(config.DEBUG_DIR, "vision_{}.png".format(int(time.time() * 1000)))
            with open(path, "wb") as f:
                f.write(base64.b64decode(data_url.split(",", 1)[1]))

        payload = {
            "model": self.s["model"],
            "temperature": config.VISION_TEMPERATURE,
            "max_tokens": config.VISION_MAX_TOKENS,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt(white_bottom, player_color, include_move,
                                                     hint_side, feedback)},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        }
        t0 = time.time()
        resp = None
        for fmt in self._formats():
            rf = self._response_format(fmt, include_move)
            if rf is None:
                payload.pop("response_format", None)
            else:
                payload["response_format"] = rf
            try:
                resp = self._post(payload)
                self.response_format = fmt  # ingat format yang berhasil
                break
            except VisionError as e:
                # Server tidak mendukung json_schema -> coba format berikutnya
                if fmt != "none" and ("400" in str(e) or "422" in str(e)):
                    continue
                raise
        self.calls += 1
        latency = time.time() - t0

        try:
            content = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise VisionError("Format respons tidak dikenal: {}".format(str(resp)[:300]))
        if isinstance(content, list):  # beberapa server mengembalikan list part
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        data = _extract_json(content or "")
        return self._to_result(data, latency)

    def _formats(self):
        order = ["json_schema", "json_object", "none"]
        return order[order.index(self.response_format):] if self.response_format in order else order

    @staticmethod
    def _response_format(fmt: str, include_move: bool):
        if fmt == "json_schema":
            return {"type": "json_schema",
                    "json_schema": {"name": "chess_board", "strict": True,
                                    "schema": _schema(include_move)}}
        if fmt == "json_object":
            return {"type": "json_object"}
        return None

    @staticmethod
    def _to_result(data: dict, latency: float) -> VisionResult:
        fen = str(data.get("fen", "")).strip()
        side = str(data.get("side_to_move", "w")).strip().lower()[:1] or "w"
        if side not in ("w", "b"):
            side = "w"
        # `ranks` lebih bisa dipercaya daripada FEN tulisan model (sering salah hitung
        # angka kosong) — jika ada & valid, timpa bagian penempatan FEN.
        placement = ranks_to_placement(data.get("ranks"))
        parts = fen.split()
        if placement:
            parts = [placement] + (parts[1:] if len(parts) > 1 else [])
        while len(parts) < 6:
            parts.append(["w", "-", "-", "0", "1"][len(parts) - 1])
        parts[1] = side
        try:
            conf = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        move = data.get("best_move_uci")
        return VisionResult(
            fen=" ".join(parts[:6]),
            side_to_move=side,
            confidence=max(0.0, min(1.0, conf)),
            notes=str(data.get("notes", "")),
            pieces_in_motion=bool(data.get("pieces_in_motion", False)),
            best_move_uci=str(move).strip().lower() if move else None,
            raw=data,
            latency=latency,
        )
