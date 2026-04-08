"""Shared location utilities for scrapers.

Maps vague regions to specific countries/cities that job APIs accept.
"""

REGION_MAP = {
    "europe": ["United Kingdom", "Germany", "France", "Netherlands", "Spain", "Italy", "Sweden", "Switzerland", "Ireland", "Poland", "Portugal", "Belgium", "Austria", "Denmark", "Norway", "Finland", "Czech Republic"],
    "asia": ["Singapore", "Japan", "India", "South Korea", "China", "Hong Kong", "Taiwan", "Thailand", "Malaysia", "Philippines", "Indonesia", "Vietnam", "Bangladesh", "Pakistan", "Sri Lanka", "Myanmar", "Cambodia"],
    "southeast asia": ["Singapore", "Thailand", "Malaysia", "Philippines", "Indonesia", "Vietnam", "Cambodia", "Myanmar", "Laos"],
    "east asia": ["Japan", "South Korea", "China", "Hong Kong", "Taiwan"],
    "south asia": ["India", "Sri Lanka", "Bangladesh", "Pakistan", "Nepal"],
    "south america": ["Brazil", "Argentina", "Colombia", "Chile", "Peru", "Ecuador", "Uruguay", "Venezuela", "Bolivia", "Paraguay"],
    "latin america": ["Mexico", "Brazil", "Argentina", "Colombia", "Chile", "Peru", "Costa Rica", "Panama", "Dominican Republic"],
    "central america": ["Mexico", "Costa Rica", "Panama", "Guatemala", "Honduras", "El Salvador"],
    "middle east": ["United Arab Emirates", "Saudi Arabia", "Qatar", "Bahrain", "Kuwait", "Oman", "Jordan", "Lebanon", "Israel", "Turkey"],
    "africa": ["South Africa", "Kenya", "Nigeria", "Egypt", "Ghana", "Morocco", "Tunisia", "Ethiopia", "Tanzania", "Rwanda", "Uganda", "Senegal"],
    "north africa": ["Egypt", "Morocco", "Tunisia", "Algeria", "Libya"],
    "west africa": ["Nigeria", "Ghana", "Senegal", "Ivory Coast"],
    "east africa": ["Kenya", "Ethiopia", "Tanzania", "Rwanda", "Uganda"],
    "oceania": ["Australia", "New Zealand"],
    "nordics": ["Sweden", "Norway", "Denmark", "Finland", "Iceland"],
    "baltics": ["Estonia", "Latvia", "Lithuania"],
    "caribbean": ["Jamaica", "Trinidad and Tobago", "Barbados", "Bahamas"],
    "worldwide": [],
    "anywhere": [],
    "global": [],
    "remote": [],
}

# Adzuna only supports these countries (verified via API)
ADZUNA_COUNTRY_MAP = {
    "United Kingdom": "gb", "Germany": "de", "France": "fr", "Netherlands": "nl",
    "Spain": "es", "Italy": "it", "Switzerland": "ch", "Austria": "at",
    "Poland": "pl", "Belgium": "be", "Singapore": "sg", "India": "in",
    "Brazil": "br", "South Africa": "za", "Australia": "au", "New Zealand": "nz",
    "United States": "us", "Canada": "ca",
}


def resolve_locations(raw_locations: list[str], max_results: int = 8) -> list[str]:
    """Convert user locations (which may include regions) to specific places."""
    result = []
    for loc in raw_locations:
        clean = loc.strip()
        lower = clean.lower()
        if lower in REGION_MAP:
            result.extend(REGION_MAP[lower])
        elif lower == "remote":
            continue
        else:
            result.append(clean)
    # Dedupe preserving order
    return list(dict.fromkeys(result))[:max_results] or [""]


def resolve_adzuna_countries(raw_locations: list[str], max_results: int = 6) -> list[str]:
    """Convert user locations to Adzuna 2-letter country codes."""
    countries = resolve_locations(raw_locations, max_results=30)
    codes = []
    for c in countries:
        # Try direct match
        if c in ADZUNA_COUNTRY_MAP:
            codes.append(ADZUNA_COUNTRY_MAP[c])
        else:
            # Try matching by splitting "London, UK" -> check "UK"
            for name, code in ADZUNA_COUNTRY_MAP.items():
                if c.lower() in name.lower() or name.lower() in c.lower():
                    codes.append(code)
                    break
    return list(dict.fromkeys(codes))[:max_results] or ["gb"]


def resolve_linkedin_locations(raw_locations: list[str], max_results: int = 6) -> list[str]:
    """Convert user locations to LinkedIn-friendly search terms."""
    result = []
    for loc in raw_locations:
        clean = loc.strip()
        lower = clean.lower()
        if lower in REGION_MAP:
            # LinkedIn handles country names fine
            result.extend(REGION_MAP[lower])
        elif lower == "remote":
            continue
        else:
            result.append(clean)
    return list(dict.fromkeys(result))[:max_results] or [""]
