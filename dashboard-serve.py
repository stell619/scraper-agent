from flask import Flask, send_from_directory, jsonify, request
import os
import json
import subprocess
import threading
import time
import re
from datetime import datetime, timedelta
from collections import deque

app = Flask(__name__)
DASHBOARD_DIR = os.path.expanduser('~/dashboard')
DATA_DIR = os.path.expanduser('~/openclaw-data')
ART_DIR = os.path.expanduser('~/art-channel')
SCRAPER_DIR = os.path.expanduser('~/scraper-agent')

bot_state = {
    'state': 'idle',
    'message': 'Idle — waiting for instructions',
    'model': 'anthropic/claude-haiku-4-5',
    'last_updated': datetime.now().isoformat(),
    'sessions_today': 0,
    'tokens_today': 0,
}

activity_log = deque(maxlen=30)
market_cache = {'crypto': None, 'stocks': None, 'last_fetch': None}
system_cache = {'data': None, 'last_fetch': None}

def read_file_lines(path):
    try:
        with open(os.path.expanduser(path)) as f:
            return f.readlines()
    except:
        return []

def get_week_start():
    today = datetime.now()
    start = today - timedelta(days=today.weekday())
    return start.strftime('%Y-%m-%d')

def log_activity(msg, level='ok'):
    t = datetime.now().strftime('%H:%M:%S')
    activity_log.appendleft({'time': t, 'msg': msg, 'level': level})

