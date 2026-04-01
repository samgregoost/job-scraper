#!/usr/bin/env python3
"""
Job Scraper Dashboard - Web UI
Usage: python dashboard.py
Then open http://localhost:5000
"""

import json
import logging
import os
import sys
import threading
from datetime import datetime

import yaml
from flask import Flask, jsonify, request, render_template, send_from_directory

from src.config_loader import load_config
from src.cv_reader import read_cv
from src.database import Database
from src.matcher import score_jobs
from src.llm_matcher import llm_score_jobs
from src.email_digest import send_digest
from src.scrapers.registry import get_enabled_scrapers
from src.models import Job

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_scraper.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("dashboard")

app = Flask(__name__, template_folder="templates", static_folder="static")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Pipeline state (shared across threads)
pipeline_state = {
    "running": False,
    "last_run": None,
    "last_result": None,
    "progress": "",
}


def get_db():
    config = load_config()
    return Database(config["database"]["path"])


# ── Pages ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


# ── API: Stats ────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    db = get_db()
    min_score = request.args.get("min_score")
    min_score = float(min_score) if min_score else None
    stats = db.get_stats(min_score=min_score)
    stats["pipeline_running"] = pipeline_state["running"]
    stats["last_run"] = pipeline_state["last_run"]
    stats["last_result"] = pipeline_state["last_result"]
    stats["pipeline_progress"] = pipeline_state["progress"]
    db.close()
    return jsonify(stats)


# ── API: Jobs ─────────────────────────────────────────────────────

@app.route("/api/jobs")
def api_jobs():
    db = get_db()
    jobs, total = db.get_jobs(
        category=request.args.get("category"),
        source=request.args.get("source"),
        status=request.args.get("status"),
        search=request.args.get("search"),
        min_score=float(request.args.get("min_score")) if request.args.get("min_score") else None,
        sort_by=request.args.get("sort_by", "score"),
        sort_dir=request.args.get("sort_dir", "DESC"),
        limit=int(request.args.get("limit", 50)),
        offset=int(request.args.get("offset", 0)),
    )
    db.close()
    return jsonify({"jobs": jobs, "total": total})


@app.route("/api/jobs/<int:job_id>")
def api_job_detail(job_id):
    db = get_db()
    job = db.get_job_by_id(job_id)
    db.close()
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify(job)


@app.route("/api/jobs/<int:job_id>/status", methods=["PUT"])
def api_update_status(job_id):
    data = request.get_json()
    status = data.get("status", "new")
    db = get_db()
    db.update_application_status(job_id, status)
    db.close()
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def api_delete_job(job_id):
    db = get_db()
    db.delete_job(job_id)
    db.close()
    return jsonify({"ok": True})


@app.route("/api/sources")
def api_sources():
    db = get_db()
    sources = db.get_distinct_sources()
    db.close()
    return jsonify(sources)


# ── API: Config ───────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_get_config():
    config = load_config()
    # Mask secrets in the response but indicate if they're set
    _mask_secret(config, ["llm", "api_key"], "ANTHROPIC_API_KEY")
    _mask_secret(config, ["scrapers", "linkedin_rapid", "rapidapi_key"], "RAPIDAPI_KEY")
    _mask_secret(config, ["scrapers", "adzuna", "app_key"], "ADZUNA_APP_KEY")
    _mask_secret(config, ["scrapers", "serpapi_google", "api_key"], "SERPAPI_KEY")
    _mask_secret(config, ["email", "smtp_password"], "SMTP_PASSWORD")
    return jsonify(config)


def _mask_secret(config: dict, path: list[str], env_var: str):
    """Show '••• (from env)' for secrets loaded from env vars."""
    obj = config
    for key in path[:-1]:
        obj = obj.get(key, {})
    final_key = path[-1]
    val = obj.get(final_key, "")
    if val and os.environ.get(env_var):
        obj[final_key] = "••• (set via environment variable)"


