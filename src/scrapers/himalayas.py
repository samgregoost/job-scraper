import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://himalayas.app/jobs/api"


class HimalayasScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "himalayas"

    def scrape(self) -> list[Job]:
        jobs = []
        offset = 0
        max_pages = 3
        limit = 50

        for page in range(max_pages):
            try:
                resp = requests.get(
                    API_URL,
                    params={"limit": limit, "offset": offset},
                    timeout=30,
                    headers={"User-Agent": "JobScraper/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("jobs", [])

                if not items:
                    break

                for item in items:
                    salary_min = item.get("minSalary")
                    salary_max = item.get("maxSalary")

                    loc = item.get("locationRestrictions", "Worldwide")
                    if isinstance(loc, list):
                        loc = ", ".join(str(l) for l in loc) if loc else "Worldwide"
                    loc = loc or "Worldwide"

                    slug = item.get("slug") or item.get("companySlug", "")
                    ext_id = slug or f"{item.get('title', '')}-{item.get('companyName', '')}-{i}-{offset}"
                    company_slug = item.get("companySlug", "")
                    job_url = f"https://himalayas.app/companies/{company_slug}/jobs" if company_slug else "https://himalayas.app/jobs"

                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=ext_id,
                            title=item.get("title", ""),
                            company=item.get("companyName", ""),
                            location=loc,
                            url=job_url,
                            description=item.get("description", ""),
                            salary_min=float(salary_min) if salary_min else None,
                            salary_max=float(salary_max) if salary_max else None,
                            salary_currency=item.get("salaryCurrency", "USD") if salary_min else None,
                            remote=True,
                            posted_date=_parse_date(item.get("pubDate")),
                            scraped_at=datetime.now(),
                        )
                    )

                logger.info(f"Himalayas: fetched {len(items)} jobs (page {page + 1})")
                offset += limit
                time.sleep(1)

            except Exception as e:
                logger.error(f"Himalayas scrape failed (page {page + 1}): {e}")
                break

        return jobs


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
