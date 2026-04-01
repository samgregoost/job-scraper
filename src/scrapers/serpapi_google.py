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

        max_offset = max(10, self.max_results)
        for query in queries:
            if len(jobs) >= self.max_results:
                break
            location = locations[0] if locations else ""
            for start in range(0, max_offset, 10):
                try:
                    params = {
                        "engine": "google_jobs",
                        "q": query,
                        "api_key": api_key,
                        "start": start,
                    }
                    if location and location.lower() != "remote":
                        params["location"] = location

                    resp = requests.get(API_URL, params=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("jobs_results", [])

                    if not results:
                        break

                    for item in results:
                        ext_id = item.get("job_id", item.get("title", "") + item.get("company_name", ""))
                        description = item.get("description", "")

                        salary_min, salary_max = None, None

                        jobs.append(
                            Job(
                                source=self.name,
                                external_id=ext_id,
                                title=item.get("title", ""),
                                company=item.get("company_name", ""),
                                location=item.get("location", ""),
                                url=item.get("share_link", item.get("related_links", [{}])[0].get("link", "") if item.get("related_links") else ""),
                                description=description,
                                salary_min=salary_min,
                                salary_max=salary_max,
                                remote="remote" in item.get("location", "").lower()
                                or "remote" in description.lower()[:200],
                                posted_date=None,
                                scraped_at=datetime.now(),
                            )
                        )

                    logger.info(f"SerpAPI: fetched {len(results)} jobs for '{query}' (start={start})")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"SerpAPI scrape failed for '{query}' start={start}: {e}")
                    break

        return jobs
