import logging
import os
import tempfile
from typing import Optional

import fitz  # PyMuPDF
import requests


def download_pdf(url: str, session: Optional[requests.Session] = None) -> Optional[str]:
    client = session or requests.Session()
    try:
        resp = client.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to download PDF", extra={"url": url, "err": str(exc)})
        return None
    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as tmp:
        tmp.write(resp.content)
    return path


def extract_pdf_text(path: str) -> str:
    text_parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n".join(text_parts)
