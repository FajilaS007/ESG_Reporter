"""Report_Fetcher tool: dynamic sustainability report discovery for any company."""
from __future__ import annotations

import pathlib
import re

import httpx

CACHE_DIR = pathlib.Path(__file__).parent.parent / "cache"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Search engines to find sustainability reports dynamically
# Uses Google and DuckDuckGo HTML search (no API key needed)
_SEARCH_QUERIES = [
    '{company} sustainability report 2023 2024 filetype:pdf',
    '{company} ESG report annual sustainability',
    '{company} environmental report site:{company_domain}',
    '{company} sustainability report India',  # for Indian companies
]

# Known Indian company sustainability report patterns
_INDIA_COMPANY_HINTS = {
    "tata": "tata.com",
    "infosys": "infosys.com",
    "wipro": "wipro.com",
    "reliance": "ril.com",
    "hdfc": "hdfcbank.com",
    "icici": "icicibank.com",
    "mahindra": "mahindra.com",
    "bajaj": "bajajfinserv.in",
    "adani": "adani.com",
    "itc": "itcportal.com",
    "hcl": "hcltech.com",
    "larsen": "larsentoubro.com",
    "l&t": "larsentoubro.com",
    "ongc": "ongcindia.com",
    "ntpc": "ntpc.co.in",
    "coal india": "coalindia.in",
}


def _normalize(company: str) -> str:
    return company.strip().lower().replace(" ", "_")


def _guess_domain(company: str) -> str:
    """Guess the company's website domain for targeted search."""
    normalized = company.strip().lower()
    for key, domain in _INDIA_COMPANY_HINTS.items():
        if key in normalized:
            return domain
    # Generic guess: remove spaces, add .com
    slug = re.sub(r"[^a-z0-9]", "", normalized)
    return f"{slug}.com"


async def _search_duckduckgo(query: str, client: httpx.AsyncClient) -> list[str]:
    """Search DuckDuckGo HTML and extract result URLs."""
    try:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=15.0,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        # Extract URLs from result links
        urls = re.findall(r'href="(https?://[^"]+)"', resp.text)
        # Filter out DuckDuckGo internal links
        return [u for u in urls if "duckduckgo.com" not in u][:10]
    except Exception:
        return []


async def _fetch_url_text(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch text content from a URL. Returns None on failure."""
    try:
        resp = await client.get(url, timeout=20.0, headers=_HEADERS, follow_redirects=True)
        if resp.status_code == 200 and len(resp.text) > 500:
            # Strip HTML tags for cleaner text
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:15000]  # cap at 15k chars for LLM context
    except Exception:
        pass
    return None


async def _find_report_via_search(company: str, client: httpx.AsyncClient) -> str | None:
    """Search the web for the company's sustainability report and return its text."""
    domain = _guess_domain(company)

    queries = [
        f'"{company}" sustainability report 2024 2023',
        f'"{company}" ESG annual report environmental',
        f'"{company}" sustainability report site:{domain}',
        f'"{company}" ESG report India BRSR',  # BRSR = India's mandatory ESG format
    ]

    for query in queries:
        urls = await _search_duckduckgo(query, client)
        for url in urls:
            # Prefer PDF or official sustainability pages
            if any(kw in url.lower() for kw in [
                "sustain", "esg", "environment", "annual", "report",
                "csr", "brsr", "impact", "responsibility"
            ]):
                text = await _fetch_url_text(url, client)
                if text and len(text) > 1000:
                    return text

    # Fallback: try direct company website sustainability page
    for path in ["/sustainability", "/esg", "/environment", "/csr", "/responsibility"]:
        url = f"https://{domain}{path}"
        text = await _fetch_url_text(url, client)
        if text and len(text) > 1000:
            return text

    return None


async def fetch_report(company: str) -> dict:
    """Fetch a sustainability report for any company globally.

    Priority: file cache → web search for report → company website scrape
    """
    normalized = _normalize(company)

    # 1. Cache check
    cache_file = CACHE_DIR / f"{normalized}.txt"
    if cache_file.exists():
        try:
            content = cache_file.read_text(encoding="utf-8")
            if content.strip():
                return {
                    "company": company,
                    "report_text": content,
                    "source": "cached",
                    "error": None,
                }
        except OSError:
            pass

    # 2. Dynamic web search for sustainability report
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
        report_text = await _find_report_via_search(company, client)

        if report_text:
            # Cache it for future requests
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(report_text, encoding="utf-8")
            except OSError:
                pass

            return {
                "company": company,
                "report_text": report_text,
                "source": "live",
                "error": None,
            }

    return {
        "company": company,
        "report_text": None,
        "source": None,
        "error": f"Could not find a sustainability report for '{company}'",
    }
