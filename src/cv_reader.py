import os
import logging

logger = logging.getLogger(__name__)


def read_cv(cv_dir: str = "cv") -> str:
    """Read all CV files from the cv/ directory and return combined text."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cv_path = os.path.join(project_root, cv_dir)

    if not os.path.isdir(cv_path):
        logger.warning(f"CV directory not found: {cv_path}")
        return ""

    texts = []
    for filename in os.listdir(cv_path):
        filepath = os.path.join(cv_path, filename)
        lower = filename.lower()

        if lower.endswith(".pdf"):
            texts.append(_read_pdf(filepath))
        elif lower.endswith(".docx"):
            texts.append(_read_docx(filepath))
        elif lower.endswith(".txt"):
            with open(filepath, "r", encoding="utf-8") as f:
                texts.append(f.read())

    combined = "\n\n".join(t for t in texts if t.strip())
    if not combined:
        logger.warning("No CV text extracted. Place a PDF, DOCX, or TXT file in the cv/ folder.")
    else:
        logger.info(f"Read CV text: {len(combined)} characters from {len(texts)} file(s)")

    return combined


def _read_pdf(filepath: str) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(filepath)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except Exception as e:
        logger.error(f"Failed to read PDF {filepath}: {e}")
        return ""


def _read_docx(filepath: str) -> str:
    try:
        from docx import Document
        doc = Document(filepath)
        return "\n".join(para.text for para in doc.paragraphs)
    except Exception as e:
        logger.error(f"Failed to read DOCX {filepath}: {e}")
        return ""
