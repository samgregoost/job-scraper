import logging
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"


class RemoteOKAPIScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "remoteok_api"

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

            # First item is metadata, skip it. Limit to max_results.
            items = data[1:] if len(data) > 1 else []
            items = items[:self.max_results]

            for item in items:
                if not isinstance(item, dict):
                    continue

                salary_min = item.get("salary_min")
                salary_max = item.get("salary_max")

                tags = item.get("tags", [])
                description = item.get("description", "")
                if tags:
                    description += "\n\nTags: " + ", ".join(tags)

                location = item.get("location", "Remote") or "Remote"

                jobs.append(
                    Job(
                        source=self.name,
                        external_id=str(item.get("id", "")),
                        title=item.get("position", ""),
                        company=item.get("company", ""),
                        location=location,
                        url=item.get("url", f"https://remoteok.com/l/{item.get('id', '')}"),
                        description=description,
                        salary_min=float(salary_min) if salary_min else None,
                        salary_max=float(salary_max) if salary_max else None,
                        salary_currency="USD" if salary_min else None,
                        remote=True,
                        posted_date=_parse_epoch(item.get("epoch")),
                        scraped_at=datetime.now(),
                    )
                )

            logger.info(f"RemoteOK API: fetched {len(items)} jobs")

        except Exception as e:
            logger.error(f"RemoteOK API scrape failed: {e}")

        return jobs


def _parse_epoch(epoch) -> datetime | None:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(int(epoch))
    except (ValueError, TypeError, OSError):
        return None
