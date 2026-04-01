import logging

from src.scrapers.base import BaseScraper
from src.scrapers.remotive import RemotiveScraper
from src.scrapers.arbeitnow import ArbeitnowScraper
from src.scrapers.themuse import TheMuseScraper
from src.scrapers.rss_feeds import RSSFeedScraper
from src.scrapers.jobicy import JobicyScraper
from src.scrapers.himalayas import HimalayasScraper
from src.scrapers.remoteok_api import RemoteOKAPIScraper
from src.scrapers.workingnomads import WorkingNomadsScraper
from src.scrapers.landingjobs import LandingJobsScraper
from src.scrapers.hn_hiring import HNHiringScraper
from src.scrapers.adzuna import AdzunaScraper
from src.scrapers.serpapi_google import SerpApiGoogleScraper
from src.scrapers.linkedin_rapid import LinkedInRapidScraper

logger = logging.getLogger(__name__)

SCRAPER_MAP: dict[str, type[BaseScraper]] = {
    # ── Free, no API key ──
    "remotive": RemotiveScraper,
    "arbeitnow": ArbeitnowScraper,
    "themuse": TheMuseScraper,
    "jobicy": JobicyScraper,
    "himalayas": HimalayasScraper,
    "remoteok_api": RemoteOKAPIScraper,
    "workingnomads": WorkingNomadsScraper,
    "landingjobs": LandingJobsScraper,
    "hn_hiring": HNHiringScraper,
    "rss_feeds": RSSFeedScraper,
    # ── Requires API key ──
    "adzuna": AdzunaScraper,
    "serpapi_google": SerpApiGoogleScraper,
    "linkedin_rapid": LinkedInRapidScraper,
}


def get_enabled_scrapers(config: dict) -> list[BaseScraper]:
    scrapers_config = config.get("scrapers", {})
    preferences = config.get("preferences", {})
    enabled = []

    for name, scraper_cls in SCRAPER_MAP.items():
        scraper_conf = scrapers_config.get(name, {})
        if scraper_conf.get("enabled", False):
            try:
                scraper = scraper_cls(config=scraper_conf, preferences=preferences)
                enabled.append(scraper)
                logger.info(f"Enabled scraper: {name}")
            except Exception as e:
                logger.error(f"Failed to init scraper '{name}': {e}")

    return enabled
