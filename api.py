from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import markdown
import os
import re

from utils.risk_analyzer import RiskCriteria
from agents.orchestrator import run_orchestrator
from utils.report_generator import generate_markdown_report
from langsmith import traceable, get_current_run_tree, Client

langsmith_client = Client()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    watchlist: List[str]
    max_volatility: float
    concentration_limit: float
    pe_threshold: float
    market: str = "US"

class FeedbackRequest(BaseModel):
    run_id: str
    key: str = "user_satisfaction"
    score: float
    comment: Optional[str] = None

from security.guardrails import (
    validate_input_request,
    check_prompt_injection,
    sanitize_html_content
)

@traceable(name="Portfolio Analysis Pipeline", run_type="chain", tags=["api", "portfolio-analysis"])
def execute_portfolio_pipeline(
    watchlist: List[str],
    max_volatility: float,
    concentration_limit: float,
    pe_threshold: float,
    market: str
):
    # Tier 1 Input Guardrail: Validate ticker formatting, bounds & anti-DoS
    is_valid, validation_msg = validate_input_request(
        watchlist,
        max_volatility,
        concentration_limit,
        pe_threshold
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Input Guardrail: {validation_msg}")

    # Tier 1 Input Guardrail: AI Prompt Injection & Jailbreak check
    input_text = ", ".join(watchlist)
    is_safe, score, guard_msg = check_prompt_injection(input_text)
    if not is_safe:
        raise HTTPException(
            status_code=400, 
            detail=f"Security Guardrail Alert: Suspicious input pattern detected ({guard_msg}). Request blocked."
        )

    criteria = RiskCriteria(
        max_volatility=max_volatility,
        sector_concentration_limit=concentration_limit,
        pe_ratio_threshold=pe_threshold
    )
    
    # Process watchlist based on market selection
    processed_watchlist = []
    for ticker in watchlist:
        ticker = ticker.strip().upper()
        if market == "NSE" and not ticker.endswith(".NS"):
            ticker += ".NS"
        processed_watchlist.append(ticker)
    
    summary = run_orchestrator(processed_watchlist, criteria)
    md_content, report_path = generate_markdown_report(summary, processed_watchlist)
        
    # Convert MD to HTML for the frontend
    raw_html_content = markdown.markdown(md_content, extensions=['tables'])

    # Tier 3 Output Guardrail: Bleach HTML Sanitization (Anti-XSS)
    safe_html_content = sanitize_html_content(raw_html_content)
    
    tree = get_current_run_tree()
    run_id = str(tree.id) if tree else None
        
    return {
        "status": "success",
        "markdown": md_content,
        "html": safe_html_content,
        "report_path": report_path,
        "summary": summary.model_dump(),
        "run_id": run_id
    }

@app.post("/api/analyze")
def analyze_portfolio(req: AnalyzeRequest):
    try:
        return execute_portfolio_pipeline(
            req.watchlist,
            req.max_volatility,
            req.concentration_limit,
            req.pe_threshold,
            req.market
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest, background_tasks: BackgroundTasks):
    """
    Step 5 Production Monitoring: Record user satisfaction and feedback
    directly onto the LangSmith run trace in the background.
    """
    def log_feedback_task():
        try:
            langsmith_client.create_feedback(
                run_id=req.run_id,
                key=req.key,
                score=req.score,
                comment=req.comment
            )
        except Exception as e:
            print(f"[!] Warning: Feedback logging error: {e}")

    background_tasks.add_task(log_feedback_task)
    return {"status": "success"}

class DownloadRequest(BaseModel):
    markdown: str
    filename: str
    run_id: Optional[str] = None

from fastapi.responses import Response
from xhtml2pdf import pisa
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_REGULAR = os.path.join(BASE_DIR, "fonts", "DejaVuSans.ttf")
FONT_BOLD = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")

@traceable(name="Download PDF Report", run_type="chain", tags=["export", "pdf-generator"])
def build_pdf_report(markdown_text: str, filename: str, run_id: Optional[str] = None) -> bytes:
    """
    Renders PDF from sanitized markdown with full unicode glyph support (including ₹).
    """
    safe_markdown = markdown_text
    replacements = {
        '‑': '-', '–': '-', '—': '-', 
        '‘': "'", '’': "'", 
        '“': '"', '”': '"', 
        '…': '...'
    }
    
    # If font is not present, fallback ₹ to Rs. for safety
    if not (os.path.exists(FONT_REGULAR) and os.path.exists(FONT_BOLD)):
        replacements['₹'] = 'Rs. '

    for old, new in replacements.items():
        safe_markdown = safe_markdown.replace(old, new)
        
    html_content = markdown.markdown(safe_markdown, extensions=['tables'])

    # Format table risk flags and recommendations into badges for PDF
    def format_pdf_td(match):
        inner = match.group(1).strip()
        strong_m = re.search(r'<strong>(.*?)</strong>', inner, re.IGNORECASE)
        if strong_m:
            word = strong_m.group(1).upper()
            if word in ['INVESTIGATE', 'SELL']:
                return f'<td><span class="badge-high">{word}</span></td>'
            elif word in ['REVIEW', 'HOLD']:
                return f'<td><span class="badge-mod">{word}</span></td>'
            else:
                return f'<td><span class="badge-low">{word}</span></td>'

        lower = inner.lower()
        if any(k in lower for k in ['high valuation', 'negative momentum', 'bearish sentiment', 'high risk', 'negative']):
            return f'<td><span class="badge-high">{inner}</span></td>'
        elif any(k in lower for k in ['moderate', 'review', 'neutral']):
            return f'<td><span class="badge-mod">{inner}</span></td>'
        elif any(k in lower for k in ['low risk', 'low']):
            return f'<td><span class="badge-low">{inner}</span></td>'
        return match.group(0)

    html_content = re.sub(r'<td>(.*?)</td>', format_pdf_td, html_content)
    
    # Configure font embedding for full unicode and rupee sign (₹)
    font_face_css = ""
    font_family_name = "Helvetica, Arial, sans-serif"
    if os.path.exists(FONT_REGULAR) and os.path.exists(FONT_BOLD):
        font_face_css = f"""
        @font-face {{
            font-family: 'CorporateSans';
            src: url('{FONT_REGULAR}');
        }}
        @font-face {{
            font-family: 'CorporateSans';
            src: url('{FONT_BOLD}');
            font-weight: bold;
        }}
        """
        font_family_name = "'CorporateSans', Helvetica, Arial, sans-serif"
    
    # Clean corporate CSS for landscape PDF
    full_html = f"""
    <html>
    <head>
        <style>
            @page {{ size: A4 landscape; margin: 1.2cm; }}
            {font_face_css}
            body {{ font-family: {font_family_name}; font-size: 11pt; color: #333333; line-height: 1.5; }}
            h1 {{ font-family: {font_family_name}; color: #111827; font-size: 20pt; border-bottom: 2px solid #2563EB; padding-bottom: 5px; }}
            h2 {{ font-family: {font_family_name}; color: #1F2937; font-size: 16pt; margin-top: 20px; }}
            h3 {{ font-family: {font_family_name}; color: #374151; font-size: 13pt; margin-top: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 15px; }}
            th, td {{ border: 1px solid #E5E7EB; padding: 8px; text-align: left; vertical-align: top; font-family: {font_family_name}; }}
            th {{ background-color: #F3F4F6; font-weight: bold; font-size: 9pt; text-transform: uppercase; }}
            td {{ font-size: 9pt; }}
            .badge-low {{ background-color: #D1FAE5; color: #065F46; padding: 2px 6px; font-weight: bold; font-size: 8pt; text-transform: uppercase; }}
            .badge-mod {{ background-color: #FEF3C7; color: #92400E; padding: 2px 6px; font-weight: bold; font-size: 8pt; text-transform: uppercase; }}
            .badge-high {{ background-color: #FFE4E6; color: #9F1239; padding: 2px 6px; font-weight: bold; font-size: 8pt; text-transform: uppercase; }}
            ul {{ margin-bottom: 15px; }}
            li {{ margin-bottom: 5px; }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """
    
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(full_html), dest=pdf_buffer)
    
    if pisa_status.err:
        raise HTTPException(status_code=500, detail="PDF generation failed")
        
    return pdf_buffer.getvalue()

@app.post("/api/download-pdf")
def download_pdf(req: DownloadRequest, background_tasks: BackgroundTasks):
    safe_filename = re.sub(r'[^a-zA-Z0-9_\.-]', '_', req.filename)
    pdf_bytes = build_pdf_report(req.markdown, safe_filename, req.run_id)

    # Step 5 Telemetry: Record download feedback in background
    if req.run_id:
        def log_download_fb():
            try:
                langsmith_client.create_feedback(
                    run_id=req.run_id,
                    key="report_downloaded",
                    score=1.0,
                    comment="User downloaded PDF report"
                )
            except Exception as e:
                print(f"[!] Warning: Download feedback logging error: {e}")
        background_tasks.add_task(log_download_fb)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'}
    )

# Serve frontend directly from the root URL for single-service deployment
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
