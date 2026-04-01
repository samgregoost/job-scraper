import logging
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://www.workingnomads.com/api/exposed_jobs/"


class WorkingNomadsScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "workingnomads"

    def scrape(self) -> list[Job]:
        jobs = []

        try:
            resp = requests.get(
                API_URL,
                timeout=30,
                headers={"User-Agent": "JobScraper/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, list):
                data = []

            for item in data:
                jobs.append(
                    Job(
                        source=self.name,
                        external_id=item.get("slug", item.get("url", "")),
                        title=item.get("title", ""),
                        company=item.get("company_name", ""),
                        location=item.get("location", "Remote") or "Remote",
                        url=item.get("url", ""),
                        description=item.get("description", ""),
                        remote=True,
                        posted_date=_parse_date(item.get("pub_date")),
                        scraped_at=datetime.now(),
                    )
                )

            logger.info(f"WorkingNomads: fetched {len(data)} jobs")

        except Exception as e:
            logger.error(f"WorkingNomads scrape failed: {e}")

        return jobs


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
