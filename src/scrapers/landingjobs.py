import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://landing.jobs/api/v1/jobs"


class LandingJobsScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "landingjobs"

    def scrape(self) -> list[Job]:
        jobs = []
        max_pages = max(1, self.max_results // 50)

        for page in range(1, max_pages + 1):
            if len(jobs) >= self.max_results:
                break
            try:
                resp = requests.get(
                    API_URL,
                    params={"limit": 50, "page": page},
                    timeout=30,
                    headers={"User-Agent": "JobScraper/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

                items = data if isinstance(data, list) else data.get("results", data.get("jobs", []))

                if not items:
                    break

                for item in items:
                    salary_min = item.get("salary_from") or item.get("salary_min")
                    salary_max = item.get("salary_to") or item.get("salary_max")
                    currency = item.get("currency_code", "EUR")

                    city = item.get("city", "")
                    country = item.get("country", "")
                    location = ", ".join(filter(None, [city, country])) or "Europe"

                    remote = item.get("remote", False) or "remote" in str(item.get("work_type", "")).lower()

                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=str(item.get("id", "")),
                            title=item.get("title", ""),
                            company=item.get("company_name", item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else ""),
                            location=location,
                            url=item.get("url", item.get("landing_url", f"https://landing.jobs/job/{item.get('id', '')}")),
                            description=item.get("description", "") or item.get("main_requirements", ""),
                            salary_min=float(salary_min) if salary_min else None,
                            salary_max=float(salary_max) if salary_max else None,
                            salary_currency=currency if salary_min else None,
                            remote=remote,
                            posted_date=_parse_date(item.get("published_at") or item.get("created_at")),
                            scraped_at=datetime.now(),
                        )
                    )

                logger.info(f"LandingJobs: fetched {len(items)} jobs (page {page})")
                time.sleep(1)

            except Exception as e:
                logger.error(f"LandingJobs scrape failed (page {page}): {e}")
                break

        return jobs


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
