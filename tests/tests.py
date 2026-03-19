import os
import sys
# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from nse_monitor.nse_api import NSEClient
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.database import Database

def test_nse_client_init():
    client = NSEClient()
    assert client.session is not None
    # Home page should be reachable
    response = client.session.get("https://www.nseindia.com", timeout=5)
    assert response.status_code == 200

def test_database_persistence():
    db = Database()
    test_id = "test_unique_id_999"
    if db.is_processed(test_id):
        # Clean up if exists from prev run
        conn = db.conn
        conn.execute("DELETE FROM processed_announcements WHERE id = ?", (test_id,))
        conn.commit()
    
    assert not db.is_processed(test_id)
    db.mark_processed(test_id, "Test Co", "2024-01-01")
    assert db.is_processed(test_id)

def test_pdf_processor_dirs():
    proc = PDFProcessor()
    from nse_monitor.config import DOWNLOADS_DIR
    assert os.path.exists(DOWNLOADS_DIR)

if __name__ == "__main__":
    pytest.main([__file__])
