from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Job:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    remote: bool = False
    posted_date: datetime | None = None
    scraped_at: datetime = field(default_factory=datetime.now)


@dataclass
class ScoredJob:
    job: Job
    score: float  # 0-100
    category: str  # "Perfect Match", "Strong Match", "Worth a Look", "Weak Match"
    skill_matches: list[str] = field(default_factory=list)
    title_similarity: float = 0.0
    location_match: bool = False
    salary_in_range: bool | None = None
    llm_reasoning: str = ""  # Claude's explanation for the score
