# high-tf — Indodax Market Intelligence Bot

Bot scanner & alert otomatis untuk pasar kripto **Indodax** (pasangan `*/IDR`). Bot ini memantau seluruh aset yang tersedia di Indodax secara berkala, menghitung indikator teknikal dasar, lalu mengirim sinyal ke Telegram dan menampilkannya di dashboard web real-time.

> Nama file utama proyek ini adalah `future_market.py`, dan dashboard-nya berjudul "CAHYO PUNYA" — merupakan bot intelligence market untuk exchange Indodax (bukan Binance/MEXC, meskipun ada sisa penamaan variabel `TOKEN_HIGH`/"Binance Intelligence" di kode).

## Fitur Utama

- **Scanner otomatis semua pasar IDR** di Indodax menggunakan library `ccxt`, berjalan terus-menerus di background thread.
- **Analisis teknikal per aset** dari candle 1 jam (100 candle terakhir):
  - SMA 20
  - RSI 14
  - **MPI (Money Pressure Index)** — rasio volume candle hijau vs merah
  - Volume spike ratio (volume terakhir dibanding rata-rata 20 periode)
- **Klasifikasi sinyal**: `STRONG ACCUMULATION`, `DISTRIBUTION/SELL`, atau `NEUTRAL` berdasarkan RSI.
- **Adaptive Take Profit (TP1/TP2/TP3)** yang dihitung dinamis dari rata-rata range harga dan kekuatan volume spike.
- **Sistem grading sinyal**: `A+ (PERFECT)`, `B (EARLY)`, `C (LOW)` berdasarkan kombinasi MPI dan volume spike.
- **Alert Telegram otomatis** hanya untuk sinyal grade `A+` yang baru berubah, lengkap dengan tombol tautan langsung ke chart Indodax.
- **Command Telegram `/cek <kode_koin>`** untuk mengecek analisis sebuah koin secara manual (contoh: `/cek btc`).
- **Dashboard web (Flask)** dengan tampilan real-time (`templates/index.html`) yang di-refresh via endpoint JSON `/api/intelligence`, dilindungi HTTP Basic Auth.
- Estimasi harga dalam USD dihitung dari kurs IDR/USD yang di-hardcode di kode (`current_usd_rate`), bukan dari API kurs live.

## Tech Stack

- Python 3
- [ccxt](https://github.com/ccxt/ccxt) — koneksi ke exchange Indodax
- [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI) (`telebot`) — bot & notifikasi Telegram
- [Flask](https://flask.palletsprojects.com/) — web dashboard & REST API
- [pandas](https://pandas.pydata.org/) — pengolahan data candle & indikator
- [python-dotenv](https://pypi.org/project/python-dotenv/) — memuat konfigurasi dari file `.env`
- `requests`, `urllib3` — utilitas HTTP

## Instalasi

1. Clone repository:
   ```bash
   git clone https://github.com/<username>/high-tf.git
   cd high-tf
   ```

2. Buat virtual environment (opsional tapi disarankan):
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

3. Install dependency yang dibutuhkan (repo ini belum menyertakan `requirements.txt`, install manual):
   ```bash
   pip install ccxt pyTelegramBotAPI pandas flask python-dotenv requests
   ```

## Konfigurasi

Buat file `DATA.env` di root project (file ini **tidak boleh di-commit ke git** — sudah masuk `.gitignore`) berisi:

```env
TOKEN_HIGH=isi_dengan_token_bot_telegram_anda
CHAT_ID=isi_dengan_chat_id_tujuan_alert
WEB_PASSWORD=ganti_dengan_password_dashboard_anda
```

Keterangan:
- `TOKEN_HIGH` — token bot Telegram (dari [@BotFather](https://t.me/BotFather)).
- `CHAT_ID` — ID chat/grup Telegram tujuan pengiriman alert sinyal.
- `WEB_PASSWORD` — password login dashboard web (username tetap `admin`). Jika tidak diset, ada nilai default di kode — **wajib diganti** sebelum deploy.

**Jangan pernah membagikan atau meng-commit token/chat ID/password asli.** Gunakan placeholder seperti di atas saat berbagi konfigurasi.

## Menjalankan

### Mode lokal (proses nyala terus, dashboard + bot live)

```bash
python future_market.py
```

Setelah berjalan:
- Bot Telegram akan aktif menerima command `/cek <koin>` dan mengirim alert otomatis untuk sinyal grade A+.
- Dashboard web dapat diakses di `http://localhost:5000/` (port bisa diubah lewat environment variable `PORT`), login dengan username `admin` dan `WEB_PASSWORD` yang telah diset.

Catatan Windows: kalau muncul `UnicodeEncodeError` saat startup, jalankan dengan `PYTHONIOENCODING=utf-8` (console default `cp1252` gak bisa cetak emoji yang dipakai di log).

### Mode 24/7 gratis (GitHub Actions, tanpa dashboard live)

`future_market.py` adalah proses persisten (Flask + bot polling nyala terus) — GitHub Actions gak bisa nahan proses kayak gitu (job dibatasi durasi, gak ada konsep "server nyala terus"). Jadi buat jalan otomatis 24/7 tanpa biaya server, dipakai `scan_once.py`: sekali jalan → scan semua market → kirim alert Telegram buat sinyal A+ yang baru berubah → exit. Dijadwalkan tiap 15 menit lewat `.github/workflows/scan.yml` (cron `*/15 * * * *`), gratis selama repo public (Actions minutes unlimited buat repo public).

Konsekuensinya dashboard web dan command `/cek` interaktif **tidak tersedia** di mode ini (gak ada proses hidup buat nge-serve/nge-poll) — cuma alert Telegram otomatis yang jalan terus.

Setup:
1. Generate token bot baru dari [@BotFather](https://t.me/BotFather) kalau token lama sudah invalid.
2. Di repo GitHub, buka **Settings → Secrets and variables → Actions**, tambahkan secret `TOKEN_HIGH` dan `CHAT_ID` (nilai sama seperti di `DATA.env`).
3. Push ke branch `main` — workflow otomatis jalan tiap 15 menit, atau trigger manual lewat tab **Actions → Indodax Scan (24/7) → Run workflow**.
4. State alert terakhir (`last_alerts.json`, biar gak kirim alert dobel) dipertahankan otomatis lewat `actions/cache` antar-run.

## Struktur Project

```
high-tf/
├── future_market.py     # Entry point: scanner, analisis, bot Telegram, server Flask
├── templates/
│   └── index.html       # Dashboard web real-time
├── LICENSE               # MIT License
└── .gitignore
```

## Disclaimer

Proyek ini dibuat untuk tujuan riset dan edukasi. Sinyal, grading, dan target profit (TP1/TP2/TP3) yang dihasilkan bersifat otomatis berdasarkan indikator teknikal sederhana (RSI, volume) dan **bukan merupakan nasihat keuangan**. Trading aset kripto memiliki risiko tinggi, termasuk risiko kehilangan seluruh modal. Gunakan bot ini dengan tanggung jawab sendiri, lakukan riset tambahan, dan jangan menggunakan dana yang tidak siap untuk hilang.
