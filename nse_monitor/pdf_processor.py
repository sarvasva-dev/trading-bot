import os
import requests
import logging
import fitz  # PyMuPDF
import random
import time
from nse_monitor.config import DOWNLOADS_DIR, HEADERS, USER_AGENTS

try:
    import pytesseract
    from PIL import Image
    import io
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
import threading
import gc

logger = logging.getLogger(__name__)

# v1.3.2: RAM-Safe OCR Lock (Ensures only 1 heavy OCR runs at a time on 1GB VPS)
_ocr_lock = threading.Lock()

class PDFProcessor:
    def __init__(self):
        if not os.path.exists(DOWNLOADS_DIR):
            os.makedirs(DOWNLOADS_DIR)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.archive_base = "https://nsearchives.nseindia.com/corporate/"

    def download_pdf(self, pdf_url, retries=3):
        """Downloads a PDF with retries and UA rotation to bypass blocks."""
        if not pdf_url or pdf_url.strip() in ["", "-", "None"]:
            return None

        # Handle relative URLs
        if not pdf_url.startswith("http"):
            pdf_url = self.archive_base + pdf_url
            
        filename = os.path.basename(pdf_url)
        local_path = os.path.join(DOWNLOADS_DIR, filename)

        if os.path.exists(local_path):
            return local_path

        for attempt in range(retries):
            # v1.4.1: Anti-Block Jitter (Round Robin timing)
            # Even for the first attempt, we wait a bit to decouple from the trigger
            if attempt == 0:
                time.sleep(random.uniform(3, 7))
            
            try:
                # Rotate User-Agent on each attempt
                ua = random.choice(USER_AGENTS)
                self.session.headers.update({"User-Agent": ua})
                
                logger.info(f"Downloading PDF (Attempt {attempt+1}/{retries}): {pdf_url}")
                
                # v1.4.2: Direct Mode (Bypassing Proxies for stability)
                # Use a fresh landing page visit to stabilize session if needed
                response = self.session.get(pdf_url, proxies=None, timeout=45, stream=True)
                response.raise_for_status()

                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"Successfully downloaded: {filename}")
                self._cleanup_downloads()
                return local_path

            except Exception as e:
                logger.warning(f"Download attempt {attempt+1} failed: {e}")
                if attempt < retries - 1:
                    wait_time = random.uniform(2, 5) * (attempt + 1)
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to download PDF after {retries} attempts: {pdf_url}")

        return None
        
    def _cleanup_downloads(self, limit=20):
        """Keeps only the latest N files in the downloads directory to save space."""
        try:
            # Get all files in download directory
            files = [os.path.join(DOWNLOADS_DIR, f) for f in os.listdir(DOWNLOADS_DIR) 
                     if os.path.isfile(os.path.join(DOWNLOADS_DIR, f))]
            
            if len(files) <= limit:
                return

            # Sort files by modification time (oldest first)
            files.sort(key=os.path.getmtime)
            
            # Oldest files exceeding the limit
            to_delete = files[:-limit]
            
            for f in to_delete:
                try:
                    os.remove(f)
                    logger.info(f"Auto-cleanup: Purged old PDF {os.path.basename(f)}")
                except Exception as e:
                    logger.error(f"Failed to purge {f}: {e}")
        except Exception as e:
            logger.error(f"Cleanup process failed: {e}")

    def extract_text(self, pdf_path):
        """Extracts text from a local PDF file, with OCR fallback for scanned images."""
        if not pdf_path or not os.path.exists(pdf_path):
            return ""

        try:
            logger.info(f"Extracting text from {pdf_path}...")
            text = ""
            import fitz 
            with fitz.open(pdf_path) as doc:
                for page in doc:
                    text += page.get_text()
            
            # Phase 2: OCR Fallback for scanned PDFs
            text = text.strip()
            if len(text) < 50 and OCR_AVAILABLE:
                logger.warning(f"Extracted <50 chars. Document might be scanned. Attempting OCR...")
                ocr_text = self._extract_text_ocr(pdf_path)
                if ocr_text:
                    text = ocr_text
                    
            return text
        except Exception as e:
            logger.error(f"Failed to extract text from {pdf_path}: {e}")
            return ""
        finally:
            try:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                    logger.debug(f"Memory cleanup: Deleted {pdf_path}")
            except Exception as cleanup_err:
                logger.warning(f"Failed to delete {pdf_path}: {cleanup_err}")

    def _extract_text_ocr(self, pdf_path, max_pages=2):
        """v1.3.2: Safe OCR implementation with global lock & RAM optimization."""
        with _ocr_lock: # Strict serial processing to save 1GB VPS from OOM
            try:
                import fitz
                text = ""
                with fitz.open(pdf_path) as doc:
                    # Limit to first few pages to save RAM
                    for i in range(min(len(doc), max_pages)):
                        page = doc[i]
                        # Moderate DPI (120) for efficiency on 1GB RAM
                        pix = page.get_pixmap(dpi=120) 
                        img = Image.open(io.BytesIO(pix.tobytes("jpeg")))
                        
                        # Extract text
                        page_text = pytesseract.image_to_string(img)
                        text += page_text + "\n"
                        
                        # Explicit cleanup per page
                        del pix
                        del img

                logger.info(f"✅ Safe OCR successful for {os.path.basename(pdf_path)}.")
                return text.strip()
            except Exception as e:
                logger.error(f"❌ Safe OCR failed for {pdf_path}: {e}")
                return ""
            finally:
                # v1.3.2: Force RAM reclamation
                gc.collect()
