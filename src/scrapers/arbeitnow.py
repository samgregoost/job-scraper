import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "arbeitnow"

    def scrape(self) -> list[Job]:
        jobs = []
        page = 1
        max_pages = max(1, self.max_results // 100)

        while page <= max_pages and len(jobs) < self.max_results:
            try:
                resp = requests.get(API_URL, params={"page": page}, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", [])

                if not items:
                    break

                for item in items:
                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=item.get("slug", str(item.get("url", ""))),
                            title=item.get("title", ""),
                            company=item.get("company_name", ""),
                            location=item.get("location", ""),
                            url=item.get("url", ""),
                            description=item.get("description", ""),
                            remote=item.get("remote", False),
                            posted_date=_parse_timestamp(item.get("created_at")),
                            scraped_at=datetime.now(),
                        )
                    )

                logger.info(f"Arbeitnow: fetched {len(items)} jobs (page {page})")
                page += 1
                time.sleep(1)

            except Exception as e:
                logger.error(f"Arbeitnow scrape failed (page {page}): {e}")
                break

        return jobs


def _parse_timestamp(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts))
    except (ValueError, TypeError, OSError):
        return None
