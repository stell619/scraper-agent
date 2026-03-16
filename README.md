# 🕷️ Scraper Agent

> **An AI-powered research agent that scrapes the web on command.**  
> Talk to it naturally. It understands what you want, runs the right scrapers, and gives you an intelligent summary.

---

## ✨ What It Does

Ask it anything research-related in plain English:

```
"How much is @mkbhd making on YouTube?"
"Best selling digital planners on Etsy under $20"
"What's Bitcoin and Ethereum doing?"
"Show me NVDA and TSLA stock prices"
"What's trending in tech right now?"
```

The agent parses your intent, runs the appropriate scrapers in parallel, and returns a clean summary — powered by your choice of LLM backend.

---

## 🧠 Architecture

```
User Input (natural language)
        ↓
  Intent Parser (LLM or keyword fallback)
        ↓
  Scrape Commands [{"module": "crypto", "action": "overview"}]
        ↓
  Scraper Engine (parallel execution)
        ↓
  LLM Summary (or formatted raw output)
        ↓
  Result + saved JSON/CSV
```

---

## 📦 Scraping Modules

| Module | What it scrapes | Actions |
|--------|----------------|---------|
| **YouTube** | Channel analytics, subscriber counts, video performance, revenue estimates | `scrape_channel`, `scrape_channels` |
| **Etsy** | Product listings, pricing analysis, bestseller signals, market research | `search` |
| **Crypto** | Live prices, market overview, big movers, Fear & Greed index | `overview`, `prices`, `movers` |
| **Finance** | Stock quotes, market indices, top gainers/losers | `quote`, `watchlist`, `market_summary` |
| **Trends** | Google Trends, Reddit hot posts, Hacker News, Product Hunt | `get_all` |

---

## 🤖 LLM Backends

Works with any of these — or none at all:

| Backend | Cost | Setup |
|---------|------|-------|
| **Ollama** (default) | Free — runs locally | Install Ollama, pull a model |
| **OpenClaw** | Free — uses your existing setup | OpenClaw in PATH |
| **Anthropic Claude** | API pricing | Set `ANTHROPIC_API_KEY` |
| **OpenAI GPT** | API pricing | Set `OPENAI_API_KEY` |
| **None / Keyword** | Free | Set `LLM_BACKEND=none` |

The keyword fallback understands common patterns (crypto tickers, @handles, stock symbols) without any LLM.

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/stell619/scraper-agent.git
cd scraper-agent

python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
nano .env  # Set your LLM backend and any API keys
```

### 3. Run

```bash
# Interactive chat mode
python agent.py

# One-shot query
python agent.py "What's trending in crypto today?"

# Skip LLM (keyword matching only)
python agent.py --no-llm "BTC ETH SOL prices"
```

---

## 💬 Example Queries

### YouTube Research
```
"How much is @mkbhd making?"
"Analyse @linustechtips and @mrwhosetheboss"
"What's @veritasium's channel like?"
```

### Etsy Product Research
```
"Best digital products on Etsy under $15"
"What physical products are trending on Etsy?"
"Find top selling printables, sort by reviews"
```

### Crypto
```
"Give me a full crypto market overview"
"What's BTC, ETH and SOL at?"
"Show me anything that pumped more than 10% today"
```

### Stocks
```
"NVDA and TSLA prices"
"Full stock market summary"
"How's the S&P and NASDAQ doing?"
```

### Trends
```
"What's trending right now?"
"What's hot on Hacker News?"
"Show me Reddit trending posts"
"What launched on Product Hunt today?"
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and configure:

```env
# LLM Backend: ollama | openclaw | anthropic | openai | none
LLM_BACKEND=ollama
OLLAMA_MODEL=llama3

# Optional API keys (scraping works without these)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Output
OUTPUT_DIR=./output
OUTPUT_FORMAT=json  # json or csv
CACHE_DIR=./.cache
```

---

## 🖥️ Dashboard

A live web dashboard showing bot status, market data, system stats, and activity log.

```bash
pip install flask
python dashboard-serve.py
```

Open `http://localhost:8080`

Configure dashboard paths in `.env`:
```env
DASHBOARD_DIR=./dashboard
```

---

## 📁 Project Structure

```
scraper-agent/
├── agent.py              # AI brain — intent parsing + orchestration
├── scraper_engine.py     # Data collection modules (YouTube, Etsy, Crypto, Finance, Trends)
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

*Built for research, market analysis, and content strategy.*
