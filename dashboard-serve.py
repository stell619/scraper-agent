#!/usr/bin/env python3
"""
SCRAPER AGENT — Dashboard Server
Live web dashboard showing bot status, market data, system stats, activity log.

USAGE:
    python dashboard-serve.py

Then open http://localhost:8080
"""

import json
import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import config

app = Flask(__name__)

# ── Paths ─────────────────────────────────────────────────────
DASHBOARD_DIR = Path(os.environ.get("DASHBOARD_DIR", Path(__file__).parent))
SCRAPER_DIR   = Path(__file__).parent
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", 8080))

# ── State ─────────────────────────────────────────────────────
bot_state = {
    "state":          "idle",
    "message":        "Idle — waiting for instructions",
    "model":          config.LLM_BACKEND,
    "last_updated":   datetime.now().isoformat(),
    "sessions_today": 0,
    "tokens_today":   0,
}

activity_log  = deque(maxlen=50)
market_cache  = {"crypto": None, "stocks": None, "last_fetch": None}
system_cache  = {"data": None,   "last_fetch": None}

_state_lock  = threading.Lock()
_cache_lock  = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────

def log_activity(msg: str, level: str = "ok"):
    t = datetime.now().strftime("%H:%M:%S")
    activity_log.appendleft({"time": t, "msg": msg, "level": level})


