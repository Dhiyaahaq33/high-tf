"""Dashboard live HIGH TF - Vercel serverless (FastAPI).

Vercel serverless itu stateless per-invocation (gak bisa nahan proses/thread
background kayak future_market.py), jadi server ini gak nyimpen state sendiri
sama sekali. Data sinyal (latest_scan.json) di-scan & di-commit balik ke repo
GitHub oleh .github/workflows/scan.yml (cron tiap 15 menit) - server ini cuma
proxy: tiap request, ambil file itu langsung dari GitHub raw content, cek
basic auth, terus tampilkan. GitHub jadi "database" gratisnya, bukan Postgres,
karena datanya read-mostly (hasil scan), bukan state transaksional.
"""
import os
import time
import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "181268")
RAW_URL = "https://raw.githubusercontent.com/Dhiyaahaq33/high-tf/main/latest_scan.json"

app = FastAPI()

_cache = {"data": None, "fetched_at": 0}
CACHE_TTL = 30  # detik - biar gak nge-hit GitHub raw tiap request kalau dashboard di-poll rapat


def check_auth(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return False
    import base64
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return False
    return username == "admin" and password == WEB_PASSWORD


def unauthorized():
    return Response(
        "Masukkan Password Dashboard\nAkses ditolak!",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Login Required"'},
    )


def fetch_snapshot():
    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["data"]
    resp = requests.get(RAW_URL, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    _cache["data"] = data
    _cache["fetched_at"] = now
    return data


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not check_auth(request):
        return unauthorized()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/intelligence")
async def get_intelligence(request: Request):
    if not check_auth(request):
        return unauthorized()
    try:
        snap = fetch_snapshot()
    except Exception as e:
        return JSONResponse({"error": f"Gagal ambil data scan: {e}", "reports": []}, status_code=502)

    scanned_at = snap.get("scanned_at", "")
    reports = snap.get("reports", [])
    for r in reports:
        r["time"] = scanned_at

    grade_order = {"A+ (PERFECT)": 0, "B (EARLY)": 1, "C (LOW)": 2}
    reports = sorted(reports, key=lambda r: grade_order.get(r.get("grade"), 3))

    return {"scanned_at": scanned_at, "reports": reports}
