#!/usr/bin/env python3
"""
SCRAPER ENGINE — Data collection modules.
The agent calls these based on user intent.
"""

import csv
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import config


# ══════════════════════════════════════════════════════════════════
#  SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════

def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(config.USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Connection": "keep-alive",
    })
    return s


def polite_delay():
    time.sleep(random.uniform(*config.REQUEST_DELAY))


def fetch(url, session=None):
    session = session or get_session()
    for attempt in range(config.MAX_RETRIES):
        try:
            polite_delay()
            r = session.get(url, timeout=config.TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt < config.MAX_RETRIES - 1:
                time.sleep((attempt + 1) * 2)
            else:
                print(f"  [ERROR] Failed: {url} -- {e}")
                return None


def parse_number(text):
    if not text:
        return 0
    text = str(text).strip().replace(",", "").replace(" ", "")
    mults = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
    for suffix, m in mults.items():
        if text.upper().endswith(suffix):
            try:
                return int(float(text[:-1]) * m)
            except ValueError:
                return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def cache_get(key):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    path = Path(config.CACHE_DIR) / f"{hashlib.md5(key.encode()).hexdigest()}.json"
    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h < config.CACHE_TTL_HOURS:
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [WARN] Corrupted cache file {path.name}: {e} — discarding")
                path.unlink(missing_ok=True)
    return None


def cache_set(key, data):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    path = Path(config.CACHE_DIR) / f"{hashlib.md5(key.encode()).hexdigest()}.json"
    path.write_text(json.dumps(data, indent=2, default=str))


def save_output(data, filename):
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = Path(config.OUTPUT_DIR) / filename
    if config.OUTPUT_FORMAT == "csv" and isinstance(data, list):
        if data and isinstance(data[0], dict):
            with open(path.with_suffix(".csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=data[0].keys())
                w.writeheader()
                w.writerows(data)
            return str(path.with_suffix(".csv"))
    path = path.with_suffix(".json")
    path.write_text(json.dumps(data, indent=2, default=str))
    return str(path)


# ══════════════════════════════════════════════════════════════════
#  MODULE 1: YOUTUBE
# ══════════════════════════════════════════════════════════════════

class YouTubeScraper:
    def __init__(self):
        self.session = get_session()

    def scrape_channel(self, identifier):
        if identifier.startswith("http"):
            url = identifier.rstrip("/")
        else:
            # Strip leading @ if present, then always use @handle URL format
            handle = identifier.lstrip("@")
            url = f"https://www.youtube.com/@{handle}"

        cached = cache_get(f"yt:{url}")
        if cached:
            return cached

        print(f"  -> Fetching {url}")
        resp = fetch(url, self.session)
        if not resp:
            # Fall back to /channel/ URL for raw UC IDs
            fallback = f"https://www.youtube.com/channel/{handle}"
            print(f"  -> Retrying {fallback}")
            resp = fetch(fallback, self.session)
        if not resp:
            return {"channel": identifier, "error": "Failed to fetch"}

        data = self._parse_channel_page(resp.text, identifier)

        resp2 = fetch(url + "/videos", self.session)
        if resp2:
            data["recent_videos"] = self._parse_videos_tab(resp2.text)

        data["estimates"] = self._estimate_revenue(data)
        data["scraped_at"] = datetime.now().isoformat()

        cache_set(f"yt:{url}", data)
        return data

    def scrape_channels(self, identifiers):
        return [self.scrape_channel(ch.strip()) for ch in identifiers if ch.strip()]

    def _parse_channel_page(self, html, identifier):
        info = {
            "channel": identifier, "name": "", "subscribers": 0,
            "total_views": 0, "video_count": 0, "description": "",
            "joined": "", "country": "", "recent_videos": [],
        }

        m = re.search(r'ytInitialData\s*=\s*(\{.+?\});\s*</', html, re.DOTALL)
        if m:
            try:
                yt = json.loads(m.group(1))
                header = yt.get("header", {}).get("c4TabbedHeaderRenderer", {})
                if header:
                    info["name"] = header.get("title", "")
                    sub_txt = header.get("subscriberCountText", {}).get("simpleText", "")
                    info["subscribers"] = parse_number(sub_txt.split()[0]) if sub_txt else 0

                ph = yt.get("header", {}).get("pageHeaderRenderer", {})
                if ph and not info["name"]:
                    info["name"] = ph.get("pageTitle", "")

                meta = yt.get("metadata", {}).get("channelMetadataRenderer", {})
                if meta:
                    info["name"] = info["name"] or meta.get("title", "")
                    info["description"] = meta.get("description", "")[:500]
            except (json.JSONDecodeError, AttributeError):
                pass

        soup = BeautifulSoup(html, "lxml")
        if not info["name"]:
            tag = soup.find("meta", property="og:title")
            if tag:
                info["name"] = tag.get("content", "")
        if not info["description"]:
            tag = soup.find("meta", property="og:description")
            if tag:
                info["description"] = tag.get("content", "")[:500]
        if not info["subscribers"]:
            m = re.search(r'([\d.,]+[KMB]?)\s*subscribers?', html, re.I)
            if m:
                info["subscribers"] = parse_number(m.group(1))

        return info

    def _parse_videos_tab(self, html):
        videos = []
        m = re.search(r'ytInitialData\s*=\s*(\{.+?\});\s*</', html, re.DOTALL)
        if not m:
            return videos
        try:
            yt = json.loads(m.group(1))
            tabs = (yt.get("contents", {})
                      .get("twoColumnBrowseResultsRenderer", {})
                      .get("tabs", []))
            for tab in tabs:
                contents = (tab.get("tabRenderer", {})
                              .get("content", {})
                              .get("richGridRenderer", {})
                              .get("contents", []))
                for item in contents[:20]:
                    vr = (item.get("richItemRenderer", {})
                              .get("content", {})
                              .get("videoRenderer", {}))
                    if vr:
                        view_txt = vr.get("viewCountText", {}).get("simpleText", "0")
                        runs = vr.get("title", {}).get("runs", [])
                        videos.append({
                            "title": runs[0].get("text", "") if runs else "",
                            "video_id": vr.get("videoId", ""),
                            "views": parse_number(view_txt.split()[0]),
                            "published": vr.get("publishedTimeText", {}).get("simpleText", ""),
                            "duration": vr.get("lengthText", {}).get("simpleText", ""),
                        })
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        return videos

    def _estimate_revenue(self, data):
        recent = data.get("recent_videos", [])
        est = {
            "monthly_views": 0, "revenue_low": 0, "revenue_high": 0,
            "avg_views_per_video": 0, "upload_freq": "unknown", "niche": "default",
        }
        if not recent:
            return est

        total_v = sum(v.get("views", 0) for v in recent)
        est["avg_views_per_video"] = total_v // max(len(recent), 1)

        monthly = sum(
            1 for v in recent
            if any(k in v.get("published", "").lower()
                   for k in ["hour", "minute", "day", "week", "1 month", "2 week", "3 week"])
        ) or 1

        est["monthly_views"] = est["avg_views_per_video"] * monthly

        if monthly >= 20: est["upload_freq"] = "daily"
        elif monthly >= 8: est["upload_freq"] = "2-3x/week"
        elif monthly >= 4: est["upload_freq"] = "weekly"
        else: est["upload_freq"] = "bi-weekly or less"

        text = (data.get("description", "") + " " +
                " ".join(v.get("title", "") for v in recent[:5])).lower()
        for niche in config.CPM_RANGES:
            if niche != "default" and niche in text:
                est["niche"] = niche
                break

        cpm_low, cpm_high = config.CPM_RANGES.get(est["niche"], config.CPM_RANGES["default"])
        mv_k = est["monthly_views"] / 1000
        est["revenue_low"] = round(mv_k * cpm_low, 2)
        est["revenue_high"] = round(mv_k * cpm_high, 2)

        return est


# ══════════════════════════════════════════════════════════════════
#  MODULE 2: ETSY PRODUCT RESEARCH
# ══════════════════════════════════════════════════════════════════

class EtsyScraper:
    def __init__(self):
        self.session = get_session()

    def search(self, query, pages=3, product_type="all",
               min_price=None, max_price=None, sort="relevance"):

        pages = min(pages, config.MAX_PAGES_PER_SEARCH)
        cached = cache_get(f"etsy:{query}:{product_type}:{pages}:{sort}")
        if cached:
            return cached

        print(f"  -> Etsy search: '{query}' (type={product_type}, pages={pages})")

        sort_map = {
            "relevance": "", "price_asc": "&order=price_asc",
            "price_desc": "&order=price_desc", "most_recent": "&order=date_desc",
            "top_reviews": "&order=most_relevant&explicit=1&min_price=0.01",
        }

        all_products = []
        for page in range(1, pages + 1):
            url = f"https://www.etsy.com/search?q={quote_plus(query)}&page={page}"
            url += sort_map.get(sort, "")
            if product_type == "digital": url += "&is_digital=true"
            elif product_type == "physical": url += "&is_digital=false"
            if min_price: url += f"&min={min_price}"
            if max_price: url += f"&max={max_price}"

            resp = fetch(url, self.session)
            if not resp:
                continue

            products = self._parse_results(resp.text)
            all_products.extend(products)
            print(f"    Page {page}: {len(products)} listings")

        seen = set()
        unique = []
        for p in all_products:
            key = p.get("listing_id") or p.get("title", "")
            if key not in seen:
                seen.add(key)
                unique.append(p)

        result = {
            "query": query, "product_type": product_type,
            "total_results": len(unique), "products": unique,
            "analysis": self._analyze(unique),
            "scraped_at": datetime.now().isoformat(),
        }

        cache_set(f"etsy:{query}:{product_type}:{pages}:{sort}", result)
        return result

    def _parse_results(self, html):
        products = []
        soup = BeautifulSoup(html, "lxml")
        listings = soup.find_all(attrs={"data-listing-id": True})
        if not listings:
            listings = soup.select(".v2-listing-card, .wt-grid__item-xs-6")

        for item in listings:
            try:
                p = {}
                p["listing_id"] = item.get("data-listing-id", "")

                title_el = item.select_one("h3, .v2-listing-card__title, [class*='title']")
                p["title"] = title_el.get_text(strip=True) if title_el else ""

                price_el = item.select_one(".currency-value, [class*='price'] span, .lc-price span")
                price_text = price_el.get_text(strip=True) if price_el else ""
                p["price"] = float(re.sub(r'[^\d.]', '', price_text)) if price_text else 0
                p["currency"] = "USD"

                rating_el = item.select_one("[class*='rating'], .stars-svg")
                if rating_el:
                    aria = rating_el.get("aria-label", "")
                    rm = re.search(r'([\d.]+)', aria)
                    p["rating"] = float(rm.group(1)) if rm else 0
                else:
                    p["rating"] = 0

                review_el = item.select_one("[class*='review'] span, .text-body-smaller")
                rev_text = review_el.get_text(strip=True) if review_el else "0"
                p["reviews"] = parse_number(re.sub(r'[^\d]', '', rev_text))

                text_block = item.get_text(" ", strip=True).lower()
                p["is_bestseller"] = "bestseller" in text_block
                p["is_digital"] = "digital download" in text_block or "instant download" in text_block
                p["free_shipping"] = "free shipping" in text_block

                shop_el = item.select_one("[class*='shop-name'], .v2-listing-card__shop")
                p["shop"] = shop_el.get_text(strip=True) if shop_el else ""

                link = item.select_one("a[href*='/listing/']")
                p["url"] = link["href"] if link else ""

                if p["title"]:
                    products.append(p)
            except Exception:
                continue

        return products

    def _analyze(self, products):
        if not products:
            return {"note": "No products to analyze"}

        prices = [p["price"] for p in products if p["price"] > 0]
        ratings = [p["rating"] for p in products if p["rating"] > 0]

        analysis = {"total_listings": len(products), "price": {}, "ratings": {}, "market_signals": {}}

        if prices:
            prices_sorted = sorted(prices)
            analysis["price"] = {
                "avg": round(sum(prices) / len(prices), 2),
                "median": round(prices_sorted[len(prices_sorted)//2], 2),
                "min": min(prices), "max": max(prices),
                "sweet_spot": f"${prices_sorted[len(prices_sorted)//4]:.2f} - ${prices_sorted[3*len(prices_sorted)//4]:.2f}",
            }

        if ratings:
            analysis["ratings"] = {
                "avg": round(sum(ratings) / len(ratings), 2),
                "pct_above_4_5": round(sum(1 for r in ratings if r >= 4.5) / len(ratings) * 100, 1),
            }

        analysis["market_signals"] = {
            "pct_bestsellers": round(sum(1 for p in products if p.get("is_bestseller")) / len(products) * 100, 1),
            "pct_digital": round(sum(1 for p in products if p.get("is_digital")) / len(products) * 100, 1),
            "pct_free_shipping": round(sum(1 for p in products if p.get("free_shipping")) / len(products) * 100, 1),
            "total_review_volume": sum(p.get("reviews", 0) for p in products),
        }

        shop_reviews = {}
        for p in products:
            shop = p.get("shop", "unknown")
            shop_reviews[shop] = shop_reviews.get(shop, 0) + p.get("reviews", 0)
        top_shops = sorted(shop_reviews.items(), key=lambda x: x[1], reverse=True)[:5]
        analysis["top_shops"] = [{"shop": s, "total_reviews": r} for s, r in top_shops]

        return analysis


# ══════════════════════════════════════════════════════════════════
#  MODULE 3: CRYPTO MARKET SCANNER
# ══════════════════════════════════════════════════════════════════

class CryptoScraper:
    COINGECKO_API = "https://api.coingecko.com/api/v3"

    def __init__(self):
        self.session = get_session()

    def get_prices(self, coins=None, top_n=20):
        if coins:
            return self._fetch_specific_coins(coins)
        return self._fetch_top_coins(top_n)

    def get_market_overview(self):
        cached = cache_get("crypto:overview")
        if cached:
            return cached

        print("  -> Fetching crypto market overview")
        data = {"global": {}, "top_gainers": [], "top_losers": [], "fear_greed": ""}

        resp = fetch(f"{self.COINGECKO_API}/global", self.session)
        if resp:
            g = resp.json().get("data", {})
            data["global"] = {
                "total_market_cap_usd": g.get("total_market_cap", {}).get("usd", 0),
                "total_volume_24h_usd": g.get("total_volume", {}).get("usd", 0),
                "btc_dominance": round(g.get("market_cap_percentage", {}).get("btc", 0), 2),
                "eth_dominance": round(g.get("market_cap_percentage", {}).get("eth", 0), 2),
                "active_cryptos": g.get("active_cryptocurrencies", 0),
                "market_cap_change_24h": round(g.get("market_cap_change_percentage_24h_usd", 0), 2),
            }

        top = self._fetch_top_coins(100)
        if top.get("coins"):
            sorted_by_change = sorted(top["coins"], key=lambda c: c.get("change_24h", 0))
            data["top_losers"] = sorted_by_change[:5]
            data["top_gainers"] = sorted_by_change[-5:][::-1]

        try:
            polite_delay()
            fg_resp = self.session.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            if fg_resp.ok:
                fg = fg_resp.json().get("data", [{}])[0]
                data["fear_greed"] = f"{fg.get('value', '?')} -- {fg.get('value_classification', '?')}"
        except Exception:
            data["fear_greed"] = "unavailable"

        data["scraped_at"] = datetime.now().isoformat()
        cache_set("crypto:overview", data)
        return data

    def find_big_movers(self, threshold_pct=10):
        top = self._fetch_top_coins(100)
        movers = {"big_gainers": [], "big_losers": [], "threshold": threshold_pct}
        for coin in top.get("coins", []):
            change = coin.get("change_24h", 0)
            if change >= threshold_pct:
                movers["big_gainers"].append(coin)
            elif change <= -threshold_pct:
                movers["big_losers"].append(coin)
        movers["big_gainers"].sort(key=lambda c: c["change_24h"], reverse=True)
        movers["big_losers"].sort(key=lambda c: c["change_24h"])
        return movers

    def _fetch_top_coins(self, n=20):
        cached = cache_get(f"crypto:top:{n}")
        if cached:
            return cached

        print(f"  -> Fetching top {n} cryptocurrencies")
        coins = []
        per_page = min(n, 250)
        pages = (n + per_page - 1) // per_page

        for page in range(1, pages + 1):
            url = (f"{self.COINGECKO_API}/coins/markets"
                   f"?vs_currency=usd&order=market_cap_desc"
                   f"&per_page={per_page}&page={page}&sparkline=false")
            resp = fetch(url, self.session)
            if not resp:
                continue
            try:
                coin_data = resp.json()
            except (json.JSONDecodeError, ValueError) as e:
                print(f"  [ERROR] Invalid JSON from CoinGecko: {e}")
                continue
            for c in coin_data:
                coins.append({
                    "rank": c.get("market_cap_rank"),
                    "name": c.get("name"),
                    "symbol": c.get("symbol", "").upper(),
                    "price": c.get("current_price"),
                    "change_24h": round(c.get("price_change_percentage_24h") or 0, 2),
                    "market_cap": c.get("market_cap"),
                    "volume_24h": c.get("total_volume"),
                    "ath": c.get("ath"),
                    "ath_date": c.get("ath_date", "")[:10],
                    "from_ath_pct": round(((c.get("current_price", 0) - c.get("ath", 1)) / max(c.get("ath", 1), 0.01)) * 100, 1),
                })

        result = {"coins": coins[:n], "count": len(coins[:n]), "scraped_at": datetime.now().isoformat()}
        cache_set(f"crypto:top:{n}", result)
        return result

    def _fetch_specific_coins(self, symbols):
        symbol_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
            "DOGE": "dogecoin", "DOT": "polkadot", "AVAX": "avalanche-2",
            "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap",
            "SHIB": "shiba-inu", "LTC": "litecoin", "ATOM": "cosmos",
            "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
            "APT": "aptos", "NEAR": "near", "FTM": "fantom",
            "PEPE": "pepe", "WIF": "dogwifcoin",
        }

        ids = []
        for s in symbols:
            s = s.strip().upper()
            if s.lower() in symbol_map.values():
                ids.append(s.lower())
            elif s in symbol_map:
                ids.append(symbol_map[s])
            else:
                ids.append(s.lower())

        ids_str = ",".join(ids)
        cached = cache_get(f"crypto:specific:{ids_str}")
        if cached:
            return cached

        print(f"  -> Fetching: {', '.join(symbols)}")
        url = (f"{self.COINGECKO_API}/coins/markets"
               f"?vs_currency=usd&ids={ids_str}&sparkline=false"
               f"&price_change_percentage=24h,7d")
        resp = fetch(url, self.session)
        if not resp:
            return {"error": "Failed to fetch coin data"}

        try:
            coin_data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  [ERROR] Invalid JSON from CoinGecko: {e}")
            return {"error": "Invalid response from CoinGecko"}
        coins = []
        for c in coin_data:
            coins.append({
                "name": c.get("name"),
                "symbol": c.get("symbol", "").upper(),
                "price": c.get("current_price"),
                "change_24h": round(c.get("price_change_percentage_24h") or 0, 2),
                "market_cap": c.get("market_cap"),
                "volume_24h": c.get("total_volume"),
                "rank": c.get("market_cap_rank"),
                "ath": c.get("ath"),
                "from_ath_pct": round(((c.get("current_price", 0) - c.get("ath", 1)) / max(c.get("ath", 1), 0.01)) * 100, 1),
                "ath_drop_pct": round((c.get("ath", 1) - c.get("current_price", 0)) / c.get("ath", 1) * 100, 1) if c.get("ath") else None,
                "price_change_7d": c.get("price_change_percentage_7d_in_currency"),
                "high_24h": c.get("high_24h"),
                "low_24h": c.get("low_24h"),
                "circulating_supply": c.get("circulating_supply"),
            })

        result = {"coins": coins, "scraped_at": datetime.now().isoformat()}
        cache_set(f"crypto:specific:{ids_str}", result)
        return result

    def get_trending(self):
        """Top 7 coins most searched on CoinGecko in the last 24hrs. Free, no API key."""
        cached = cache_get("crypto:trending")
        if cached:
            return cached

        print("  -> Fetching CoinGecko trending coins")
        url = f"{self.COINGECKO_API}/search/trending"
        resp = fetch(url, self.session)
        if not resp:
            return {"error": "Failed to fetch trending"}

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            return {"error": f"Invalid response: {e}"}

        coins = []
        for item in data.get("coins", []):
            c = item.get("item", {})
            coins.append({
                "rank":   c.get("market_cap_rank"),
                "name":   c.get("name"),
                "symbol": c.get("symbol"),
                "score":  c.get("score"),  # trending rank 0-6
            })

        result = {
            "trending_coins": coins,
            "note": "Most searched coins on CoinGecko in last 24hrs",
            "scraped_at": datetime.now().isoformat(),
        }
        cache_set("crypto:trending", result)
        return result


# ══════════════════════════════════════════════════════════════════
#  MODULE 4: STOCK / FINANCE SCANNER
# ══════════════════════════════════════════════════════════════════

class FinanceScraper:
    def __init__(self):
        self.session = get_session()

    def get_quote(self, symbol):
        symbol = symbol.upper().strip()
        cached = cache_get(f"fin:quote:{symbol}")
        if cached:
            return cached

        print(f"  -> Fetching quote: {symbol}")
        url = f"https://finance.yahoo.com/quote/{symbol}/"
        resp = fetch(url, self.session)
        if not resp:
            return {"symbol": symbol, "error": "Could not fetch quote"}

        data = self._parse_yahoo_quote(resp.text, symbol)
        data["scraped_at"] = datetime.now().isoformat()
        cache_set(f"fin:quote:{symbol}", data)
        return data

    def get_watchlist(self, symbols):
        return [self.get_quote(s.strip()) for s in symbols if s.strip()]

    def get_market_summary(self):
        cached = cache_get("fin:market_summary")
        if cached:
            return cached

        print("  -> Fetching market summary")
        indices = {
            "S&P 500": "^GSPC", "NASDAQ": "^IXIC", "DOW": "^DJI",
            "Russell 2000": "^RUT", "VIX": "^VIX", "10Y Treasury": "^TNX",
        }

        summary = {"indices": {}, "scraped_at": datetime.now().isoformat()}
        for name, ticker in indices.items():
            quote = self.get_quote(ticker)
            if "error" not in quote:
                summary["indices"][name] = {
                    "price": quote.get("price"),
                    "change": quote.get("change"),
                    "change_pct": quote.get("change_pct"),
                }

        url = "https://finance.yahoo.com/markets/stocks/gainers/"
        resp = fetch(url, self.session)
        if resp:
            summary["top_gainers"] = self._parse_movers_page(resp.text)[:5]

        url2 = "https://finance.yahoo.com/markets/stocks/losers/"
        resp2 = fetch(url2, self.session)
        if resp2:
            summary["top_losers"] = self._parse_movers_page(resp2.text)[:5]

        cache_set("fin:market_summary", summary)
        return summary

    def _parse_yahoo_quote(self, html, symbol):
        data = {"symbol": symbol, "price": 0, "change": 0, "change_pct": 0}
        soup = BeautifulSoup(html, "lxml")

        price_selectors = [
            'fin-streamer[data-field="regularMarketPrice"]',
            '[data-testid="qsp-price"]', '.livePrice span',
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                try:
                    data["price"] = float(el.get("data-value", el.get_text()).replace(",", ""))
                    break
                except (ValueError, TypeError):
                    continue

        change_el = soup.select_one('fin-streamer[data-field="regularMarketChange"]')
        if change_el:
            try:
                data["change"] = float(change_el.get("data-value", "0"))
            except (ValueError, TypeError):
                pass

        pct_el = soup.select_one('fin-streamer[data-field="regularMarketChangePercent"]')
        if pct_el:
            try:
                data["change_pct"] = round(float(pct_el.get("data-value", "0")), 2)
            except (ValueError, TypeError):
                pass

        stat_labels = soup.find_all("span", string=re.compile(
            r"(Market Cap|Volume|P/E|EPS|52 Week|Prev|Open|Day)", re.I))
        for label in stat_labels:
            key = label.get_text(strip=True).lower()
            value_el = label.find_next("span")
            if value_el:
                val = value_el.get_text(strip=True)
                if "market cap" in key: data["market_cap"] = val
                elif "volume" in key and "avg" not in key: data["volume"] = val
                elif "p/e" in key: data["pe_ratio"] = val
                elif "eps" in key: data["eps"] = val
                elif "52 week" in key: data["week_52_range"] = val
                elif "prev" in key: data["prev_close"] = val
                elif "open" in key and "day" not in key: data["open"] = val

        return data

    def _parse_movers_page(self, html):
        movers = []
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table tbody tr")[:10]
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 4:
                movers.append({
                    "symbol": cells[0].get_text(strip=True),
                    "name": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    "price": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    "change_pct": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                })
        return movers


# ══════════════════════════════════════════════════════════════════
#  MODULE 5: TREND DETECTION
# ══════════════════════════════════════════════════════════════════

class TrendScraper:
    def __init__(self):
        self.session = get_session()

    def get_all_trends(self):
        cached = cache_get("trends:all")
        if cached:
            return cached

        print("  -> Gathering trends from all sources...")
        trends = {
            "google": self.google_trends(),
            "reddit": self.reddit_trending(),
            "hackernews": self.hackernews_top(),
            "producthunt": self.producthunt_today(),
            "scraped_at": datetime.now().isoformat(),
        }
        cache_set("trends:all", trends)
        return trends

    def google_trends(self):
        print("    -> Google Trends")
        url = "https://trends.google.com/trending/rss?geo=US"
        resp = fetch(url, self.session)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.find_all("item")
        trends = []
        for item in items[:20]:
            title = item.find("title")
            traffic = item.find("ht:approx_traffic") or item.find("approx_traffic")
            trends.append({
                "topic": title.get_text(strip=True) if title else "",
                "traffic": traffic.get_text(strip=True) if traffic else "",
                "source": "google_trends",
            })
        return trends

    def reddit_trending(self):
        print("    -> Reddit")
        posts = []
        subreddits = [
            "wallstreetbets",   # high-signal stock sentiment
            "CryptoCurrency",   # crypto community
            "investing",        # serious investors
            "stocks",           # stock discussion
            "technology",       # tech trends
            "popular",          # general internet pulse
        ]
        # Reddit needs a descriptive UA; use a separate session so we don't
        # clobber the randomised UA used by every other scraper.
        reddit_session = get_session()
        reddit_session.headers["User-Agent"] = "Python:scraper-agent:v1.0 (educational use)"
        for sub in subreddits:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=15"
            resp = fetch(url, reddit_session)
            if not resp:
                continue
            try:
                data = resp.json()
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    posts.append({
                        "title": post.get("title", ""),
                        "subreddit": post.get("subreddit", ""),
                        "score": post.get("score", 0),
                        "comments": post.get("num_comments", 0),
                        "url": post.get("url", ""),
                        "source": "reddit",
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        posts.sort(key=lambda p: p.get("score", 0), reverse=True)
        return posts[:20]

    def hackernews_top(self):
        print("    -> Hacker News")
        stories = []
        url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        resp = fetch(url, self.session)
        if not resp:
            return []

        try:
            ids = resp.json()[:15]
        except (json.JSONDecodeError, TypeError):
            return []

        for story_id in ids:
            url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            resp = fetch(url, self.session)
            if resp:
                try:
                    s = resp.json()
                    stories.append({
                        "title": s.get("title", ""),
                        "score": s.get("score", 0),
                        "comments": s.get("descendants", 0),
                        "url": s.get("url", ""),
                        "by": s.get("by", ""),
                        "source": "hackernews",
                    })
                except (json.JSONDecodeError, KeyError):
                    continue
        return stories

    def producthunt_today(self):
        print("    -> Product Hunt")
        url = "https://www.producthunt.com/"
        resp = fetch(url, self.session)
        if not resp:
            return []

        products = []
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select("[data-test='post-item'], .styles_item__Dk_nz, section a[href*='/posts/']")
        for item in items[:10]:
            title_el = item.select_one("h3, [class*='title'], strong")
            desc_el = item.select_one("p, [class*='tagline']")
            products.append({
                "name": title_el.get_text(strip=True) if title_el else "",
                "tagline": desc_el.get_text(strip=True) if desc_el else "",
                "source": "producthunt",
            })
        return [p for p in products if p["name"]]


# ══════════════════════════════════════════════════════════════════
#  MODULE 6: STOCKTWITS SENTIMENT
# ══════════════════════════════════════════════════════════════════

class StocktwitsScraper:
    """
    Scrapes Stocktwits for real-time stock and crypto sentiment.
    Free public API, no key required.
    Stocktwits is Twitter specifically for traders.
    """

    def __init__(self):
        self.token = os.environ.get("STOCKTWITS_ACCESS_TOKEN", "")
        self.session = get_session()
        self.base = "https://api.stocktwits.com/api/2"

    def get_trending(self):
        """Get trending symbols on Stocktwits right now."""
        cached = cache_get("stocktwits:trending")
        if cached:
            return cached

        print("  -> Fetching Stocktwits trending symbols")
        token_param = f"?access_token={self.token}" if self.token else ""
        url = f"{self.base}/trending/symbols.json{token_param}"
        resp = fetch(url, self.session)
        if not resp:
            if not self.token:
                return {
                    "skipped": True,
                    "reason": "Stocktwits requires an access token — add STOCKTWITS_ACCESS_TOKEN to .env",
                }
            return {"error": "Stocktwits unavailable"}

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            return {"error": f"Invalid response: {e}"}

        symbols = []
        for s in data.get("symbols", [])[:15]:
            symbols.append({
                "symbol":          s.get("symbol"),
                "title":           s.get("title"),
                "watchlist_count": s.get("watchlist_count"),
            })

        result = {
            "trending_symbols": symbols,
            "note": "Most discussed symbols on Stocktwits right now",
            "scraped_at": datetime.now().isoformat(),
        }
        cache_set("stocktwits:trending", result)
        return result

    def get_symbol_sentiment(self, symbol):
        """Get recent messages and bullish/bearish sentiment for a ticker."""
        symbol = symbol.upper().strip()
        cached = cache_get(f"stocktwits:{symbol}")
        if cached:
            return cached

        print(f"  -> Fetching Stocktwits sentiment: {symbol}")
        token_param = f"?access_token={self.token}" if self.token else ""
        url = f"{self.base}/streams/symbol/{symbol}.json{token_param}"
        resp = fetch(url, self.session)
        if not resp:
            if not self.token:
                return {
                    "symbol": symbol,
                    "skipped": True,
                    "reason": "Stocktwits requires an access token — add STOCKTWITS_ACCESS_TOKEN to .env",
                }
            return {"symbol": symbol, "error": "Stocktwits unavailable"}

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            return {"error": f"Invalid response: {e}"}

        messages = []
        bullish = 0
        bearish = 0

        for msg in data.get("messages", [])[:20]:
            sentiment = msg.get("entities", {}).get("sentiment", {})
            if sentiment:
                basic = sentiment.get("basic", "")
                if basic == "Bullish":
                    bullish += 1
                elif basic == "Bearish":
                    bearish += 1

            messages.append({
                "body":      msg.get("body", "")[:200],
                "sentiment": sentiment.get("basic", "neutral") if sentiment else "neutral",
                "likes":     msg.get("likes", {}).get("total", 0),
                "created":   msg.get("created_at", ""),
            })

        total = bullish + bearish
        bull_pct = round(bullish / total * 100) if total else 50

        result = {
            "symbol":          symbol,
            "bullish":         bullish,
            "bearish":         bearish,
            "bull_pct":        bull_pct,
            "sentiment_label": (
                "BULLISH" if bull_pct > 60 else
                "BEARISH" if bull_pct < 40 else
                "NEUTRAL"
            ),
            "top_messages":    messages[:10],
            "scraped_at":      datetime.now().isoformat(),
        }
        cache_set(f"stocktwits:{symbol}", result)
        return result


# ══════════════════════════════════════════════════════════════════
#  MASTER DISPATCHER
# ══════════════════════════════════════════════════════════════════

def execute_scrape_command(command):
    module = command.get("module", "").lower()
    action = command.get("action", "")
    params = command.get("params", {})

    try:
        if module == "youtube":
            yt = YouTubeScraper()
            if action in ("scrape_channel", "channel"):
                handle = (
                    params.get("handle") or
                    params.get("channel") or
                    (params.get("channels") or [""])[0] or
                    (params.get("handles") or [""])[0]
                )
                return yt.scrape_channel(handle)
            elif action == "scrape_channels":
                handles = params.get("handles") or params.get("channels") or []
                return {"channels": [yt.scrape_channel(h) for h in handles]}
            else:
                return {"error": f"Unknown YouTube action: {action}"}

        elif module == "etsy":
            return EtsyScraper().search(
                query=params.get("query", ""), pages=params.get("pages", 3),
                product_type=params.get("product_type", "all"),
                min_price=params.get("min_price"), max_price=params.get("max_price"),
                sort=params.get("sort", "relevance"),
            )

        elif module == "crypto":
            crypto = CryptoScraper()
            if action == "overview": return crypto.get_market_overview()
            elif action == "prices": return crypto.get_prices(coins=params.get("coins"), top_n=params.get("top_n", 20))
            elif action == "movers": return crypto.find_big_movers(params.get("threshold", 10))
            elif action == "trending": return crypto.get_trending()
            else: return crypto.get_market_overview()

        elif module == "finance":
            fin = FinanceScraper()
            if action == "quote":
                # Accept both symbol (str) and symbols (list) from LLM
                sym = params.get("symbol") or (params.get("symbols") or [""])[0]
                return fin.get_quote(sym)
            elif action == "watchlist": return {"quotes": fin.get_watchlist(params.get("symbols", []))}
            elif action == "market_summary": return fin.get_market_summary()
            else: return fin.get_market_summary()

        elif module == "trends":
            tr = TrendScraper()
            source = params.get("source", "all")
            if source == "all": return tr.get_all_trends()
            elif source == "google": return {"trends": tr.google_trends()}
            elif source == "reddit": return {"trends": tr.reddit_trending()}
            elif source == "hackernews": return {"trends": tr.hackernews_top()}
            elif source == "producthunt": return {"trends": tr.producthunt_today()}
            else: return tr.get_all_trends()

        elif module == "stocktwits":
            st = StocktwitsScraper()
            if not st.token:
                return {
                    "skipped": True,
                    "reason": "Stocktwits access token not configured",
                    "fix": "Register free app at stocktwits.com/developers and add STOCKTWITS_ACCESS_TOKEN to .env",
                }
            if action == "trending":
                return st.get_trending()
            elif action == "sentiment":
                return st.get_symbol_sentiment(params.get("symbol", "BTC"))
            else:
                return st.get_trending()

        else:
            return {"error": f"Unknown module: {module}"}

    except Exception as e:
        return {"error": str(e), "module": module, "action": action}
