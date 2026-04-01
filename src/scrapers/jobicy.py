import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicyScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "jobicy"

    def scrape(self) -> list[Job]:
        jobs = []
        queries = self._build_search_queries()

        per_query = min(self.max_results, 50)
        for query in queries:
            if len(jobs) >= self.max_results:
                break
            try:
                resp = requests.get(
                    API_URL,
                    params={"count": per_query, "tag": query},
                    timeout=30,
                    headers={"User-Agent": "JobScraper/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("jobs", []):
                    salary_min, salary_max, currency = _parse_salary(item)
                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=str(item.get("id", "")),
                            title=item.get("jobTitle", ""),
                            company=item.get("companyName", ""),
                            location=item.get("jobGeo", "Remote"),
                            url=item.get("url", ""),
                            description=item.get("jobDescription", ""),
                            salary_min=salary_min,
                            salary_max=salary_max,
                            salary_currency=currency,
                            remote=True,
                            posted_date=_parse_date(item.get("pubDate")),
                            scraped_at=datetime.now(),
                        )
                    )
                logger.info(f"Jobicy: fetched {len(data.get('jobs', []))} jobs for '{query}'")
            except Exception as e:
                logger.error(f"Jobicy scrape failed for '{query}': {e}")
            time.sleep(1)

        return _dedupe(jobs)


def _parse_salary(item) -> tuple:
    sal_min = item.get("annualSalaryMin")
    sal_max = item.get("annualSalaryMax")
    currency = item.get("salaryCurrency", "USD")
    try:
        sal_min = float(sal_min) if sal_min else None
        sal_max = float(sal_max) if sal_max else None
    except (ValueError, TypeError):
        sal_min, sal_max = None, None
    return sal_min, sal_max, currency


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception:
            return None


def _dedupe(jobs: list[Job]) -> list[Job]:
    seen = set()
    unique = []
    for job in jobs:
        if job.external_id not in seen:
            seen.add(job.external_id)
            unique.append(job)
    return unique
