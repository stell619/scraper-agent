# 🕷️ Scraper Agent

> **An AI-powered market intelligence agent that scrapes the web on command.**
> Talk to it naturally. It understands what you want, runs the right scrapers, and gives you a sharp financial terminal-style summary.

---

## ✨ What It Does

Ask it anything research-related in plain English:

```
"Compare BTC, ETH and SOL right now"
"What's the hottest crypto right now?"
"What do traders think about NVDA?"
"How much is @mkbhd making on YouTube?"
"Best selling digital planners on Etsy under $20"
"What's trending in tech right now?"
```

The agent parses your intent, runs the appropriate scrapers in parallel, and returns a clean DATA + ANALYSIS brief — powered by your choice of LLM backend.

---

## 🧠 Architecture

```
User Input (natural language)
        ↓
  Intent Parser (Ollama — local, free)
        ↓
  Confidence Check
  ├── High confidence → proceed
  └── Low confidence
        ├── Clarification menu (up to 2 rounds) → re-parse enriched query
        └── After 2 rounds → "Use Claude instead? [y/N]"
                              ├── Yes → Claude API (Haiku)
                              └── No  → proceed with Ollama's best attempt
        ↓
  Scrape Commands [{"module": "crypto", "action": "prices", "params": {...}}]
        ↓
  Scraper Engine (parallel execution)
        ↓
  Financial Terminal Output (DATA block + ANALYSIS)
        ↓
  Result + saved JSON
```

**How confidence is evaluated:**
- Empty result — Ollama returned no commands
- Keyword mismatch — query mentions crypto terms but Ollama routed to the wrong module
- Missing action — parsed command has no action field
- Trending without domain — "what's trending" with no crypto/stocks/internet context
- Too short/vague — query has no recognisable keywords

**What happens on low confidence:**
Before offering Claude as a fallback, the agent shows a numbered clarification menu (up to 2 rounds) so you can steer the re-parse without spending API credits. Claude is only offered after two failed rounds.

**LLM routing note:** The intent parser uses an explicit system prompt to force JSON output from local models. The summariser uses a separate system message to prevent models like Mistral from generating commands instead of natural language — a common failure mode when no system prompt is provided.

---

## 📦 Scraping Modules

| Module | What it scrapes | Actions |
|--------|----------------|---------|
| **YouTube** | Channel analytics, subscriber counts, video performance, revenue estimates | `scrape_channel`, `scrape_channels` |
| **Etsy** | Product listings, pricing analysis, bestseller signals, market research | `search` |
| **Crypto** | Live prices, market overview, big movers, Fear & Greed index, trending coins | `overview`, `prices`, `movers`, `trending` |
| **Finance** | Stock quotes, market indices, top gainers/losers | `quote`, `watchlist`, `market_summary` |
| **Trends** | Google Trends, Reddit (r/wallstreetbets, r/CryptoCurrency, r/investing), Hacker News, Product Hunt | `get_all` |
| **Stocktwits** | Real-time trader sentiment, bullish/bearish signals, trending symbols | `trending`, `sentiment` |

---

## 🤖 LLM Backends

Works with any of these — or none at all:

| Backend | Cost | Role |
|---------|------|------|
| **Ollama** (default) | Free — runs locally | Primary intent parser + summariser |
| **Claude API** (Haiku) | ~$0.001/query | Escalation fallback when Ollama is uncertain |
| **OpenClaw** | Free | Uses your existing OpenClaw setup |
| **OpenAI GPT** | API pricing | Alternative to Claude for escalation |
| **None / Keyword** | Free | Pattern matching — no LLM at all |

The default strategy is **Ollama-first** — every query runs through your local model for free. Claude API is only called when the confidence check detects a likely misparse and you confirm the escalation. This keeps costs near zero for typical usage.

> ⚠️ The `ollama` Python package must be installed — it is included in `requirements.txt`. Without it the agent silently falls back to keyword matching for every query.

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/stell619/scraper-agent.git
cd scraper-agent

python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

# If using Ollama backend (default), also install:
ollama pull mistral  # or llama3, qwen2.5-coder etc
```

### 2. Configure

```bash
cp .env.example .env
nano .env  # Set your LLM backend and any API keys
```

### 3. Run

```bash
# Interactive chat mode
python3 agent.py

