#!/usr/bin/env python3
"""
Market Intelligence Agent

An AI-powered finance and crypto research agent.
Ask it about markets, crypto, stocks, sentiment,
and what's moving — it gathers data from multiple
sources and gives you an intelligent analysis.

Data sources: CoinGecko, Yahoo Finance, Reddit
(r/wallstreetbets, r/CryptoCurrency, r/investing),
Stocktwits, Hacker News, YouTube

USAGE:
    python3 agent.py
    python3 agent.py "what's moving in crypto today"
    python3 agent.py "is ETH looking bullish on Reddit"
    python3 agent.py "NVDA sentiment on Stocktwits"
    python3 agent.py --no-escalate "BTC overview"
"""

import argparse
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

# Set to False via --no-escalate to suppress Claude escalation prompts
INTERACTIVE = True

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


SYSTEM_PROMPT = """You are a market intelligence assistant that converts user requests into structured data collection commands.

ROUTING RULES — follow exactly:
- Crypto tokens (BTC, ETH, SOL, BNB, XRP, DOGE, any coin/token) → ALWAYS "crypto" module, NEVER "finance"
- Stocks (NVDA, TSLA, AAPL, indices) → "finance" module
- "trending/hot/popular/moving" with no domain → use BOTH "trends" AND "crypto" modules
- "what's moving in crypto" → crypto.movers + crypto.overview
- "market sentiment" or "what do people think about X" → trends.get_all + relevant crypto or finance module
- Multiple crypto coins mentioned → run ONE crypto prices command with ALL coins listed, plus one crypto overview command
- "what's hot/best performing/top movers" in crypto → run crypto movers, crypto trending, AND crypto overview commands
- "is X a good buy / should I buy X" → run crypto prices for X, stocktwits sentiment for X, and trends with reddit source
- Broad queries → run 2-3 relevant modules in parallel, more data is better, the AI will interpret it
- NEVER route a crypto ticker to finance module

You have access to these modules:
1. **youtube** - Channel analytics, video performance, revenue estimates
   Actions: scrape_channel, scrape_channels
   Params: channel (str), channels (list of str)

2. **etsy** - Product research, trending products, pricing analysis
   Actions: search
   Params: query (str), pages (int 1-5), product_type ("all"/"digital"/"physical"), min_price (float), max_price (float), sort ("relevance"/"price_asc"/"price_desc"/"most_recent"/"top_reviews")

3. **crypto** - Cryptocurrency prices, market overview, big movers, trending coins
   Actions: overview, prices, movers, trending
   Params: coins (list of symbols), top_n (int), threshold (float)
   - crypto.trending → most searched coins on CoinGecko in last 24hrs

4. **finance** - Stock quotes, market summary, watchlists
   Actions: quote, watchlist, market_summary
   Params: symbol (str), symbols (list of str)

5. **trends** - Trending topics from Google, Reddit (r/wallstreetbets, r/CryptoCurrency, r/investing), HN, Product Hunt
   Actions: get_all
   Params: source ("all"/"google"/"reddit"/"hackernews"/"producthunt")

6. **stocktwits** - Real-time trader sentiment (Twitter for stocks/crypto, free public API)
   Actions: trending, sentiment
   Params: symbol (str)
   - stocktwits.trending → most discussed stocks/crypto on Stocktwits right now
   - stocktwits.sentiment(symbol) → bullish/bearish % + recent trader messages for any ticker

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

User: "What's the sentiment on ETH?"
[{"module":"stocktwits","action":"sentiment","params":{"symbol":"ETH"}},{"module":"crypto","action":"prices","params":{"coins":["ETH"]}},{"module":"trends","action":"get_all","params":{"source":"reddit"}}]

User: "What crypto is trending right now?"
[{"module":"crypto","action":"trending","params":{}},{"module":"crypto","action":"overview","params":{}}]

User: "How much is @mkbhd making on YouTube?"
[{"module":"youtube","action":"scrape_channel","params":{"handle":"mkbhd"}}]

User: "What's trending in tech right now?"
[{"module":"trends","action":"get_all","params":{"source":"hackernews"}}]

User: "Analyse @linustechtips and @mkbhd"
[{"module":"youtube","action":"scrape_channels","params":{"channels":["@linustechtips","@mkbhd"]}}]

User: "What do traders think about NVDA?"
[{"module":"stocktwits","action":"sentiment","params":{"symbol":"NVDA"}},{"module":"finance","action":"quote","params":{"symbol":"NVDA"}}]

User: "Compare BTC ETH and SOL right now"
[{"module":"crypto","action":"prices","params":{"coins":["BTC","ETH","SOL"]}},{"module":"crypto","action":"overview","params":{}}]

User: "What's the hottest crypto right now"
[{"module":"crypto","action":"movers","params":{"threshold":5}},{"module":"crypto","action":"trending","params":{}},{"module":"crypto","action":"overview","params":{}}]

Return ONLY the JSON array. No explanation. No markdown. No backticks."""


