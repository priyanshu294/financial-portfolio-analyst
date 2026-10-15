import os
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor
from tavily import TavilyClient
from langsmith import traceable
from security.guardrails import sanitize_news_text

_tavily_client: Optional[TavilyClient] = None

def get_tavily_client() -> Optional[TavilyClient]:
    global _tavily_client
    if _tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if api_key:
            try:
                _tavily_client = TavilyClient(api_key=api_key)
            except Exception as e:
                print(f"[!] Warning: Could not initialize Tavily client: {e}")
    return _tavily_client

@traceable(name="Fetch Tavily News", run_type="tool")
def fetch_and_analyze_news(ticker: str) -> Dict[str, Any]:
    try:
        client = get_tavily_client()
        if not client:
            return {
                "ticker": ticker,
                "latest_headline": "No major events",
                "llm_analysis": "News service not configured or unavailable."
            }

        # Fetch news using Tavily
        query = f"{ticker} stock latest news today headlines"
        response = client.search(query=query, search_depth="basic", max_results=3, topic="news", days=2)

        results = response.get("results", [])
        if not results:
            return {"ticker": ticker, "llm_analysis": "No recent news found.", "latest_headline": "No recent news available"}
            
        sanitized_items = []
        for res in results:
            title = sanitize_news_text(res.get('title', 'No Title'), max_chars=120)
            content = sanitize_news_text(res.get('content', '')[:600], max_chars=600)
            url = res.get('url', '')
            sanitized_items.append(f"- {title}: {content}... ({url})")

        results_str = "\n".join(sanitized_items)
        
        # Pick the first title that isn't just a file slug
        latest_headline = "News Available"
        for r in results:
            title = sanitize_news_text(r.get("title", ""), max_chars=120)
            if len(title) > 10 and not title.lower().startswith(ticker.lower() + "-"):
                latest_headline = title
                break
        
        return {
            "ticker": ticker,
            "latest_headline": latest_headline,
            "llm_analysis": results_str
        }
    except Exception as e:
        return {
            "ticker": ticker, 
            "latest_headline": "No major events",
            "llm_analysis": f"Data temporarily unavailable."
        }

@traceable(name="News Sub-Agent", run_type="tool")
def analyze_news_data(watchlist: List[str]) -> Dict[str, Any]:
    results = {}
    workers = min(10, max(1, len(watchlist)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_and_analyze_news, ticker): ticker for ticker in watchlist}
        for future in futures:
            ticker = futures[future]
            results[ticker] = future.result()
    return results
