"""Location lookup: find Indian state-level company locations using Groq LLM."""
from __future__ import annotations

import json
import os
import re

from groq import AsyncGroq

_GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Canonical state names — used for normalisation only, NOT as a strict filter
_CANONICAL_STATES: dict[str, str] = {
    "andhra pradesh": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "odisha": "Odisha",
    "orissa": "Odisha",          # common alternate spelling
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamil nadu": "Tamil Nadu",
    "tamilnadu": "Tamil Nadu",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "up": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "west bengal": "West Bengal",
    # Union Territories
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "chandigarh": "Chandigarh",
    "dadra and nagar haveli": "Dadra and Nagar Haveli",
    "daman and diu": "Daman and Diu",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "ncr": "Delhi",
    "jammu and kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
    "puducherry": "Puducherry",
    "pondicherry": "Puducherry",
}


def _normalise_state(raw: str) -> str | None:
    """Map a raw LLM state string to a canonical Indian state name.

    Returns None only if the string is clearly not an Indian state
    (e.g. a country name like 'USA' or 'China').
    """
    key = raw.strip().lower()
    key = re.sub(r"\s+", " ", key)

    # Direct match
    if key in _CANONICAL_STATES:
        return _CANONICAL_STATES[key]

    # Partial match — e.g. "Tamil Nadu, India" or "State of Karnataka"
    for k, v in _CANONICAL_STATES.items():
        if k in key:
            return v

    # If it looks like a non-Indian country/region, skip it
    non_india = {"usa", "united states", "uk", "united kingdom", "china", "singapore",
                 "australia", "canada", "germany", "france", "japan", "uae", "dubai",
                 "global", "worldwide", "international"}
    if key in non_india:
        return None

    # Unknown but plausible Indian state — keep it as-is with title case
    # This handles new UTs or LLM variations we haven't mapped
    return raw.strip().title()


async def get_company_locations(company: str) -> list[dict]:
    """Return Indian state-level locations where the company operates.

    Each entry: {"city": "Chennai", "state": "Tamil Nadu", "country": "India"}
    Deduplicates by state. Returns empty list on failure.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    client = AsyncGroq(api_key=api_key)

    system_prompt = (
        "You are a business intelligence assistant specialising in Indian corporate geography. "
        "Return ONLY valid JSON with a key 'locations' containing an array. "
        "Each item: {\"city\": \"<primary city>\", \"state\": \"<full Indian state name>\", \"country\": \"India\"}. "
        "Use full official state names (e.g. 'Tamil Nadu', not 'TN'). "
        "Only include Indian states and union territories."
    )

    user_prompt = (
        f'List every Indian state or union territory where "{company}" has any presence '
        f'(offices, factories, warehouses, stores, data centres, service centres, etc.). '
        f'For each state include the primary/largest city. '
        f'Return ONLY this JSON (no explanation): '
        f'{{"locations":[{{"city":"string","state":"string","country":"India"}}]}}'
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        # Accept any list-valued key the LLM might use
        locations: list = []
        for key in ("locations", "offices", "states", "data"):
            val = data.get(key)
            if isinstance(val, list):
                locations = val
                break
        if not locations:
            # Last resort: grab the first list value in the response
            for v in data.values():
                if isinstance(v, list):
                    locations = v
                    break

        seen_states: set[str] = set()
        result: list[dict] = []

        for loc in locations:
            if not isinstance(loc, dict):
                continue
            city = (loc.get("city") or "").strip()
            raw_state = (loc.get("state") or "").strip()

            if not raw_state:
                continue

            canonical = _normalise_state(raw_state)
            if canonical is None:
                continue  # non-Indian region, skip

            state_key = canonical.lower()
            if state_key not in seen_states:
                seen_states.add(state_key)
                result.append({"city": city, "state": canonical, "country": "India"})

        result.sort(key=lambda x: x["state"])
        return result[:30]

    except Exception as e:
        # Return the error as a special marker so the API can surface it
        raise RuntimeError(f"Location lookup failed: {e}") from e