def get_system_stats():
    now = time.time()
    if system_cache['data'] and system_cache['last_fetch'] and (now - system_cache['last_fetch']) < 5:
        return system_cache['data']
    stats = {}
    try:
        with open('/proc/stat') as f:
            line = f.readline()
        parts = line.split()
        idle = int(parts[4])
        total = sum(int(p) for p in parts[1:])
        time.sleep(0.1)
        with open('/proc/stat') as f:
            line2 = f.readline()
        parts2 = line2.split()
        idle2 = int(parts2[4])
        total2 = sum(int(p) for p in parts2[1:])
        diff_idle = idle2 - idle
        diff_total = total2 - total
        stats['cpu_pct'] = round((1 - diff_idle / max(diff_total, 1)) * 100, 1) if diff_total > 0 else 0
    except:
        stats['cpu_pct'] = 0
    stats['cpu_cores'] = os.cpu_count() or 0
    try:
        load = os.getloadavg()
        stats['load_1m'] = round(load[0], 2)
        stats['load_5m'] = round(load[1], 2)
        stats['load_15m'] = round(load[2], 2)
    except:
        stats['load_1m'] = 0
    try:
        with open('/proc/meminfo') as f:
            mem = {}
            for line in f:
                parts = line.split()
                mem[parts[0].rstrip(':')] = int(parts[1])
        total = mem.get('MemTotal', 0) / 1024 / 1024
        available = mem.get('MemAvailable', 0) / 1024 / 1024
        used = total - available
        stats['ram_total_gb'] = round(total, 1)
        stats['ram_used_gb'] = round(used, 1)
        stats['ram_pct'] = round((used / total) * 100, 1) if total > 0 else 0
    except:
        stats['ram_total_gb'] = 0
        stats['ram_used_gb'] = 0
        stats['ram_pct'] = 0
    try:
        st = os.statvfs('/')
        total = st.f_blocks * st.f_frsize / (1024**3)
        free = st.f_bfree * st.f_frsize / (1024**3)
        used = total - free
        stats['disk_total_gb'] = round(total, 0)
        stats['disk_used_gb'] = round(used, 0)
        stats['disk_pct'] = round((used / total) * 100, 1) if total > 0 else 0
    except:
        stats['disk_total_gb'] = 0
        stats['disk_used_gb'] = 0
        stats['disk_pct'] = 0
    try:
        with open('/proc/uptime') as f:
            uptime_secs = float(f.read().split()[0])
        hours = int(uptime_secs // 3600)
        mins = int((uptime_secs % 3600) // 60)
        stats['uptime'] = f'{hours}h {mins}m'
    except:
        stats['uptime'] = '?'
    try:
        temps = []
        thermal_dir = '/sys/class/thermal/'
        if os.path.exists(thermal_dir):
            for zone in os.listdir(thermal_dir):
                temp_file = os.path.join(thermal_dir, zone, 'temp')
                if os.path.exists(temp_file):
                    with open(temp_file) as f:
                        temp = int(f.read().strip()) / 1000
                        if 0 < temp < 120:
                            temps.append(temp)
        stats['cpu_temp'] = round(max(temps), 1) if temps else None
    except:
        stats['cpu_temp'] = None
    try:
        result = subprocess.run(['pgrep', '-f', 'openclaw-gateway'], capture_output=True, text=True, timeout=2)
        stats['openclaw_running'] = result.returncode == 0
    except:
        stats['openclaw_running'] = False
    try:
        with open('/proc/net/dev') as f:
            lines = f.readlines()
        total_rx = 0
        total_tx = 0
        for line in lines[2:]:
            parts = line.split()
            if parts[0].rstrip(':') not in ('lo',):
                total_rx += int(parts[1])
                total_tx += int(parts[9])
        stats['net_rx_mb'] = round(total_rx / (1024**2), 1)
        stats['net_tx_mb'] = round(total_tx / (1024**2), 1)
    except:
        stats['net_rx_mb'] = 0
        stats['net_tx_mb'] = 0
    try:
        stats['processes'] = len([p for p in os.listdir('/proc') if p.isdigit()])
    except:
        stats['processes'] = 0
    system_cache['data'] = stats
    system_cache['last_fetch'] = now
    return stats

def run_scraper(query):
    try:
        cmd = f'cd {SCRAPER_DIR} && source venv/bin/activate && python agent.py --no-llm "{query}"'
        result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=120)
        return result.stdout
    except subprocess.TimeoutExpired:
        return 'ERROR: Scraper timed out'
    except Exception as e:
        return f'ERROR: {e}'

def fetch_market_data():
    while True:
        try:
            log_activity('Fetching crypto data...', 'active')
            crypto_raw = run_scraper('crypto market overview')
            crypto_data = parse_crypto_output(crypto_raw)
            market_cache['crypto'] = crypto_data
            log_activity('Crypto data updated', 'ok')
            log_activity('Fetching stock data...', 'active')
            stock_raw = run_scraper('stock market summary')
            stock_data = parse_stock_output(stock_raw)
            market_cache['stocks'] = stock_data
            log_activity('Stock data updated', 'ok')
            market_cache['last_fetch'] = datetime.now().isoformat()
        except Exception as e:
            log_activity(f'Market fetch error: {e}', 'err')
        time.sleep(300)

def parse_crypto_output(raw):
    data = {'total_market_cap': '', 'btc_dominance': '', 'change_24h': '', 'fear_greed': '', 'top_coins': [], 'gainers': [], 'losers': []}
    try:
        cache_dir = os.path.join(SCRAPER_DIR, '.cache')
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                fpath = os.path.join(cache_dir, f)
                try:
                    with open(fpath) as fp:
                        d = json.load(fp)
                    if 'global' in d:
                        g = d['global']
                        cap = g.get('total_market_cap_usd', 0)
                        if cap > 0:
                            data['total_market_cap'] = f'${cap/1e12:.2f}T'
                        data['btc_dominance'] = f"{g.get('btc_dominance', 0)}%"
                        data['change_24h'] = f"{g.get('market_cap_change_24h', 0):+.2f}%"
                        data['fear_greed'] = d.get('fear_greed', '')
                        for coin in d.get('top_gainers', [])[:5]:
                            data['gainers'].append({'symbol': coin.get('symbol', ''), 'price': coin.get('price', 0), 'change': coin.get('change_24h', 0)})
                        for coin in d.get('top_losers', [])[:5]:
                            data['losers'].append({'symbol': coin.get('symbol', ''), 'price': coin.get('price', 0), 'change': coin.get('change_24h', 0)})
                    if 'coins' in d and not data['top_coins']:
                        for coin in d['coins'][:20]:
                            data['top_coins'].append({'rank': coin.get('rank', 0), 'symbol': coin.get('symbol', ''), 'name': coin.get('name', ''), 'price': coin.get('price', 0), 'change': coin.get('change_24h', 0), 'market_cap': coin.get('market_cap', 0)})
                except:
                    continue
    except:
        pass
    if not data['total_market_cap']:
        for line in raw.split('\n'):
            if 'Total Market Cap' in line:
                m = re.search(r'\$[\d.]+T', line)
                if m: data['total_market_cap'] = m.group()
            elif 'BTC Dominance' in line:
                m = re.search(r'[\d.]+%', line)
                if m: data['btc_dominance'] = m.group()
            elif '24h Change' in line:
                m = re.search(r'[+-][\d.]+%', line)
                if m: data['change_24h'] = m.group()
            elif 'Fear' in line and 'Greed' in line:
                data['fear_greed'] = line.split(':')[-1].strip() if ':' in line else line.strip()
    return data

def parse_stock_output(raw):
    data = {'indices': [], 'gainers': [], 'losers': []}
    try:
        cache_dir = os.path.join(SCRAPER_DIR, '.cache')
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                fpath = os.path.join(cache_dir, f)
                try:
                    with open(fpath) as fp:
                        d = json.load(fp)
                    if 'indices' in d:
                        for name, vals in d['indices'].items():
                            data['indices'].append({'name': name, 'price': vals.get('price', 0), 'change_pct': vals.get('change_pct', 0)})
                        for g in d.get('top_gainers', [])[:5]:
                            data['gainers'].append(g)
                        for l in d.get('top_losers', [])[:5]:
                            data['losers'].append(l)
                except:
                    continue
    except:
        pass
    return data

@app.route('/')
def dashboard():
    return send_from_directory(DASHBOARD_DIR, 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(DASHBOARD_DIR, filename)

@app.route('/webhook/openclaw', methods=['POST'])
def openclaw_webhook():
    data = request.json or {}
    event = data.get('event', '')
    message = data.get('message', '')
    if event in ('thinking', 'running', 'tool_call', 'processing'):
        bot_state['state'] = 'busy'
        bot_state['message'] = message or 'Processing...'
        bot_state['last_updated'] = datetime.now().isoformat()
        log_activity(bot_state['message'], 'active')
    elif event in ('done', 'idle', 'complete'):
        bot_state['state'] = 'idle'
        bot_state['message'] = 'Idle — waiting for instructions'
        bot_state['last_updated'] = datetime.now().isoformat()
        bot_state['sessions_today'] = bot_state.get('sessions_today', 0) + 1
        log_activity(message or 'Task complete', 'ok')
    elif event == 'model_switch':
        bot_state['model'] = message
        log_activity('Model switched to ' + message, 'warn')
    elif event == 'error':
        log_activity('Error: ' + message, 'err')
    return jsonify({'ok': True})

@app.route('/status/busy', methods=['POST'])
def set_busy():
    data = request.json or {}
    bot_state['state'] = 'busy'
    bot_state['message'] = data.get('message', 'Processing...')
    bot_state['last_updated'] = datetime.now().isoformat()
    log_activity(bot_state['message'], 'active')
    return jsonify({'ok': True})

@app.route('/status/idle', methods=['POST'])
def set_idle():
    data = request.json or {}
    msg = data.get('message', 'Task complete')
    bot_state['state'] = 'idle'
    bot_state['message'] = 'Idle — waiting for instructions'
    bot_state['last_updated'] = datetime.now().isoformat()
    log_activity(msg, 'ok')
    return jsonify({'ok': True})

@app.route('/api/status')
def status():
    return jsonify(bot_state)

@app.route('/api/activity')
def activity():
    return jsonify({'log': list(activity_log)})

@app.route('/api/system')
def system():
    return jsonify(get_system_stats())

@app.route('/api/crypto')
def crypto():
    return jsonify(market_cache.get('crypto') or {})

@app.route('/api/stocks')
def stocks():
    return jsonify(market_cache.get('stocks') or {})

@app.route('/api/market_age')
def market_age():
    return jsonify({'last_fetch': market_cache.get('last_fetch')})

@app.route('/api/stats')
def stats():
    week_start = get_week_start()
    gym_lines = read_file_lines('~/openclaw-data/gym-log.txt')
    gym_this_week = sum(1 for l in gym_lines if week_start[:7] in l and 'completed' in l.lower())
    pipeline_lines = read_file_lines('~/art-channel/pipeline.log')
    pipeline_this_week = sum(1 for l in pipeline_lines if week_start[:7] in l)
    paintings_dir = os.path.expanduser('~/art-channel/paintings_output')
    try:
        images_total = len([f for f in os.listdir(paintings_dir) if f.endswith(('.png', '.jpg'))])
    except:
        images_total = 0
    api_spend = 0.0
    try:
        with open(os.path.expanduser('~/art-channel/generation_log.json')) as f:
            gen_log = json.load(f)
            successful = sum(1 for g in gen_log if g.get('status') == 'success')
            api_spend = round(successful * 0.08, 2)
    except:
        pass
    current_model = bot_state['model']
    try:
        with open(os.path.expanduser('~/.openclaw/openclaw.json')) as f:
            config = json.load(f)
            current_model = config.get('agents', {}).get('defaults', {}).get('model', {}).get('primary', current_model)
            bot_state['model'] = current_model
    except:
        pass
    return jsonify({
        'pipeline_runs_week': pipeline_this_week,
        'images_total': images_total,
        'gym_sessions_week': gym_this_week,
        'api_spend_total': api_spend,
        'current_model': current_model,
    })

@app.route('/api/scrape', methods=['POST'])
def trigger_scrape():
    data = request.json or {}
    query = data.get('query', '')
    if not query:
        return jsonify({'error': 'No query'}), 400
    bot_state['state'] = 'busy'
    bot_state['message'] = f'Scraping: {query}'
    log_activity(f'Manual scrape: {query}', 'active')
    def _run():
        run_scraper(query)
        bot_state['state'] = 'idle'
        bot_state['message'] = 'Idle — waiting for instructions'
        log_activity(f'Scrape complete: {query}', 'ok')
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True})

if __name__ == '__main__':
    log_activity('Dashboard v2 server started', 'ok')
    log_activity('System stats monitor active', 'ok')
    market_thread = threading.Thread(target=fetch_market_data, daemon=True)
    market_thread.start()
    log_activity('Market data fetcher started (5min cycle)', 'ok')
    print('Dashboard v2 running at http://0.0.0.0:8080')
    app.run(host='0.0.0.0', port=8080, debug=False)
