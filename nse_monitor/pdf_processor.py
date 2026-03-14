import os
import requests
import fitz  # PyMuPDF
import logging
from nse_monitor.config import DOWNLOADS_DIR, HEADERS

logger = logging.getLogger(__name__)

class PDFProcessor:
    def __init__(self):
        if not os.path.exists(DOWNLOADS_DIR):
            os.makedirs(DOWNLOADS_DIR)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.archive_base = "https://nsearchives.nseindia.com/corporate/"

    def download_pdf(self, pdf_url):
        """Downloads a PDF from NSE archives."""
        try:
            # Handle relative URLs
            if not pdf_url.startswith("http"):
                pdf_url = self.archive_base + pdf_url
                
            filename = os.path.basename(pdf_url)
            local_path = os.path.join(DOWNLOADS_DIR, filename)

            # Check if file already exists
            if os.path.exists(local_path):
                return local_path

            logger.info(f"Downloading PDF: {pdf_url}")
            response = self.session.get(pdf_url, timeout=30)
            response.raise_for_status()

            with open(local_path, "wb") as f:
                f.write(response.content)
            
            return local_path
        except Exception as e:
            logger.error(f"Failed to download PDF {pdf_url}: {e}")
            return None

    def extract_text(self, pdf_path):
        """Extracts text from a local PDF file."""
        if not pdf_path or not os.path.exists(pdf_path):
            return ""

        try:
            logger.info(f"Extracting text from {pdf_path}...")
            text = ""
            with fitz.open(pdf_path) as doc:
                for page in doc:
                    text += page.get_text()
            return text.strip()
        except Exception as e:
            logger.error(f"Failed to extract text from {pdf_path}: {e}")
            return ""
