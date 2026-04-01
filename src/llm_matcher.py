"""
LLM-powered job matching using Claude API.

Strategy:
1. Rule-based matcher does a fast first pass on ALL jobs (free, instant)
2. LLM deeply analyzes the top N candidates (configurable, default 30)
3. Claude returns score, reasoning, matched skills, and red flags
4. Jobs are batched (5 per API call) to minimize costs

This gives the best of both worlds: fast filtering + intelligent scoring.
"""

import json
import logging
import time

import anthropic

from src.models import Job, ScoredJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 5  # Jobs per API call
DEFAULT_TOP_N = 30  # How many top rule-based matches to send to LLM


def llm_score_jobs(
    jobs: list[Job],
    cv_text: str,
    preferences: dict,
    scoring_config: dict,
    llm_config: dict,
    search_statement: str = "",
) -> list[ScoredJob]:
    """Score jobs using Claude. Expects pre-filtered candidates."""
    api_key = llm_config.get("api_key", "")
    if not api_key:
        logger.error("LLM matching enabled but no API key provided")
        return []

    model = llm_config.get("model", "claude-haiku-4-5-20251001")
    top_n = llm_config.get("top_n", DEFAULT_TOP_N)

    # Limit to top_n
    candidates = jobs[:top_n]
    logger.info(f"LLM scoring {len(candidates)} jobs with {model}")

    client = anthropic.Anthropic(api_key=api_key)
    profile = _build_profile(cv_text, preferences, search_statement)
    thresholds = scoring_config.get("thresholds", {})

    all_scored: list[ScoredJob] = []

    # Process in batches
    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(f"LLM batch {batch_num}/{total_batches} ({len(batch)} jobs)")

        try:
            scored = _score_batch(client, model, profile, batch, thresholds)
            all_scored.extend(scored)
        except Exception as e:
            logger.error(f"LLM batch {batch_num} failed: {e}")
            # Fallback: give these jobs a neutral score
            for job in batch:
                all_scored.append(
                    ScoredJob(
                        job=job,
                        score=50.0,
                        category="Worth a Look",
                        llm_reasoning="LLM scoring failed, using default score.",
                    )
                )

        # Rate limit courtesy
        if i + BATCH_SIZE < len(candidates):
            time.sleep(0.5)

    all_scored.sort(key=lambda s: s.score, reverse=True)
    logger.info(
        f"LLM scoring complete: {len(all_scored)} jobs. "
        f"Top: {all_scored[0].score if all_scored else 0}"
    )
    return all_scored


def _build_profile(cv_text: str, preferences: dict, search_statement: str = "") -> str:
    """Build a concise candidate profile for the prompt."""
    parts = []

    # Search statement is the candidate's own voice — most important signal
    if search_statement:
        parts.append(f"=== WHAT I'M LOOKING FOR (in the candidate's own words) ===\n{search_statement}")

    if cv_text:
        # Truncate CV to save tokens
        cv_truncated = cv_text[:3000]
        parts.append(f"=== RESUME ===\n{cv_truncated}")

    parts.append(f"=== STRUCTURED PREFERENCES ===")
    parts.append(f"Desired titles: {', '.join(preferences.get('job_titles', []))}")
    parts.append(f"Key skills: {', '.join(preferences.get('skills', []))}")
    parts.append(f"Locations: {', '.join(preferences.get('locations', []))}")
    parts.append(f"Remote: {preferences.get('remote_preference', 'remote_preferred')}")
    parts.append(f"Level: {preferences.get('experience_level', 'mid')}")

    salary = preferences.get("salary_range", {})
    if salary.get("min") or salary.get("max"):
        parts.append(
            f"Salary: {salary.get('currency', 'USD')} "
            f"{salary.get('min', '?')}-{salary.get('max', '?')}"
        )

    return "\n".join(parts)


def _score_batch(
    client: anthropic.Anthropic,
    model: str,
    profile: str,
    jobs: list[Job],
    thresholds: dict,
) -> list[ScoredJob]:
    """Send a batch of jobs to Claude for scoring."""
    jobs_text = ""
    for idx, job in enumerate(jobs):
        desc = job.description[:1500]  # Truncate long descriptions
        salary_info = ""
        if job.salary_min:
            salary_info = f"\nSalary: {job.salary_currency or ''}{job.salary_min:,.0f}"
            if job.salary_max:
                salary_info += f" - {job.salary_max:,.0f}"

        jobs_text += f"""
--- JOB {idx + 1} ---
Title: {job.title}
Company: {job.company}
Location: {job.location}
Remote: {job.remote}{salary_info}
Description: {desc}
"""

    prompt = f"""You are a career matching expert. Score how well each job matches this candidate.

{profile}

{jobs_text}

For EACH job, return a JSON array with one object per job containing:
- "index": job number (1-based)
- "score": integer 0-100 (be discriminating: 90+ = dream job, 70-89 = strong fit, 50-69 = decent, 30-49 = weak, <30 = poor)
- "reasoning": 1-2 sentence explanation of the score. If the candidate wrote a "WHAT I'M LOOKING FOR" statement, reference how the job does or doesn't match their stated intent, priorities, and deal-breakers.
- "matched_skills": array of specific skills from the candidate that match this job
- "red_flags": any concerns (e.g. overqualified, wrong location, missing key skills, misaligned with what they're looking for)

IMPORTANT: The candidate's "WHAT I'M LOOKING FOR" statement (if provided) is the most important matching signal. It captures nuance that structured fields cannot — industry preference, work culture, values, deal-breakers. Weight it heavily.

Be honest and critical. Only give 80+ to jobs that genuinely align with their stated intent, skills, and preferences.

Return ONLY valid JSON array, no other text."""

    message = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Parse JSON from response
    results = _parse_llm_response(response_text, len(jobs))

    scored = []
    for idx, job in enumerate(jobs):
        result = results.get(idx + 1, {})
        score = float(result.get("score", 50))
        score = max(0, min(100, score))

        reasoning = result.get("reasoning", "")
        red_flags = result.get("red_flags", "")
        if red_flags:
            reasoning += f" Red flags: {red_flags}"

        matched = result.get("matched_skills", [])
        if isinstance(matched, str):
            matched = [s.strip() for s in matched.split(",")]

        category = _categorize(score, thresholds)

        scored.append(
            ScoredJob(
                job=job,
                score=score,
                category=category,
                skill_matches=matched,
                title_similarity=0.0,
                location_match="remote" in job.location.lower() or job.remote,
                salary_in_range=None,
                llm_reasoning=reasoning,
            )
        )

    return scored


def _parse_llm_response(text: str, expected_count: int) -> dict:
    """Parse Claude's JSON response, handling edge cases."""
    # Try to extract JSON array from response
    text = text.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return {item["index"]: item for item in data if "index" in item}
        return {}
    except json.JSONDecodeError:
        # Try to find JSON array in response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
                return {item["index"]: item for item in data if "index" in item}
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse LLM response: {text[:200]}")
        return {}


def _categorize(score: float, thresholds: dict) -> str:
    if score >= thresholds.get("perfect_match", 80):
        return "Perfect Match"
    if score >= thresholds.get("strong_match", 60):
        return "Strong Match"
    if score >= thresholds.get("worth_a_look", 40):
        return "Worth a Look"
    return "Weak Match"
