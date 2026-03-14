from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Announcement:
    symbol: str
    company: str
    subject: str
    description: str
    time: datetime
    pdf_url: Optional[str]
    raw_id: str  # unique key from NSE (sm_pid or constructed)


@dataclass
class ProcessedAlert:
    company: str
    headline: str
    summary: str
    impact: str
    confidence: str
    time: datetime
    pdf_url: Optional[str]
    symbol: Optional[str] = None
