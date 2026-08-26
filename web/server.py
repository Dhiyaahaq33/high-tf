"""HIGH TF paper-trading simulation - Vercel serverless (FastAPI) + Neon Postgres.

Beda dari server.py versi lama (proxy baca-doang ke latest_scan.json di GitHub):
sekarang ada state transaksional (saldo, posisi terbuka, PnL) yang berubah tiap
ada trade dieksekusi - Vercel serverless stateless per-invocation jadi gak bisa
nyimpen ini di memori, dipindah ke Postgres (Neon, gratis) sebagai single source
of truth, dibaca ulang di awal tiap request. Pola persis sama kayak
axanctum-intelligence.

Alur:
- scan_once.py (GitHub Actions, cron tiap 15 menit) nemuin sinyal grade A+ baru,
  POST ke /signal di sini (pakai header X-Bot-Secret, bukan basic auth browser).
- Kalau auto-open nyala, sinyal langsung dieksekusi jadi posisi simulasi -
  TAPI ditolak kalau margin-of-safety udah kelewat batas (lihat check_margin_safety).
- price_monitor_once.py (GitHub Actions, cron tiap 5 menit) cek harga live
  Indodax buat posisi terbuka, auto-close yang kena TP/SL.
- Dashboard (browser, basic auth admin/WEB_PASSWORD) baca & kontrol semua ini
  lewat endpoint di bawah, di-poll tiap beberapa detik dari frontend.
"""
import base64
import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

TZ_WIB = timezone(timedelta(hours=7))

WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "181268")
BOT_SECRET = os.environ.get("BOT_SECRET", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

_db_pool: Optional[asyncpg.Pool] = None
_db_ready = False


def check_auth(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return False
    return username == "admin" and password == WEB_PASSWORD


def require_auth(request: Request):
    if not check_auth(request):
        raise HTTPException(401, "Password salah", headers={"WWW-Authenticate": 'Basic realm="Login Required"'})


def require_bot_secret(request: Request):
    if not BOT_SECRET or request.headers.get("x-bot-secret") != BOT_SECRET:
        raise HTTPException(401, "Bot secret salah")


async def get_pool() -> asyncpg.Pool:
    global _db_pool, _db_ready
    if not DATABASE_URL:
        raise HTTPException(500, "DATABASE_URL belum diset")
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(DATABASE_URL, ssl="require", min_size=0, max_size=3)
    if not _db_ready:
        async with _db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sim_account (
                    key TEXT PRIMARY KEY,
                    value DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS sim_positions (
                    id BIGINT PRIMARY KEY,
                    data JSONB
                );
                CREATE TABLE IF NOT EXISTS sim_history (
                    id BIGINT PRIMARY KEY,
                    data JSONB
                );
                CREATE TABLE IF NOT EXISTS sim_signals (
                    id BIGINT PRIMARY KEY,
                    data JSONB
                );
                CREATE UNIQUE INDEX IF NOT EXISTS sim_positions_symbol_uidx
                    ON sim_positions ((data->>'symbol'));
            """)
        _db_ready = True
    return _db_pool


DEFAULT_ACCOUNT = {
    "balance":             1000.0,
    "realized_pnl":        0.0,
    "wins":                0,
    "losses":              0,
    "max_positions":       0,
    "default_leverage":    5,
    "default_margin_pct":  10,
    "auto_open":           False,
    "max_margin_usage_pct": 50,   # margin-of-safety: total margin terpakai / equity, batas atas sebelum open ditolak
    "signal_id_counter":   1,
}


async def load_state() -> dict:
    pool = await get_pool()
    state = dict(DEFAULT_ACCOUNT)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM sim_account")
        for r in rows:
            key = r["key"]
            if key in ("wins", "losses", "signal_id_counter", "max_positions"):
                state[key] = int(r["value"])
            elif key == "auto_open":
                state[key] = bool(r["value"])
            else:
                state[key] = r["value"]

        pos_rows = await conn.fetch("SELECT data FROM sim_positions ORDER BY id")
        state["positions"] = [json.loads(r["data"]) for r in pos_rows]

        sig_rows = await conn.fetch("SELECT data FROM sim_signals ORDER BY id DESC LIMIT 100")
        state["signals"] = [json.loads(r["data"]) for r in sig_rows]

        hist_rows = await conn.fetch("SELECT data FROM sim_history ORDER BY id DESC LIMIT 100")
        state["history"] = [json.loads(r["data"]) for r in hist_rows]

    return state


async def save_account(state: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        for key in (
            "balance", "realized_pnl", "wins", "losses",
            "signal_id_counter", "auto_open", "max_positions",
            "default_leverage", "default_margin_pct", "max_margin_usage_pct",
        ):
            await conn.execute(
                """
                INSERT INTO sim_account(key, value) VALUES($1,$2)
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
                """,
                key, float(state.get(key, 0) or 0),
            )


def margin_used(positions: list) -> float:
    return sum(p["margin"] for p in positions)


def check_margin_safety(state: dict, new_margin: float) -> Optional[str]:
    """Margin-of-safety guard: total margin terpakai (termasuk posisi yang mau
    dibuka) dibanding total equity (balance + margin yang udah terkunci di
    posisi lain) gak boleh lewat max_margin_usage_pct. Return alasan penolakan
    kalau kelewat, None kalau aman."""
    used = margin_used(state["positions"])
    equity = state["balance"] + used
    if equity <= 0:
        return "Equity habis"
    projected_ratio = (used + new_margin) / equity * 100
    cap = state.get("max_margin_usage_pct", 50)
    if projected_ratio > cap:
        return f"Margin of safety kelewat batas ({projected_ratio:.1f}% > {cap:.0f}%) - posisi ditolak"
    return None


async def open_position_atomic(pos: dict, margin: float) -> bool:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO sim_positions(id, data) VALUES($1,$2)",
                    pos["id"], json.dumps(pos),
                )
                bal_row = await conn.fetchrow("SELECT value FROM sim_account WHERE key='balance' FOR UPDATE")
                balance = float(bal_row["value"]) if bal_row else 1000.0
                balance -= margin
                await conn.execute(
                    """
                    INSERT INTO sim_account(key, value) VALUES('balance', $1)
                    ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
                    """,
                    float(balance),
                )
        return True
    except asyncpg.UniqueViolationError:
        return False


async def save_signal(sig: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sim_signals(id, data) VALUES($1,$2)
            ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data
            """,
            sig["id"], json.dumps(sig),
        )


async def delete_signal(sig_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sim_signals WHERE id=$1", sig_id)


async def _close_position_in_state(state: dict, pos_id: int, reason: str, exit_price: float):
    pos = next((p for p in state["positions"] if p["id"] == pos_id), None)
    if not pos:
        return None
    pct = (exit_price - pos["entry"]) / pos["entry"] if pos["entry"] else 0
    pnl = (pct if pos["direction"] == "LONG" else -pct) * pos["margin"] * pos["leverage"]

    hist_entry = {
        "id":        int(time.time() * 1000),
        "time":      datetime.now(TZ_WIB).strftime("%d/%m %H:%M"),
        "symbol":    pos["symbol"],
        "direction": pos["direction"],
        "entry":     pos["entry"],
        "exit":      round(exit_price, 8),
        "pnl":       round(pnl, 4),
        "reason":    reason,
        "opened_at": pos.get("opened_at", ""),
        "tp":        pos["tp"],
        "sl":        pos["sl"],
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            claimed = await conn.fetchrow("DELETE FROM sim_positions WHERE id=$1 RETURNING id", pos_id)
            if not claimed:
                return None

            bal_row = await conn.fetchrow("SELECT value FROM sim_account WHERE key='balance' FOR UPDATE")
            pnl_row = await conn.fetchrow("SELECT value FROM sim_account WHERE key='realized_pnl' FOR UPDATE")
            win_row = await conn.fetchrow("SELECT value FROM sim_account WHERE key='wins' FOR UPDATE")
            loss_row = await conn.fetchrow("SELECT value FROM sim_account WHERE key='losses' FOR UPDATE")

            balance = float(bal_row["value"]) if bal_row else 1000.0
            realized = float(pnl_row["value"]) if pnl_row else 0.0
            wins = int(win_row["value"]) if win_row else 0
            losses = int(loss_row["value"]) if loss_row else 0

            balance += pos["margin"] + pnl
            realized += pnl
            if pnl >= 0:
                wins += 1
            else:
                losses += 1

            for key, val in [("balance", balance), ("realized_pnl", realized), ("wins", wins), ("losses", losses)]:
                await conn.execute(
                    """
                    INSERT INTO sim_account(key, value) VALUES($1,$2)
                    ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
                    """,
                    key, float(val),
                )

            await conn.execute(
                """
                INSERT INTO sim_history(id, data) VALUES($1,$2)
                ON CONFLICT(id) DO NOTHING
                """,
                hist_entry["id"], json.dumps(hist_entry),
            )

    return pnl


def _state_response(state: dict) -> dict:
    used = margin_used(state["positions"])
    equity = state["balance"] + used
    return {
        "type":                 "state",
        "balance":              state["balance"],
        "realized_pnl":         state["realized_pnl"],
        "wins":                 state["wins"],
        "losses":               state["losses"],
        "positions":            state["positions"],
        "signals":              state["signals"],
        "history":              state["history"][:50],
        "max_positions":        state.get("max_positions", 0),
        "default_leverage":     state.get("default_leverage", 5),
        "default_margin_pct":   state.get("default_margin_pct", 10),
        "auto_open":            state.get("auto_open", False),
        "max_margin_usage_pct": state.get("max_margin_usage_pct", 50),
        "margin_used":          round(used, 4),
        "margin_usage_pct":     round((used / equity * 100) if equity > 0 else 0, 1),
        "equity":               round(equity, 4),
    }


app = FastAPI(title="HIGH TF SIMULATION")


class Signal(BaseModel):
    symbol: str; direction: str; entry: float; tp: float; sl: float
    grade: str = "B"; leverage: int = 5


class ApproveRequest(BaseModel):
    signal_id: int; leverage: Optional[int] = None
    tp: Optional[float] = None; sl: Optional[float] = None
    margin_pct: Optional[float] = None


class CloseRequest(BaseModel):
    position_id: int; exit_price: float; reason: str = "Manual"


class DepositRequest(BaseModel):
    amount: float


class SettingsRequest(BaseModel):
    default_leverage: Optional[int] = None
    default_margin_pct: Optional[float] = None
    max_margin_usage_pct: Optional[float] = None


async def try_open_from_signal(state: dict, sig: dict, leverage: Optional[int] = None,
                                tp: Optional[float] = None, sl: Optional[float] = None,
                                margin_pct: Optional[float] = None):
    symbol = sig["symbol"]
    max_pos = state.get("max_positions", 0)
    already_open = any(p["symbol"] == symbol for p in state["positions"])
    if already_open:
        return False, f"{symbol} sudah ada posisi terbuka"
    if max_pos > 0 and len(state["positions"]) >= max_pos:
        return False, f"Max posisi ({max_pos}) sudah tercapai"

    mpct = (margin_pct if margin_pct is not None else state.get("default_margin_pct", 10)) / 100
    margin = round(state["balance"] * mpct, 4)
    if margin <= 0 or state["balance"] < margin:
        return False, "Saldo tidak cukup"

    guard_reason = check_margin_safety(state, margin)
    if guard_reason:
        return False, guard_reason

    pos = {
        "id":        int(time.time() * 1000),
        "symbol":    symbol,
        "direction": sig["direction"],
        "entry":     sig["entry"],
        "tp":        tp if tp is not None else sig["tp"],
        "sl":        sl if sl is not None else sig["sl"],
        "leverage":  leverage if leverage is not None else state.get("default_leverage", 5),
        "margin":    margin,
        "opened_at": datetime.now(TZ_WIB).strftime("%d/%m %H:%M"),
    }
    opened = await open_position_atomic(pos, margin)
    if not opened:
        return False, f"{symbol} sudah dibuka proses lain (race)"
    return True, pos


@app.get("/state")
async def get_state(request: Request):
    require_auth(request)
    state = await load_state()
    return _state_response(state)


@app.post("/signal")
async def receive_signal(sig: Signal, request: Request):
    require_bot_secret(request)
    state = await load_state()
    signal_id = state["signal_id_counter"]
    signal = {
        "id": signal_id, "symbol": sig.symbol.upper(),
        "direction": sig.direction.upper(), "entry": sig.entry,
        "tp": sig.tp, "sl": sig.sl, "grade": sig.grade,
        "leverage": sig.leverage,
        "time": datetime.now(TZ_WIB).strftime("%H:%M:%S"),
    }
    state["signal_id_counter"] = signal_id + 1
    await save_signal(signal)
    await save_account(state)
    print(f"[Signal] {signal['symbol']} {signal['direction']}")

    if state.get("auto_open", False):
        ok, result = await try_open_from_signal(state, signal)
        if ok:
            await delete_signal(signal_id)
            print(f"[AutoOpen] {signal['symbol']} {signal['direction']} @ {signal['entry']}")
        else:
            print(f"[AutoOpen] {signal['symbol']} ditolak: {result}")

    return {"ok": True, "signal_id": signal_id}


@app.post("/set-auto-open")
async def set_auto_open(enabled: bool, request: Request):
    require_auth(request)
    state = await load_state()
    state["auto_open"] = enabled
    await save_account(state)
    return {"ok": True, "auto_open": enabled}


@app.post("/approve")
async def approve_signal(req: ApproveRequest, request: Request):
    require_auth(request)
    state = await load_state()
    sig = next((s for s in state["signals"] if s["id"] == req.signal_id), None)
    if not sig:
        raise HTTPException(404, "Sinyal tidak ditemukan")

    ok, result = await try_open_from_signal(state, sig, req.leverage, req.tp, req.sl, req.margin_pct)
    if not ok:
        return {"ok": False, "reason": result}
    await delete_signal(req.signal_id)
    return {"ok": True, "position_id": result["id"]}


@app.post("/reject/{signal_id}")
async def reject_signal(signal_id: int, request: Request):
    require_auth(request)
    await delete_signal(signal_id)
    return {"ok": True}


@app.post("/close")
async def close_position(req: CloseRequest, request: Request):
    require_auth(request)
    state = await load_state()
    pnl = await _close_position_in_state(state, req.position_id, req.reason, req.exit_price)
    if pnl is None:
        raise HTTPException(404, "Posisi tidak ditemukan")
    return {"ok": True, "pnl": pnl}


@app.post("/set-max-positions")
async def set_max_positions(max_pos: int, request: Request):
    require_auth(request)
    state = await load_state()
    state["max_positions"] = max(0, max_pos)
    await save_account(state)
    return {"ok": True, "max_positions": state["max_positions"]}


@app.post("/save-settings")
async def save_settings(req: SettingsRequest, request: Request):
    require_auth(request)
    state = await load_state()
    if req.default_leverage is not None:
        state["default_leverage"] = max(1, req.default_leverage)
    if req.default_margin_pct is not None:
        state["default_margin_pct"] = max(1, min(100, req.default_margin_pct))
    if req.max_margin_usage_pct is not None:
        state["max_margin_usage_pct"] = max(1, min(100, req.max_margin_usage_pct))
    await save_account(state)
    return {"ok": True}


@app.post("/deposit")
async def deposit(req: DepositRequest, request: Request):
    require_auth(request)
    if req.amount == 0:
        raise HTTPException(400, "Jumlah tidak boleh 0")
    state = await load_state()
    state["balance"] += req.amount
    await save_account(state)
    return {"ok": True, "balance": state["balance"]}


@app.post("/set-balance")
async def set_balance(req: DepositRequest, request: Request):
    require_auth(request)
    if req.amount <= 0:
        raise HTTPException(400, "Saldo harus lebih dari 0")
    state = await load_state()
    state["balance"] = req.amount
    await save_account(state)
    return {"ok": True, "balance": state["balance"]}


@app.post("/reset")
async def reset(request: Request):
    require_auth(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sim_positions; DELETE FROM sim_history; "
            "DELETE FROM sim_signals; DELETE FROM sim_account;"
        )
    return {"ok": True}


# --- Dipakai price_monitor_once.py (GitHub Actions), bukan browser ---
@app.get("/positions-for-monitor")
async def positions_for_monitor(request: Request):
    require_bot_secret(request)
    state = await load_state()
    return {"positions": state["positions"]}


@app.post("/close-by-monitor")
async def close_by_monitor(req: CloseRequest, request: Request):
    require_bot_secret(request)
    state = await load_state()
    pnl = await _close_position_in_state(state, req.position_id, req.reason, req.exit_price)
    if pnl is None:
        return {"ok": False}
    return {"ok": True, "pnl": pnl}


@app.get("/price/{symbol}")
async def get_price(symbol: str, request: Request):
    require_auth(request)
    try:
        resp = requests.get(f"https://indodax.com/api/ticker/{symbol.lower()}idr", timeout=6)
        resp.raise_for_status()
        last = float(resp.json()["ticker"]["last"])
        return {"symbol": symbol.upper(), "price": last}
    except Exception as e:
        raise HTTPException(502, f"Gagal ambil harga: {e}")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    require_auth(request)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()
