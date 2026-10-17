from pydantic import BaseModel, Field
from typing import List, Optional

class RiskCriteria(BaseModel):
    max_volatility: float = Field(default=0.30, description="Maximum acceptable annualized volatility")
    sector_concentration_limit: float = Field(default=0.25, description="Maximum acceptable concentration in a single sector")
    pe_ratio_threshold: float = Field(default=30.0, description="Maximum acceptable P/E ratio before flagging for valuation risk")

class PositionAnalysis(BaseModel):
    ticker: str = Field(description="Stock ticker symbol")
    price: float = Field(description="Current price")
    pe_ratio: Optional[float] = Field(description="Price to Earnings ratio")
    momentum_52w: float = Field(description="52-week price momentum / return")
    latest_news_headline: str = Field(description="A short summary of the most impactful news event (max 5-8 words). Do NOT write 'Error' or 'Unavailable'. If data is missing or no news, write 'No major events'.")
    risk_flag: str = Field(default="Low Risk", description="Individual stock-specific risk flag. Must be one of: 'High Valuation', 'Negative Momentum', 'Bearish Sentiment', or 'Low Risk'. NEVER use 'Sector Concentration' here as sector concentration is evaluated at the portfolio level.")
    recommendation: str = Field(description="Action recommendation: hold, review, or investigate")
    rationale: str = Field(description="Detailed explanation for the recommendation (2-3 sentences), citing specific metrics and news.")

class PortfolioSummary(BaseModel):
    overall_risk_score: int = Field(description="Portfolio risk score from 1 (lowest) to 10 (highest)")
    net_momentum: str = Field(description="Summary of overall portfolio momentum (e.g., Bullish, Bearish, Neutral)")
    key_risks: List[str] = Field(description="List of top risks facing the portfolio (rich detail)")
    positions: List[PositionAnalysis] = Field(description="Detailed analysis of each position")
    red_flags: List[str] = Field(description="High-priority red flags ranked by impact with citations")
    action_items: List[str] = Field(description="Specific executive decisions the user should consider")
