import asyncio
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.database import Database
from nse_monitor.report_builder import ReportBuilder

logging.basicConfig(level=logging.INFO)


class DummyBot:
    def send_report(self, report_text):
        return True

    def _send_raw(self, chat_id, text, reply_markup=None):
        return True


class DummyLLM:
    async def summarize_morning_batch(self, items):
        return {
            "theme": "Market Update",
            "summary": "Test summary",
            "sentiment": "Neutral",
        }


async def _fake_indices():
    return {"GIFT Nifty": "0", "Dow Jones": "0", "Nasdaq": "0"}


async def _fake_bulk():
    return {"deals": [], "recap_date": "N/A", "actual_date": "N/A", "is_stale": True}


def test_report_builder_generates_text():
    db = Database()
    builder = ReportBuilder(DummyBot(), db, DummyLLM())
    # Monkeypatch async sources to avoid network calls
    builder.global_source.fetch_indices = _fake_indices
    report = asyncio.run(builder.build_pre_market_report(hours=1))
    assert isinstance(report, str)
    assert "NSE PULSE" in report
