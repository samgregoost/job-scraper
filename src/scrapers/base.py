from abc import ABC, abstractmethod
from src.models import Job


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

    def _build_search_queries(self) -> list[str]:
        return self.preferences.get("job_titles", [])
