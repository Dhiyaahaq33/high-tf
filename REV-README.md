# CAHYO INTELLIGENCE — HIGH TF EDITION
Nama Proyek Asli: Future Market (future_market.py) — Varian High Timeframe

## Apa Ini?

Ini adalah bot scanner otomatis untuk pasar kripto **Indodax** (semua pasangan `/IDR`), versi **High Timeframe (1 jam)** dari keluarga bot "Future Market" / "Cahyo Intelligence".

Bot ini jalan 24 jam memindai seluruh koin yang diperdagangkan di Indodax, menghitung indikator teknikal (RSI, kekuatan volume beli/jual, lonjakan volume), lalu memberi **sinyal AKUMULASI (beli) atau DISTRIBUSI (jual)** beserta target profit (TP1/TP2/TP3) yang dihitung otomatis. Sinyal grade tertinggi (`A+ PERFECT`) langsung dikirim ke Telegram, dan semua hasil scan bisa dipantau real-time lewat dashboard web bergaya "hacker terminal" hijau-hitam.

Dibanding versi bot Indodax lain yang mungkin memakai timeframe lebih pendek (scalping), versi ini memakai candle **1 jam**, jadi sinyalnya lebih cocok untuk swing/posisi yang tidak perlu dipantau tiap menit.

## Fitur Utama

- **Auto-Scan Semua Koin IDR**: memindai semua pasangan `/IDR` yang ada di Indodax secara berulang tanpa henti.
- **Analisis Teknikal Otomatis**: RSI (14), SMA 20, rasio volume hijau vs merah (disebut "B-Power"/MPI), dan deteksi lonjakan volume (volume spike).
- **Sistem Grading Sinyal**: setiap sinyal diberi grade `A+ (PERFECT)`, `B (EARLY)`, atau `C (LOW)` berdasarkan kombinasi kekuatan sinyal.
- **Target Profit Adaptif**: TP1, TP2, TP3 dihitung otomatis berdasarkan rata-rata volatilitas (range candle) dan kekuatan lonjakan volume — bukan angka tetap.
- **Notifikasi Telegram Otomatis**: hanya sinyal grade `A+` yang dikirim ke Telegram, lengkap dengan tombol "Lihat Chart" langsung ke Indodax.
- **Perintah Telegram `/cek <koin>`**: cek manual analisis sebuah koin kapan saja, contoh `/cek btc`.
- **Dashboard Web Live**: tampilan web (`templates/index.html`) yang auto-refresh tiap 2 detik, menampilkan semua sinyal aktif dengan warna hijau (beli), merah (jual), kuning (netral), plus efek suara saat ada sinyal baru.
- **Proteksi Login Dashboard**: dashboard web dikunci dengan username/password (Basic Auth), password bisa diatur lewat `DATA.env`.
- **Konversi Harga ke USD**: harga IDR dikonversi otomatis ke estimasi USD dengan kurs yang bisa disesuaikan di kode.

## Teknologi yang Dipakai

- **Python 3** — bahasa utama bot ini.
- **Flask** — web server untuk dashboard dan API (`/api/intelligence`).
- **ccxt** — library untuk konek ke exchange Indodax dan ambil data harga/candle (OHLCV).
- **pandas** — hitung indikator teknikal (RSI, SMA, rata-rata volume, dll).
- **pyTelegramBotAPI (`telebot`)** — kirim notifikasi & terima perintah dari Telegram.
- **python-dotenv** — memuat konfigurasi rahasia dari file `DATA.env`.
- **requests** — komunikasi HTTP tambahan.
- **HTML/CSS/JavaScript (vanilla)** — dashboard web di `templates/index.html`, tanpa framework frontend, auto-polling API tiap 2 detik.

## Cara Instalasi

Laptop sudah punya Python 3.11.6 dan pip 26.1.1, jadi cukup ikuti langkah ini lewat PowerShell:

1. **Masuk ke folder proyek** (path ada spasi, selalu pakai tanda kutip):
   ```powershell
   cd "D:\BOT\MONEY\HIGH TF"
   ```

