import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://serpapi.com/search.json"


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
        locations = self.preferences.get("locations", [""])

        per_query_limit = max(10, self.max_results // max(len(queries), 1))
        for query in queries:
            if len(jobs) >= self.max_results:
                break
            location = locations[0] if locations else ""
            next_page_token = None
            query_start = len(jobs)

            for page in range(max(1, per_query_limit // 10)):
                if len(jobs) - query_start >= per_query_limit:
                    break
                try:
                    params = {
                        "engine": "google_jobs",
                        "q": query,
                        "api_key": api_key,
                    }
                    if location and location.lower() != "remote":
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

                    logger.info(f"SerpAPI: fetched {len(results)} jobs for '{query}' (page {page + 1})")

                    # Get next page token for pagination
                    next_page_token = data.get("serpapi_pagination", {}).get("next_page_token")
                    if not next_page_token or len(jobs) >= self.max_results:
                        break

                    time.sleep(2)
                except Exception as e:
                    logger.error(f"SerpAPI scrape failed for '{query}' page {page + 1}: {e}")
                    break

        return jobs
