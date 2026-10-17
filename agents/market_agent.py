import os
import re
import urllib.request
import requests
import yfinance as yf
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from langsmith import traceable

# Shared requests session with browser headers
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

# Reference sector mapping for prominent Indian (NSE/BSE) equities
INDIAN_SECTORS = {
    "TCS": "Technology", "INFY": "Technology", "WIPRO": "Technology", "HCLTECH": "Technology", "TECHM": "Technology", "LTIM": "Technology",
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy", "COALINDIA": "Energy",
    "HDFCBANK": "Financial Services", "ICICIBANK": "Financial Services", "SBIN": "Financial Services", "KOTAKBANK": "Financial Services", "AXISBANK": "Financial Services", "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services",
    "TATAMOTORS": "Consumer Cyclical", "MARUTI": "Consumer Cyclical", "M&M": "Consumer Cyclical", "BAJAJ-AUTO": "Consumer Cyclical", "EICHERMOT": "Consumer Cyclical",
    "SUNPHARMA": "Healthcare", "DRREDDY": "Healthcare", "CIPLA": "Healthcare", "DIVISLAB": "Healthcare", "APOLLOHOSP": "Healthcare",
    "ITC": "Consumer Defensive", "HINDUNILVR": "Consumer Defensive", "NESTLEIND": "Consumer Defensive", "BRITANNIA": "Consumer Defensive", "TATACONSUM": "Consumer Defensive",
    "TATASTEEL": "Basic Materials", "JSWSTEEL": "Basic Materials", "HINDALCO": "Basic Materials", "GRASIM": "Basic Materials",
    "BHARTIARTL": "Communication Services",
    "LT": "Industrials", "ADANIENT": "Industrials", "ADANIPORTS": "Industrials",
    "NTPC": "Utilities", "POWERGRID": "Utilities", "TITAN": "Consumer Cyclical", "ASIANPAINT": "Basic Materials", "ULTRACEMCO": "Basic Materials"
}

def parse_compact_number(s: str) -> int:
    if not s or s == "-":
        return 0
    s = s.replace(",", "").strip()
    multiplier = 1
    if s.endswith("T"):
        multiplier = 10**12
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 10**9
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 10**6
        s = s[:-1]
    elif s.endswith("K") or s.endswith("k"):
        multiplier = 10**3
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except Exception:
        return 0

def fetch_google_finance_data(ticker: str) -> Dict[str, Any]:
    """
    Direct scraper for Google Finance key statistics (PE, EPS, Price, Market Cap).
    Unlike Yahoo, Google Finance does NOT require cookies/crumbs and does not block
    cloud datacenter IP addresses (Render, AWS, DigitalOcean).
    """
    clean = ticker.strip().upper()
    queries = []
    if clean.endswith(".NS"):
        queries = [f"{clean[:-3]}:NSE"]
    elif clean.endswith(".BO"):
        queries = [f"{clean[:-3]}:BOM"]
    else:
        queries = [f"{clean}:NASDAQ", f"{clean}:NYSE"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    for q in queries:
        try:
            url = f"https://www.google.com/finance/quote/{q}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as res:
                html = res.read().decode("utf-8", errors="ignore")

            if "We couldn't find any match" in html:
                continue

            stats = {}
            for m in re.finditer(r'<div class="SwQK7">([^<]+)</div><div class="dO6ijd">([^<]+)</div>', html):
                stats[m.group(1).strip()] = m.group(2).strip()

            pe_ratio = None
            if "P/E ratio" in stats and stats["P/E ratio"] not in ["-", ""]:
                try:
                    pe_ratio = float(stats["P/E ratio"].replace(",", ""))
                except ValueError:
                    pass

            price = None
            spans = re.findall(r'<span[^>]*>[₹\$]([\d,]+\.\d{2})</span>', html)
            if spans:
                try:
                    price = float(spans[0].replace(",", ""))
                except ValueError:
                    pass

            if pe_ratio is None and price and "EPS" in stats and stats["EPS"] not in ["-", ""]:
                try:
                    eps_clean = re.sub(r"[^0-9.]", "", stats["EPS"])
                    if eps_clean and float(eps_clean) > 0:
                        pe_ratio = round(price / float(eps_clean), 2)
                except Exception:
                    pass

            mkt_cap = parse_compact_number(stats.get("Mkt. cap", ""))

            return {"pe_ratio": pe_ratio, "price": price, "market_cap": mkt_cap, "stats": stats}
        except Exception:
            continue
    return {}

# Browser-impersonating session using curl_cffi to bypass cloud IP / datacenter blocks
_cffi_session = None
_cached_crumb = None

def get_yahoo_crumb():
    global _cffi_session, _cached_crumb
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None, None

    if _cffi_session is None or _cached_crumb is None:
        try:
            s = cffi_requests.Session(impersonate="chrome120")
            s.get("https://fc.yahoo.com", timeout=5)
            r = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=5)
            if r.status_code == 200 and r.text and len(r.text) < 50:
                _cffi_session = s
                _cached_crumb = r.text.strip()
        except Exception:
            _cffi_session = None
            _cached_crumb = None
    return _cffi_session, _cached_crumb

