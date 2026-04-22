import os
import asyncio
import pytest
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.llm_processor import LLMProcessor


@pytest.mark.integration
def test_sarvam_key():
    if not os.getenv("SARVAM_API_KEY", "").strip():
        pytest.skip("SARVAM_API_KEY not set")

    processor = LLMProcessor()
    async def _run():
        try:
            return await processor.analyze_news(
                company="TESTCO",
                text="Company wins confirmed Rs 500 crore order from PSU; execution starts next quarter.",
                source_type="NSE",
                market_status="OPEN",
            )
        finally:
            await processor.close()

    result = asyncio.run(
        _run()
    )
    assert isinstance(result, dict)
    assert "impact_score" in result
