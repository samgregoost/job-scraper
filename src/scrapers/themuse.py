import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://www.themuse.com/api/public/jobs"

LEVEL_MAP = {
    "junior": "Entry Level",
    "mid": "Mid Level",
    "senior": "Senior Level",
    "lead": "Senior Level",
}


class TheMuseScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "themuse"

    def scrape(self) -> list[Job]:
        jobs = []
        level = LEVEL_MAP.get(
            self.preferences.get("experience_level", "mid"), "Mid Level"
        )

        for page in range(0, 3):
            try:
                params = {
                    "page": page,
                    "descending": "true",
                    "level": level,
                }
                api_key = self.config.get("api_key")
                if api_key:
                    params["api_key"] = api_key

                resp = requests.get(API_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("results", []):
                    locations = ", ".join(
                        loc.get("name", "") for loc in item.get("locations", [])
                    )
                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=str(item["id"]),
                            title=item.get("name", ""),
                            company=item.get("company", {}).get("name", ""),
                            location=locations or "Not specified",
                            url=item.get("refs", {}).get("landing_page", ""),
                            description=item.get("contents", ""),
                            remote="Remote" in locations,
                            posted_date=_parse_date(item.get("publication_date")),
                            scraped_at=datetime.now(),
                        )
                    )

                logger.info(f"TheMuse: fetched {len(data.get('results', []))} jobs (page {page})")
                time.sleep(1)

            except Exception as e:
                logger.error(f"TheMuse scrape failed (page {page}): {e}")
                break

        return jobs


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
