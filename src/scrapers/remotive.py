import logging
import time
from datetime import datetime

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "remotive"

    def scrape(self) -> list[Job]:
        jobs = []
        # Remotive search works better with single keywords, not full titles
        raw_queries = self._build_search_queries()
        queries = set()
        for q in raw_queries:
            for word in q.lower().split():
                if len(word) > 3 and word not in ("senior", "junior", "staff", "lead"):
                    queries.add(word)
        # Also add skills as search terms
        for skill in self.preferences.get("skills", []):
            if len(skill) > 2:
                queries.add(skill.lower())
        queries = list(queries)[:8]  # Cap at 8 queries to avoid rate limits

        for query in queries:
            try:
                resp = requests.get(
                    API_URL,
                    params={"search": query, "limit": 100},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("jobs", []):
                    jobs.append(
                        Job(
                            source=self.name,
                            external_id=str(item["id"]),
                            title=item.get("title", ""),
                            company=item.get("company_name", ""),
                            location=item.get("candidate_required_location", "Anywhere"),
                            url=item.get("url", ""),
                            description=item.get("description", ""),
                            salary_min=None,
                            salary_max=None,
                            salary_currency=None,
                            remote=True,
                            posted_date=_parse_date(item.get("publication_date")),
                            scraped_at=datetime.now(),
                        )
                    )
                logger.info(f"Remotive: fetched {len(data.get('jobs', []))} jobs for '{query}'")
            except Exception as e:
                logger.error(f"Remotive scrape failed for '{query}': {e}")

            time.sleep(1)

        return _dedupe(jobs)


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _dedupe(jobs: list[Job]) -> list[Job]:
    seen = set()
    unique = []
    for job in jobs:
        if job.external_id not in seen:
            seen.add(job.external_id)
            unique.append(job)
    return unique
