import logging
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

from src.models import Job, ScoredJob

logger = logging.getLogger(__name__)


def score_jobs(
    jobs: list[Job],
    cv_text: str,
    preferences: dict,
    scoring_config: dict,
    search_statement: str = "",
) -> list[ScoredJob]:
    if not jobs:
        return []

    weights = scoring_config.get("weights", {})
    thresholds = scoring_config.get("thresholds", {})

    # Combine CV text with search statement for TF-IDF
    combined_cv = cv_text
    if search_statement:
        combined_cv = f"{search_statement}\n\n{cv_text}"

    # Pre-compute TF-IDF for CV + all job descriptions
    corpus = [combined_cv] + [job.description for job in jobs]
    tfidf = TfidfVectorizer(
        stop_words="english", max_features=5000, ngram_range=(1, 2)
    )

    try:
        tfidf_matrix = tfidf.fit_transform(corpus)
        cv_vector = tfidf_matrix[0:1]
        job_vectors = tfidf_matrix[1:]
        tfidf_scores = cosine_similarity(cv_vector, job_vectors).flatten()
    except Exception as e:
        logger.warning(f"TF-IDF failed, falling back to keyword only: {e}")
        tfidf_scores = [0.0] * len(jobs)

    user_skills = [s.lower() for s in preferences.get("skills", [])]
    user_titles = preferences.get("job_titles", [])
    user_locations = [loc.lower() for loc in preferences.get("locations", [])]
    remote_pref = preferences.get("remote_preference", "remote_preferred")
    exp_level = preferences.get("experience_level", "mid")
    salary_range = preferences.get("salary_range", {})

    scored = []
    for i, job in enumerate(jobs):
        has_description = len(job.description.strip()) > 50

        skills_score, matched_skills = _skills_score(
            job.description, user_skills, tfidf_scores[i]
        )
        title_score = _title_score(job.title, user_titles)
        loc_score = _location_score(job.location, job.remote, user_locations, remote_pref)
        sal_score = _salary_score(job.salary_min, job.salary_max, salary_range)
        exp_score = _experience_score(job.description, exp_level)

        if has_description:
            # Normal weights
            composite = (
                weights.get("skills_match", 0.35) * skills_score
                + weights.get("title_match", 0.25) * title_score
                + weights.get("location_match", 0.20) * loc_score
                + weights.get("salary_match", 0.10) * sal_score
                + weights.get("experience_match", 0.10) * exp_score
            )
        else:
            # No description: heavily boost title and location, give neutral for unknowns
            skills_score = 50.0  # neutral instead of 0
            exp_score = 50.0     # neutral instead of 0
            # Also check if any skills appear in the title itself
            title_lower = job.title.lower()
            title_skill_matches = [s for s in user_skills if s in title_lower]
            if title_skill_matches:
                skills_score = min(50 + len(title_skill_matches) * 15, 90)
                matched_skills = title_skill_matches

            composite = (
                0.15 * skills_score       # reduced since no description
                + 0.45 * title_score      # title is primary signal
                + 0.30 * loc_score        # location is secondary
                + 0.05 * sal_score
                + 0.05 * exp_score
            )

        final_score = min(round(composite, 1), 100.0)
        category = _categorize(final_score, thresholds)

        scored.append(
            ScoredJob(
                job=job,
                score=final_score,
                category=category,
                skill_matches=matched_skills,
                title_similarity=title_score,
                location_match=loc_score > 50,
                salary_in_range=sal_score > 50 if job.salary_min else None,
            )
        )

    scored.sort(key=lambda s: s.score, reverse=True)
    logger.info(f"Scored {len(scored)} jobs. Top score: {scored[0].score if scored else 0}")
    return scored


def _skills_score(
    description: str, user_skills: list[str], tfidf_score: float
) -> tuple[float, list[str]]:
    desc_lower = description.lower()
    matched = [skill for skill in user_skills if skill in desc_lower]

    if not user_skills:
        keyword_ratio = 0.0
    else:
        keyword_ratio = len(matched) / len(user_skills)

    # Blend TF-IDF similarity with exact keyword matching
    blended = 0.6 * (tfidf_score * 100) + 0.4 * (keyword_ratio * 100)
    return min(blended, 100.0), matched


