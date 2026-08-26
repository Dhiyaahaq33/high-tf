"""Cron job (GitHub Actions, tiap 5 menit): cek harga live Indodax buat posisi
simulasi yang lagi terbuka di web/server.py, auto-close yang kena TP/SL.

Dipisah dari scan_once.py karena beda ritme - sinyal baru dicari tiap 15 menit
(butuh scan 493 aset), tapi TP/SL pada posisi yang KEBUKA harus dicek lebih
sering biar gak telat nutup pas harga udah lewat target.
"""
import os
import time
import ccxt
import requests

SERVER_URL = os.environ.get("SERVER_URL", "https://high-tf-dashboard.vercel.app")
BOT_SECRET = os.environ.get("BOT_SECRET")

if not BOT_SECRET:
    raise ValueError("Kritis: BOT_SECRET belum diset.")

HEADERS = {"X-Bot-Secret": BOT_SECRET}
exchange = ccxt.indodax({'enableRateLimit': True})


def get_positions():
    resp = requests.get(f"{SERVER_URL}/positions-for-monitor", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()["positions"]


def get_price(symbol):
    ticker = exchange.fetch_ticker(f"{symbol}/IDR")
    return ticker["last"]


def close_position(pos_id, exit_price, reason):
    resp = requests.post(
        f"{SERVER_URL}/close-by-monitor", headers=HEADERS, timeout=15,
        json={"position_id": pos_id, "exit_price": exit_price, "reason": reason},
    )
    resp.raise_for_status()
    return resp.json()


def main():
    positions = get_positions()
    print(f"Monitoring {len(positions)} posisi terbuka...")
    closed = 0

    for pos in positions:
        try:
            price = get_price(pos["symbol"])
        except Exception as e:
            print(f"[warn] gagal ambil harga {pos['symbol']}: {e}")
            continue

        direction = pos["direction"]
        tp, sl = pos["tp"], pos["sl"]
        hit = None

        if direction == "LONG":
            if price >= tp:
                hit = "TP"
            elif price <= sl:
                hit = "SL"
        else:  # SHORT
            if price <= tp:
                hit = "TP"
            elif price >= sl:
                hit = "SL"

        if hit:
            try:
                close_position(pos["id"], price, hit)
                print(f"[Close] {pos['symbol']} {direction} kena {hit} @ {price}")
                closed += 1
            except Exception as e:
                print(f"[warn] gagal tutup posisi {pos['symbol']}: {e}")

        time.sleep(0.3)

    print(f"Done. {closed} posisi ditutup.")


if __name__ == "__main__":
    main()
