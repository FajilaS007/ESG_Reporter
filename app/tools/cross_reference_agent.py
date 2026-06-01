"""Cross_Reference_Agent tool: LLM-backed greenwashing detection via Groq API."""
from __future__ import annotations

import json
import os
import re

from groq import AsyncGroq

_GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Token budget: stay under 6000 TPM (free tier limit)
_MAX_REPORT_CHARS = 1500
_MAX_ARTICLES = 5
_MAX_EXCERPT_CHARS = 150

_DEFAULT_DISCLAIMER = (
    "These findings are potential risk indicators based on automated analysis "
    "and should not be interpreted as legal verdicts or definitive conclusions."
)

# Credibility tiers for news sources
# Tier 1 (0.9): Major verified outlets — government, wire services, top newspapers
# Tier 2 (0.7): Established regional/business press
# Tier 3 (0.5): General news sites
# Tier 4 (0.2): Blogs, unknown sources — low weight, barely affects score
_CREDIBLE_SOURCES_T1 = {
    "reuters", "bloomberg", "bbc", "associated press", "ap news",
    "the hindu", "hindustan times", "times of india", "economic times",
    "business standard", "livemint", "mint", "ndtv", "pti",
    "financial times", "wall street journal", "wsj", "guardian",
    "sebi", "mca", "bse", "nse", "moneycontrol", "cnbc", "forbes",
    "the wire", "scroll", "down to earth", "india today",
}
_CREDIBLE_SOURCES_T2 = {
    "business today", "outlook", "deccan herald", "telegraph india",
    "tribune", "news18", "zee news", "firstpost", "the quint",
    "techcrunch", "wired", "verge", "inc42", "yourstory",
}


def _source_credibility(source_name: str) -> float:
    """Return a credibility weight 0.2–0.9 based on the news source.
    Also checks URL domains since LLM sometimes returns domain instead of name.
    """
    name = source_name.lower().strip()
    # Strip protocol and www from URLs
    name = re.sub(r'^https?://(www\.)?', '', name)

    for t1 in _CREDIBLE_SOURCES_T1:
        if t1 in name:
            return 0.9
    for t2 in _CREDIBLE_SOURCES_T2:
        if t2 in name:
            return 0.7
    # Has a recognizable domain pattern (e.g. .com, .in, .org)
    if re.search(r'\.(com|in|org|net|co\.in)', name):
        return 0.5
    # Non-empty but unrecognized
    if name:
        return 0.3
    return 0.2  # empty/unknown source


def _apply_credibility_weights(risk_indicators: list[dict]) -> list[dict]:
    """Adjust confidence_score by source credibility.
    Stores raw_confidence and source_credibility separately for UI display.
    Final score = LLM confidence × source credibility weight.
    """
    for indicator in risk_indicators:
        citation = indicator.get("citation") or {}
        source_name = citation.get("source_name", "")
        # Also check the URL for credibility if source_name is weak
        source_url = citation.get("url", "")
        credibility = max(
            _source_credibility(source_name),
            _source_credibility(source_url),
        )
        raw_confidence = indicator.get("confidence_score", 0.0)
        indicator["raw_confidence"] = raw_confidence
        indicator["confidence_score"] = round(raw_confidence * credibility, 3)
        indicator["source_credibility"] = credibility
    return risk_indicators

_SYSTEM_PROMPT_TEMPLATE = """You are an ESG analyst detecting greenwashing. Compare the company's sustainability report claims against news articles. Find contradictions and return ONLY this JSON:

{{"risk_indicators":[{{"claim":"string","contradicting_evidence":"string","gri_category":"string or null","tcfd_pillar":"string or null","confidence_score":0.0,"citation":{{"source_name":"string","url":"string","published_date":"string"}}}}],"disclaimer":"string"}}

GRI categories: GRI 305 Emissions, GRI 302 Energy, GRI 303 Water, GRI 304 Biodiversity, GRI 306 Waste
TCFD pillars: TCFD Strategy, TCFD Risk Management, TCFD Metrics & Targets, TCFD Governance
Frame findings as risk indicators, not legal verdicts. Company: {company}"""

_USER_PROMPT_TEMPLATE = """Report (excerpt):
{report_text}

News:
{articles_text}

Return ONLY the JSON object."""