def _title_score(job_title: str, user_titles: list[str]) -> float:
    if not user_titles:
        return 50.0

    best = max(
        fuzz.token_sort_ratio(job_title.lower(), ut.lower()) for ut in user_titles
    )
    return best


def _location_score(
    job_location: str, is_remote: bool, user_locations: list[str], remote_pref: str
) -> float:
    if is_remote or "remote" in job_location.lower():
        if remote_pref in ("remote_only", "remote_preferred"):
            return 100.0
        return 70.0  # onsite_ok but remote is fine

    # Check if job location matches any preferred location
    job_loc_lower = job_location.lower()
    for loc in user_locations:
        if loc == "remote":
            continue
        if loc in job_loc_lower or job_loc_lower in loc:
            return 100.0
        if fuzz.partial_ratio(loc, job_loc_lower) > 80:
            return 85.0

    if remote_pref == "remote_only":
        return 0.0
    if remote_pref == "onsite_ok":
        return 40.0
    return 20.0  # remote_preferred but job is onsite elsewhere


def _salary_score(
    job_min: float | None,
    job_max: float | None,
    salary_range: dict,
) -> float:
    user_min = salary_range.get("min")
    user_max = salary_range.get("max")

    # If no salary data from job, give neutral score
    if job_min is None and job_max is None:
        return 50.0
    if not user_min and not user_max:
        return 50.0

    job_lo = job_min or 0
    job_hi = job_max or job_lo

    # Calculate overlap
    overlap_lo = max(job_lo, user_min or 0)
    overlap_hi = min(job_hi, user_max or float("inf"))

    if overlap_lo <= overlap_hi:
        # There is overlap
        overlap_range = overlap_hi - overlap_lo
        total_range = max(job_hi - job_lo, 1)
        return min(60 + 40 * (overlap_range / total_range), 100.0)

    # No overlap — how far off?
    if job_hi < (user_min or 0):
        gap = (user_min or 0) - job_hi
        penalty = min(gap / (user_min or 1) * 100, 100)
        return max(0, 30 - penalty)
    return 20.0


def _experience_score(description: str, user_level: str) -> float:
    desc_lower = description.lower()

    level_keywords = {
        "junior": ["junior", "entry level", "entry-level", "graduate", "0-2 years", "1-2 years", "0-1 years"],
        "mid": ["mid level", "mid-level", "intermediate", "2-5 years", "3-5 years", "2+ years", "3+ years"],
        "senior": ["senior", "staff", "5+ years", "5-10 years", "7+ years", "experienced"],
        "lead": ["lead", "principal", "architect", "manager", "8+ years", "10+ years", "head of"],
    }

    # Check for years of experience pattern
    years_match = re.search(r"(\d+)\+?\s*(?:years?|yrs?)", desc_lower)
    detected_years = int(years_match.group(1)) if years_match else None

    level_ranges = {"junior": (0, 2), "mid": (2, 5), "senior": (5, 10), "lead": (8, 15)}
    user_range = level_ranges.get(user_level, (2, 5))

    # Score based on years if detected
    if detected_years is not None:
        if user_range[0] <= detected_years <= user_range[1]:
            return 100.0
        distance = min(abs(detected_years - user_range[0]), abs(detected_years - user_range[1]))
        return max(0, 100 - distance * 20)

    # Fallback: keyword matching
    user_keywords = level_keywords.get(user_level, [])
    for kw in user_keywords:
        if kw in desc_lower:
            return 90.0

    # Check for mismatched levels
    for level, keywords in level_keywords.items():
        if level != user_level:
            for kw in keywords:
                if kw in desc_lower:
                    distance = abs(
                        list(level_keywords.keys()).index(level)
                        - list(level_keywords.keys()).index(user_level)
                    )
                    return max(0, 80 - distance * 30)

    return 50.0  # No experience info found, neutral


def _categorize(score: float, thresholds: dict) -> str:
    if score >= thresholds.get("perfect_match", 80):
        return "Perfect Match"
    if score >= thresholds.get("strong_match", 60):
        return "Strong Match"
    if score >= thresholds.get("worth_a_look", 40):
        return "Worth a Look"
    return "Weak Match"
