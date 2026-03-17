#!/usr/bin/env python3
"""
SCRAPER AGENT — AI Brain
Talk to this. It understands what you want, runs scrapers, reports back.

USAGE:
    python agent.py                          (interactive chat)
    python agent.py "find trending crypto"   (one-shot)
    python agent.py --no-llm "crypto movers" (skip LLM)

BACKENDS:
    OpenClaw (uses your existing setup — Haiku)
    Ollama (free, local)
    Anthropic / OpenAI (API keys)
    No LLM (keyword matching)
"""

import json
import sys
import re
import os
import subprocess
from datetime import datetime

import config
from scraper_engine import execute_scrape_command, save_output

HAS_OLLAMA = False
HAS_ANTHROPIC = False
HAS_OPENAI = False
HAS_OPENCLAW = False

try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    pass

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    pass

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    pass

# Check if OpenClaw is available
try:
    result = subprocess.run(["which", "openclaw"], capture_output=True, text=True)
    HAS_OPENCLAW = result.returncode == 0
except Exception:
    pass


SYSTEM_PROMPT = """You are a research assistant that converts user requests into structured scraping commands.

You have access to these modules:
1. **youtube** - Channel analytics, video performance, revenue estimates
   Actions: scrape_channel, scrape_channels
   Params: channel (str), channels (list of str)

2. **etsy** - Product research, trending products, pricing analysis
   Actions: search
   Params: query (str), pages (int 1-5), product_type ("all"/"digital"/"physical"), min_price (float), max_price (float), sort ("relevance"/"price_asc"/"price_desc"/"most_recent"/"top_reviews")

3. **crypto** - Cryptocurrency prices, market overview, big movers
   Actions: overview, prices, movers
   Params: coins (list of symbols), top_n (int), threshold (float)

4. **finance** - Stock quotes, market summary, watchlists
   Actions: quote, watchlist, market_summary
   Params: symbol (str), symbols (list of str)

5. **trends** - Trending topics from Google, Reddit, HN, Product Hunt
   Actions: get_all
   Params: source ("all"/"google"/"reddit"/"hackernews"/"producthunt")

RESPOND WITH ONLY a JSON array of commands. Each command: module, action, params.

Examples:
User: "How is MKBHD doing on YouTube?"
[{"module":"youtube","action":"scrape_channels","params":{"channels":["@mkbhd"]}}]

User: "Best digital planners on Etsy under $20"
[{"module":"etsy","action":"search","params":{"query":"digital planner","product_type":"digital","max_price":20,"sort":"top_reviews","pages":3}}]

User: "Full market overview crypto and stocks"
[{"module":"crypto","action":"overview","params":{}},{"module":"finance","action":"market_summary","params":{}}]

User: "BTC and SOL price, anything pumping?"
[{"module":"crypto","action":"prices","params":{"coins":["BTC","SOL"]}},{"module":"crypto","action":"movers","params":{"threshold":10}}]

Return ONLY the JSON array. No explanation. No markdown. No backticks."""


SUMMARY_PROMPT = """You are a sharp research analyst. The user asked: "{question}"

Here are the raw scraping results:

{data}

Provide a clear, insightful summary. Include:
- Key numbers and metrics (interpret them, don't just list)
- Notable patterns or surprises
- Actionable takeaways
- For financial data, note significant moves
- For product research, highlight best opportunities

Keep it conversational but data-driven. Use specific numbers."""


# ── LLM Backends ─────────────────────────────────────────────

def llm_call(prompt, system="", temperature=0.1):
    backend = config.LLM_BACKEND.lower()
    if backend == "openclaw" and HAS_OPENCLAW:
        return _openclaw_call(prompt, system)
    elif backend == "ollama" and HAS_OLLAMA:
        return _ollama_call(prompt, system, temperature)
    elif backend == "anthropic" and HAS_ANTHROPIC:
        return _anthropic_call(prompt, system, temperature)
    elif backend == "openai" and HAS_OPENAI:
        return _openai_call(prompt, system, temperature)
    else:
        return _keyword_fallback(prompt)