@app.route("/api/config", methods=["PUT"])
def api_save_config():
    data = request.get_json()

    # Preserve secrets that come from env vars — don't let the UI overwrite them
    # with empty strings or masked placeholders
    _preserve_secret(data, ["llm", "api_key"], "ANTHROPIC_API_KEY")
    _preserve_secret(data, ["scrapers", "linkedin_rapid", "rapidapi_key"], "RAPIDAPI_KEY")
    _preserve_secret(data, ["scrapers", "adzuna", "app_key"], "ADZUNA_APP_KEY")
    _preserve_secret(data, ["scrapers", "serpapi_google", "api_key"], "SERPAPI_KEY")
    _preserve_secret(data, ["email", "smtp_password"], "SMTP_PASSWORD")

    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return jsonify({"ok": True})


def _preserve_secret(data: dict, path: list[str], env_var: str):
    """If an env var provides the secret, keep the yaml value empty so
    the env override works on next load. Don't save masked placeholders."""
    obj = data
    for key in path[:-1]:
        if key not in obj:
            return
        obj = obj[key]
    final_key = path[-1]
    val = obj.get(final_key, "")
    # If value is masked or env var is set, keep yaml empty
    if "•••" in str(val) or (os.environ.get(env_var) and not val):
        obj[final_key] = ""
    elif os.environ.get(env_var) and val == os.environ.get(env_var):
        # Don't write the actual secret to yaml if it matches env
        obj[final_key] = ""


# ── API: CV ───────────────────────────────────────────────────────

@app.route("/api/cv", methods=["GET"])
def api_cv_status():
    cv_dir = os.path.join(PROJECT_ROOT, "cv")
    files = []
    if os.path.isdir(cv_dir):
        for f in os.listdir(cv_dir):
            if f.lower().endswith((".pdf", ".docx", ".txt")):
                fpath = os.path.join(cv_dir, f)
                files.append({
                    "name": f,
                    "size": os.path.getsize(fpath),
                    "modified": datetime.fromtimestamp(os.path.getmtime(fpath)).isoformat(),
                })
    cv_text = read_cv()

    # Detect skills from CV text
    config = load_config()
    user_skills = config.get("preferences", {}).get("skills", [])
    cv_lower = cv_text.lower()

    detected_skills = []
    for skill in user_skills:
        detected_skills.append({
            "name": skill,
            "found": skill.lower() in cv_lower,
        })

    # Also detect common tech skills not in config
    common_skills = [
        "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust",
        "Ruby", "PHP", "Swift", "Kotlin", "React", "Angular", "Vue", "Node.js",
        "Django", "Flask", "FastAPI", "Spring", "Express", "Next.js",
        "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Terraform",
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
        "REST", "GraphQL", "gRPC", "Git", "CI/CD", "Linux",
        "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
        "Agile", "Scrum", "Microservices", "Serverless",
    ]
    extra_found = []
    for skill in common_skills:
        if skill.lower() in cv_lower and skill not in user_skills:
            extra_found.append(skill)

    return jsonify({
        "files": files,
        "text_length": len(cv_text),
        "preview": cv_text[:2000] if cv_text else "",
        "detected_skills": detected_skills,
        "extra_skills_found": extra_found,
    })


@app.route("/api/cv/delete/<filename>", methods=["DELETE"])
def api_cv_delete(filename):
    cv_dir = os.path.join(PROJECT_ROOT, "cv")
    filepath = os.path.join(cv_dir, filename)
    # Prevent path traversal
    if not os.path.abspath(filepath).startswith(os.path.abspath(cv_dir)):
        return jsonify({"error": "Invalid path"}), 400
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"ok": True})
    return jsonify({"error": "File not found"}), 404


@app.route("/api/cv/upload", methods=["POST"])
def api_cv_upload():
    cv_dir = os.path.join(PROJECT_ROOT, "cv")
    os.makedirs(cv_dir, exist_ok=True)

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No filename"}), 400

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ("pdf", "docx", "txt"):
        return jsonify({"error": "Only PDF, DOCX, TXT allowed"}), 400

    filepath = os.path.join(cv_dir, f.filename)
    f.save(filepath)
    return jsonify({"ok": True, "filename": f.filename})


# ── API: Pipeline ─────────────────────────────────────────────────