SUMMARY_PROMPT = """You are a financial terminal. Present the data below as a concise intelligence brief.

Original question: {question}

Data gathered:
{data}

Respond in exactly this format:

DATA
----
[Structured data block — price table, sentiment card, or key metrics depending on the query.
For prices: show symbol | price | 24h% | 7d% | market cap as a compact table.
For sentiment: show bullish%, bearish%, key trader quotes.
For market overview: show total cap, BTC dominance, fear/greed, top movers.
Keep it tight — numbers only, no prose here.]

ANALYSIS
--------
[3-4 sentences, analyst voice. No bullet points. No filler phrases like "it's worth noting" or "overall".
Answer the question directly, highlight what's surprising or actionable, connect dots across sources if relevant.]"""


CLARIFICATION_TEMPLATES = {
    "crypto_ambiguous": {
        "question": "What would you like to know about crypto?",
        "options": [
            "Top gaining/losing coins right now",
            "Full market overview (BTC dominance, fear/greed)",
            "Specific coin prices (tell me which)",
            "What's trending about crypto on Reddit/HN",
        ],
    },
    "ticker_ambiguous": {
        "question": "That ticker could be a crypto or a stock — which did you mean?",
        "options": [
            "Crypto (CoinGecko price)",
            "Stock (Yahoo Finance quote)",
        ],
    },
    "trending_ambiguous": {
        "question": "What kind of trending are you after?",
        "options": [
            "What's hot on the internet today (Reddit, HN, Product Hunt)",
            "Top trending crypto coins by volume/gains",
            "Trending stocks / market movers",
            "All of the above",
        ],
    },
    "no_commands": {
        "question": "I wasn't sure what to search for. What are you looking for?",
        "options": [
            "Crypto prices or market data",
            "Stock prices or market data",
            "YouTube channel analytics",
            "Etsy product research",
            "What's trending on the internet",
        ],
    },
    "finance_crypto_conflict": {
        "question": "Are you asking about the crypto token or the stock?",
        "options": [
            "Crypto token (e.g. ETH = Ethereum)",
            "Stock ticker (e.g. ETH = Ethan Allen Interiors)",
        ],
    },
    "vague_query": {
        "question": "Your query is a bit broad — want me to narrow it down?",
        "options": [
            "Just run everything relevant",
            "Let me rephrase my query",
        ],
    },
}


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


def _parse_intent_ollama(query):
    """Module-level intent parse via Ollama — useful for testing routing."""
    raw = llm_call(query, system=SYSTEM_PROMPT, temperature=0.0)
    try:
        clean = re.sub(r'```json\s*|\s*```', '', raw).strip()
        match = re.search(r'\[.*\]', clean, re.DOTALL)
        if match:
            commands = json.loads(match.group(0))
            return commands if isinstance(commands, list) else [commands]
    except (json.JSONDecodeError, AttributeError):
        pass
    return json.loads(_keyword_fallback(query))


# ── Confidence & Escalation ──────────────────────────────────

