import re
import os
import bleach
from typing import List, Dict, Any, Tuple
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from utils.risk_analyzer import PortfolioSummary
from langsmith import traceable

# Regex pattern for valid tickers: US & International (e.g. AAPL, BRK.B, RELIANCE.NS, TCS.BO, 0700.HK)
TICKER_REGEX = re.compile(r"^[A-Z0-9.\-]{1,12}$")

# Suspicious phrases commonly used in Prompt Injections and Jailbreak attacks
INJECTION_KEYWORDS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"you\s+are\s+now\s+(a\s+)?(new|different|unrestricted|dan|jailbreak)",
    r"system\s+prompt",
    r"as\s+an\s+ai\s+without\s+rules",
    r"developer\s+mode",
    r"<script",
    r"javascript:",
    r"drop\s+table",
    r"delete\s+from",
]

# Non-compliant / promissory financial advice phrases that violate SEC/FINRA guidelines
NON_COMPLIANT_ADVICE_PATTERNS = [
    (re.compile(r"\bguaranteed\s+(return|profit|gain|money)\b", re.IGNORECASE), "potential market return"),
    (re.compile(r"\bcannot\s+lose\b", re.IGNORECASE), "carries standard investment risk"),
    (re.compile(r"\b100%\s+risk[\s-]free\b", re.IGNORECASE), "subject to market volatility"),
    (re.compile(r"\bsure\s+thing\b", re.IGNORECASE), "speculative position"),
    (re.compile(r"\bmust\s+buy\s+immediately\b", re.IGNORECASE), "consider reviewing position"),
    (re.compile(r"\binvest\s+all\s+(your\s+)?(life\s+)?savings\b", re.IGNORECASE), "consider balanced allocation"),
]

# Initialize Prompt Guard Model lazily
_prompt_guard_llm = None

def get_prompt_guard():
    global _prompt_guard_llm
    if _prompt_guard_llm is None:
        groq_api_key = os.getenv("GROQ_API_KEY")
        if groq_api_key:
            try:
                _prompt_guard_llm = ChatGroq(
                    model_name="meta-llama/llama-prompt-guard-2-86m",
                    temperature=0,
                    groq_api_key=groq_api_key
                )
            except Exception as e:
                print(f"[!] Warning: Could not initialize Llama Prompt Guard: {e}")
    return _prompt_guard_llm

# ==============================================================================
# TIER 1: INPUT GUARDRAILS (Pre-LLM)
# ==============================================================================

@traceable(name="Guardrail: Input Validator", run_type="tool")
def validate_input_request(
    watchlist: List[str], 
    max_volatility: float, 
    concentration_limit: float, 
    pe_threshold: float
) -> Tuple[bool, str]:
    """
    Validates user input parameters and ticker symbols against syntax,
    length, boundary ranges, and injection attacks.
    """
    if not watchlist or len(watchlist) == 0:
        return False, "Watchlist cannot be empty."

    if len(watchlist) > 20:
        return False, "Watchlist exceeds maximum allowed limit of 20 tickers (anti-DoS protection)."

    # Validate numerical boundaries
    if not (0.01 <= max_volatility <= 1.5):
        return False, "Volatility threshold must be between 0.01 and 1.50."
    
    if not (0.01 <= concentration_limit <= 1.0):
        return False, "Concentration limit must be between 0.01 and 1.00."

    if not (1.0 <= pe_threshold <= 500.0):
        return False, "P/E threshold must be between 1.0 and 500.0."

    # Validate each ticker syntax
    for ticker in watchlist:
        clean_ticker = ticker.strip().upper()
        if not TICKER_REGEX.match(clean_ticker):
            return False, f"Invalid ticker format: '{ticker}'. Tickers must only contain alphanumeric characters, dots, or hyphens."

    return True, "Valid"

