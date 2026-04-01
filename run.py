#!/usr/bin/env python3
"""
Job Scraper - Main Entry Point

Usage:
    python run.py --once          Run the pipeline once and exit
    python run.py --daemon        Run on daily schedule (keeps process alive)
    python run.py --test-email    Send a test digest with dummy data
    python run.py --reprocess     Re-score all jobs in database
"""

import argparse
import logging
import sys
import time
from datetime import datetime

import schedule

from src.config_loader import load_config
from src.cv_reader import read_cv
from src.database import Database
from src.matcher import score_jobs
from src.llm_matcher import llm_score_jobs
from src.email_digest import send_digest
from src.scrapers.registry import get_enabled_scrapers
from src.models import Job, ScoredJob

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("job_scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("job_scraper")


def run_pipeline(config: dict | None = None):
    """Execute the full scrape -> match -> notify pipeline."""
    start = datetime.now()
    logger.info("=" * 50)
    logger.info("Starting job scraper pipeline")

    if config is None:
        config = load_config()

    # 1. Read CV
    cv_text = read_cv()
    if not cv_text:
        logger.warning("No CV found. Matching will rely on config preferences only.")
        cv_text = " ".join(config["preferences"].get("skills", []))

    # 2. Scrape jobs from all enabled sources
    scrapers = get_enabled_scrapers(config)
    if not scrapers:
        logger.error("No scrapers enabled! Check config.yaml")
        return

    all_jobs: list[Job] = []
    for scraper in scrapers:
        try:
            logger.info(f"Running scraper: {scraper.name}")
            jobs = scraper.scrape()
            all_jobs.extend(jobs)
            logger.info(f"  -> {len(jobs)} jobs from {scraper.name}")
        except Exception as e:
            logger.error(f"Scraper {scraper.name} failed: {e}", exc_info=True)

    logger.info(f"Total jobs scraped: {len(all_jobs)}")

    if not all_jobs:
        logger.warning("No jobs scraped from any source. Check your internet connection and scraper configs.")
        return

    # 3. Store in database (dedup)
    db = Database(config["database"]["path"])
    db.clear_all_scores()
    new_jobs = db.insert_jobs(all_jobs)
    logger.info(f"New jobs (not seen before): {len(new_jobs)}")

    # 4. Score ALL jobs (new + existing) with current preferences
    all_db_jobs = _load_all_jobs(db)
    if all_db_jobs:
        # Step 1: Rule-based fast scoring on ALL jobs in DB
        logger.info(f"Scoring all {len(all_db_jobs)} jobs with current preferences...")
        scored = score_jobs(
            all_db_jobs,
            cv_text,
            config["preferences"],
            config["scoring"],
            search_statement=config.get("job_search_statement", ""),
        )
        db.update_scores(scored)

        # Step 2: LLM deep scoring on top candidates (if enabled)
        llm_config = config.get("llm", {})
        if llm_config.get("enabled") and llm_config.get("api_key"):
            top_n = llm_config.get("top_n", 30)
            # Take top rule-based matches for LLM analysis
            top_candidates = [s.job for s in scored[:top_n]]
            logger.info(f"Running LLM scoring on top {len(top_candidates)} candidates...")

            llm_scored = llm_score_jobs(
                top_candidates,
                cv_text,
                config["preferences"],
                config["scoring"],
                llm_config,
                search_statement=config.get("job_search_statement", ""),
            )
            if llm_scored:
                db.update_scores(llm_scored)
                logger.info(f"LLM re-scored {len(llm_scored)} jobs")

        # 5. Filter matches and send digest
        min_score = config["scoring"]["thresholds"].get("worth_a_look", 40)
        matches = db.get_todays_matches(min_score=min_score)

        if matches:
            send_digest(
                matches,
                config["email"],
                total_scraped=len(all_jobs),
                total_new=len(new_jobs),
            )
        else:
            logger.info("No matches above threshold today.")
    else:
        logger.info("No jobs in database to score.")

    db.close()
    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Pipeline completed in {elapsed:.1f}s")
    logger.info("=" * 50)


def _load_all_jobs(db: Database) -> list[Job]:
    """Load all jobs from the database as Job objects."""
    rows = db.conn.execute("SELECT * FROM jobs ORDER BY scraped_at DESC").fetchall()
    jobs = []
    for row in rows:
        jobs.append(
            Job(
                source=row["source"],
                external_id=row["external_id"],
                title=row["title"],
                company=row["company"],
                location=row["location"],
                url=row["url"],
                description=row["description"],
                salary_min=row["salary_min"],
                salary_max=row["salary_max"],
                salary_currency=row["salary_currency"],
                remote=bool(row["remote"]),
                posted_date=None,
                scraped_at=datetime.now(),
            )
        )
    return jobs


def run_reprocess(config: dict):
    """Re-score all unscored jobs in the database."""
    cv_text = read_cv()
    if not cv_text:
        cv_text = " ".join(config["preferences"].get("skills", []))

    db = Database(config["database"]["path"])
    unscored = db.get_all_unscored()

    if not unscored:
        logger.info("No unscored jobs found.")
        db.close()
        return

    # Convert DB rows back to Job objects
    jobs = []
    for row in unscored:
        jobs.append(
            Job(
                source=row["source"],
                external_id=row["external_id"],
                title=row["title"],
                company=row["company"],
                location=row["location"],
                url=row["url"],
                description=row["description"],
                salary_min=row["salary_min"],
                salary_max=row["salary_max"],
                salary_currency=row["salary_currency"],
                remote=bool(row["remote"]),
                posted_date=None,
                scraped_at=datetime.now(),
            )
        )

    scored = score_jobs(jobs, cv_text, config["preferences"], config["scoring"],
                        search_statement=config.get("job_search_statement", ""))
    db.update_scores(scored)
    db.close()
    logger.info(f"Re-scored {len(scored)} jobs")


def send_test_email(config: dict):
    """Send a test email with sample data."""
    sample_matches = [
        {
            "title": "Senior Python Developer",
            "company": "TechCorp",
            "location": "Remote",
            "url": "https://example.com/job/1",
            "score": 92.5,
            "category": "Perfect Match",
            "skill_matches": "Python,Django,REST APIs",
            "salary_min": 90000,
            "salary_max": 120000,
            "salary_currency": "USD",
        },
        {
            "title": "Backend Engineer",
            "company": "StartupXYZ",
            "location": "London, UK",
            "url": "https://example.com/job/2",
            "score": 74.3,
            "category": "Strong Match",
            "skill_matches": "Python,Docker,PostgreSQL",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
        },
        {
            "title": "Full Stack Developer",
            "company": "BigCo",
            "location": "Berlin, Germany",
            "url": "https://example.com/job/3",
            "score": 55.0,
            "category": "Worth a Look",
            "skill_matches": "JavaScript,REST APIs",
            "salary_min": 65000,
            "salary_max": 85000,
            "salary_currency": "EUR",
        },
    ]

    send_digest(
        sample_matches,
        config["email"],
        total_scraped=150,
        total_new=42,
    )
    logger.info("Test email sent (or printed to console if email is disabled)")


def main():
    parser = argparse.ArgumentParser(description="Job Scraper & Matcher")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Run pipeline once and exit")
    group.add_argument("--daemon", action="store_true", help="Run on daily schedule")
    group.add_argument("--test-email", action="store_true", help="Send test digest email")
    group.add_argument("--reprocess", action="store_true", help="Re-score all jobs in DB")

    args = parser.parse_args()
    config = load_config()

    if args.once:
        run_pipeline(config)

    elif args.daemon:
        run_time = config.get("schedule", {}).get("run_time", "08:00")
        logger.info(f"Scheduling daily run at {run_time}")

        schedule.every().day.at(run_time).do(run_pipeline, config=config)

        # Also run immediately on start
        run_pipeline(config)

        while True:
            schedule.run_pending()
            time.sleep(60)

    elif args.test_email:
        send_test_email(config)

    elif args.reprocess:
        run_reprocess(config)


if __name__ == "__main__":
    main()
