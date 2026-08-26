"""Entry point buat mode GitHub Actions: satu kali scan semua market IDR di Indodax,
kirim alert Telegram buat sinyal grade A+ yang baru berubah, lalu exit.

Beda sama future_market.py (mode lama, proses nyala terus - Flask dashboard + bot
Telegram polling live) - script ini didesain buat dipanggil berkala lewat cron
(lihat .github/workflows/scan.yml), karena Actions gak bisa nahan proses persisten.
last_alerts.json dipertahankan lewat actions/cache biar alert gak dobel tiap run
(pola sama kayak signal.log di project idx-algo-signal-surya).
"""
import ccxt
import time
import json
import os
import urllib3
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv("DATA.env")

TOKEN = os.getenv("TOKEN_HIGH")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("Kritis: TOKEN_HIGH / CHAT_ID belum diset (env var atau DATA.env).")

STATE_FILE = "last_alerts.json"
SNAPSHOT_FILE = "latest_scan.json"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
exchange = ccxt.indodax({'enableRateLimit': True, 'verify': False})
current_usd_rate = 16200


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def fetch_all_markets():
    markets = exchange.load_markets()
    return [s for s in markets if s.endswith('/IDR')]


def get_market_analysis(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if not ohlcv or len(ohlcv) < 20:
            return None
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])

        df['sma_20'] = df['close'].rolling(window=20).mean()
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / loss)))

        green_vol = df[df['close'] > df['open']]['vol'].sum()
        red_vol = df[df['close'] < df['open']]['vol'].sum()
        mpi = (green_vol / (green_vol + red_vol)) * 100 if (green_vol + red_vol) > 0 else 50

        last = df.iloc[-1]
        df['vol_avg'] = df['vol'].rolling(window=20).mean()
        vol_spike_ratio = last['vol'] / df['vol_avg'].iloc[-1] if df['vol_avg'].iloc[-1] > 0 else 0

        signal = "NEUTRAL"
        if last['rsi'] < 35:
            signal = "STRONG ACCUMULATION"
        elif last['rsi'] > 65:
            signal = "DISTRIBUTION / SELL"

        curr_p = last['close']

        df['range_pct'] = (df['high'] - df['low']) / df['low']
        avg_range = df['range_pct'].tail(20).mean()
        base_step = max(min(avg_range, 0.08), 0.01)
        power_multiplier = 1.0 + (vol_spike_ratio / 10)

        if "ACCUMULATION" in signal:
            tp1_raw = curr_p * (1 + base_step)
            tp2_raw = curr_p * (1 + base_step * 1.8 * power_multiplier)
            tp3_raw = curr_p * (1 + base_step * 3.5 * power_multiplier)
        elif "DISTRIBUTION" in signal:
            tp1_raw = curr_p * (1 - base_step)
            tp2_raw = curr_p * (1 - base_step * 1.8 * power_multiplier)
            tp3_raw = curr_p * (1 - base_step * 3.5 * power_multiplier)
        else:
            tp1_raw = tp2_raw = tp3_raw = curr_p

        grade = "C (LOW)"
        if "ACCUMULATION" in signal and mpi > 65 and vol_spike_ratio > 1.5:
            grade = "A+ (PERFECT)"
        elif "DISTRIBUTION" in signal and mpi < 35 and vol_spike_ratio > 1.5:
            grade = "A+ (PERFECT)"
        elif (mpi > 65 or mpi < 35) and vol_spike_ratio <= 1.5:
            grade = "B (EARLY)"

        return {
            'price_usd': (curr_p / current_usd_rate) * 0.95,
            'tp1_usd': (tp1_raw / current_usd_rate) * 0.95,
            'tp2_usd': (tp2_raw / current_usd_rate) * 0.95,
            'tp3_usd': (tp3_raw / current_usd_rate) * 0.95,
            'rsi': last['rsi'], 'mpi': mpi, 'signal': signal, 'vol_spike': vol_spike_ratio, 'grade': grade
        }
    except Exception as e:
        print(f"[warn] gagal analisis {symbol}: {e}")
        return None


def send_alert(coin_name, data):
    msg = (
        f"*CAHYO INTELLIGENCE ALERT*\n"
        f"Asset: `{coin_name}`\n"
        f"Grade: *{data['grade']}*\n"
        f"Signal: *{data['signal']}*\n"
        f"Entry: `${data['price_usd']:.8f}`\n"
        f"TP1: `${data['tp1_usd']:.8f}`\n"
        f"TP2: `${data['tp2_usd']:.8f}`\n"
        f"TP3: `${data['tp3_usd']:.8f}`\n"
        f"Power: `{data['mpi']:.1f}%` | Vol: `{data['vol_spike']:.1f}x`\n"
        f"https://indodax.com/market/{coin_name}IDR"
    )
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    resp.raise_for_status()


def main():
    symbols = fetch_all_markets()
    print(f"Scanning {len(symbols)} assets...")

    state = load_state()
    alert_count = 0
    snapshot = []
    scanned_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for symbol in symbols:
        data = get_market_analysis(symbol)
        if data is None:
            continue
        coin_name = symbol.split('/')[0]

        snapshot.append({
            "asset": coin_name, "signal": data['signal'], "grade": data['grade'],
            "price": f"{data['price_usd']:.8f}",
            "tp1": f"{data['tp1_usd']:.8f}", "tp2": f"{data['tp2_usd']:.8f}", "tp3": f"{data['tp3_usd']:.8f}",
            "rsi": f"{data['rsi']:.2f}", "mpi": f"{data['mpi']:.1f}", "vol": f"{data['vol_spike']:.1f}"
        })

        if data['grade'] == "A+ (PERFECT)":
            if state.get(coin_name) != data['signal']:
                try:
                    send_alert(coin_name, data)
                    alert_count += 1
                except Exception as e:
                    print(f"[warn] gagal kirim alert {coin_name}: {e}")
                state[coin_name] = data['signal']
        elif coin_name in state:
            del state[coin_name]

    save_state(state)
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump({"scanned_at": scanned_at, "reports": snapshot}, f)
    print(f"Done. {alert_count} alert terkirim. Snapshot: {len(snapshot)} assets.")


if __name__ == "__main__":
    main()