def run_scraper(query: str) -> str:
    """Run a scraper query via the agent CLI."""
    try:
        venv_python = SCRAPER_DIR / "venv" / "bin" / "python"
        python_cmd  = str(venv_python) if venv_python.exists() else "python3"
        result = subprocess.run(
            [python_cmd, str(SCRAPER_DIR / "agent.py"), "--no-llm", query],
            capture_output=True, text=True, timeout=120, cwd=str(SCRAPER_DIR)
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return "ERROR: Scraper timed out"
    except Exception as e:
        return f"ERROR: {e}"


# ── System Stats ──────────────────────────────────────────────

def get_system_stats() -> dict:
    """Read system metrics from /proc — no external tools needed."""
    now = time.time()
    if (system_cache["data"]
            and system_cache["last_fetch"]
            and now - system_cache["last_fetch"] < 5):
        return system_cache["data"]

    stats = {}

    # CPU usage
    try:
        with open("/proc/stat") as f:
            line1 = f.readline()
        time.sleep(0.1)
        with open("/proc/stat") as f:
            line2 = f.readline()
        p1 = [int(x) for x in line1.split()[1:]]
        p2 = [int(x) for x in line2.split()[1:]]
        idle_diff  = p2[3] - p1[3]
        total_diff = sum(p2) - sum(p1)
        stats["cpu_pct"] = round((1 - idle_diff / max(total_diff, 1)) * 100, 1)
    except Exception:
        stats["cpu_pct"] = 0

    stats["cpu_cores"] = os.cpu_count() or 0

    # Load average
    try:
        load = os.getloadavg()
        stats["load_1m"]  = round(load[0], 2)
        stats["load_5m"]  = round(load[1], 2)
        stats["load_15m"] = round(load[2], 2)
    except Exception:
        stats["load_1m"] = stats["load_5m"] = stats["load_15m"] = 0

    # RAM
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                mem[parts[0].rstrip(":")] = int(parts[1])
        total_gb = mem.get("MemTotal", 0) / 1024 / 1024
        avail_gb = mem.get("MemAvailable", 0) / 1024 / 1024
        used_gb  = total_gb - avail_gb
        stats["ram_total_gb"] = round(total_gb, 1)
        stats["ram_used_gb"]  = round(used_gb, 1)
        stats["ram_pct"]      = round(used_gb / max(total_gb, 1) * 100, 1)
    except Exception:
        stats["ram_total_gb"] = stats["ram_used_gb"] = stats["ram_pct"] = 0

    # Disk
    try:
        st = os.statvfs("/")
        total_gb = st.f_blocks * st.f_frsize / (1024 ** 3)
        free_gb  = st.f_bfree  * st.f_frsize / (1024 ** 3)
        used_gb  = total_gb - free_gb
        stats["disk_total_gb"] = round(total_gb)
        stats["disk_used_gb"]  = round(used_gb)
        stats["disk_pct"]      = round(used_gb / max(total_gb, 1) * 100, 1)
    except Exception:
        stats["disk_total_gb"] = stats["disk_used_gb"] = stats["disk_pct"] = 0

    # Uptime
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        stats["uptime"] = f"{h}h {m}m"
    except Exception:
        stats["uptime"] = "?"

    # CPU temp
    try:
        temps = []
        thermal = "/sys/class/thermal"
        if os.path.exists(thermal):
            for zone in os.listdir(thermal):
                tf = os.path.join(thermal, zone, "temp")
                if os.path.exists(tf):
                    with open(tf) as f:
                        t = int(f.read().strip()) / 1000
                    if 0 < t < 120:
                        temps.append(t)
        stats["cpu_temp"] = round(max(temps), 1) if temps else None
    except Exception:
        stats["cpu_temp"] = None

    # Process count
    try:
        stats["processes"] = len([p for p in os.listdir("/proc") if p.isdigit()])
    except Exception:
        stats["processes"] = 0

    # Network I/O
    try:
        total_rx = total_tx = 0
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                parts = line.split()
                if parts[0].rstrip(":") != "lo":
                    total_rx += int(parts[1])
                    total_tx += int(parts[9])
        stats["net_rx_mb"] = round(total_rx / (1024 ** 2), 1)
        stats["net_tx_mb"] = round(total_tx / (1024 ** 2), 1)
    except Exception:
        stats["net_rx_mb"] = stats["net_tx_mb"] = 0

    system_cache["data"]       = stats
    system_cache["last_fetch"] = now
    return stats


# ── Market Data ───────────────────────────────────────────────

def _load_cache_files() -> list:
    """Load all JSON files from the scraper cache directory."""
    results = []
    cache_dir = SCRAPER_DIR / ".cache"
    if not cache_dir.exists():
        return results
    for f in cache_dir.glob("*.json"):
        try:
            results.append(json.loads(f.read_text()))
        except Exception:
            continue
    return results


def parse_crypto_from_cache() -> dict:
    data = {
        "total_market_cap": "", "btc_dominance": "",
        "change_24h": "", "fear_greed": "",
        "top_coins": [], "gainers": [], "losers": [],
    }
    for d in _load_cache_files():
        if "global" in d:
            g   = d["global"]
            cap = g.get("total_market_cap_usd", 0)
            if cap > 0:
                data["total_market_cap"] = f"${cap / 1e12:.2f}T"
            data["btc_dominance"] = f"{g.get('btc_dominance', 0)}%"
            data["change_24h"]    = f"{g.get('market_cap_change_24h', 0):+.2f}%"
            data["fear_greed"]    = d.get("fear_greed", "")
            data["gainers"] = [
                {"symbol": c.get("symbol"), "price": c.get("price"), "change": c.get("change_24h")}
                for c in d.get("top_gainers", [])[:5]
            ]
            data["losers"] = [
                {"symbol": c.get("symbol"), "price": c.get("price"), "change": c.get("change_24h")}
                for c in d.get("top_losers", [])[:5]
            ]
        if "coins" in d and not data["top_coins"]:
            data["top_coins"] = [
                {
                    "rank":       c.get("rank"),
                    "symbol":     c.get("symbol"),
                    "name":       c.get("name"),
                    "price":      c.get("price"),
                    "change":     c.get("change_24h"),
                    "market_cap": c.get("market_cap"),
                }
                for c in d["coins"][:20]
            ]
    return data


def parse_stocks_from_cache() -> dict:
    data = {"indices": [], "gainers": [], "losers": []}
    for d in _load_cache_files():
        if "indices" in d:
            data["indices"] = [
                {"name": name, "price": v.get("price"), "change_pct": v.get("change_pct")}
                for name, v in d["indices"].items()
            ]
            data["gainers"] = d.get("top_gainers", [])[:5]
            data["losers"]  = d.get("top_losers",  [])[:5]
    return data


def fetch_market_data_loop():
    """Background thread — refresh market data every 5 minutes."""
    while True:
        try:
            log_activity("Fetching crypto market data...", "active")
            run_scraper("crypto market overview")
            with _cache_lock:
                market_cache["crypto"] = parse_crypto_from_cache()
            log_activity("Crypto data updated", "ok")

            log_activity("Fetching stock market data...", "active")
            run_scraper("stock market summary")
            with _cache_lock:
                market_cache["stocks"] = parse_stocks_from_cache()
                market_cache["last_fetch"] = datetime.now().isoformat()
            log_activity("Stock data updated", "ok")
        except Exception as e:
            log_activity(f"Market fetch error: {e}", "err")

        time.sleep(300)


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    index = DASHBOARD_DIR / "dashboard-index.html"
    if index.exists():
        return send_from_directory(str(DASHBOARD_DIR), "dashboard-index.html")
    return "<h1>Dashboard not found</h1><p>Set DASHBOARD_DIR in .env</p>", 404


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(DASHBOARD_DIR), filename)