# One-shot query
python3 agent.py "What's the hottest crypto right now?"

# Skip LLM (keyword matching only)
python3 agent.py --no-llm "BTC ETH SOL prices"

# Skip escalation prompts (non-interactive/piped use)
python3 agent.py --no-escalate "some ambiguous query"

# Pipe query via stdin
echo "bitcoin price" | python3 agent.py --no-escalate -
```

---

## 💬 Example Queries

### Crypto
```
"Compare BTC, ETH and SOL right now"
"What's the hottest crypto right now?"
"Give me a full crypto market overview"
"Show me anything that pumped more than 10% today"
```

### Sentiment & Trader Pulse
```
"What do traders think about NVDA?"
"Is ETH looking bullish right now?"
"What's the sentiment on BTC?"
"What are people saying about SOL on Reddit?"
```

### Stocks
```
"NVDA and TSLA prices"
"Full stock market summary"
"How's the S&P and NASDAQ doing?"
```

### YouTube Research
```
"How much is @mkbhd making?"
"Analyse @linustechtips and @mkbhd"
"What's @veritasium's channel like?"
```

### Etsy Product Research
```
"Best digital products on Etsy under $15"
"What physical products are trending on Etsy?"
"Find top selling printables, sort by reviews"
```

### Trends
```
"What's trending in tech right now?"
"What's hot on Hacker News?"
"Show me Reddit finance posts"
"What launched on Product Hunt today?"
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and configure:

```env
# LLM Backend: ollama | openclaw | anthropic | openai | none
LLM_BACKEND=ollama
OLLAMA_MODEL=mistral

# Optional — escalation fallback when Ollama is uncertain
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Optional — Stocktwits trader sentiment
# Register a free app at stocktwits.com/developers
STOCKTWITS_ACCESS_TOKEN=

# Output
OUTPUT_DIR=./output
OUTPUT_FORMAT=json  # json or csv
CACHE_DIR=./.cache
```

---

## 🖥️ Dashboard

A live terminal-style command centre showing live market data, system stats, agent status, and activity log.

```bash
python dashboard-serve.py
```

Open `http://localhost:8080`

**What's on the dashboard:**
- **System bar** — CPU usage, RAM, Disk, CPU temp, Uptime, Network I/O (reads `/proc` directly, no tools needed)
- **Hero stats** — Bitcoin price, Total Market Cap, Fear & Greed gauge (SVG semicircle with colour zones), BTC Dominance
- **Top Cryptocurrencies** — up to 20 coins with rank, price, and 24h change
- **Stock Market** — major indices (S&P 500, NASDAQ, DOW, etc.) and top gainers
- **Crypto Movers** — top gainers and losers over 24h
- **Agent Status** — live state, sessions today, LLM backend, data age, activity log
- **Run a Scrape** — send any natural-language query directly from the browser

Market data refreshes automatically every 5 minutes in the background. The Fear & Greed index follows the official Alternative.me colour zones: red (Extreme Fear 0–24), amber (Fear 25–49), green (Greed 50–74), cyan (Extreme Greed 75–100).

Configure in `.env`:
```env
DASHBOARD_DIR=.        # points to the project root
DASHBOARD_PORT=8080
```

---

## 📁 Project Structure

```
scraper-agent/
├── agent.py              # AI brain — intent parsing, confidence check, orchestration
├── scraper_engine.py     # Data modules (YouTube, Etsy, Crypto, Finance, Trends, Stocktwits)
├── config.py             # Configuration loader
├── dashboard-serve.py    # Flask dashboard server
├── dashboard-index.html  # Dashboard frontend
├── requirements.txt      # Python dependencies
├── .env.example          # Environment template
└── output/               # Scraped data (gitignored)
```

---

## 🔧 Extending

### Add a new scraper module

1. Add a class to `scraper_engine.py`:

```python
class MyScraper:
    def scrape_something(self, query):
        # fetch, parse, return dict
        return {"results": [...]}
```

2. Add to the dispatcher in `execute_scrape_command()`:

```python
elif module == "mymodule":
    return MyScraper().scrape_something(params.get("query"))
```

