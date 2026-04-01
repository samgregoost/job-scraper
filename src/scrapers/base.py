from abc import ABC, abstractmethod
from src.models import Job

DEFAULT_MAX_RESULTS = 50


class BaseScraper(ABC):
    def __init__(self, config: dict, preferences: dict):
        self.config = config
        self.preferences = preferences

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def scrape(self) -> list[Job]:
        ...

    @property
    def max_results(self) -> int:
        """Max jobs to fetch from this source. Configurable per-scraper via config."""
        return int(self.config.get("max_results", DEFAULT_MAX_RESULTS))

    def _build_search_queries(self) -> list[str]:
        return self.preferences.get("job_titles", [])