# ── Webhook (OpenClaw integration) ────────────────────────────

@app.route("/webhook/openclaw", methods=["POST"])
def openclaw_webhook():
    data  = request.json or {}
    event = data.get("event", "")
    msg   = data.get("message", "")

    if event in ("thinking", "running", "tool_call", "processing"):
        with _state_lock:
            bot_state.update({"state": "busy", "message": msg or "Processing...",
                              "last_updated": datetime.now().isoformat()})
        log_activity(msg or "Processing...", "active")

    elif event in ("done", "idle", "complete"):
        with _state_lock:
            bot_state.update({"state": "idle", "message": "Idle — waiting for instructions",
                              "last_updated": datetime.now().isoformat(),
                              "sessions_today": bot_state.get("sessions_today", 0) + 1})
        log_activity(msg or "Task complete", "ok")

    elif event == "error":
        log_activity(f"Error: {msg}", "err")

    return jsonify({"ok": True})


@app.route("/status/busy", methods=["POST"])
def set_busy():
    msg = (request.json or {}).get("message", "Processing...")
    with _state_lock:
        bot_state.update({"state": "busy", "message": msg,
                          "last_updated": datetime.now().isoformat()})
    log_activity(msg, "active")
    return jsonify({"ok": True})


@app.route("/status/idle", methods=["POST"])
def set_idle():
    msg = (request.json or {}).get("message", "Task complete")
    with _state_lock:
        bot_state.update({"state": "idle", "message": "Idle — waiting for instructions",
                          "last_updated": datetime.now().isoformat()})
    log_activity(msg, "ok")
    return jsonify({"ok": True})


# ── Data API ──────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify(bot_state)


@app.route("/api/activity")
def api_activity():
    return jsonify({"log": list(activity_log)})


@app.route("/api/system")
def api_system():
    return jsonify(get_system_stats())


@app.route("/api/crypto")
def api_crypto():
    return jsonify(market_cache.get("crypto") or {})


@app.route("/api/stocks")
def api_stocks():
    return jsonify(market_cache.get("stocks") or {})


@app.route("/api/market_age")
def api_market_age():
    return jsonify({"last_fetch": market_cache.get("last_fetch")})


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    query = (request.json or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    with _state_lock:
        bot_state.update({"state": "busy", "message": f"Scraping: {query}"})
    log_activity(f"Manual scrape: {query}", "active")

    def _run():
        run_scraper(query)
        with _state_lock:
            bot_state.update({"state": "idle", "message": "Idle — waiting for instructions"})
        log_activity(f"Scrape complete: {query}", "ok")
        with _cache_lock:
            market_cache["crypto"] = parse_crypto_from_cache()
            market_cache["stocks"] = parse_stocks_from_cache()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Scraping '{query}' in background"})


# ── Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    log_activity("Dashboard server starting...", "ok")
    log_activity(f"Scraper dir: {SCRAPER_DIR}", "ok")
    log_activity(f"LLM backend: {config.LLM_BACKEND}", "ok")

    market_thread = threading.Thread(target=fetch_market_data_loop, daemon=True)
    market_thread.start()
    log_activity("Market data fetcher started (5min refresh cycle)", "ok")

    print(f"\n🕷️  Scraper Agent Dashboard")
    print(f"   Running at http://0.0.0.0:{DASHBOARD_PORT}")
    print(f"   Scraper dir: {SCRAPER_DIR}")
    print(f"   Press Ctrl+C to stop\n")

    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