2. **(Opsional tapi disarankan) Buat virtual environment** supaya library bot ini tidak bercampur dengan proyek Python lain:
   ```powershell
   py -3.11 -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install semua library yang dibutuhkan** (tidak ada file `requirements.txt` di folder ini, jadi install manual satu-satu):
   ```powershell
   pip install ccxt pyTelegramBotAPI pandas flask python-dotenv requests urllib3
   ```

   Catatan: kalau nanti mau lebih rapi, buat file `requirements.txt` berisi baris di atas supaya instalasi berikutnya tinggal `pip install -r requirements.txt`.

4. **Siapkan file `DATA.env`** — file ini sudah ada di folder, isinya jangan diubah sembarangan kecuali tahu apa yang diubah (lihat bagian Catatan Penting).

## Cara Menjalankan

1. Pastikan virtual environment aktif (kalau dipakai):
   ```powershell
   cd "D:\BOT\MONEY\HIGH TF"
   .\venv\Scripts\Activate.ps1
   ```

2. Jalankan bot:
   ```powershell
   python future_market.py
   ```

3. Kalau berhasil, di terminal akan muncul pesan seperti `Intelligence Engine Ready: X Assets Scanned.` — artinya bot sudah mulai memindai pasar.

4. **Buka Dashboard Web**: buka browser ke `http://localhost:5000` (atau ganti port sesuai variabel environment `PORT` kalau diset). Akan diminta login:
   - Username: `admin`
   - Password: sesuai nilai `WEB_PASSWORD` di `DATA.env` (default `181268` kalau tidak diset).

5. **Cek via Telegram**: kirim perintah `/cek btc` (ganti `btc` dengan kode koin lain) ke bot Telegram yang tokennya terpasang di `DATA.env` untuk cek analisis manual.

6. Bot akan otomatis mengirim alert ke Telegram tiap kali menemukan sinyal grade `A+ (PERFECT)`, tanpa perlu aksi tambahan.

7. Untuk menghentikan bot, tekan `Ctrl + C` di terminal.


## Catatan Penting

- **File `DATA.env` berisi data rahasia** (kemungkinan token bot Telegram, chat ID, dan password dashboard). **Isi file ini TIDAK ditampilkan dalam dokumentasi ini demi keamanan.**
- File `DATA.env` **sudah terdaftar di `.gitignore`** folder ini, jadi aman dari ter-commit ke git secara tidak sengaja. Tetap disarankan untuk:
  - Jangan pernah membagikan isi `DATA.env` ke publik (chat, screenshot, upload repo, dll).
  - Jangan push folder ini ke repository GitHub yang bersifat publik tanpa memastikan `DATA.env` benar-benar terkecuali.
  - Kalau token/password pernah bocor atau diduga bocor, segera revoke/ganti token bot Telegram-nya.
- Bot ini melakukan request terus-menerus ke API Indodax (loop tanpa henti) — pastikan koneksi internet stabil saat dijalankan dalam waktu lama.
- Tidak ada file `requirements.txt` di folder ini saat dokumentasi ini dibuat — daftar library di atas didapat dari membaca langsung kode `future_market.py`.
- Tidak ditemukan file README asli di folder ini — dokumentasi ini dibuat dari nol berdasarkan hasil membaca kode `future_market.py` dan `templates/index.html`.

## Kebutuhan API LLM

- **Butuh API LLM?** Tidak — semua sinyal (RSI, volume, grading A+/B/C, target profit) dihitung murni pakai rumus teknikal (pandas/ccxt), bukan lewat model bahasa. Bot ini rule-based sepenuhnya.
- **Bisa pakai API Claude (Anthropic)?** Tidak relevan untuk cara kerja inti — proyek ini tidak memproses bahasa alami / tidak butuh LLM sama sekali. Kalau mau nambah fitur opsional seperti narasi penjelasan sinyal ke Telegram ("kenapa BTC dapat grade A+ sekarang") dalam bahasa natural, itu bisa ditambahkan pakai Claude Haiku 4.5 (cepat & murah untuk narasi singkat per sinyal) sebagai fitur tempelan di luar logic scanning yang sudah ada.

## Instalasi & Eksekusi Offline

- **Bisa instalasi offline?** Tidak untuk install pertama — `pip install ccxt pyTelegramBotAPI pandas flask python-dotenv requests urllib3` wajib online karena narik package dari PyPI. Kalau semua package itu sudah pernah didownload/di-cache di komputer yang sama, instalasi ulang bisa lewat cache pip lokal tanpa internet.
- **Bisa dijalankan offline (setelah terinstall)?** Tidak — bot ini terus-menerus manggil API live Indodax (lewat ccxt) untuk data harga/candle dan juga API Telegram untuk kirim notifikasi/terima perintah `/cek`. Tanpa internet, bot tidak bisa scan pasar maupun kirim sinyal, jadi wajib online selama berjalan.