def confidence_check(commands, original_query):
    """
    Returns (is_confident: bool, reason: str)

    Checks multiple signals to decide if Ollama's
    intent parsing result is trustworthy.
    """
    query_lower = original_query.lower()

    # Broad query bypass — if query is clearly general/exploratory
    # and Ollama returned something, trust it
    BROAD_SIGNALS = [
        "what's", "whats", "trending", "popular", "hot",
        "today", "right now", "overview", "general",
        "moving", "market", "sentiment", "happening",
    ]
    broad_score = sum(1 for w in BROAD_SIGNALS if w in query_lower)
    if broad_score >= 2 and commands:
        return True, "ok"

    # Signal 1: Empty or no commands
    if not commands:
        return False, "no commands were parsed from your query"

    # Signal 2: Keyword mismatch — obvious intent in query
    # doesn't match any parsed module
    modules_found = [c.get("module", "") for c in commands]

    keyword_map = {
        "crypto":  ["btc", "eth", "bitcoin", "ethereum", "crypto",
                    "sol", "bnb", "coin", "token", "pump", "dump", "market cap"],
        "finance": ["stock", "nasdaq", "s&p", "nyse", "share",
                    "dividend", "earnings", "market"],
        "youtube": ["youtube", "channel", "@", "subscriber",
                    "views", "revenue", "youtuber"],
        "etsy":    ["etsy", "sell", "listing", "shop",
                    "printable", "digital product"],
        "trends":  ["trending", "hacker news", "reddit",
                    "product hunt", "viral", "hot"],
    }

    for module, keywords in keyword_map.items():
        if any(kw in query_lower for kw in keywords):
            if module not in modules_found:
                return False, (
                    f"your query mentions {module}-related terms but "
                    f"Ollama parsed it as {modules_found}"
                )

    # Signal 3: Any parsed command is missing an action
    for cmd in commands:
        if not cmd.get("action"):
            return False, "parsed command has no action"

    # Signal 4: "Trending" query with no domain specified — inherently ambiguous
    trend_signals = ["trending", "what's popular", "what's hot", "viral", "buzz"]
    domain_signals = (keyword_map["crypto"] + keyword_map["finance"] +
                      keyword_map["youtube"] + keyword_map["etsy"])
    if any(w in query_lower for w in trend_signals):
        if not any(d in query_lower for d in domain_signals):
            return False, "query asks what's trending but doesn't specify a domain (crypto, stocks, internet?)"

    # Signal 5: Very short/vague query with no recognisable keywords
    all_known = [kw for kws in keyword_map.values() for kw in kws]
    if len(original_query.split()) <= 3 and not any(kw in query_lower for kw in all_known):
        return False, "query is very short and has no recognisable keywords"

    return True, "ok"


def select_clarification_template(commands, query):
    """
    Picks the most relevant clarification template based on
    the confidence failure signals. Returns template key or None.
    """
    query_lower = query.lower()
    modules_found = [c.get("module", "") for c in commands]

    crypto_words = ["btc", "eth", "bitcoin", "ethereum",
                    "crypto", "sol", "bnb", "coin", "token"]
    stock_words  = ["stock", "nasdaq", "s&p", "nyse", "share", "dividend", "earnings"]
    yt_words     = ["youtube", "channel", "subscriber", "views", "youtuber"]
    etsy_words   = ["etsy", "listing", "shop", "printable", "digital product"]
    trend_words  = ["trending", "popular", "hot", "viral", "moving", "top", "what's big"]

    has_crypto = any(w in query_lower for w in crypto_words)
    has_trend  = any(w in query_lower for w in trend_words)

    # No commands at all
    if not commands:
        return "no_commands"

    # No recognisable domain keywords — purely vague
    all_domain = crypto_words + stock_words + yt_words + etsy_words + trend_words
    if not any(w in query_lower for w in all_domain):
        return "no_commands"

    # Crypto keywords but Ollama routed to finance instead
    if has_crypto and "finance" in modules_found and "crypto" not in modules_found:
        return "finance_crypto_conflict"

    # Crypto keywords but wrong module entirely
    if has_crypto and "crypto" not in modules_found:
        return "crypto_ambiguous"

    # Trending without a domain — could mean internet trends, crypto, or stocks
    if has_trend and len(modules_found) < 2:
        return "trending_ambiguous"

    return None


