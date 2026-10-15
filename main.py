import os
import argparse
from utils.risk_analyzer import RiskCriteria
from agents.orchestrator import run_orchestrator
from utils.report_generator import generate_markdown_report

def main():
    parser = argparse.ArgumentParser(description="Autonomous Financial Portfolio & News Analyst")
    parser.add_argument("--watchlist", type=str, required=True, help="Comma-separated list of ticker symbols (e.g., AAPL,MSFT,TSLA)")
    parser.add_argument("--max-volatility", type=float, default=0.30, help="Maximum acceptable volatility (default: 0.30)")
    parser.add_argument("--concentration-limit", type=float, default=0.25, help="Sector concentration limit (default: 0.25)")
    parser.add_argument("--pe-threshold", type=float, default=30.0, help="P/E ratio threshold for valuation risk (default: 30.0)")
    
    args = parser.parse_args()
    
    watchlist = [ticker.strip().upper() for ticker in args.watchlist.split(",")]
    
    criteria = RiskCriteria(
        max_volatility=args.max_volatility,
        sector_concentration_limit=args.concentration_limit,
        pe_ratio_threshold=args.pe_threshold
    )
    
    print(f"\n=======================================================")
    print(f"Starting Autonomous Portfolio Analysis")
    print(f"Watchlist: {watchlist}")
    print(f"Risk Criteria: PE > {criteria.pe_ratio_threshold}, Sector > {criteria.sector_concentration_limit*100}%")
    print(f"=======================================================\n")
    
    try:
        summary = run_orchestrator(watchlist, criteria)
        md_content, filename = generate_markdown_report(summary, watchlist)
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        print(f"\n[SUCCESS] Analysis complete!")
        print(f"[INFO] Report generated at: {filename}")
    except Exception as e:
        print(f"\n[ERROR] Analysis failed: {e}")

if __name__ == "__main__":
    main()
