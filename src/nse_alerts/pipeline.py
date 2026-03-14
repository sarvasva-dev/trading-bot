import logging
from typing import List

from .config import Settings
from .dedup_store import DedupStore
from .llm import summarize_and_classify
from .models import Announcement, ProcessedAlert
from .nse_client import NSEClient
from .pdf_utils import download_pdf, extract_pdf_text
from .telegram_bot import TelegramBot


class Pipeline:
    def __init__(self, settings: Settings, store: DedupStore | None = None):
        self.settings = settings
        self.client = NSEClient(index=settings.nse_index)
        self.store = store or DedupStore()
        self.bot = TelegramBot(settings.telegram_token, settings.telegram_chat_id)

    def run_once(self) -> List[ProcessedAlert]:
        announcements = self.client.fetch_announcements()
        fresh = [a for a in announcements if not self.store.seen(a.raw_id)]
        logging.info("Fetched announcements", extra={"total": len(announcements), "fresh": len(fresh)})
        processed: List[ProcessedAlert] = []
        for ann in fresh:
            try:
                processed_alert = self._process_announcement(ann)
                self.bot.send_alert(processed_alert)
                processed.append(processed_alert)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to process announcement", exc_info=exc)
        self.store.mark([a.raw_id for a in fresh])
        return processed

    def _process_announcement(self, ann: Announcement) -> ProcessedAlert:
        pdf_path = None
        pdf_text = ann.description
        if ann.pdf_url:
            pdf_path = download_pdf(ann.pdf_url, session=self.client.session)
            if pdf_path:
                try:
                    pdf_text = extract_pdf_text(pdf_path)
                finally:
                    import os

                    if pdf_path and os.path.exists(pdf_path):
                        os.remove(pdf_path)
        summary, impact, confidence = summarize_and_classify(
            text=pdf_text,
            company=ann.company,
            headline=ann.subject,
            api_key=self.settings.xai_api_key,
            mock=self.settings.mock_llm,
        )
        return ProcessedAlert(
            company=ann.company,
            headline=ann.subject,
            summary=summary,
            impact=impact,
            confidence=confidence,
            time=ann.time,
            pdf_url=ann.pdf_url,
            symbol=ann.symbol,
        )
