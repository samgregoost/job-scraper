import logging
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from src.models import Job
from src.scrapers.base import BaseScraper
from src.scrapers.locations import resolve_linkedin_locations

logger = logging.getLogger(__name__)

API_URL = "https://linkedin-jobs-search.p.rapidapi.com/"


class LinkedInRapidScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "linkedin_rapid"

    def scrape(self) -> list[Job]:
        api_key = self.config.get("rapidapi_key", "")
        if not api_key:
            logger.warning("LinkedIn RapidAPI: missing rapidapi_key, skipping")
            return []

        jobs = []
        queries = self._build_search_queries()
        search_locations = resolve_linkedin_locations(
            self.preferences.get("locations", [""]),
            max_results=4,
        )

        per_query = max(10, self.max_results // max(len(queries), 1))
        per_loc = max(10, per_query // max(len(search_locations), 1))
        max_pages_per_loc = max(1, per_loc // 10)

        for query in queries:
            if len(jobs) >= self.max_results:
                break

            for location in search_locations:
                if len(jobs) >= self.max_results:
                    break

                loc_start = len(jobs)
                for page_num in range(1, max_pages_per_loc + 1):
                    if len(jobs) - loc_start >= per_loc:
                        break

                    try:
                        headers = {
                            "X-RapidAPI-Key": api_key,
                            "X-RapidAPI-Host": "linkedin-jobs-search.p.rapidapi.com",
                            "Content-Type": "application/json",
                        }
                        payload = {
                            "search_terms": query,
                            "location": location,
                            "page": str(page_num),
                        }

                        resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
                        resp.raise_for_status()
                        data = resp.json()
                        items = data if isinstance(data, list) else []

                        if not items:
                            break

                        for item in items:
                            url = item.get("linkedin_job_url_cleaned", "")
                            description = _fetch_linkedin_description(url)

                            jobs.append(
                                Job(
                                    source=self.name,
                                    external_id=item.get("job_id", url),
                                    title=item.get("job_title", ""),
                                    company=item.get("company_name", ""),
                                    location=item.get("job_location", ""),
                                    url=url,
                                    description=description,
                                    remote="remote" in item.get("job_location", "").lower(),
                                    posted_date=_parse_date(item.get("posted_date")),
                                    scraped_at=datetime.now(),
                                )
                            )

                        loc_label = location or "worldwide"
                        logger.info(f"LinkedIn: fetched {len(items)} jobs for '{query}' in {loc_label} (page {page_num})")
                        time.sleep(2)
                    except Exception as e:
                        logger.error(f"LinkedIn scrape failed for '{query}' in {location}: {e}")
                        break

        return jobs


def _fetch_linkedin_description(url: str) -> str:
    """Fetch job description from LinkedIn public job page."""
    if not url:
        return ""
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        desc_el = (
            soup.find("div", class_="show-more-less-html__markup")
            or soup.find("div", class_="description__text")
            or soup.find("section", class_="show-more-less-html")
            or soup.find("div", {"class": lambda c: c and "description" in c.lower()})
        )

        if desc_el:
            return desc_el.get_text(separator="\n", strip=True)

        return ""
    except Exception:
        return ""


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