3. Add to the `SYSTEM_PROMPT` in `agent.py` so the LLM knows it exists.

### Add a new LLM backend

Add a `_mybackend_call()` function in `agent.py` following the existing pattern, then add it to `llm_call()`.

---

## 🔄 Recent Changes

**v1.3 — Dashboard Rebuild & Polish**
- **Full dashboard rebuild** — dark terminal aesthetic with CRT scanlines, directional card border lighting, and ambient gradient atmosphere
- **Fear & Greed SVG gauge** — animated semicircle arc with a floating indicator dot; colour zones match Alternative.me official ranges
- **Hero stat cards** — Bitcoin price, Total Market Cap, Fear & Greed index, BTC Dominance; all centred and auto-updated
- **Top Cryptocurrencies table** — up to 20 coins with rank, symbol, name, price, 24h change; populated automatically on startup
- **Stock Market panel** — indices and top gainers in a properly grid-aligned three-column layout
- **Crypto Movers** — dedicated top gainers and top losers panels
- **System stats bar** — CPU, RAM, disk, temperature, uptime, network; reads `/proc` and `/sys` with no shell tools
- **Agent Status + Activity Log** — live state indicator, sessions today, LLM backend label, data age, scrollable terminal log
- **Run a Scrape panel** — submit any natural-language query from the browser and watch it execute in real time
- **Dashboard bug fix** — resolved "Dashboard not found" caused by wrong `DASHBOARD_DIR` path in `.env`; now correctly set to project root (`.`)
- **Market data loop** — background fetcher now runs both `crypto market overview` and `top 20 crypto prices` each cycle so the full coin table is always populated
- **`/api/stats` endpoint** — new endpoint exposing sessions today, tokens today, and current LLM model
- **Progress bar polish** — system stat bars animate their fill width on update; removed distracting wave-sweep shimmer animation

**v1.2 — Market Intelligence & Sentiment**
- **Stocktwits integration** — real-time trader sentiment (bullish/bearish %) for any stock or crypto ticker
- **CoinGecko trending** — most searched coins in the last 24hrs (`crypto.trending`)
- **Reddit finance** — r/wallstreetbets, r/CryptoCurrency, r/investing pulled into the trends module
- **7-day price data** — `crypto.prices` now includes 7d % change alongside 24h
- **Financial terminal output** — summaries now return a structured DATA block (price table, sentiment card) followed by a concise ANALYSIS paragraph
- **Multi-asset routing** — "compare BTC ETH SOL" correctly sends all coins in a single API call
- **YouTube URL fix** — `@handle` URLs now use the correct modern YouTube format; accepts `handle`, `channel`, `channels`, or `handles` params interchangeably
- **SYSTEM_PROMPT routing rules** — explicit rules at the top prevent crypto tickers routing to finance module

**v1.1 — Escalation & Reliability**
- **Clarification loop** — before offering Claude, the agent shows a numbered menu to steer Ollama's re-parse (up to 2 rounds)
- **Ollama→Claude escalation** — confidence check detects low-quality parses and offers Claude API as a final fallback
- **--no-escalate flag** — skip all prompts for non-interactive/piped use
- **argparse CLI** — cleaner argument handling, supports stdin via `-`
- **Thread safety** — `bot_state` and `market_cache` protected with `threading.Lock()`
- **JSON error handling** — all `.json()` calls wrapped in try/except
- **Ollama routing fixed** — was silently falling back to keyword matching when `ollama` package not installed
- **Mistral summariser** — explicit system prompt prevents command hallucination
- **Reddit session isolation** — no longer overwrites shared User-Agent
- **Cache corruption** — corrupted files detected, logged and discarded

---

## ⚠️ Legal & Ethics

- This tool scrapes publicly available data
- Respects rate limits with configurable delays (default 1.5–3.5s between requests)
- Uses rotating user agents
- Built-in caching reduces repeat requests
- Do not use to scrape at scale or violate sites' Terms of Service
- YouTube revenue estimates are approximations based on public CPM data — not financial advice

---

## 📋 Requirements

- Python 3.10+
- Internet connection
- Ollama (optional, for free local LLM) — [ollama.ai](https://ollama.ai)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for research, market analysis, and content strategy. | Python 3.10+ | MIT License | v1.3*
