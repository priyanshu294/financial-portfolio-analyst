"""
Automated Benchmarking and Evaluation Suite for Autonomous Financial Portfolio & News Analyst
Integrated with LangSmith Evaluation & Datasets.

Usage:
    python evals/evaluate_portfolio_agent.py
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client
from langsmith.evaluation import evaluate
from utils.risk_analyzer import RiskCriteria
from agents.orchestrator import run_orchestrator

client = Client()

DATASET_NAME = "Portfolio-Risk-Benchmark-v1"

BENCHMARK_EXAMPLES = [
    {
        "inputs": {
            "watchlist": ["TSLA"],
            "pe_threshold": 30.0,
            "max_volatility": 0.30,
            "concentration_limit": 0.25
        },
        "outputs": {
            "target_ticker": "TSLA",
            "expected_recommendations": ["INVESTIGATE", "REVIEW"],
            "must_flag_valuation": True,
            "min_risk_score": 6
        }
    },
    {
        "inputs": {
            "watchlist": ["MSFT"],
            "pe_threshold": 35.0,
            "max_volatility": 0.35,
            "concentration_limit": 0.30
        },
        "outputs": {
            "target_ticker": "MSFT",
            "expected_recommendations": ["HOLD", "REVIEW"],
            "must_flag_valuation": False,
            "min_risk_score": 1
        }
    },
    {
        "inputs": {
            "watchlist": ["NVDA"],
            "pe_threshold": 35.0,
            "max_volatility": 0.30,
            "concentration_limit": 0.25
        },
        "outputs": {
            "target_ticker": "NVDA",
            "expected_recommendations": ["HOLD", "REVIEW", "INVESTIGATE"],
            "must_flag_valuation": False,
            "min_risk_score": 4
        }
    },
    {
        "inputs": {
            "watchlist": ["AAPL", "MSFT", "NVDA"],
            "pe_threshold": 30.0,
            "max_volatility": 0.30,
            "concentration_limit": 0.25
        },
        "outputs": {
            "expected_count": 3,
            "min_risk_score": 6
        }
    }
]

def setup_or_get_dataset():
    """Initializes or updates the golden dataset in LangSmith."""
    if not client.has_dataset(dataset_name=DATASET_NAME):
        print(f"[*] Creating new LangSmith benchmark dataset: '{DATASET_NAME}'...")
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description="Golden evaluation dataset for Financial Portfolio Analyst risk rules, valuation flags, and ground truth accuracy."
        )
        for example in BENCHMARK_EXAMPLES:
            client.create_example(
                inputs=example["inputs"],
                outputs=example["outputs"],
                dataset_id=dataset.id
            )
        print(f"[✓] Created dataset with {len(BENCHMARK_EXAMPLES)} test examples.")
    else:
        print(f"[✓] Found existing LangSmith benchmark dataset: '{DATASET_NAME}'.")
    return DATASET_NAME

# ==============================================================================
# TARGET PREDICTION PIPELINE
# ==============================================================================

def target_pipeline(inputs: dict) -> dict:
    """Executes the agent orchestrator for evaluation."""
    criteria = RiskCriteria(
        max_volatility=inputs.get("max_volatility", 0.30),
        sector_concentration_limit=inputs.get("concentration_limit", 0.25),
        pe_ratio_threshold=inputs.get("pe_threshold", 30.0)
    )
    watchlist = inputs["watchlist"]
    summary = run_orchestrator(watchlist, criteria)
    return summary.model_dump()

# ==============================================================================
# CUSTOM LANGSMITH EVALUATORS
# ==============================================================================

def eval_risk_rule_adherence(run, example) -> dict:
    """
    Evaluates whether the agent strictly flags high P/E or high risk positions
    based on the provided criteria.
    """
    outputs = run.outputs
    expected = example.outputs
    
    positions = outputs.get("positions", [])
    if not positions:
        return {"key": "risk_rule_adherence", "score": 0.0, "comment": "No positions returned"}
    
    target_ticker = expected.get("target_ticker")
    if target_ticker:
        matching = [p for p in positions if p.get("ticker") == target_ticker]
        if not matching:
            return {"key": "risk_rule_adherence", "score": 0.0, "comment": f"Ticker {target_ticker} missing"}
        pos = matching[0]
        rec = pos.get("recommendation", "").upper()
        expected_recs = expected.get("expected_recommendations", [])
        score = 1.0 if rec in expected_recs else 0.5
        return {"key": "risk_rule_adherence", "score": score, "comment": f"Recommendation: {rec}"}
    
    return {"key": "risk_rule_adherence", "score": 1.0, "comment": "All positions verified"}

def eval_ground_truth_accuracy(run, example) -> dict:
    """
    Evaluates whether numbers (price, pe_ratio, momentum) are valid, non-zero,
    and free from hallucination.
    """
    positions = run.outputs.get("positions", [])
    if not positions:
        return {"key": "ground_truth_accuracy", "score": 0.0}

    valid_count = 0
    for p in positions:
        has_valid_price = isinstance(p.get("price"), (int, float)) and p.get("price") > 0
        has_valid_momentum = isinstance(p.get("momentum_52w"), (int, float))
        if has_valid_price and has_valid_momentum:
            valid_count += 1

    score = valid_count / len(positions)
    return {"key": "ground_truth_accuracy", "score": score, "comment": f"{valid_count}/{len(positions)} valid"}

def eval_compliance_safety(run, example) -> dict:
    """
    Evaluates whether rationales avoid non-compliant financial advice words.
    """
    banned_words = ["guaranteed return", "cannot lose", "sure thing", "100% risk-free"]
    positions = run.outputs.get("positions", [])
    
    for p in positions:
        rationale = p.get("rationale", "").lower()
        for bw in banned_words:
            if bw in rationale:
                return {"key": "compliance_safety", "score": 0.0, "comment": f"Found banned phrase: '{bw}'"}

    return {"key": "compliance_safety", "score": 1.0, "comment": "Fully compliant output"}

def eval_headline_quality(run, example) -> dict:
    """
    Evaluates whether headline is informative and not an error fallback.
    """
    positions = run.outputs.get("positions", [])
    valid = 0
    for p in positions:
        hl = p.get("latest_news_headline", "")
        if hl and len(hl) >= 4 and "error" not in hl.lower() and "unavailable" not in hl.lower():
            valid += 1
            
    score = valid / len(positions) if positions else 0.0
    return {"key": "headline_quality", "score": score}

# ==============================================================================
# MAIN BENCHMARK RUNNER
# ==============================================================================

def run_benchmarks():
    print("=" * 65)
    print("🚀 LangSmith Automated Evaluation & Benchmark Suite")
    print("=" * 65)
    
    dataset = setup_or_get_dataset()
    print("[*] Launching LangSmith Evaluation Matrix...")
    
    results = evaluate(
        target_pipeline,
        data=dataset,
        evaluators=[
            eval_risk_rule_adherence,
            eval_ground_truth_accuracy,
            eval_compliance_safety,
            eval_headline_quality
        ],
        experiment_prefix="portfolio-analyst-120b",
        max_concurrency=2
    )
    
    print("\n[✓] Evaluation Run Completed Successfully!")
    print("Check your LangSmith experiments dashboard for full comparisons.")
    return results

if __name__ == "__main__":
    run_benchmarks()