@traceable(name="Fetch Stock Market Data", run_type="tool")
def fetch_market_data(ticker: str) -> Dict[str, Any]:
    """
    Fetches historical and real-time market data with multi-tier fallbacks:
    1. yfinance with browser session headers
    2. yfinance fast_info (bypasses Yahoo crumb 401s on cloud datacenters)
    3. curl_cffi TLS-impersonated Yahoo quoteSummary (direct PE & sector for Indian/Global stocks)
    4. yfinance recent history candles
    5. Finnhub API fallback for price, P/E, and sector
    """
    clean_ticker = ticker.strip().upper()
    try:
        stock = yf.Ticker(clean_ticker, session=_session)
        
        info = {}
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        # 1. Price extraction with multi-tier fallbacks
        price = info.get("currentPrice") or info.get("regularMarketPrice")

        # Fallback to fast_info (does not require Yahoo crumb, works on cloud datacenters)
        if not price or float(price) <= 0:
            try:
                fi = stock.fast_info
                price = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
            except Exception:
                pass

        # Fallback to recent history candles
        if not price or float(price) <= 0:
            try:
                h = stock.history(period="5d")
                if not h.empty:
                    price = float(h["Close"].iloc[-1])
            except Exception:
                pass

        # 2. 52-Week Momentum
        momentum_52w = info.get("52WeekChange")
        if momentum_52w is not None:
            momentum_52w = float(momentum_52w) * 100
        else:
            try:
                yc = getattr(stock.fast_info, "year_change", None)
                if yc is not None:
                    momentum_52w = float(yc) * 100
            except Exception:
                pass

        if momentum_52w is None:
            try:
                history = stock.history(period="1y")
                if not history.empty and len(history) > 1:
                    start_price = history['Close'].iloc[0]
                    end_price = history['Close'].iloc[-1]
                    momentum_52w = ((end_price - start_price) / start_price) * 100
                else:
                    momentum_52w = 0.0
            except Exception:
                momentum_52w = 0.0

        # 3. P/E ratio, Market Cap, Sector, Moving Averages
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        dividend_yield = info.get("dividendYield") or 0.0
        
        market_cap = info.get("marketCap")
        if not market_cap:
            try:
                market_cap = getattr(stock.fast_info, "market_cap", 0)
            except Exception:
                market_cap = 0

        sector = info.get("sector") or "Unknown"

        fifty_day_avg = info.get("fiftyDayAverage")
        if not fifty_day_avg:
            try:
                fifty_day_avg = getattr(stock.fast_info, "fifty_day_average", 0.0)
            except Exception:
                fifty_day_avg = 0.0

        two_hundred_day_avg = info.get("twoHundredDayAverage")
        if not two_hundred_day_avg:
            try:
                two_hundred_day_avg = getattr(stock.fast_info, "two_hundred_day_average", 0.0)
            except Exception:
                two_hundred_day_avg = 0.0

        beta = info.get("beta") or 1.0

        # 4. Direct curl_cffi quoteSummary Fallback (Bypasses cloud datacenter IP blocks for Indian & Global stocks)
        if pe_ratio is None or sector == "Unknown" or not price or float(price) <= 0:
            cs, crumb = get_yahoo_crumb()
            if cs and crumb:
                try:
                    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{clean_ticker}?modules=summaryDetail,defaultKeyStatistics,assetProfile,financialData&crumb={crumb}"
                    cres = cs.get(url, timeout=5).json()
                    cresult = cres.get("quoteSummary", {}).get("result", [{}])[0]
                    csd = cresult.get("summaryDetail", {})
                    cks = cresult.get("defaultKeyStatistics", {})
                    cap = cresult.get("assetProfile", {})
                    cfd = cresult.get("financialData", {})

                    if not price or float(price) <= 0:
                        price = cfd.get("currentPrice", {}).get("raw") or csd.get("regularMarketPrice", {}).get("raw")
                    
                    if pe_ratio is None:
                        pe_ratio = csd.get("trailingPE", {}).get("raw") or csd.get("forwardPE", {}).get("raw")
                        # If still None, compute price / trailingEps
                        if pe_ratio is None and cks.get("trailingEps", {}).get("raw") and price:
                            teps = float(cks["trailingEps"]["raw"])
                            if teps > 0:
                                pe_ratio = round(float(price) / teps, 2)

                    if sector == "Unknown" and cap.get("sector"):
                        sector = cap["sector"]

                    if not market_cap and csd.get("marketCap", {}).get("raw"):
                        market_cap = csd["marketCap"]["raw"]
                except Exception as ce:
                    pass

        # 5. Finnhub Fallback (For US stocks or ADRs)
        finnhub_key = os.getenv("FINNHUB_API_KEY")
        if finnhub_key and (not price or float(price) <= 0 or pe_ratio is None or sector == "Unknown"):
            try:
                finnhub_symbol = clean_ticker.split(".")[0]
                if not price or float(price) <= 0:
                    q_res = requests.get(f"https://finnhub.io/api/v1/quote?symbol={finnhub_symbol}&token={finnhub_key}", timeout=4).json()
                    if q_res.get("c"):
                        price = float(q_res["c"])
                
                if pe_ratio is None:
                    m_res = requests.get(f"https://finnhub.io/api/v1/stock/metric?symbol={finnhub_symbol}&metric=all&token={finnhub_key}", timeout=4).json()
                    pe = m_res.get("metric", {}).get("peBasicExclExtraTTM") or m_res.get("metric", {}).get("peTTM")
                    if pe:
                        pe_ratio = float(pe)
                
                if sector == "Unknown":
                    p_res = requests.get(f"https://finnhub.io/api/v1/stock/profile2?symbol={finnhub_symbol}&token={finnhub_key}", timeout=4).json()
                    if p_res.get("finnhubIndustry"):
                        sector = p_res["finnhubIndustry"]
            except Exception:
                pass

        # 6. High-Reliability Google Finance Fallback (Guaranteed to work on cloud datacenters without crumbs/blocks)
        if pe_ratio is None or not price or float(price) <= 0 or not market_cap:
            gf_data = fetch_google_finance_data(clean_ticker)
            if gf_data:
                if pe_ratio is None and gf_data.get("pe_ratio") is not None:
                    pe_ratio = gf_data["pe_ratio"]
                if (not price or float(price) <= 0) and gf_data.get("price") is not None:
                    price = gf_data["price"]
                if not market_cap and gf_data.get("market_cap"):
                    market_cap = gf_data["market_cap"]

        # 7. Map reference sector if still Unknown
        if sector == "Unknown":
            raw_sym = clean_ticker.split(".")[0]
            if raw_sym in INDIAN_SECTORS:
                sector = INDIAN_SECTORS[raw_sym]

        return {
            "ticker": ticker,
            "price": float(price or 0.0),
            "pe_ratio": float(pe_ratio) if pe_ratio is not None else None,
            "dividend_yield": float(dividend_yield or 0.0),
            "market_cap": int(market_cap or 0),
            "sector": str(sector),
            "momentum_52w_percent": round(float(momentum_52w or 0.0), 2),
            "50d_ma": float(fifty_day_avg or 0.0),
            "200d_ma": float(two_hundred_day_avg or 0.0),
            "beta": float(beta or 1.0)
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "price": 0.0, "pe_ratio": None, "sector": "Unknown", "momentum_52w_percent": 0.0}

@traceable(name="Market Sub-Agent", run_type="tool")
def analyze_market_data(watchlist: List[str]) -> Dict[str, Any]:
    results = {}
    workers = min(10, max(1, len(watchlist)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_market_data, ticker): ticker for ticker in watchlist}
        for future in futures:
            ticker = futures[future]
            results[ticker] = future.result()
    return results