def ask_clarification(template_key, original_query):
    """
    Presents a numbered clarification menu to the user.
    Returns an enriched query string to re-parse, or None to skip.
    """
    if not INTERACTIVE:
        return None

    template = CLARIFICATION_TEMPLATES.get(template_key)
    if not template:
        return None

    print()
    print(f"  🤔 {template['question']}")
    print()
    for i, opt in enumerate(template["options"], 1):
        print(f"     {i}. {opt}")
    print()

    try:
        answer = input(
            "  Enter number (or press Enter to proceed as-is): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not answer:
        return None

    try:
        idx = int(answer) - 1
        if 0 <= idx < len(template["options"]):
            chosen = template["options"][idx]
            enriched = f"{original_query} — specifically: {chosen}"
            print(f"  ✓ Got it — searching for: {chosen}")
            return enriched
    except ValueError:
        # Free-form text answer
        enriched = f"{original_query} — specifically: {answer}"
        print("  ✓ Got it.")
        return enriched

    return None


def escalate_to_claude(query):
    """
    Re-runs intent parsing using Claude API.
    Returns parsed commands list or None on failure.
    """
    if not config.ANTHROPIC_API_KEY:
        print("  ⚠️  ANTHROPIC_API_KEY not set — cannot escalate to Claude.")
        return None

    print("  🤖 Escalating to Claude API...")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        commands = json.loads(raw.strip())
        if isinstance(commands, list):
            print(f"  ✅ Claude parsed {len(commands)} command(s)")
            return commands
    except Exception as e:
        print(f"  ❌ Claude escalation failed: {e}")
    return None


def prompt_escalation(reason, ollama_result, query, clarification_round=0):
    """
    First tries clarification (up to 2 rounds), then offers Claude API.

    Round 0/1: show a clarification menu → re-parse enriched query.
    Round 2+:  offer Claude API as final fallback.
    """
    if not INTERACTIVE:
        return ollama_result

    # ── Round cap: offer Claude after 2 failed clarifications ────
    if clarification_round >= 2:
        print()
        print("  ⚠️  Still uncertain after clarification.")
        print(f"  Best attempt: {json.dumps(ollama_result)}")
        print()
        try:
            answer = input(
                "  Use Claude API for a better result? [y/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ollama_result
        if answer in ("y", "yes"):
            result = escalate_to_claude(query)
            return result if result else ollama_result
        return ollama_result

    # ── Pick the best clarification template ─────────────────────
    template_key = select_clarification_template(ollama_result, query)

    if template_key:
        enriched_query = ask_clarification(template_key, query)
        if enriched_query:
            print("  🔄 Re-parsing with your clarification...")
            agent = ScraperAgent(use_llm=True)
            new_commands = agent._parse_intent(enriched_query)
            is_confident, new_reason = confidence_check(new_commands, enriched_query)
            if is_confident:
                return new_commands
            # Still not confident — recurse for round 2
            return prompt_escalation(
                new_reason, new_commands, enriched_query,
                clarification_round + 1,
            )

    # ── No template matched — fall through to Claude offer ───────
    print()
    print(f"  ⚠️  Low confidence: {reason}")
    if ollama_result:
        print(f"  Ollama parsed: {json.dumps(ollama_result)}")
    else:
        print("  Ollama returned: nothing")
    print()
    try:
        answer = input(
            "  Use Claude API for better understanding? [y/N] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ollama_result

    if answer in ("y", "yes"):
        result = escalate_to_claude(query)
        return result if result else ollama_result

    print("  Proceeding with Ollama's parsing...")
    return ollama_result


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

        # Confidence check — only when an LLM actually ran
        if self.use_llm and config.LLM_BACKEND not in ("none", ""):
            is_confident, reason = confidence_check(commands, user_input)
            if not is_confident:
                commands = prompt_escalation(reason, commands, user_input)

        # Final fallback if still empty after escalation
        if not commands:
            print("  ⚠️  No commands parsed — trying keyword fallback...")
            try:
                commands = json.loads(_keyword_fallback(user_input))
            except json.JSONDecodeError:
                pass

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
        print("  → Interpreting results against your question...")
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
    |            SCRAPER AGENT  v1.2                      |
    |                                                      |
    |  Talk to me naturally. I'll scrape the web for you.  |
    |                                                      |
    |  Examples:                                           |
    |  * "Compare BTC, ETH and SOL"                        |
    |  * "What's the hottest crypto right now?"            |
    |  * "What do traders think about NVDA?"               |
    |  * "How much is @mkbhd making on YouTube?"           |
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
    global INTERACTIVE

    parser = argparse.ArgumentParser(
        description="Scraper Agent — AI-powered web research"
    )
    parser.add_argument(
        "query", nargs="*",
        help="Query to run (omit for interactive mode; pass - to read from stdin)",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM, use keyword matching only",
    )
    parser.add_argument(
        "--no-escalate", action="store_true",
        help="Skip Claude escalation prompts (non-interactive mode)",
    )
    args = parser.parse_args()
    INTERACTIVE = not args.no_escalate

    if args.query:
        if args.query == ["-"]:
            query = sys.stdin.read().strip()
        else:
            query = " ".join(args.query)
        agent = ScraperAgent(use_llm=not args.no_llm)
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
