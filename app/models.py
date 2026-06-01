from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel


class Citation(BaseModel):
    source_name: str
    url: str
    published_date: str


class RiskIndicator(BaseModel):
    claim: str
    contradicting_evidence: str
    gri_category: Optional[str] = None
    tcfd_pillar: Optional[str] = None
    confidence_score: float
    source_credibility: float = 0.5  # Added by _apply_credibility_weights
    raw_confidence: Optional[float] = None  # Original LLM confidence before credibility weighting
    citation: Citation


class DataSourceStatuses(BaseModel):
    report: Literal["cached", "live", "unavailable"]
    news: Literal["available", "unavailable"]


class AuditRequest(BaseModel):
    company: str
    location: Optional[str] = None  # e.g. "Chennai, Tamil Nadu"


class LocationsRequest(BaseModel):
    company: str


class AuditReport(BaseModel):
    company: str
    audit_timestamp: str
    true_green_score: Optional[float] = None
    contradiction_count: int
    overall_confidence: float
    risk_indicators: List[RiskIndicator]
    data_source_statuses: DataSourceStatuses
    disclaimer: str
    location: Optional[str] = None
    city: Optional[str] = None  # Extracted location components
    state: Optional[str] = None
    country: Optional[str] = None


class LocationAuditSummary(BaseModel):
    """Summary of an audit for a specific location."""
    location: str
    city: str
    state: Optional[str] = None
    country: str = "India"
    true_green_score: Optional[float] = None
    contradiction_count: int
    overall_confidence: float
    audit_timestamp: str


class CompanyAuditsBySociety(BaseModel):
    """All audits for a company grouped by country and state."""
    company: str
    total_locations: int
    audits_by_country: dict[str, dict[str, List[LocationAuditSummary]]]  # {country: {state: [audits]}}
    average_score: Optional[float] = None
    worst_performing_location: Optional[LocationAuditSummary] = None
    best_performing_location: Optional[LocationAuditSummary] = None


class NewsArticle(BaseModel):
    title: str
    published_date: str
    source_name: str
    url: str
    excerpt: str


class ScoreBreakdown(BaseModel):
    base_score: float
    deductions: List[dict]


class ScorerOutput(BaseModel):
    true_green_score: Optional[float] = None
    contradiction_count: int
    score_breakdown: ScoreBreakdown


def serialize(report: AuditReport) -> str:
    """Serialize an AuditReport to a JSON string."""
    return report.model_dump_json()


def deserialize(json_str: str) -> AuditReport:
    """Deserialize a JSON string to an AuditReport."""
    return AuditReport.model_validate_json(json_str)
