import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class AdzunaScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "adzuna"

    def scrape(self) -> list[Job]:
        app_id = self.config.get("app_id", "")
        app_key = self.config.get("app_key", "")
        country = self.config.get("country", "gb")

        if not app_id or not app_key:
            logger.warning("Adzuna: missing app_id or app_key, skipping")
            return []

        jobs = []
        queries = self._build_search_queries()

        for query in queries:
          for page in range(1, 4):  # 3 pages x 50 = up to 150 per query
            try:
                url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
                resp = requests.get(
                    url,
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": query,
                        "results_per_page": 50,
                        "content-type": "application/json",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])

                if not results:
                    break

                for item in results:
                    salary_min = item.get("salary_min")
                    salary_max = item.get("salary_max")

                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=str(item.get("id", "")),
                            title=item.get("title", ""),
                            company=item.get("company", {}).get("display_name", ""),
                            location=item.get("location", {}).get("display_name", ""),
                            url=item.get("redirect_url", ""),
                            description=item.get("description", ""),
                            salary_min=salary_min,
                            salary_max=salary_max,
                            salary_currency="GBP" if country == "gb" else "USD",
                            remote="remote" in item.get("title", "").lower()
                            or "remote" in item.get("description", "").lower(),
                            posted_date=_parse_date(item.get("created")),
                            scraped_at=datetime.now(),
                        )
                    )

                logger.info(f"Adzuna: fetched {len(results)} jobs for '{query}' (page {page})")
                time.sleep(1)
            except Exception as e:
                logger.error(f"Adzuna scrape failed for '{query}' page {page}: {e}")
                break

        return jobs


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