def _format_articles(articles: list[dict]) -> str:
    # Cap to top 10 articles, truncate excerpts
    lines = []
    for i, article in enumerate(articles[:_MAX_ARTICLES], 1):
        excerpt = (article.get("excerpt") or "")[:_MAX_EXCERPT_CHARS]
        lines.append(
            f"[{i}] {article.get('title', '')}\n"
            f"    Source: {article.get('source_name', '')} | "
            f"Date: {article.get('published_date', '')} | "
            f"URL: {article.get('url', '')}\n"
            f"    {excerpt}"
        )
    return "\n\n".join(lines)


def _clamp_confidence_scores(risk_indicators: list[dict]) -> list[dict]:
    """Clamp raw LLM confidence scores, then apply source credibility weighting."""
    for indicator in risk_indicators:
        score = indicator.get("confidence_score")
        if isinstance(score, (int, float)):
            indicator["confidence_score"] = max(0.0, min(1.0, float(score)))
        else:
            indicator["confidence_score"] = 0.5  # default if LLM omits it
    # Apply credibility weighting after clamping
    return _apply_credibility_weights(risk_indicators)


def _ensure_disclaimer(result: dict) -> dict:
    disclaimer = result.get("disclaimer")
    if not disclaimer or not str(disclaimer).strip():
        result["disclaimer"] = _DEFAULT_DISCLAIMER
    return result


def _strip_code_fences(content: str) -> str:
    """Strip markdown code fences some models wrap around JSON."""
    content = content.strip()
    if content.startswith("```"):
        parts = content.split("```")
        # parts[1] is the content between first pair of fences
        content = parts[1].lstrip("json").strip() if len(parts) >= 2 else content
    return content


async def _call_llm(client: AsyncGroq, system_prompt: str, user_prompt: str) -> dict | None:
    """Call Groq and return parsed JSON dict, or None on failure."""
    try:
        response = await client.chat.completions.create(
            model=_GROQ_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=4096,
        )
        content = response.choices[0].message.content or ""
        content = _strip_code_fences(content)
        return json.loads(content)
    except json.JSONDecodeError:
        return None
    except Exception as e:
        # Surface the actual error so it shows in the disclaimer
        raise RuntimeError(f"Groq API error: {e}") from e


async def cross_reference(
    company: str,
    report_text: str | None,
    articles: list[dict],
    location: str | None = None,
) -> dict:
    """Cross-reference a sustainability report against news articles using Groq LLM.

    Returns a dict with keys:
      - risk_indicators: list of dicts describing greenwashing risk indicators
      - disclaimer: non-empty string
    """
    if not report_text or not report_text.strip():
        # No official report — analyze news alone for ESG risk signals
        if not articles:
            return {
                "risk_indicators": [],
                "disclaimer": "No sustainability report available for analysis.",
            }
        # Use news-only analysis mode
        report_text = (
            f"No official sustainability report found for {company}. "
            f"Analyze the news articles below for ESG risk signals, environmental violations, "
            f"social issues, or governance concerns. Treat any negative environmental or "
            f"social news as a potential greenwashing risk indicator."
        )

    if not articles:
        return {
            "risk_indicators": [],
            "disclaimer": "No news articles available for cross-referencing.",
        }

    location_context = (
        f" Focus specifically on the company's operations, environmental impact, "
        f"and ESG issues in {location}, India." if location else ""
    )
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(company=company) + location_context
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        report_text=report_text[:_MAX_REPORT_CHARS],
        articles_text=_format_articles(articles),
    )

    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))

    # First attempt
    try:
        result = await _call_llm(client, system_prompt, user_prompt)
    except RuntimeError as e:
        return {
            "risk_indicators": [],
            "disclaimer": f"Analysis could not be completed: {e}. Please check your GROQ_API_KEY in .env",
        }

    # Retry once on JSON parse failure
    if result is None:
        try:
            result = await _call_llm(client, system_prompt, user_prompt)
        except RuntimeError as e:
            return {
                "risk_indicators": [],
                "disclaimer": f"Analysis could not be completed: {e}.",
            }

    if result is None:
        return {
            "risk_indicators": [],
            "disclaimer": "Analysis could not be completed due to an LLM JSON parsing error.",
        }

    risk_indicators = result.get("risk_indicators", [])
    if not isinstance(risk_indicators, list):
        risk_indicators = []

    risk_indicators = _clamp_confidence_scores(risk_indicators)
    result["risk_indicators"] = risk_indicators
    result = _ensure_disclaimer(result)

    return result
