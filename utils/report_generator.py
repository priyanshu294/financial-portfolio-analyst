import os
from datetime import datetime
from utils.risk_analyzer import PortfolioSummary

def generate_markdown_report(summary: PortfolioSummary, watchlist: list[str]) -> tuple[str, str]:
    date_str = datetime.now().strftime("%Y-%m-%d")
    tickers_str = "_".join(watchlist)
    # Truncate filename if watchlist is too long
    if len(tickers_str) > 30:
        tickers_str = tickers_str[:30] + "_etc"
    filename = f"reports/Portfolio_{tickers_str}_{date_str}.md"
    
    md_content = f"# Executive Portfolio Risk Brief\n"
    md_content += f"**Date:** {date_str}\n\n"
    md_content += f"## Portfolio Summary\n"
    md_content += f"- **Risk Score:** {summary.overall_risk_score} / 10\n"
    md_content += f"- **Net Momentum:** {summary.net_momentum}\n\n"
    
    md_content += f"### Key Risks\n"
    for risk in summary.key_risks:
        md_content += f"- {risk}\n"
    
    md_content += f"\n## Position-by-Position Analysis\n"
    md_content += "| Ticker | Price | P/E | 52W Momentum | Latest Headline | Risk Flag | Recommendation |\n"
    md_content += "|---|---|---|---|---|---|---|\n"
    
    for pos in summary.positions:
        flag = pos.risk_flag if (pos.risk_flag and str(pos.risk_flag).strip().lower() not in ["none", "null", "", "sector concentration", "concentration"]) else "Low Risk"
        pe = round(pos.pe_ratio, 2) if pos.pe_ratio else "N/A"
        headline = pos.latest_news_headline.replace("|", "-") # escape markdown tables
        currency_symbol = "₹" if pos.ticker.endswith(".NS") or pos.ticker.endswith(".BO") else "$"
        md_content += f"| {pos.ticker} | {currency_symbol}{pos.price:.2f} | {pe} | {pos.momentum_52w}% | {headline} | {flag} | **{pos.recommendation.upper()}** |\n"
        
    md_content += f"\n### Rationale\n"
    for pos in summary.positions:
        md_content += f"- **{pos.ticker}:** {pos.rationale}\n"
        
    md_content += f"\n## Red Flags & Opportunities\n"
    for rf in summary.red_flags:
        md_content += f"- {rf}\n"
        
    md_content += f"\n## Executive Action Items\n"
    for item in summary.action_items:
        md_content += f"- {item}\n"
        
    md_content += f"\n\n---\n*Disclaimer: This analysis is for informational purposes only and does not constitute investment advice. It is generated autonomously by an AI agent and may contain inaccuracies. Please verify all data before making financial decisions.*\n"
    
    return md_content, filename
