import os
import requests
import yfinance as yf
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from langsmith import traceable

# Configure a shared requests session with browser headers to avoid cloud IP blocks
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

@traceable(name="Fetch Stock Market Data", run_type="tool")
def fetch_market_data(ticker: str) -> Dict[str, Any]:
    """
    Fetches historical and real-time market data with multi-tier fallbacks:
    1. yfinance with browser session headers
    2. yfinance fast_info (bypasses Yahoo crumb 401s on cloud datacenters)
    3. yfinance recent history candles
    4. Finnhub API fallback for price, P/E, and sector
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

        # 4. Finnhub Fallback (Crucial for Cloud Datacenters like Render where Yahoo blocks crumbs)
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
            except Exception as fe:
                print(f"[!] Warning: Finnhub fallback error for {clean_ticker}: {fe}")

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
