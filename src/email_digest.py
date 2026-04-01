import os
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


def send_digest(
    matches: list[dict],
    email_config: dict,
    total_scraped: int = 0,
    total_new: int = 0,
):
    perfect = [j for j in matches if j.get("category") == "Perfect Match"]
    strong = [j for j in matches if j.get("category") == "Strong Match"]
    worth = [j for j in matches if j.get("category") == "Worth a Look"]

    # Render HTML
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_dir = os.path.join(project_root, "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("email_digest.html")

    html = template.render(
        date=datetime.now().strftime("%A, %B %d, %Y"),
        total_scraped=total_scraped,
        total_new=total_new,
        total_matches=len(matches),
        perfect_matches=perfect,
        strong_matches=strong,
        worth_a_look=worth,
    )

    if not email_config.get("enabled", False):
        logger.info("Email disabled, printing summary to console")
        _print_summary(perfect, strong, worth)
        return html

    # Send email
    subject = (
        f"{email_config.get('subject_prefix', '[JobDigest]')} "
        f"{len(matches)} matches found - {datetime.now().strftime('%Y-%m-%d')}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_config.get("from_address", "")
    msg["To"] = ", ".join(email_config.get("to_addresses", []))

    # Plain text fallback
    plain = _build_plain_text(perfect, strong, worth)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        smtp_host = email_config.get("smtp_host", "smtp.gmail.com")
        smtp_port = email_config.get("smtp_port", 587)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(
                email_config.get("smtp_user", ""),
                email_config.get("smtp_password", ""),
            )
            server.sendmail(
                email_config.get("from_address", ""),
                email_config.get("to_addresses", []),
                msg.as_string(),
            )
        logger.info(f"Digest email sent to {email_config.get('to_addresses')}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        logger.info("Falling back to console output")
        _print_summary(perfect, strong, worth)

    return html


def _build_plain_text(perfect, strong, worth) -> str:
    lines = ["=== Neesha's Daily Catch ===\n"]

    for label, jobs in [("PERFECT MATCH", perfect), ("STRONG MATCH", strong), ("WORTH A LOOK", worth)]:
        if jobs:
            lines.append(f"\n--- {label} ({len(jobs)}) ---")
            for j in jobs:
                lines.append(f"  [{j['score']}] {j['title']} @ {j['company']}")
                lines.append(f"        {j['location']} | {j['url']}")

    return "\n".join(lines)


def _print_summary(perfect, strong, worth):
    print("\n" + "=" * 60)
    print("  NEESHA'S DAILY CATCH")
    print("=" * 60)

    for label, jobs in [
        ("PERFECT MATCH", perfect),
        ("STRONG MATCH", strong),
        ("WORTH A LOOK", worth),
    ]:
        if jobs:
            print(f"\n  {label} ({len(jobs)})")
            print("  " + "-" * 40)
            for j in jobs[:10]:
                print(f"  [{j['score']:5.1f}] {j['title']}")
                print(f"          {j['company']} | {j['location']}")
                print(f"          {j['url']}")
                print()

    if not perfect and not strong and not worth:
        print("\n  Nothing caught Neesha's eye today. The spies will try harder tomorrow!\n")

    print("=" * 60)
