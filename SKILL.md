# scraper-agent

Web research and market intelligence tool. Scrapes live data from multiple sources and returns structured results.

## When to Use

Trigger this skill when the user asks about:
- **Crypto/market data**: prices, movers, market overview, fear & greed, any coin by symbol
- **Stock/finance**: stock prices, market summary, indices, watchlists, gainers/losers
- **YouTube analytics**: channel stats, subscriber counts, revenue estimates, video performance
- **Etsy product research**: trending products, digital/physical, pricing analysis, bestsellers
- **Trending topics**: what's hot on Google, Reddit, Hacker News, Product Hunt

Keywords: crypto, bitcoin, BTC, ETH, stock, NVDA, TSLA, market, YouTube, channel, Etsy, trending, what's hot, side hustle, product research, how much does X make

## How to Use

The scraper agent lives at `~/scraper-agent/` and runs inside a Python virtual environment.

**Always activate the venv first**, then run the command:
```bash
cd ~/scraper-agent && source venv/bin/activate && python agent.py --no-llm "USER'S QUERY HERE"
```

**IMPORTANT**: Always use `--no-llm` flag. You ARE the LLM — the scraper just needs to fetch data and return raw results. You will interpret and summarize the results yourself.

### Query Examples

| User says | Command |
|---|---|
| "What's bitcoin at?" | `python agent.py --no-llm "bitcoin price"` |
| "How's the crypto market?" | `python agent.py --no-llm "crypto market overview"` |
| "Any big crypto movers today?" | `python agent.py --no-llm "crypto big movers"` |
| "Check NVDA and TSLA" | `python agent.py --no-llm "NVDA TSLA stock price"` |
| "How's the stock market?" | `python agent.py --no-llm "stock market summary"` |
| "How much does @mkbhd make?" | `python agent.py --no-llm "@mkbhd youtube"` |
| "Compare @mkbhd and @veritasium" | `python agent.py --no-llm "@mkbhd @veritasium youtube"` |
| "Best digital products on Etsy" | `python agent.py --no-llm "etsy digital products best selling"` |
| "What's trending in tech?" | `python agent.py --no-llm "trending tech"` |
| "Full market overview" | `python agent.py --no-llm "crypto market overview stock market summary"` |

### Multiple Topics

If the user asks about multiple things (e.g., "check crypto and stocks"), run the agent once with all topics in the query. The agent handles multi-module routing internally.

## Output

The agent prints structured results to stdout. Read the output and summarize it for the user in your own style — highlight key numbers, notable moves, and actionable insights. Don't just dump raw data.

## Errors

- **403 errors on Etsy**: Etsy blocks scrapers aggressively. Let the user know and suggest specific search terms to try.
- **Timeout/connection errors**: The scraper has built-in retries. If it still fails, let the user know the source might be down.
- **Empty results**: Some sources may return no data. Report what you got and note what's missing.

## Location

- Script: `~/scraper-agent/agent.py`
- Venv: `~/scraper-agent/venv/`
- Output files: `~/scraper-agent/output/`
- Cache: `~/scraper-agent/.cache/` (auto-expires after 4 hours)
