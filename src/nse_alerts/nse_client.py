import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests

from .models import Announcement


BASE_URL = "https://www.nseindia.com"
ANNOUNCEMENTS_API = "/api/corporate-announcements"
ARCHIVE_BASE = "https://nsearchives.nseindia.com/corporate/"


class NSEClient:
    def __init__(self, index: str = "equities"):
        self.index = index
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        )

    def _warm_up(self) -> None:
        # Initial visit to homepage to set cookies
        try:
            self.session.get(BASE_URL, timeout=20)
        except Exception as e:
            logging.warning(f"Warmup homepage fetch failed: {e}")
        time.sleep(1)
        
        # Second visit to announcements page to set specific cookies
        try:
             self.session.get(f"{BASE_URL}/companies-listing/corporate-filings-announcements", timeout=20)
        except Exception as e:
             logging.warning(f"Warmup announcements page fetch failed: {e}")
        time.sleep(1)

    def fetch_announcements(
        self, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None
    ) -> List[Announcement]:
        self._warm_up()
        if not to_date:
            to_date = datetime.utcnow()
        if not from_date:
            from_date = to_date - timedelta(days=1)
        params = {
            "index": self.index,
            "from_date": from_date.strftime("%d-%m-%Y"),
            "to_date": to_date.strftime("%d-%m-%Y"),
        }
        url = f"{BASE_URL}{ANNOUNCEMENTS_API}"
        logging.debug("Requesting announcements", extra={"params": params})
        
        # Update headers for API request
        self.session.headers.update({
             "Accept": "*/*",
             "Sec-Fetch-Dest": "empty",
             "Sec-Fetch-Mode": "cors",
             "Sec-Fetch-Site": "same-origin",
             "Referer": f"{BASE_URL}/companies-listing/corporate-filings-announcements",
             "X-Requested-With": "XMLHttpRequest",
        })

        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception:
            logging.error("Failed to parse JSON response. Status: %s, Text (first 500 chars): %s", resp.status_code, resp.text[:500])
            raise

        records = payload if isinstance(payload, list) else payload.get("data", [])
        announcements: List[Announcement] = []
        for item in records:
            try:
                announcements.append(self._parse_item(item))
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed to parse item", extra={"item": item, "err": str(exc)})
        return announcements

    def _parse_item(self, item: dict) -> Announcement:
        symbol = item.get("symbol") or item.get("sm_symbol") or ""
        company = item.get("company") or item.get("sm_company") or symbol
        subject = item.get("subject") or item.get("sm_desc") or ""
        description = item.get("description") or item.get("desc") or subject
        raw_time = item.get("announcementTime") or item.get("sm_announce_time")
        time_obj = self._parse_datetime(raw_time)
        pdf_url = self._extract_pdf_url(item)
        raw_id = str(item.get("sm_pid") or item.get("id") or f"{symbol}-{raw_time}-{subject}")
        return Announcement(
            symbol=symbol,
            company=company,
            subject=subject,
            description=description,
            time=time_obj,
            pdf_url=pdf_url,
            raw_id=raw_id,
        )

    @staticmethod
    def _parse_datetime(raw: str | None) -> datetime:
        if not raw:
            return datetime.utcnow()
        # NSE typically: "14-Mar-2026 10:30"
        for fmt in ("%d-%b-%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                return datetime.strptime(raw.strip(), fmt)
            except Exception:
                continue
        return datetime.utcnow()

    @staticmethod
    def _extract_pdf_url(item: dict) -> Optional[str]:
        direct = item.get("pdfUrl") or item.get("attachmentUrl")
        if direct:
            return direct
        att = item.get("attchmntFile") or item.get("attachment")
        if att:
            if att.startswith("http"):
                return att
            return f"{ARCHIVE_BASE}{att}"
        return None
