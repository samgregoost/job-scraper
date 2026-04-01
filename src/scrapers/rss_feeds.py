import logging
import hashlib
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class RSSFeedScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "rss_feeds"

    def scrape(self) -> list[Job]:
        jobs = []
        feeds = self.config.get("feeds", [])

        for feed_info in feeds:
            feed_name = feed_info.get("name", "Unknown")
            feed_url = feed_info.get("url", "")

            if not feed_url:
                continue

            try:
                feed = feedparser.parse(feed_url)

                if feed.bozo and not feed.entries:
                    logger.warning(f"RSS feed '{feed_name}' returned no entries: {feed.bozo_exception}")
                    continue

                for entry in feed.entries:
                    ext_id = entry.get("id") or entry.get("link") or ""
                    if not ext_id:
                        continue

                    hashed_id = hashlib.md5(ext_id.encode()).hexdigest()

                    # Try content:encoded first, then summary, then description
                    description = ""
                    if entry.get("content"):
                        description = entry["content"][0].get("value", "")
                    if not description:
                        description = entry.get("summary", "") or entry.get("description", "")

                    title = entry.get("title", "")
                    company = _extract_company(title, entry)
                    link = entry.get("link", "")

                    # If description is too short, try fetching from the page
                    if len(description.strip()) < 50 and link:
                        description = _fetch_page_description(link)

                    jobs.append(
                        Job(
                            source=f"rss_{feed_name.lower().replace(' ', '_')}",
                            external_id=hashed_id,
                            title=title,
                            company=company,
                            location="Remote",
                            url=link,
                            description=description,
                            remote=True,
                            posted_date=_parse_published(entry),
                            scraped_at=datetime.now(),
                        )
                    )

                logger.info(f"RSS '{feed_name}': fetched {len(feed.entries)} entries")

            except Exception as e:
                logger.error(f"RSS feed '{feed_name}' failed: {e}")

        return jobs


def _fetch_page_description(url: str) -> str:
    """Fetch job description from the actual page when RSS has no content."""
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common job description selectors
        for selector in [
            {"class_": "job-description"},
            {"class_": "listing-container"},
            {"class_": "job_description"},
            {"class_": "job-content"},
            {"class_": "entry-content"},
            {"class_": "job-details"},
            {"class_": "description"},
            {"itemprop": "description"},
        ]:
            el = soup.find(["div", "section", "article"], **selector)
            if el and len(el.get_text(strip=True)) > 50:
                return el.get_text(separator="\n", strip=True)

        # Fallback: try meta description
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"]

        return ""
    except Exception:
        return ""


def _extract_company(title: str, entry) -> str:
    # Many RSS feeds put "Company: Title" or "Title at Company"
    if " at " in title:
        parts = title.rsplit(" at ", 1)
        if len(parts) == 2:
            return parts[1].strip()
    if ": " in title:
        parts = title.split(": ", 1)
        if len(parts) == 2:
            return parts[0].strip()
    # Try author field
    return entry.get("author", "")


def _parse_published(entry) -> datetime | None:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        try:
            from time import mktime
            return datetime.fromtimestamp(mktime(published))
        except (TypeError, ValueError, OverflowError):
            pass
    return None
