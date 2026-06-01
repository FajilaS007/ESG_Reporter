"""News_Fetcher tool: multi-source news retrieval with date filtering."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

NEWSAPI_URL = "https://newsapi.org/v2/everything"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

_MAX_ARTICLES = 50

# Browser-like headers to avoid RSS blocks
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_audit_timestamp(audit_timestamp: str | None) -> datetime:
    if audit_timestamp:
        dt = datetime.fromisoformat(audit_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return datetime.now(tz=timezone.utc)


def _cutoff_date(audit_dt: datetime) -> datetime:
    try:
        return audit_dt.replace(year=audit_dt.year - 2)
    except ValueError:
        return audit_dt.replace(year=audit_dt.year - 2, day=28)


def _parse_date(raw: str) -> str:
    """Normalize various date formats to YYYY-MM-DD ISO8601 string."""
    if not raw:
        return ""
    raw = raw.strip()

    # GDELT format: 20240115T120000Z
    if len(raw) >= 8 and raw[:8].isdigit() and "T" in raw:
        try:
            return datetime.strptime(raw[:8], "%Y%m%d").date().isoformat()
        except ValueError:
            pass

    # Already ISO8601 date: 2024-01-15 or 2024-01-15T...
    if len(raw) >= 10 and raw[4] == "-":
        return raw[:10]

    # RFC 2822 (RSS pubDate): Mon, 15 Jan 2024 12:00:00 +0000
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        pass

    return raw[:10] if len(raw) >= 10 else raw


def _within_window(published_date: str, cutoff: datetime) -> bool:
    try:
        dt = datetime.fromisoformat(published_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except (ValueError, TypeError):
        # If we can't parse the date, include the article rather than drop it
        return True


def _filter_and_cap(articles: list[dict], cutoff: datetime) -> list[dict]:
    filtered = [a for a in articles if _within_window(a["published_date"], cutoff)]
    return filtered[:_MAX_ARTICLES]


async def _fetch_newsapi(company: str, client: httpx.AsyncClient) -> list[dict]:
    api_key = os.environ.get("NEWSAPI_KEY", "")
    if not api_key:
        raise ValueError("NEWSAPI_KEY not set")
    params = {
        "q": company,
        "apiKey": api_key,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 100,
    }
    response = await client.get(NEWSAPI_URL, params=params, timeout=15.0)
    response.raise_for_status()
    data = response.json()
    articles = []
    for item in data.get("articles", []):
        articles.append({
            "title": item.get("title") or "",
            "published_date": _parse_date((item.get("publishedAt") or "")[:10]),
            "source_name": (item.get("source") or {}).get("name") or "",
            "url": item.get("url") or "",
            "excerpt": item.get("description") or item.get("content") or "",
        })
    return articles


async def _fetch_gdelt(query: str, client: httpx.AsyncClient) -> list[dict]:
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": 75,
        "format": "json",
        "timespan": "24months",
    }
    response = await client.get(GDELT_URL, params=params, timeout=20.0)
    response.raise_for_status()
    data = response.json()
    articles = []
    for item in (data.get("articles") or []):
        articles.append({
            "title": item.get("title") or "",
            "published_date": _parse_date(item.get("seendate") or item.get("publisheddate") or ""),
            "source_name": item.get("domain") or "",
            "url": item.get("url") or "",
            "excerpt": item.get("title") or "",  # GDELT doesn't provide excerpts
        })
    return articles


async def _fetch_google_news_rss(company: str, client: httpx.AsyncClient) -> list[dict]:
    params = {"q": f"{company} sustainability environment", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    response = await client.get(
        GOOGLE_NEWS_RSS_URL, params=params, timeout=15.0, headers=_HEADERS
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    articles = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub_date_raw = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
        description = (item.findtext("description") or "").strip()

        articles.append({
            "title": title,
            "published_date": _parse_date(pub_date_raw),
            "source_name": source_name,
            "url": link,
            "excerpt": description or title,
        })
    return articles


def _build_queries(company: str, state: str | None) -> tuple[str, str]:
    """Return (api_query, rss_query) tuned for state-scoped or global search.

    When a state is provided the queries explicitly include the state name so
    news retrieval is scoped to that Indian state.
    """
    if state:
        api_query = f'"{company}" "{state}"'
        rss_query = f"{company} {state} sustainability environment ESG"
    else:
        api_query = f'"{company}"'
        rss_query = f"{company} sustainability environment ESG India"
    return api_query, rss_query


def _extract_state(location: str | None) -> str | None:
    """Pull the state component out of a 'City, State' or 'City, State, Country' string."""
    if not location or not location.strip():
        return None
    parts = [p.strip() for p in location.split(",")]
    # parts[1] is the state in both 2-part and 3-part formats
    return parts[1] if len(parts) >= 2 else None


async def fetch_news(company: str, audit_timestamp: str | None = None, location: str | None = None) -> dict:
    """Fetch recent news articles for a company, scoped to an Indian state when provided.

    Query strategy:
      - With location  → primary query includes state name (e.g. '"Infosys" "Karnataka"')
      - Without location → global query with India context

    Tries NewsAPI → GDELT → Google News RSS in order.
    Returns: {company, articles, error}
    """
    audit_dt = _parse_audit_timestamp(audit_timestamp)
    cutoff = _cutoff_date(audit_dt)
    errors: list[str] = []

    state = _extract_state(location)
    api_query, rss_query = _build_queries(company, state)

    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        # 1. NewsAPI
        try:
            raw = await _fetch_newsapi(api_query, client)
            articles = _filter_and_cap(raw, cutoff)
            if articles:
                return {"company": company, "articles": articles, "error": None}
            errors.append("NewsAPI: returned 0 articles after filtering")
        except Exception as exc:
            errors.append(f"NewsAPI: {exc}")

        # 2. GDELT — build a state-aware GDELT query
        try:
            gdelt_query = api_query + ' sustainability OR environment OR emissions OR ESG'
            raw = await _fetch_gdelt(gdelt_query, client)
            articles = _filter_and_cap(raw, cutoff)
            if articles:
                return {"company": company, "articles": articles, "error": None}
            errors.append("GDELT: returned 0 articles after filtering")
        except Exception as exc:
            errors.append(f"GDELT: {exc}")

        # 3. Google News RSS
        try:
            raw = await _fetch_google_news_rss(rss_query, client)
            articles = _filter_and_cap(raw, cutoff)
            if articles:
                return {"company": company, "articles": articles, "error": None}
            errors.append("Google News RSS: returned 0 articles after filtering")
        except Exception as exc:
            errors.append(f"Google News RSS: {exc}")

        # 4. Fallback: if state-scoped search returned nothing, retry without state
        if state and not articles:
            fallback_api, fallback_rss = _build_queries(company, None)
            try:
                raw = await _fetch_google_news_rss(fallback_rss, client)
                articles = _filter_and_cap(raw, cutoff)
                if articles:
                    return {"company": company, "articles": articles, "error": None}
            except Exception as exc:
                errors.append(f"Google News RSS (fallback): {exc}")

    return {"company": company, "articles": [], "error": "; ".join(errors)}
