import os
import yaml


def load_config(path: str = "config.yaml") -> dict:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(project_root, path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve relative database path
    db_path = config.get("database", {}).get("path", "data/jobs.db")
    if not os.path.isabs(db_path):
        config["database"]["path"] = os.path.join(project_root, db_path)

    # Override secrets from environment variables (for Railway/cloud deploys)
    _env_override(config, "llm", "api_key", "ANTHROPIC_API_KEY")
    _env_override(config, "email", "smtp_password", "SMTP_PASSWORD")
    _env_override(config, "scrapers.linkedin_rapid", "rapidapi_key", "RAPIDAPI_KEY")
    _env_override(config, "scrapers.adzuna", "app_id", "ADZUNA_APP_ID")
    _env_override(config, "scrapers.adzuna", "app_key", "ADZUNA_APP_KEY")
    _env_override(config, "scrapers.serpapi_google", "api_key", "SERPAPI_KEY")

    return config


def _env_override(config: dict, section: str, key: str, env_var: str):
    """Override a config value with an environment variable if set."""
    val = os.environ.get(env_var)
    if not val:
        return

    # Navigate nested sections like "scrapers.linkedin_rapid"
    parts = section.split(".")
    obj = config
    for part in parts:
        if part not in obj:
            obj[part] = {}
        obj = obj[part]

    obj[key] = val
