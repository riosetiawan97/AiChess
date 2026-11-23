# AiChess — Vision-Action Chess Agent

Agent Python untuk Windows yang **membaca papan catur dari screenshot memakai
Vision LLM (model multimodal)**, menentukan langkah terbaik, lalu
**menggerakkan mouse** untuk memindahkan bidak di layar — misalnya saat
berlatih melawan bot di browser.

> **Etika & ToS.** Gunakan hanya melawan komputer/bot latihan, papan analisis,
> GUI catur lokal, atau untuk riset. Memakainya di game online melawan manusia
> adalah *cheating*, melanggar ToS (chess.com, lichess, dll.) dan berujung ban.
> Untuk bot online yang legal gunakan [Lichess Bot API](https://lichess.org/api#tag/Bot).

---

## 1. Arsitektur & alur data

```
                ┌──────────────┐
                │  config.py   │  ROI papan, provider LLM, mode, mouse, hotkey
                └──────┬───────┘
                       │ (dibaca semua modul)
┌──────────────────────▼─────────────────────────────────────────────────┐
│ main.py — loop utama + kill-switch (Ctrl+Shift+Q / ESC, F8 = pause)    │
│                                                                        │
│  1. screen_capture.grab()          mss → array RGB area papan          │
│  2. fingerprint + frame_diff       papan tidak berubah? → skip (0 API) │
│  3. wait_for_stable()              tunggu animasi bidak selesai        │
│  4. vision_reader.read()           PNG base64 → Vision LLM → JSON      │
│        {ranks, fen, side_to_move, confidence, pieces_in_motion,        │
│         notes, [best_move_uci]}                                        │
│  5. decision_engine.board_from_fen chess.Board(fen) + cek status valid │
│        └─ tidak valid / conf rendah → jeda 0.5 s → capture ulang       │
│  6. decision_engine.reconcile()    cocokkan dengan state yang dilacak  │
│        SAME     : layar = posisi yang sudah diketahui                  │
│        ONE_MOVE : layar = posisi lama + 1 langkah legal (lawan)        │
│        RESYNC   : tidak nyambung → konfirmasi baca ke-2 → pakai vision │
│  7. decision_engine.decide()       hybrid → Stockfish | pure_llm → UCI │
│                                    dari LLM yang divalidasi legalnya   │
│  8. mouse_controller.execute()     UCI → piksel → drag / click-click   │
│  9. frame berikutnya memverifikasi langkah kita benar-benar masuk      │
└────────────────────────────────────────────────────────────────────────┘
```

| File | Tugas |
|---|---|
| `config.py` | Semua pengaturan: ROI papan, provider/endpoint/model Vision LLM, warna pemain, mode keputusan, jeda, gaya mouse, hotkey. Membaca `calibration.json` dan API key dari env. Mengaktifkan DPI awareness Windows. |
| `screen_capture.py` | Screenshot cepat via `mss`, fingerprint & selisih frame, tunggu frame stabil, konversi ke PNG/base64 (opsional dengan label koordinat a–h / 1–8). |
| `vision_reader.py` | Request ke endpoint OpenAI-compatible `/chat/completions` dengan *structured output* (`json_schema` → turun ke `json_object` bila tidak didukung). Mengembalikan FEN, giliran, confidence, catatan animasi, dan (mode pure LLM) langkah UCI. |
| `decision_engine.py` | Validasi FEN dengan `python-chess` (membersihkan hak rokade/en passant yang salah baca), sinkronisasi state, Stockfish (hybrid), validasi langkah LLM (pure LLM) + fallback ke Stockfish. |
| `mouse_controller.py` | Mapping kotak → piksel sesuai orientasi papan, gerakan halus yang bisa dibatalkan, drag atau click-and-click, popup promosi, parkir kursor. |
| `main.py` | Orkestrasi loop, retry, verifikasi langkah, hotkey kill-switch & pause, mode `--dry-run`, `--once`, `--image`. |
| `calibrate.py` | Kalibrasi bounding box papan + gambar cek grid. |
| `tests/test_agent.py` | 12 tes (tanpa API key, memakai server LLM palsu di localhost). |

**Kenapa hybrid lebih akurat:** Vision LLM bagus mengenali gambar tapi lemah
menghitung catur dan kadang salah baca 1–2 kotak. Di mode hybrid LLM hanya
*membaca*, `python-chess` menolak posisi mustahil, dan `reconcile()` mencocokkan
hasil baca dengan "posisi terakhir + satu langkah legal". Akibatnya langkah
lawan diketahui pasti (termasuk rokade, en passant, promosi), giliran tidak
perlu ditebak dari gambar, dan Stockfish yang memilih langkah — tidak ada blunder.

---

## 2. Setup

```powershell
# Python 3.9+ (proyek ini memakai venv di .venv)
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**Stockfish** (wajib untuk mode hybrid): unduh dari
<https://stockfishchess.org/download/>, ekstrak, lalu simpan sebagai
`stockfish\stockfish.exe` (atau ubah `STOCKFISH_PATH` di `config.py`).

Uji instalasi (tanpa API key, mouse tidak bergerak):

```powershell
.venv\Scripts\python tests\test_agent.py
```

---

## 3. Kalibrasi bounding box papan

1. Buka papan di browser (misalnya *Play vs Computer*). Atur zoom/ukuran
   jendela **sekarang** — setelah kalibrasi jangan digeser atau di-zoom lagi.
2. Jalankan:
   ```powershell
   .venv\Scripts\python calibrate.py
   ```
3. Arahkan kursor ke **sudut kiri-atas** area 8×8 (tepi luar kotak, bukan
   bingkai/label), tekan Enter. Ulangi untuk **sudut kanan-bawah**.
4. Jawab warna kita (`white`/`black`) dan warna di bawah layar (`auto` =
   warna kita di bawah, yang dipakai kebanyakan situs).
5. Buka `calibration_check.png`: garis merah harus pas di batas kotak dan
   label kotak (a1, h8, …) sesuai papan. Kalau meleset, ulangi.

Alternatif tanpa interaksi: `python calibrate.py --roi LEFT TOP WIDTH HEIGHT`.
Cek ulang kapan saja: `python calibrate.py --check`.

> **Scaling Windows 125%/150%:** `config.py` memanggil
> `SetProcessDpiAwareness(2)` agar `mss` dan `pyautogui` sama-sama memakai
> piksel fisik. Kalau klik meleset, kalibrasi ulang setelah mengubah scaling.

---

## 4. Memilih Vision LLM: cloud vs lokal

Semua provider dipanggil lewat API **OpenAI-compatible**, jadi cukup ganti
preset di `config.py` (`VISION_PROVIDER`) atau pakai argumen/env.

### Cloud (OpenAI / Gemini / OpenRouter)

```powershell
# OpenAI
$env:OPENAI_API_KEY = "sk-..."
.venv\Scripts\python main.py --provider openai

# Google Gemini
$env:GEMINI_API_KEY = "..."
.venv\Scripts\python main.py --provider gemini

# Ganti model tanpa mengedit file
.venv\Scripts\python main.py --provider openai --model gpt-4.1
```

Supaya permanen: `setx OPENAI_API_KEY "sk-..."` (buka terminal baru setelahnya).
API key **tidak pernah** ditulis ke file proyek.

### Lokal (Ollama)

```powershell
# 1. Install Ollama dari https://ollama.com, lalu unduh model vision:
ollama pull qwen2.5vl:7b
# 2. Jalankan agent (tanpa API key)
.venv\Scripts\python main.py --provider ollama
```

Model lain: `--model llama3.2-vision` atau ubah `VISION_PROVIDERS["ollama"]["model"]`.
Server OpenAI-compatible lain (LM Studio, vLLM):
`$env:AICHESS_BASE_URL = "http://localhost:1234/v1"`.

> **VRAM GPU kecil (≤ 4 GB)?** `qwen2.5vl:7b` bisa gagal dengan
> `CUDA error: out of memory`. Paksa jalan di CPU (lambat, ±3 menit per
> pembacaan di CPU i7 generasi ke-4):
> `ollama create qwen2.5vl-cpu -f ollama/Modelfile.cpu` lalu
> `python main.py --provider ollama --model qwen2.5vl-cpu`.
> Untuk PC seperti itu provider cloud (Gemini/OpenAI) jauh lebih praktis.
>
> Model lokal kecil lebih sering salah baca papan. Pakai mode **hybrid**
> (default) supaya salah baca tersaring oleh validasi dan `reconcile()`.

---

## 5. Menjalankan

```powershell
# Uji baca sekali, mouse tidak bergerak
.venv\Scripts\python main.py --once

# Saran langkah saja (Anda yang menggerakkan bidak)
.venv\Scripts\python main.py --dry-run

# Otomatis penuh — kita main putih, mode hybrid
.venv\Scripts\python main.py --color white

# Main hitam, mode pure LLM, gaya click-and-click
.venv\Scripts\python main.py --color black --mode pure_llm --style click

# Tes vision dari file gambar (tanpa layar)
.venv\Scripts\python main.py --image contoh_papan.png
```

### Kontrol darurat

| Aksi | Efek |
|---|---|
| `Ctrl+Shift+Q` atau `ESC` | Hentikan agent seketika (gerakan mouse dibatalkan, tombol mouse dilepas) |
| `F8` | Pause / resume |
| Kursor dibanting ke **pojok layar** | Fail-safe `pyautogui` — abort |
| `Ctrl+C` di terminal | Berhenti |

### Pengaturan penting di `config.py`

| Nama | Arti |
|---|---|
| `DECISION_MODE` | `"hybrid"` (disarankan) atau `"pure_llm"` |
| `ENGINE_MOVETIME`, `ENGINE_ELO`, `ENGINE_SKILL_LEVEL` | kekuatan Stockfish |
| `CHANGE_THRESHOLD` | sensitivitas deteksi perubahan frame (naikkan jika API terpanggil karena efek hover) |
| `STABLE_FRAMES`, `RETRY_DELAY`, `VISION_RETRIES` | penanganan animasi & retry |
| `MIN_CONFIDENCE` | batas confidence hasil vision |
| `MOUSE_STYLE` | `"drag"` atau `"click"` |
| `MOVE_DELAY_RANGE` | jeda acak sebelum melangkah |
| `VISION_IMAGE_MAX_SIZE` | ukuran gambar dikirim (token vs akurasi) |
| `SAVE_DEBUG_IMAGES` | simpan gambar yang dikirim ke LLM di `debug/` |

---

## 6. Penanganan error & akurasi

- **Deteksi perubahan frame:** thumbnail grayscale 64×64 dibandingkan dengan
  frame terakhir yang diproses. API hanya dipanggil jika rata-rata selisih
  > `CHANGE_THRESHOLD`, lalu menunggu `STABLE_FRAMES` frame identik.
- **Validasi FEN:** `chess.Board(fen)` + `board.status()` (raja, pion di rank
  1/8, jumlah bidak, skak mustahil, dll.). Gagal → jeda `RETRY_DELAY`, capture
  ulang, dan alasan penolakan dikirim balik ke LLM sebagai umpan balik.
- **Tidak ada langkah ganda:** langkah kita dicatat; frame berikutnya harus
  menampilkannya (`SAME`). Jika layar masih menunjukkan posisi sebelum langkah,
  langkah diulang (maks. 3x, lalu agent di-pause).
- **Legalitas langkah:** setiap langkah (Stockfish maupun LLM) dicek
  `move in board.legal_moves` sebelum mouse bergerak.

---

## 7. Modul lama (offline, tanpa LLM)

Folder `chessbot/` berisi versi sebelumnya yang membaca papan dengan
*template matching* OpenCV (tanpa API, tapi perlu membuat template bidak),
lengkap dengan GUI Tkinter (`AiChess.bat`). Masih bisa dipakai:
`.venv\Scripts\python -m chessbot.gui`.
