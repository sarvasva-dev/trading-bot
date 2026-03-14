import logging
from typing import Tuple

from openai import OpenAI


def summarize_and_classify(
    text: str,
    company: str,
    headline: str,
    api_key: str,
    mock: bool = False,
) -> Tuple[str, str, str]:
    if mock:
        return ("Mock summary", "Neutral", "0.50")
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )
    prompt = (
        "Summarize the following NSE corporate announcement in 2 sentences. "
        "Identify market impact as Bullish, Bearish, or Neutral. "
        "Return JSON with fields summary, impact, confidence (0-1).\n"
        f"Company: {company}\nHeadline: {headline}\nText:\n{text}"
    )
    try:
        completion = client.chat.completions.create(
            model="grok-4-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = completion.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001
        logging.exception("LLM call failed: %s", exc)
        raise
    return _parse_llm_response(content)


def _parse_llm_response(content: str) -> Tuple[str, str, str]:
    # Very light parser to avoid json import errors if the model returns minor prose.
    import json

    try:
        data = json.loads(content)
        return (
            str(data.get("summary", "")),
            str(data.get("impact", "Neutral")),
            str(data.get("confidence", "0.5")),
        )
    except Exception:
        # Fallback: attempt to heuristically split
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        summary = lines[0] if lines else ""
        impact = "Neutral"
        confidence = "0.5"
        for ln in lines:
            lower = ln.lower()
            if "bullish" in lower:
                impact = "Bullish"
            if "bearish" in lower:
                impact = "Bearish"
            if "confidence" in lower:
                digits = "".join(ch for ch in ln if ch.isdigit() or ch == ".")
                if digits:
                    confidence = digits
        return summary, impact, confidence