@app.route("/api/pipeline/run", methods=["POST"])
def api_run_pipeline():
    if pipeline_state["running"]:
        return jsonify({"error": "Pipeline already running"}), 409

    thread = threading.Thread(target=_run_pipeline_thread, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Pipeline started"})


def _run_pipeline_thread():
    pipeline_state["running"] = True
    pipeline_state["progress"] = "Loading config..."
    result = {"scraped": 0, "new": 0, "matches": 0, "errors": []}

    try:
        config = load_config()

        pipeline_state["progress"] = "Reading CV..."
        cv_text = read_cv()
        if not cv_text:
            cv_text = " ".join(config["preferences"].get("skills", []))

        pipeline_state["progress"] = "Initializing scrapers..."
        scrapers = get_enabled_scrapers(config)

        all_jobs: list[Job] = []
        for i, scraper in enumerate(scrapers, 1):
            pipeline_state["progress"] = f"Scraping {scraper.name} ({i}/{len(scrapers)})..."
            try:
                jobs = scraper.scrape()
                all_jobs.extend(jobs)
            except Exception as e:
                result["errors"].append(f"{scraper.name}: {str(e)}")

        result["scraped"] = len(all_jobs)

        if all_jobs:
            pipeline_state["progress"] = "Saving to database..."
            db = Database(config["database"]["path"])
            new_jobs = db.insert_jobs(all_jobs)
            result["new"] = len(new_jobs)

            # Clear scores right before re-scoring (not earlier)
            pipeline_state["progress"] = "Clearing old scores..."
            db.clear_all_scores()

            # Score ALL jobs in DB with current preferences
            all_db_rows = db.conn.execute("SELECT * FROM jobs").fetchall()
            all_db_jobs = [
                Job(source=r["source"], external_id=r["external_id"], title=r["title"],
                    company=r["company"], location=r["location"], url=r["url"],
                    description=r["description"], salary_min=r["salary_min"],
                    salary_max=r["salary_max"], salary_currency=r["salary_currency"],
                    remote=bool(r["remote"]), posted_date=None, scraped_at=datetime.now())
                for r in all_db_rows
            ]

            if all_db_jobs:
                pipeline_state["progress"] = f"Scoring {len(all_db_jobs)} jobs (rule-based)..."
                scored = score_jobs(all_db_jobs, cv_text, config["preferences"], config["scoring"],
                                    search_statement=config.get("job_search_statement", ""))
                db.update_scores(scored)

                # LLM scoring on top candidates
                llm_config = config.get("llm", {})
                if llm_config.get("enabled") and llm_config.get("api_key"):
                    top_n = llm_config.get("top_n", 30)
                    top_candidates = [s.job for s in scored[:top_n]]
                    pipeline_state["progress"] = f"AI analyzing top {len(top_candidates)} matches..."
                    llm_scored = llm_score_jobs(
                        top_candidates, cv_text, config["preferences"],
                        config["scoring"], llm_config,
                        search_statement=config.get("job_search_statement", ""),
                    )
                    if llm_scored:
                        db.update_scores(llm_scored)

                min_score = config["scoring"]["thresholds"].get("worth_a_look", 40)
                matches = db.get_todays_matches(min_score=min_score)
                result["matches"] = len(matches)

                if matches and config.get("email", {}).get("enabled"):
                    pipeline_state["progress"] = "Sending email digest..."
                    send_digest(matches, config["email"], len(all_jobs), len(new_jobs))

            db.close()

        pipeline_state["progress"] = "Done!"
        pipeline_state["last_result"] = result
        pipeline_state["last_run"] = datetime.now().isoformat()

    except Exception as e:
        pipeline_state["progress"] = f"Error: {str(e)}"
        result["errors"].append(str(e))
        pipeline_state["last_result"] = result

    finally:
        pipeline_state["running"] = False


@app.route("/api/pipeline/reprocess", methods=["POST"])
def api_reprocess():
    if pipeline_state["running"]:
        return jsonify({"error": "Pipeline already running"}), 409

    thread = threading.Thread(target=_reprocess_thread, daemon=True)
    thread.start()
    return jsonify({"ok": True})


def _reprocess_thread():
    pipeline_state["running"] = True
    pipeline_state["progress"] = "Re-scoring all jobs..."

    try:
        config = load_config()
        cv_text = read_cv()
        if not cv_text:
            cv_text = " ".join(config["preferences"].get("skills", []))

        db = Database(config["database"]["path"])

        # Re-score ALL jobs, not just unscored
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

        if jobs:
            pipeline_state["progress"] = f"Rule-based scoring {len(jobs)} jobs..."
            scored = score_jobs(jobs, cv_text, config["preferences"], config["scoring"],
                                search_statement=config.get("job_search_statement", ""))
            db.update_scores(scored)

            # LLM re-score top matches
            llm_config = config.get("llm", {})
            if llm_config.get("enabled") and llm_config.get("api_key"):
                top_n = llm_config.get("top_n", 30)
                top_candidates = [s.job for s in scored[:top_n]]
                pipeline_state["progress"] = f"AI re-analyzing top {len(top_candidates)} matches..."
                llm_scored = llm_score_jobs(
                    top_candidates, cv_text, config["preferences"],
                    config["scoring"], llm_config,
                    search_statement=config.get("job_search_statement", ""),
                )
                if llm_scored:
                    db.update_scores(llm_scored)

            pipeline_state["progress"] = f"Re-scored {len(scored)} jobs"
        else:
            pipeline_state["progress"] = "No jobs to re-score"

        db.close()
        pipeline_state["last_run"] = datetime.now().isoformat()

    except Exception as e:
        pipeline_state["progress"] = f"Error: {str(e)}"
    finally:
        pipeline_state["running"] = False


# ── API: Test Email ───────────────────────────────────────────────

@app.route("/api/email/test", methods=["POST"])
def api_test_email():
    config = load_config()
    sample = [
        {"title": "Senior Python Developer", "company": "TechCorp", "location": "Remote",
         "url": "#", "score": 92.5, "category": "Perfect Match",
         "skill_matches": "Python,Django", "salary_min": 90000, "salary_max": 120000, "salary_currency": "USD"},
        {"title": "Backend Engineer", "company": "StartupXYZ", "location": "London, UK",
         "url": "#", "score": 74.3, "category": "Strong Match",
         "skill_matches": "Python,Docker", "salary_min": None, "salary_max": None, "salary_currency": None},
    ]
    try:
        send_digest(sample, config["email"], 150, 42)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Export CSV ───────────────────────────────────────────────

@app.route("/api/export/csv")
def api_export_csv():
    """Export jobs to CSV with optional filters."""
    import csv
    import io

    db = get_db()
    jobs, total = db.get_jobs(
        category=request.args.get("category"),
        source=request.args.get("source"),
        status=request.args.get("status"),
        search=request.args.get("search"),
        min_score=float(request.args.get("min_score")) if request.args.get("min_score") else None,
        sort_by=request.args.get("sort_by", "score"),
        sort_dir=request.args.get("sort_dir", "DESC"),
        limit=10000,
        offset=0,
    )
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Company", "Location", "Score", "Category",
        "Status", "Skills Matched", "Source", "Remote",
        "Salary Min", "Salary Max", "Currency",
        "AI Reasoning", "URL", "Scraped At",
    ])
    for j in jobs:
        writer.writerow([
            j.get("title", ""),
            j.get("company", ""),
            j.get("location", ""),
            j.get("score", ""),
            j.get("category", ""),
            j.get("application_status", ""),
            j.get("skill_matches", ""),
            j.get("source", ""),
            "Yes" if j.get("remote") else "No",
            j.get("salary_min", ""),
            j.get("salary_max", ""),
            j.get("salary_currency", ""),
            j.get("llm_reasoning", ""),
            j.get("url", ""),
            j.get("scraped_at", ""),
        ])

    from flask import Response
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    status_filter = request.args.get("status", "all")
    filename = f"jobs_{status_filter}_{timestamp}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── API: Logs ─────────────────────────────────────────────────────

@app.route("/api/logs")
def api_logs():
    log_path = os.path.join(PROJECT_ROOT, "job_scraper.log")
    lines = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-100:]  # Last 100 lines
    return jsonify({"lines": lines})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    print(f"\n  Job Scraper Dashboard")
    print(f"  http://localhost:{port}\n")
    app.run(debug=debug, host="0.0.0.0", port=port)
