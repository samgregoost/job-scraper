import os
import sqlite3
import logging
from datetime import datetime
from src.models import Job, ScoredJob

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    remote INTEGER NOT NULL DEFAULT 0,
    posted_date TEXT,
    scraped_at TEXT NOT NULL,
    score REAL,
    category TEXT,
    skill_matches TEXT,
    llm_reasoning TEXT,
    application_status TEXT NOT NULL DEFAULT 'new',
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped ON jobs(scraped_at);
CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
"""


class Database:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # Migrations: add columns if missing
        for col, coltype in [
            ("llm_reasoning", "TEXT"),
            ("notes", "TEXT DEFAULT ''"),
            ("applied_date", "TEXT"),
            ("status_changed_at", "TEXT"),
            ("score_breakdown", "TEXT"),
            ("red_flags", "TEXT DEFAULT ''"),
        ]:
            try:
                self.conn.execute(f"SELECT {col} FROM jobs LIMIT 1")
            except sqlite3.OperationalError:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {coltype}")
        self.conn.commit()

    def insert_jobs(self, jobs: list[Job]) -> list[Job]:
        """Insert jobs, skip duplicates. Returns only newly inserted jobs."""
        new_jobs = []
        for job in jobs:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO jobs
                       (source, external_id, title, company, location, url, description,
                        salary_min, salary_max, salary_currency, remote, posted_date, scraped_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job.source,
                        job.external_id,
                        job.title,
                        job.company,
                        job.location,
                        job.url,
                        job.description,
                        job.salary_min,
                        job.salary_max,
                        job.salary_currency,
                        int(job.remote),
                        job.posted_date.isoformat() if job.posted_date else None,
                        job.scraped_at.isoformat(),
                    ),
                )
                if self.conn.total_changes and self._last_was_insert():
                    new_jobs.append(job)
            except sqlite3.Error as e:
                logger.error(f"DB insert error for {job.source}/{job.external_id}: {e}")
        self.conn.commit()
        logger.info(f"Inserted {len(new_jobs)} new jobs out of {len(jobs)} total")
        return new_jobs

    def _last_was_insert(self) -> bool:
        return self.conn.execute("SELECT changes()").fetchone()[0] > 0

    def update_scores(self, scored_jobs: list[ScoredJob]):
        for sj in scored_jobs:
            self.conn.execute(
                """UPDATE jobs SET score = ?, category = ?, skill_matches = ?,
                   llm_reasoning = ?, score_breakdown = ?, red_flags = ?
                   WHERE source = ? AND external_id = ?""",
                (
                    sj.score,
                    sj.category,
                    ",".join(sj.skill_matches),
                    sj.llm_reasoning,
                    sj.score_breakdown,
                    sj.red_flags,
                    sj.job.source,
                    sj.job.external_id,
                ),
            )
        self.conn.commit()

    def get_todays_matches(self, min_score: float = 40) -> list[dict]:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = self.conn.execute(
            """SELECT * FROM jobs
               WHERE score >= ? AND scraped_at LIKE ?
               ORDER BY score DESC""",
            (min_score, f"{today}%"),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_all_unscored(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score IS NULL ORDER BY scraped_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_jobs(
        self,
        category: str | None = None,
        source: str | None = None,
        status: str | None = None,
        search: str | None = None,
        min_score: float | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort_by: str = "score",
        sort_dir: str = "DESC",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Flexible job query with filtering, sorting, pagination."""
        where_clauses = []
        params: list = []

        if category and category != "all":
            where_clauses.append("category = ?")
            params.append(category)
        if source and source != "all":
            where_clauses.append("source = ?")
            params.append(source)
        if status and status != "all":
            where_clauses.append("application_status = ?")
            params.append(status)
        if search:
            where_clauses.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])
        if min_score is not None:
            where_clauses.append("score >= ?")
            params.append(min_score)
        if date_from:
            where_clauses.append("scraped_at >= ?")
            params.append(date_from)
        if date_to:
            where_clauses.append("scraped_at <= ?")
            params.append(date_to + "T23:59:59")

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        allowed_sort = {"score", "scraped_at", "title", "company", "category"}
        sort_col = sort_by if sort_by in allowed_sort else "score"
        direction = "ASC" if sort_dir.upper() == "ASC" else "DESC"

        # Null scores sort last
        null_order = "LAST" if direction == "DESC" else "FIRST"

        count_row = self.conn.execute(
            f"SELECT COUNT(*) FROM jobs {where}", params
        ).fetchone()
        total = count_row[0]

        rows = self.conn.execute(
            f"""SELECT * FROM jobs {where}
                ORDER BY {sort_col} IS NULL, {sort_col} {direction}
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return [dict(r) for r in rows], total

    def get_stats(self, min_score: float | None = None) -> dict:
        """Dashboard summary statistics. Optionally filter by minimum score."""
        today = datetime.now().strftime("%Y-%m-%d")
        stats = {}

        # Base filter
        score_filter = ""
        score_params: list = []
        if min_score is not None:
            score_filter = " AND score >= ?"
            score_params = [min_score]

        # Totals (unfiltered for context)
        row = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        stats["total_jobs_unfiltered"] = row[0]

        # Filtered totals
        row = self.conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE 1=1{score_filter}", score_params
        ).fetchone()
        stats["total_jobs"] = row[0]

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE scraped_at LIKE ?{score_filter}",
            [f"{today}%"] + score_params,
        ).fetchone()
        stats["today_jobs"] = row[0]

        # Category counts (filtered)
        row = self.conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE score >= 80{score_filter}", score_params
        ).fetchone()
        stats["perfect_matches"] = row[0]

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE score >= 60 AND score < 80{score_filter}",
            score_params,
        ).fetchone()
        stats["strong_matches"] = row[0]

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE score >= 40 AND score < 60{score_filter}",
            score_params,
        ).fetchone()
        stats["worth_a_look"] = row[0]

        # Application status counts (filtered)
        for status_name in ["new", "saved", "applied", "interviewing", "rejected", "offer"]:
            row = self.conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE application_status = ?{score_filter}",
                [status_name] + score_params,
            ).fetchone()
            stats[f"status_{status_name}"] = row[0]

        # Legacy key
        stats["applied"] = stats["status_applied"]

        row = self.conn.execute(
            "SELECT COUNT(DISTINCT source) FROM jobs"
        ).fetchone()
        stats["sources_count"] = row[0]

        # By source (filtered)
        rows = self.conn.execute(
            f"""SELECT source, COUNT(*) as cnt FROM jobs
                WHERE 1=1{score_filter}
                GROUP BY source ORDER BY cnt DESC""",
            score_params,
        ).fetchall()
        stats["by_source"] = {r["source"]: r["cnt"] for r in rows}

        # By category (filtered)
        rows = self.conn.execute(
            f"""SELECT category, COUNT(*) as cnt FROM jobs
                WHERE category IS NOT NULL{score_filter}
                GROUP BY category""",
            score_params,
        ).fetchall()
        stats["by_category"] = {r["category"]: r["cnt"] for r in rows}

        # By status (filtered)
        rows = self.conn.execute(
            f"""SELECT application_status, COUNT(*) as cnt FROM jobs
                WHERE 1=1{score_filter}
                GROUP BY application_status""",
            score_params,
        ).fetchall()
        stats["by_status"] = {r["application_status"]: r["cnt"] for r in rows}

        # Avg score (filtered)
        row = self.conn.execute(
            f"SELECT AVG(score) FROM jobs WHERE score IS NOT NULL{score_filter}",
            score_params,
        ).fetchone()
        stats["avg_score"] = round(row[0], 1) if row[0] else 0

        # Score distribution histogram (10-point buckets)
        score_dist = {}
        for lo in range(0, 100, 10):
            hi = lo + 10
            label = f"{lo}-{hi}"
            row = self.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE score >= ? AND score < ?",
                (lo, hi),
            ).fetchone()
            score_dist[label] = row[0]
        stats["score_distribution"] = score_dist

        # Application pipeline funnel
        stats["pipeline_funnel"] = {
            "new": stats["status_new"],
            "saved": stats["status_saved"],
            "applied": stats["status_applied"],
            "interviewing": stats["status_interviewing"],
            "offer": stats["status_offer"],
            "rejected": stats["status_rejected"],
        }

        return stats

    def update_application_status(self, job_id: int, status: str):
        now = datetime.now().isoformat()
        # Auto-set applied_date when moving to "applied"
        if status == "applied":
            self.conn.execute(
                """UPDATE jobs SET application_status = ?, status_changed_at = ?,
                   applied_date = COALESCE(applied_date, ?)
                   WHERE id = ?""",
                (status, now, now, job_id),
            )
        else:
            self.conn.execute(
                "UPDATE jobs SET application_status = ?, status_changed_at = ? WHERE id = ?",
                (status, now, job_id),
            )
        self.conn.commit()

    def update_notes(self, job_id: int, notes: str):
        self.conn.execute("UPDATE jobs SET notes = ? WHERE id = ?", (notes, job_id))
        self.conn.commit()

    def bulk_update_status(self, job_ids: list[int], status: str):
        now = datetime.now().isoformat()
        placeholders = ",".join("?" * len(job_ids))
        if status == "applied":
            self.conn.execute(
                f"""UPDATE jobs SET application_status = ?, status_changed_at = ?,
                    applied_date = COALESCE(applied_date, ?)
                    WHERE id IN ({placeholders})""",
                [status, now, now] + job_ids,
            )
        else:
            self.conn.execute(
                f"UPDATE jobs SET application_status = ?, status_changed_at = ? WHERE id IN ({placeholders})",
                [status, now] + job_ids,
            )
        self.conn.commit()

    def bulk_delete(self, job_ids: list[int]):
        placeholders = ",".join("?" * len(job_ids))
        self.conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
        self.conn.commit()

    def delete_job(self, job_id: int):
        self.conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self.conn.commit()

    def delete_all(self):
        self.conn.execute("DELETE FROM jobs")
        self.conn.commit()
        logger.info("Deleted all jobs from database")

    def get_job_by_id(self, job_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_distinct_sources(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT source FROM jobs ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows]

    def clear_all_scores(self):
        """Reset scores, categories, and LLM reasoning. Preserves application_status."""
        self.conn.execute(
            "UPDATE jobs SET score = NULL, category = NULL, skill_matches = NULL, llm_reasoning = NULL"
        )
        self.conn.commit()
        logger.info("Cleared all job scores (application status preserved)")

    def close(self):
        self.conn.close()