@traceable(name="Guardrail: Prompt Guard", run_type="tool")
def check_prompt_injection(user_input_str: str) -> Tuple[bool, float, str]:
    """
    Checks user input string for Prompt Injection / Jailbreak attempts.
    Returns: (is_safe: bool, score: float, reason: str)
    """
    # 1. Fast Heuristic Rule-Based Check
    for pattern in INJECTION_KEYWORDS:
        if re.search(pattern, user_input_str, re.IGNORECASE):
            return False, 1.0, "Input matched blacklisted prompt injection pattern."

    # 2. AI Llama Prompt Guard Check
    guard = get_prompt_guard()
    if guard:
        try:
            res = guard.invoke([HumanMessage(content=user_input_str)])
            # Llama-prompt-guard-2-86m returns the probability of injection as a float string
            score = float(res.content.strip())
            # Threshold 0.85: values > 0.85 indicate malicious intent
            if score > 0.85:
                return False, score, f"Llama Prompt Guard flagged high injection probability ({score:.2%})."
            return True, score, "Safe"
        except Exception as e:
            # If the model call fails or rate limits, fallback safely to the regex heuristic
            pass

    return True, 0.0, "Safe"

# ==============================================================================
# TIER 2: INGESTION GUARDRAILS (Mid-LLM / Web Scraped Data Sanitization)
# ==============================================================================

@traceable(name="Guardrail: News Sanitizer", run_type="tool")
def sanitize_news_text(raw_text: str, max_chars: int = 1500) -> str:
    """
    Sanitizes external web and news content before passing it into the
    Orchestrator prompt to prevent Indirect Prompt Injection and context poisoning.
    """
    if not raw_text:
        return "No text available."

    cleaned = raw_text

    # Neutralize potential instruction-hijacking commands embedded in web content
    for pattern in INJECTION_KEYWORDS:
        cleaned = re.sub(pattern, "[FILTERED_INSTRUCTION]", cleaned, flags=re.IGNORECASE)

    # Strip dangerous executable HTML/script tags that might be in scraped snippets
    cleaned = re.sub(r"<[^>]*>", "", cleaned)

    # Truncate length to mitigate Context-Window Stuffing / Denial of Service
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "... [TRUNCATED_FOR_SAFETY]"

    return cleaned

# ==============================================================================
# TIER 3: OUTPUT GUARDRAILS (Post-LLM & Rendering Security)
# ==============================================================================

@traceable(name="Guardrail: Compliance Auditor", run_type="tool")
def audit_output_compliance(summary: PortfolioSummary) -> PortfolioSummary:
    """
    Audits the LLM's generated rationales, key risks, and action items to ensure:
    1. Compliance with regulatory standards (no promissory or illegal advisory claims).
    2. Redaction of banned financial claims.
    """
    for pos in summary.positions:
        if pos.rationale:
            cleaned_rationale = pos.rationale
            for pattern, replacement in NON_COMPLIANT_ADVICE_PATTERNS:
                cleaned_rationale = pattern.sub(replacement, cleaned_rationale)
            pos.rationale = cleaned_rationale

    # Audit Key Risks
    if hasattr(summary, "key_risks") and summary.key_risks:
        audited_risks = []
        for risk in summary.key_risks:
            cleaned_risk = risk
            for pattern, replacement in NON_COMPLIANT_ADVICE_PATTERNS:
                cleaned_risk = pattern.sub(replacement, cleaned_risk)
            audited_risks.append(cleaned_risk)
        summary.key_risks = audited_risks

    # Audit Action Items
    if hasattr(summary, "action_items") and summary.action_items:
        audited_actions = []
        for action in summary.action_items:
            cleaned_action = action
            for pattern, replacement in NON_COMPLIANT_ADVICE_PATTERNS:
                cleaned_action = pattern.sub(replacement, cleaned_action)
            audited_actions.append(cleaned_action)
    # Audit Market Context
    if hasattr(summary, "market_context") and summary.market_context:
        cleaned_context = summary.market_context
        for pattern, replacement in NON_COMPLIANT_ADVICE_PATTERNS:
            cleaned_context = pattern.sub(replacement, cleaned_context)
        summary.market_context = cleaned_context

    return summary

@traceable(name="Guardrail: HTML Sanitizer", run_type="tool")
def sanitize_html_content(raw_html: str) -> str:
    """
    Sanitizes HTML generated from Markdown to prevent Stored XSS attacks
    when rendering inside the frontend DOM or generating PDFs.
    """
    from bleach.css_sanitizer import CSSSanitizer

    allowed_tags = [
        'p', 'b', 'i', 'strong', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'ul', 'ol', 'li', 'hr', 'span', 'div'
    ]
    allowed_attrs = {
        '*': ['class', 'style'],
        'span': ['class'],
        'div': ['class']
    }
    
    clean_html = bleach.clean(
        raw_html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        css_sanitizer=CSSSanitizer(),
        strip=True
    )
    return clean_html
