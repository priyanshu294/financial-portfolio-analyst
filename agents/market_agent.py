import yfinance as yf
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from langsmith import traceable

@traceable(name="Fetch Stock Market Data", run_type="tool")
def fetch_market_data(ticker: str) -> Dict[str, Any]:
    """Fetches historical and real-time market data using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        # Calculate 52-week momentum
        momentum_52w = info.get("52WeekChange")
        if momentum_52w is not None:
            momentum_52w = momentum_52w * 100
        else:
            history = stock.history(period="1y")
            if not history.empty and len(history) > 1:
                start_price = history['Close'].iloc[0]
                end_price = history['Close'].iloc[-1]
                momentum_52w = ((end_price - start_price) / start_price) * 100
            else:
                momentum_52w = 0.0

        # Safe truthiness fallbacks to avoid None values
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        pe_ratio = info.get("trailingPE") or info.get("forwardPE") or None

        return {
            "ticker": ticker,
            "price": float(price),
            "pe_ratio": float(pe_ratio) if pe_ratio is not None else None,
            "dividend_yield": float(info.get("dividendYield") or 0.0),
            "market_cap": int(info.get("marketCap") or 0),
            "sector": info.get("sector") or "Unknown",
            "momentum_52w_percent": round(momentum_52w, 2),
            "50d_ma": float(info.get("fiftyDayAverage") or 0.0),
            "200d_ma": float(info.get("twoHundredDayAverage") or 0.0),
            "beta": float(info.get("beta") or 1.0)
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}

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
