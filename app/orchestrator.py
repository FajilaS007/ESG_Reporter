"""Orchestrator: coordinates all tools to produce an ESG AuditReport."""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import datetime, timezone

from app.tools.report_fetcher import fetch_report
from app.tools.news_fetcher import fetch_news
from app.tools.cross_reference_agent import cross_reference
from app.tools.scorer import compute_score

CACHE_DIR = pathlib.Path(__file__).resolve().parent / "cache"


def _parse_location(location: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse location string into (city, state, country).
    
    Expected format: "City, State" or "City, State, Country"
    Always defaults country to India since the app is India-scoped.
    """
    if not location or not location.strip():
        return None, None, None
    
    parts = [p.strip() for p in location.split(",")]
    if len(parts) == 1:
        # Single token — treat as state name (no city)
        return None, parts[0], "India"
    elif len(parts) == 2:
        return parts[0], parts[1], "India"
    else:
        return parts[0], parts[1], parts[2] if parts[2] else "India"


def _format_location(city: str | None, state: str | None, country: str | None) -> str:
    """Reconstruct location string from components."""
    parts = [p for p in [city, state, country] if p]
    return ", ".join(parts) if parts else ""


def _get_score_cache_path(company: str, location: str | None = None) -> pathlib.Path:
    """Generate a cache file path for a company's audit score.
    
    Cache key is company + state name (extracted from location) so that
    "Chennai, Tamil Nadu" and "Coimbatore, Tamil Nadu" map to the same cache entry.
    """
    slug = company.strip().lower().replace(" ", "_").replace("-", "_")
    if location:
        # Extract state from "City, State" or "City, State, Country"
        parts = [p.strip() for p in location.split(",")]
        state = parts[1] if len(parts) >= 2 else parts[0]
        state_slug = state.lower().replace(" ", "_").replace("-", "_")
        filename = f"{slug}_{state_slug}.json"
    else:
        filename = f"{slug}.json"
    return CACHE_DIR / filename


def _load_cached_score(company: str, location: str | None = None) -> dict | None:
    """Load a cached audit score if it exists. Returns None if not found or invalid."""
    cache_path = _get_score_cache_path(company, location)
    if not cache_path.exists():
        return None
    try:
        content = cache_path.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception:
        return None


def _save_score_cache(company: str, audit_result: dict, location: str | None = None) -> None:
    """Save the audit result to cache for future reuse."""
    cache_path = _get_score_cache_path(company, location)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(audit_result, indent=2), encoding="utf-8")
    except Exception:
        # Silently fail — caching is optional
        pass


def _get_all_audits_for_company(company: str) -> dict[str, dict]:
    """Load all cached audits for a company, organized by location.
    
    Returns: {location: audit_data, ...}
    """
    company_slug = company.strip().lower().replace(" ", "_").replace("-", "_")
    audits = {}
    
    if not CACHE_DIR.exists():
        return audits
    
    for cache_file in CACHE_DIR.glob(f"{company_slug}*.json"):
        try:
            content = cache_file.read_text(encoding="utf-8")
            audit = json.loads(content)
            location = audit.get("location") or "Global"
            audits[location] = audit
        except Exception:
            continue
    
    return audits


def _group_audits_by_state_country(audits: dict[str, dict]) -> dict[str, dict[str, list]]:
    """Group audits by country and state.
    
    Returns: {country: {state: [audit_list]}}
    """
    grouped = {}
    for location, audit in audits.items():
        city = audit.get("city")
        state = audit.get("state") or "Unknown"
        country = audit.get("country") or "India"
        
        if country not in grouped:
            grouped[country] = {}
        if state not in grouped[country]:
            grouped[country][state] = []
        
        grouped[country][state].append({
            "location": location,
            "city": city,
            "state": state,
            "country": country,
            "true_green_score": audit.get("true_green_score"),
            "contradiction_count": audit.get("contradiction_count", 0),
            "overall_confidence": audit.get("overall_confidence", 0.0),
            "audit_timestamp": audit.get("audit_timestamp"),
        })
    
    return grouped


async def run_audit(company: str, location: str | None = None) -> dict:
    """Run a full ESG audit for the given company, optionally scoped to a location.
    
    Returns a cached score if one exists. Otherwise, runs the full audit pipeline
    and caches the result for future use.
    """
    # Check if a cached score exists — if so, return it
    cached_result = _load_cached_score(company, location)
    if cached_result is not None:
        return cached_result
    
    # Parse location into components
    city, state, country = _parse_location(location)
    
    # Use state as the scoping context for news and LLM analysis
    # This ensures news search and LLM prompts are state-scoped, not city-scoped
    state_context = state if state else None

    audit_timestamp = datetime.now(timezone.utc).isoformat()

    # Fetch report and news concurrently
    # News search is scoped to the Indian state if provided
    report_result, news_result = await asyncio.gather(
        fetch_report(company),
        fetch_news(company, audit_timestamp, location=location),
    )

    report_text: str | None = report_result.get("report_text")
    report_source: str | None = report_result.get("source")
    articles: list[dict] = news_result.get("articles") or []

    # Determine data source statuses
    if report_source == "cached":
        report_status = "cached"
    elif report_source == "live":
        report_status = "live"
    else:
        report_status = "unavailable"

    news_status = "available" if articles else "unavailable"

    data_source_statuses = {
        "report": report_status,
        "news": news_status,
    }

    # Both sources unavailable — return minimal report
    if report_text is None and not articles:
        return {
            "company": company,
            "audit_timestamp": audit_timestamp,
            "true_green_score": None,
            "contradiction_count": 0,
            "overall_confidence": 0.0,
            "risk_indicators": [],
            "data_source_statuses": data_source_statuses,
            "disclaimer": (
                "Insufficient data: neither sustainability report nor news articles "
                "could be retrieved."
            ),
        }

    # Cross-reference report against news (report_text may be None — agent handles it)
    # Pass state_context so the LLM focuses on that state's operations
    cross_ref_result = await cross_reference(company, report_text, articles, location=state_context)
    risk_indicators: list[dict] = cross_ref_result.get("risk_indicators") or []
    disclaimer: str = cross_ref_result.get("disclaimer", "")

    # Compute score — penalize if no official report exists
    score_data = compute_score(risk_indicators, has_report=report_text is not None)

    # Compute overall confidence
    if not risk_indicators:
        overall_confidence = 0.0
    else:
        overall_confidence = sum(
            r.get("confidence_score", 0.0) for r in risk_indicators
        ) / len(risk_indicators)

    audit_result = {
        "company": company,
        "audit_timestamp": audit_timestamp,
        "true_green_score": score_data.get("true_green_score"),
        "contradiction_count": score_data.get("contradiction_count", 0),
        "overall_confidence": overall_confidence,
        "risk_indicators": risk_indicators,
        "data_source_statuses": data_source_statuses,
        "disclaimer": disclaimer,
        "location": location,
        "city": city,
        "state": state,
        "country": country or "India",
    }
    
    # Cache the result for future audits
    _save_score_cache(company, audit_result, location)
    
    return audit_result