def _openclaw_call(prompt, system):
    """Use OpenClaw CLI to call Haiku via your existing setup. Free (you already pay for it)."""
    try:
        # Combine system prompt and user prompt into one message
        if system:
            full_message = f"INSTRUCTIONS: {system}\n\nUSER REQUEST: {prompt}"
        else:
            full_message = prompt

        result = subprocess.run(
            [
                "openclaw", "agent",
                "--session-id", "scraper-agent",
                "--message", full_message,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"  [OpenClaw error: {result.stderr.strip()}] Falling back to keyword matching")
            return _keyword_fallback(prompt)

        data = json.loads(result.stdout)
        payloads = data.get("result", {}).get("payloads", [])
        if payloads:
            return payloads[0].get("text", "")

        return _keyword_fallback(prompt)

    except subprocess.TimeoutExpired:
        print("  [OpenClaw timeout] Falling back to keyword matching")
        return _keyword_fallback(prompt)
    except Exception as e:
        print(f"  [OpenClaw error: {e}] Falling back to keyword matching")
        return _keyword_fallback(prompt)


def _ollama_call(prompt, system, temperature):
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = ollama.chat(
            model=config.OLLAMA_MODEL,
            messages=messages,
            options={"temperature": temperature},
        )
        return response["message"]["content"]
    except Exception as e:
        print(f"  [Ollama error: {e}] Falling back to keyword matching")
        return _keyword_fallback(prompt)


def _anthropic_call(prompt, system, temperature):
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL, max_tokens=1024,
            system=system, messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.content[0].text
    except Exception as e:
        print(f"  [Anthropic error: {e}] Falling back to keyword matching")
        return _keyword_fallback(prompt)


def _openai_call(prompt, system, temperature):
    try:
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  [OpenAI error: {e}] Falling back to keyword matching")
        return _keyword_fallback(prompt)


def _keyword_fallback(prompt):
    prompt_lower = prompt.lower()
    commands = []

    # YouTube
    yt_signals = ["youtube", "youtuber", "channel", "subscriber", "views per",
                  "how much.*mak", "upload", "video performance"]
    if any(s in prompt_lower for s in yt_signals) or re.search(r'@\w+', prompt):
        handles = re.findall(r'@[\w]+', prompt)
        if handles:
            commands.append({"module": "youtube", "action": "scrape_channels",
                           "params": {"channels": handles}})
        else:
            quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', prompt)
            names = [q[0] or q[1] for q in quoted]
            if names:
                commands.append({"module": "youtube", "action": "scrape_channels",
                               "params": {"channels": [f"@{n.replace(' ', '')}" for n in names]}})

    # Etsy
    etsy_signals = ["etsy", "product research", "selling well", "best selling",
                    "digital product", "physical product", "handmade", "print on demand",
                    "trending product", "what to sell"]
    if any(s in prompt_lower for s in etsy_signals):
        p_type = "all"
        if "digital" in prompt_lower: p_type = "digital"
        elif "physical" in prompt_lower: p_type = "physical"

        query = "trending bestseller"
        q_match = re.search(r'(?:for|about|like|selling|find|search)\s+["\']?(.+?)["\']?\s*(?:on|$)', prompt_lower)
        if q_match:
            query = q_match.group(1).strip()

        commands.append({"module": "etsy", "action": "search",
                        "params": {"query": query, "product_type": p_type, "pages": 3, "sort": "top_reviews"}})

    # Crypto
    crypto_signals = ["crypto", "bitcoin", "btc", "eth", "ethereum", "solana", "sol",
                      "altcoin", "defi", "token", "coin", "market cap"]
    crypto_symbols = re.findall(
        r'\b(BTC|ETH|SOL|BNB|XRP|ADA|DOGE|DOT|AVAX|MATIC|LINK|UNI|SHIB|LTC|ATOM|ARB|OP|SUI|APT|NEAR|PEPE|WIF)\b',
        prompt.upper())

    if any(s in prompt_lower for s in crypto_signals) or crypto_symbols:
        if crypto_symbols:
            commands.append({"module": "crypto", "action": "prices",
                           "params": {"coins": list(set(crypto_symbols))}})
        if any(w in prompt_lower for w in ["overview", "market", "summary", "overall"]):
            commands.append({"module": "crypto", "action": "overview", "params": {}})
        if any(w in prompt_lower for w in ["mover", "big move", "pump", "dump", "spike", "crash", "alert"]):
            commands.append({"module": "crypto", "action": "movers", "params": {"threshold": 10}})
        if not commands or not any(c["module"] == "crypto" for c in commands):
            commands.append({"module": "crypto", "action": "overview", "params": {}})

    # Finance / stocks
    stock_tickers = re.findall(r'\b([A-Z]{1,5})\b', prompt)
    known_tickers = {"AAPL", "NVDA", "TSLA", "GOOGL", "GOOG", "MSFT", "AMZN", "META",
                     "AMD", "INTC", "NFLX", "DIS", "BA", "JPM", "GS", "V", "MA",
                     "WMT", "TGT", "COST", "NKE", "SBUX", "MCD", "PFE", "JNJ",
                     "SPY", "QQQ", "IWM", "VTI", "VOO", "ARKK"}
    matched_tickers = [t for t in stock_tickers if t in known_tickers]

    finance_signals = ["stock", "share price", "market summary", "s&p", "nasdaq",
                       "dow jones", "earnings", "p/e", "dividend", "bull", "bear"]

    if matched_tickers:
        commands.append({"module": "finance", "action": "watchlist",
                        "params": {"symbols": matched_tickers}})
    if any(s in prompt_lower for s in finance_signals):
        if any(w in prompt_lower for w in ["summary", "overview", "market", "indices", "today"]):
            commands.append({"module": "finance", "action": "market_summary", "params": {}})

    # Trends
    trend_signals = ["trending", "what's hot", "what's popular", "buzz", "viral",
                     "front page", "hacker news", "product hunt", "google trends"]
    if any(s in prompt_lower for s in trend_signals):
        source = "all"
        if "reddit" in prompt_lower: source = "reddit"
        elif "google" in prompt_lower: source = "google"
        elif "hacker" in prompt_lower or "hn" in prompt_lower: source = "hackernews"
        elif "product hunt" in prompt_lower: source = "producthunt"
        commands.append({"module": "trends", "action": "get_all", "params": {"source": source}})

    if not commands:
        commands.append({"module": "trends", "action": "get_all", "params": {"source": "all"}})

    return json.dumps(commands)


# ── Agent Core ───────────────────────────────────────────────

class ScraperAgent:
    def __init__(self, use_llm=True, save_results=True):
        self.use_llm = use_llm
        self.save_results = save_results
        self.history = []

    def process(self, user_input):
        print(f"\n{'='*60}")
        print(f"  QUERY: {user_input}")
        print(f"{'='*60}")

        print("\n[1/3] Understanding your request...")
        commands = self._parse_intent(user_input)
        if not commands:
            return "Couldn't figure out what to scrape. Try mentioning YouTube channels, Etsy products, crypto coins, or stock tickers."

        print(f"  -> Planned {len(commands)} scraping task(s):")
        for i, cmd in enumerate(commands):
            print(f"    {i+1}. {cmd['module']}.{cmd['action']}({json.dumps(cmd.get('params', {}), default=str)[:80]})")

        print(f"\n[2/3] Scraping data...")
        all_results = {}
        for i, cmd in enumerate(commands):
            label = f"{cmd['module']}_{cmd['action']}"
            print(f"  -> Running: {label}")
            result = execute_scrape_command(cmd)
            all_results[f"{label}_{i}"] = result

            if self.save_results:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_output(result, f"{label}_{ts}")

        print(f"\n[3/3] Analyzing results...")
        if self.use_llm and config.LLM_BACKEND not in ("none", ""):
            summary = self._summarize(user_input, all_results)
        else:
            summary = self._format_raw(all_results)

        self.history.append({
            "query": user_input, "commands": commands,
            "timestamp": datetime.now().isoformat(),
        })

        return summary

    def _parse_intent(self, user_input):
        if self.use_llm and config.LLM_BACKEND not in ("none", ""):
            raw = llm_call(user_input, system=SYSTEM_PROMPT, temperature=0.0)
        else:
            raw = _keyword_fallback(user_input)

        try:
            clean = re.sub(r'```json\s*|\s*```', '', raw).strip()
            match = re.search(r'\[.*\]', clean, re.DOTALL)
            if match:
                commands = json.loads(match.group(0))
                return commands if isinstance(commands, list) else [commands]
        except (json.JSONDecodeError, AttributeError):
            pass

        raw = _keyword_fallback(user_input)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    def _summarize(self, question, results):
        data_str = json.dumps(results, indent=2, default=str)
        if len(data_str) > 8000:
            data_str = data_str[:8000] + "\n... [truncated]"
        prompt = SUMMARY_PROMPT.format(question=question, data=data_str)
        return llm_call(prompt, system="You are a research analyst. Summarize the provided data in clear, natural language. Do NOT output JSON or commands.", temperature=0.3)

    def _format_raw(self, results):
        output = []
        for key, data in results.items():
            output.append(f"\n{'~'*40}")
            output.append(f"  {key.upper()}")
            output.append(f"{'~'*40}")

            if isinstance(data, dict):
                if "error" in data:
                    output.append(f"  ERROR: {data['error']}")
                    continue

                if "coins" in data:
                    for coin in data["coins"][:10]:
                        change = coin.get("change_24h", 0)
                        arrow = "^" if change > 0 else "v" if change < 0 else "-"
                        output.append(
                            f"  {arrow} {coin.get('symbol','?'):>6} "
                            f"${coin.get('price',0):>12,.2f}  "
                            f"{change:>+6.1f}%  "
                            f"MCap: ${coin.get('market_cap',0)/1e9:.1f}B"
                        )

                elif "products" in data:
                    analysis = data.get("analysis", {})
                    price = analysis.get("price", {})
                    output.append(f"  Found: {data.get('total_results', 0)} products")
                    output.append(f"  Avg price: ${price.get('avg', 0):.2f}")
                    output.append(f"  Sweet spot: {price.get('sweet_spot', 'N/A')}")
                    output.append(f"  Bestsellers: {analysis.get('market_signals', {}).get('pct_bestsellers', 0)}%")
                    for p in data["products"][:5]:
                        output.append(f"    * ${p.get('price',0):.2f} | *{p.get('rating',0)} | {p.get('title','')[:60]}")

                elif "channels" in data:
                    for ch in data["channels"]:
                        est = ch.get("estimates", {})
                        output.append(f"  {ch.get('name', ch.get('channel', '?'))}")
                        output.append(f"    Subscribers: {ch.get('subscribers',0):,}")
                        output.append(f"    Monthly views: ~{est.get('monthly_views',0):,}")
                        output.append(f"    Est. revenue: ${est.get('revenue_low',0):,.0f} - ${est.get('revenue_high',0):,.0f}/mo")
                        output.append(f"    Upload freq: {est.get('upload_freq', '?')}")

                elif "indices" in data:
                    for name, vals in data.get("indices", {}).items():
                        change = vals.get("change_pct", 0)
                        arrow = "^" if change > 0 else "v"
                        output.append(f"  {arrow} {name:>15}: {vals.get('price',0):>12,.2f}  ({change:+.2f}%)")

                elif "global" in data:
                    g = data["global"]
                    output.append(f"  Total Market Cap: ${g.get('total_market_cap_usd',0)/1e12:.2f}T")
                    output.append(f"  BTC Dominance: {g.get('btc_dominance',0)}%")
                    output.append(f"  24h Change: {g.get('market_cap_change_24h',0):+.2f}%")
                    output.append(f"  Fear & Greed: {data.get('fear_greed', '?')}")

                else:
                    output.append(json.dumps(data, indent=2, default=str)[:2000])

        return "\n".join(output)


# ── CLI ──────────────────────────────────────────────────────

def print_banner():
    print("""
    ======================================================
    |            SCRAPER AGENT  v1.1                      |
    |                                                      |
    |  Talk to me naturally. I'll scrape the web for you.  |
    |                                                      |
    |  Examples:                                           |
    |  * "How much is @mkbhd making on YouTube?"           |
    |  * "Best selling digital products on Etsy under $30" |
    |  * "What's Bitcoin and Ethereum at?"                 |
    |  * "Show me NVDA and TSLA stock prices"              |
    |  * "What's trending in tech right now?"              |
    |                                                      |
    |  Commands:  quit/exit, help, status, clear cache     |
    ======================================================
    """)

    backend = config.LLM_BACKEND
    if backend == "openclaw":
        status = "[OK] OpenClaw (Haiku via your setup)" if HAS_OPENCLAW else "[X] openclaw not found in PATH"
    elif backend == "ollama":
        status = "[OK] Ollama (free, local)" if HAS_OLLAMA else "[X] Ollama not installed"
    elif backend == "anthropic":
        status = "[OK] Anthropic Claude" if HAS_ANTHROPIC else "[X] anthropic not installed"
    elif backend == "openai":
        status = "[OK] OpenAI" if HAS_OPENAI else "[X] openai not installed"
    else:
        status = "[>>] Keyword matching (no LLM)"

    print(f"  LLM Backend: {status}")
    print(f"  Output dir:  {config.OUTPUT_DIR}")
    print()


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        if query.startswith("--no-llm "):
            agent = ScraperAgent(use_llm=False)
            query = query[9:]
        else:
            agent = ScraperAgent(use_llm=True)
        result = agent.process(query)
        print(result)
        return

    print_banner()
    agent = ScraperAgent(use_llm=True)

    while True:
        try:
            user_input = input("\n  You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("  Goodbye!")
            break
        if user_input.lower() == "help":
            print_banner()
            continue
        if user_input.lower() == "status":
            print(f"  Backend: {config.LLM_BACKEND}")
            print(f"  Queries this session: {len(agent.history)}")
            print(f"  Output: {config.OUTPUT_DIR}")
            continue
        if user_input.lower() == "clear cache":
            import shutil
            if os.path.exists(config.CACHE_DIR):
                shutil.rmtree(config.CACHE_DIR)
                print("  Cache cleared.")
            continue

        result = agent.process(user_input)
        print(f"\n{result}")


if __name__ == "__main__":
    main()
