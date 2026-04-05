import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper
from src.scrapers.locations import resolve_locations

logger = logging.getLogger(__name__)

API_URL = "https://serpapi.com/search.json"

# Map vague regions to specific countries SerpAPI accepts (kept for reference)
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


def _resolve_serp_locations(raw_locations: list[str]) -> list[str]:
    """Convert user locations to SerpAPI-compatible ones (no commas)."""
    resolved = resolve_locations(raw_locations, max_results=8)
    # SerpAPI doesn't like commas — strip "London, UK" -> "London"
    return [loc.split(",")[0].strip() for loc in resolved]


class SerpApiGoogleScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "serpapi_google"

    def scrape(self) -> list[Job]:
        api_key = self.config.get("api_key", "")
        if not api_key:
            logger.warning("SerpAPI: missing api_key, skipping")
            return []

        jobs = []
        queries = self._build_search_queries()
        serp_locations = _resolve_serp_locations(self.preferences.get("locations", []))
        per_query = max(10, self.max_results // max(len(queries), 1))
        per_loc = max(10, per_query // max(len(serp_locations), 1))

        for query in queries:
            if len(jobs) >= self.max_results:
                break

            for location in serp_locations:
                if len(jobs) >= self.max_results:
                    break

                next_page_token = None
                loc_start = len(jobs)

                for page in range(max(1, per_loc // 10)):
                    if len(jobs) - loc_start >= per_loc:
                        break

                    try:
                        params = {
                            "engine": "google_jobs",
                            "q": query,
                            "api_key": api_key,
                        }
                        if location:
                            params["location"] = location
                        if next_page_token:
                            params["next_page_token"] = next_page_token

                        resp = requests.get(API_URL, params=params, timeout=30)
                        resp.raise_for_status()
                        data = resp.json()
                        results = data.get("jobs_results", [])

                        if not results:
                            break

                        for item in results:
                            ext_id = item.get("job_id", item.get("title", "") + item.get("company_name", ""))
                            description = item.get("description", "")

                            jobs.append(
                                Job(
                                    source=self.name,
                                    external_id=ext_id,
                                    title=item.get("title", ""),
                                    company=item.get("company_name", ""),
                                    location=item.get("location", ""),
                                    url=item.get("share_link", ""),
                                    description=description,
                                    remote="remote" in item.get("location", "").lower()
                                    or "remote" in description.lower()[:200],
                                    posted_date=None,
                                    scraped_at=datetime.now(),
                                )
                            )

                        loc_label = location or "worldwide"
                        logger.info(f"SerpAPI: fetched {len(results)} jobs for '{query}' in {loc_label} (page {page + 1})")

                        next_page_token = data.get("serpapi_pagination", {}).get("next_page_token")
                        if not next_page_token:
                            break

                        time.sleep(2)
                    except Exception as e:
                        logger.error(f"SerpAPI scrape failed for '{query}' in {location or 'worldwide'}: {e}")
                        break

        return jobs
