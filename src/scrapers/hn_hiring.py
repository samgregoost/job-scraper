import logging
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"


class HNHiringScraper(BaseScraper):
    """Scrapes Hacker News 'Ask HN: Who is hiring?' monthly threads."""

    @property
    def name(self) -> str:
        return "hn_hiring"

    def scrape(self) -> list[Job]:
        jobs = []

        try:
            # Find the latest "Who is hiring?" thread
            resp = requests.get(
                ALGOLIA_URL,
                params={
                    "tags": "story",
                    "query": "Ask HN Who is hiring",
                    "hitsPerPage": 10,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            threads = [
                h for h in data.get("hits", [])
                if "who is hiring" in h.get("title", "").lower()
                and "ask hn" in h.get("title", "").lower()
                and "freelancer" not in h.get("title", "").lower()
            ]

            if not threads:
                logger.warning("HN Hiring: no 'Who is hiring' thread found")
                return []

            thread = threads[0]
            thread_id = thread["objectID"]
            logger.info(f"HN Hiring: found thread '{thread['title']}' (ID: {thread_id})")

            # Fetch comments (job postings)
            comments = self._fetch_comments(thread_id)
            logger.info(f"HN Hiring: fetched {len(comments)} comments")

            for comment in comments:
                job = self._parse_comment(comment)
                if job:
                    jobs.append(job)

            logger.info(f"HN Hiring: parsed {len(jobs)} job postings")

        except Exception as e:
            logger.error(f"HN Hiring scrape failed: {e}")

        return jobs

    def _fetch_comments(self, thread_id: str) -> list[dict]:
        """Fetch top-level comments from Algolia."""
        all_comments = []
        page = 0
        max_pages = 5

        while page < max_pages:
            try:
                resp = requests.get(
                    ALGOLIA_URL,
                    params={
                        "tags": f"comment,story_{thread_id}",
                        "hitsPerPage": 100,
                        "page": page,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                hits = data.get("hits", [])

                if not hits:
                    break

                # Only top-level comments (direct replies to the thread)
                top_level = [h for h in hits if h.get("parent_id") == int(thread_id)]
                all_comments.extend(top_level if top_level else hits[:20])

                page += 1
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"HN comment fetch error (page {page}): {e}")
                break

        return all_comments

    def _parse_comment(self, comment: dict) -> Job | None:
        """Parse an HN comment into a Job. Returns None if not a job posting."""
        text = comment.get("comment_text", "")
        if not text or len(text) < 50:
            return None

        # Clean HTML
        soup = BeautifulSoup(text, "html.parser")
        clean_text = soup.get_text(separator="\n")

        # First line usually has: "Company | Location | Role | ..."
        lines = clean_text.strip().split("\n")
        first_line = lines[0] if lines else ""

        parts = [p.strip() for p in first_line.split("|")]
        if len(parts) < 2:
            return None  # Probably not a job posting

        company = parts[0][:100]
        title = ""
        location = "Not specified"

        for part in parts[1:]:
            lower = part.lower()
            if any(kw in lower for kw in ["engineer", "developer", "manager", "designer", "analyst", "scientist", "devops", "sre", "hiring"]):
                title = part
            elif any(kw in lower for kw in ["remote", "sf", "nyc", "london", "berlin", "usa", "eu", "onsite"]):
                location = part

        if not title:
            title = parts[1] if len(parts) > 1 else company

        is_remote = any(kw in first_line.lower() for kw in ["remote", "anywhere"])

        # Extract URL from comment
        link = ""
        a_tag = soup.find("a")
        if a_tag and a_tag.get("href"):
            link = a_tag["href"]
        if not link:
            link = f"https://news.ycombinator.com/item?id={comment.get('objectID', '')}"

        return Job(
            source=self.name,
            external_id=comment.get("objectID", ""),
            title=title[:200],
            company=company[:100],
            location=location,
            url=link,
            description=clean_text,
            remote=is_remote,
            posted_date=_parse_date(comment.get("created_at")),
            scraped_at=datetime.now(),
        )


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
