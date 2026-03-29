import logging
import json
import requests
import time
import os
import re
try:
    from nse_monitor.config import SARVAM_API_KEY
except ImportError:
    SARVAM_API_KEY = None

# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# THE FULL 22-RULE INSTITUTIONAL PROMPT TEMPLATE (v1.0)
# ─────────────────────────────────────────────────────────────────────────────
INSTITUTIONAL_PROMPT = """
ROLE: Lead Quantitative Strategist, NSE Institutional Desk (Top-Tier Hedge Fund)
TASK: Analyze this market news/filing with MAXIMUM PRECISION for immediate institutional impact.

══════════════════════════════════════════════════════════════
THE 22-RULE INSTITUTIONAL INTELLIGENCE ENGINE (v1.0)
══════════════════════════════════════════════════════════════

RULE 1 — NO-FOMO POLICY:
  If the event has ALREADY occurred/concluded (past tense), assign impact_score: 0.
  EXCEPTION: Dividends, Bonus Issues, and Stock Splits are VALID even if declared in the past, provided the EX-DATE is in the future.
  Valid triggers are FUTURE-ONLY: Upcoming orders, prospective deals, pending approvals.

RULE 2 — FORWARD-LOOKING FILTER:
  Keywords that indicate high-value future triggers:
  "wins order", "bags deal", "awarded contract", "receives LOI", "signs MOU",
  "FDA approval", "merger announced", "acquisition", "JV formation", "capacity expansion".

RULE 3 — SOURCE-AWARE INTELLIGENCE:
  - NSE Official Filings: Trust fully. Score >= 5 is significant.
  - Media (ET/Moneycontrol): Be EXTREMELY STRICT. Only score >= 8 if event is definitively confirmed.
  - SME Segment: Apply same rules but flag is_sme = true.

RULE 4 — CRORE VALUE MULTIPLIER:
  - Deal > 500 Cr for Large Cap: +2 boost to score.
  - Deal > 100 Cr for Mid/SmallCap: +2 boost to score.
  - Deal < 10 Cr: Automatic rejection unless sector-critical.

RULE 5 — CORPORATE ACTION PRECISION:
  Accept ONLY if Ex-Date is in the FUTURE:
  - Dividend (>5% yield of face value): Score 5-6.
  - Bonus Issue, Stock Split: Score 6-7.
  - Buyback (>10% of equity): Score 7-8.
  - Rights Issue: Score 4-5.

RULE 6 — GOVERNANCE HIERARCHY:
  - CEO/MD/CFO Resignation (sudden, not retirement): Score 7, Bearish.
  - CEO/MD Appointment (new strategic hire): Score 6, Bullish.
  - Independent Director changes: Reject (score 0).
  - Auditor Resignation (Big 4): Score 6, Bearish.
  - Routine shareholding/trading window: Score 0.

RULE 7 — DEBT & CREDIT INTELLIGENCE:
  - Credit Rating Upgrade (CRISIL/ICRA/CARE): Score 6, Bullish.
  - Credit Rating Downgrade: Score 7, Bearish. URGENT.
  - NCD/Bond issuance > 500 Cr: Score 5, Neutral.
  - Loan default notice / NPA: Score 8, Bearish. CRITICAL.

RULE 8 — LEGAL & REGULATORY:
  - SEBI enquiry/show-cause notice: Score 7, Bearish.
  - CBI/ED raid or arrest: Score 9, Bearish. CRITICAL.
  - Favourable court ruling: Score 6, Bullish.
  - Routine patent filing: Score 3, Neutral.

RULE 9 — SECTOR INTELLIGENCE:
  - Pharma: USFDA approval/rejection is HIGH IMPACT (Score 8-9).
  - Infra/Defence: Government tender wins > 200 Cr are HIGH IMPACT (Score 7+).
  - Banking: RBI licence grant/cancel, NPA data are CRITICAL.
  - IT: Large Multi-year deal > 500 Cr is HIGH IMPACT.
  - Auto: Production numbers, EV launch/partnership.
  - Real Estate: Land acquisition > 100 Cr, RERA registration.

RULE 10 — PROMOTER ACTIVITY:
  - Promoter buying > 1% stake (Open Market): Score 6, Bullish.
  - Promoter pledging > 20% holding: Score 7, Bearish.
  - Promoter selling large stake: Score 7, Bearish.

RULE 11 — FII/DII INTELLIGENCE:
  - FII bulk buy > 1% equity: Score 6, Bullish.
  - FII bulk sell > 1% equity: Score 6, Bearish.
  - DII accumulation: Score 4, Bullish.

RULE 12 — EARNINGS INTELLIGENCE:
  - Quarterly results: Score only if PAT is > 20% surprise vs estimates.
  - Annual results with strong guidance: Score 6-7.
  - Profit warning / downgrade guidance: Score 7-8, Bearish.

RULE 13 — JOINT VENTURES & PARTNERSHIPS:
  - JV with Global Fortune 500 company: Score 7-8, Bullish.
  - Strategic MOU (not binding): Score 4-5, Bullish (low confidence).
  - Technology licencing agreement: Score 5-6, Bullish.

RULE 14 — EXCLUSION LIST (Score 0 immediately):
  Board meeting intimation, Record date for AGM, Postal ballot results,
  Name change announcements, Registered office change, ESOP grants (routine),
  Shareholding pattern >1%/<1% threshold crossing (unless promoter-driven),
  Compliance certificates, Annual report filing, Demerger (if already known).

RULE 15 — TIMING & MARKET STATUS CONTEXT:
  - If MARKET OPEN and news is < 3 minutes old: MAXIMUM URGENCY. Flag time_critical = true.
  - If MARKET OPEN and news is 3-30 minutes old: Normal urgency.
  - If MARKET CLOSED (weekend/night): Focus on "Open Gap" potential. Flag expected_move carefully.

RULE 16 — DEDUPLICATION AWARENESS:
  If filing appears to be a duplicate or clarification of prior news, reduce score by 3.
  Look for keywords: "correction to", "amendment to", "in continuation of".

RULE 17 — MULTI-ITEM CONSOLIDATION:
  If multiple filings from same company in the same cycle, analyze collectively.
  Aggregate context text for a holistic view.

RULE 18 — INTRADAY vs POSITIONAL CLASSIFICATION:
  - expected_move = "Intraday" if event is a sudden shock (Legal/Governance/Pharma FDA).
  - expected_move = "Positional" if event has multi-day duration (Order win, JV, Expansion).
  - expected_move = "Long-Term" if event affects structural value (Merger, Buyback, Demerger).

RULE 19 — GLOBAL LINKAGE:
  Check if news is linked to global macro (e.g., US rates, China slowdown, Oil prices).
  If yes, add global_linkage = true in output.

RULE 20 — SME SEGMENT FLAG:
  For SME segment stocks, flag is_sme = true.
  Apply same scoring but note that liquidity is low and volatility is extreme.

RULE 21 — SECTOR SENTIMENT BOOST:
  If the sector is currently in a BULL RUN (e.g., Defence in 2024-25),
  boost impact_score by 1 for positive triggers in that sector.

RULE 22 — CRORE VALUE INJECTION:
  Always scan the filing text for any numerical amount.
  {amount_hint}

══════════════════════════════════════════════════════════════
CONTEXT VARIABLES
══════════════════════════════════════════════════════════════
MARKET STATUS: {market_status}
SOURCE TYPE:   {source_name}
{source_bias}
DETECTED DEAL AMOUNT: {amount_found}

FILING/NEWS DATA:
{context_text}

══════════════════════════════════════════════════════════════
OUTPUT FORMAT — STRICT JSON ONLY. NO PROSE. NO MARKDOWN.
══════════════════════════════════════════════════════════════
{{
  "valid_event": boolean,
  "symbol": "NSE_SYMBOL or UNKNOWN",
  "trigger": "Short 1-line trigger in plain English",
  "impact_score": integer (1-10),
  "is_big_ticket": boolean,
  "is_sme": boolean,
  "time_critical": boolean,
  "global_linkage": boolean,
  "sentiment": "Bullish | Bearish | Neutral",
  "sector": "SECTOR_NAME",
  "expected_move": "Intraday | Positional | Long-Term",
  "key_insight": "1 professional sentence on WHY this matters",
  "summary": "2-sentence executive summary"
}}
"""


class LLMProcessor:
    def __init__(self):
        self.sarvam_key = SARVAM_API_KEY

        if self.sarvam_key:
            logger.info("✅ AI Engine (Sarvam HTTP Core): Ready — 22-Rule Mode Active")
        else:
            logger.error("SARVAM_API_KEY is missing in .env")

    def analyze_single_event(self, event_group, market_status="CLOSED", source_name="NSE"):
        """Analyzes a single event using the full 22-Rule Institutional Engine."""
        if not self.sarvam_key:
            return None

        # Build consolidated context
        lead_news = event_group[0]
        context_text = f"HEADLINE: {lead_news['headline']}\nSUMMARY: {lead_news.get('summary', '')}"

        # Rule #3: Source bias
        source_bias = ""
        if source_name not in ("NSE", "SME"):
            source_bias = (
                "⚠️ MEDIA SOURCE DETECTED: Be EXTREMELY STRICT. "
                "Only score >= 8 if event is definitively confirmed by the article."
            )

        # Rule #22: Amount detection
        amount_found = self._extract_amount(context_text)
        amount_hint = (
            f"Detected amounts in filing: {amount_found}. Apply Rule #4 accordingly."
            if amount_found
            else "No specific amount detected."
        )

        prompt = INSTITUTIONAL_PROMPT.format(
            market_status=market_status,
            source_name=source_name,
            source_bias=source_bias,
            amount_found=amount_found or "None detected",
            amount_hint=amount_hint,
            context_text=context_text
        )

        return self._run_prompt(prompt)

    def _run_prompt(self, prompt):
        """v1.4.2: Robust direct-request implementation (Bypassing SDK attribute errors)."""
        if not self.sarvam_key:
            return None
            
        url = "https://api.sarvam.ai/v1/chat/completions"
        headers = {
            "api-subscription-key": self.sarvam_key,
            "Content-Type": "application/json"
        }
        payload = {
            "model": "sarvam-30b",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior quantitative analyst at an Indian hedge fund. "
                        "You MUST return ONLY valid JSON. No markdown, no prose, no explanation. "
                        "Apply all 22 institutional rules rigorously."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        
        for attempt in range(3):
            try:
                # v1.4.2: Direct API call for stability
                logger.info(f"📡 Dispatching Institutional Prompt to Sarvam AI Core (Attempt {attempt + 1}/3)...")
                r = requests.post(url, headers=headers, json=payload, timeout=60)
                r.raise_for_status()
                data = r.json()
                
                content_raw = data['choices'][0]['message']['content']

                if not content_raw:
                    logger.warning("Sarvam returned empty response.")
                    return None

                return self._robust_json_parse(content_raw)

            except Exception as e:
                logger.error(f"Sarvam AI attempt {attempt + 1} failed: {e}", exc_info=False)
                if attempt < 2:
                    import time
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return None

    def _robust_json_parse(self, raw_text):
        """Extracts and repairs JSON from LLM output."""
        if not raw_text:
            return None

        cleaned = raw_text.strip()

        # Strip markdown
        if "```" in cleaned:
            cleaned = re.sub(r"```json|```", "", cleaned).strip()

        start = cleaned.find("{")
        if start == -1:
            logger.warning(f"No JSON start found in: {cleaned[:100]}...")
            return None

        end = cleaned.rfind("}")
        if end == -1 or end < start:
            logger.warning("Truncated JSON detected. Attempting repair...")
            json_str = cleaned[start:] + "\n}"
        else:
            json_str = cleaned[start:end + 1]

        # Clean trailing commas
        json_str = re.sub(r",\s*([\]\}])", r"\1", json_str)

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.error("JSON Parse failed after repair. Attempting regex extraction...")
            return self._regex_extract(json_str)

    def _extract_amount(self, text):
        """Finds Crore/Billion values in filing text."""
        if not text:
            return None
        matches = re.findall(
            r'([\d,]+(?:\.\d+)?)\s*(?:Cr|Crore|Billion|Million|Rs\.?|INR|Lakh)',
            text, re.IGNORECASE
        )
        return ", ".join(matches[:5]) if matches else None

    def _regex_extract(self, text):
        """Last-ditch regex extraction when JSON is broken."""
        try:
            valid = "true" in text.lower()
            symbol_match = re.search(r'"symbol":\s*"([^"]+)"', text)
            score_match = re.search(r'"impact_score":\s*(\d+)', text)
            trigger_match = re.search(r'"trigger":\s*"([^"]+)"', text)
            sentiment_match = re.search(r'"sentiment":\s*"([^"]+)"', text)

            if symbol_match and score_match:
                return {
                    "valid_event": valid,
                    "symbol": symbol_match.group(1),
                    "impact_score": int(score_match.group(1)),
                    "trigger": trigger_match.group(1) if trigger_match else "Analysis Partial",
                    "sentiment": sentiment_match.group(1) if sentiment_match else "Neutral",
                    "is_big_ticket": False,
                    "is_sme": False,
                    "time_critical": False,
                    "global_linkage": False,
                    "sector": "Unknown",
                    "expected_move": "Intraday",
                    "key_insight": "Partial extraction due to JSON error.",
                    "summary": "Full analysis failed. Critical parameters recovered."
                }
        except Exception:
            pass
        return None

    def summarize_morning_batch(self, analyzed_items):
        """Creates an executive summary of all off-market news for the 08:30 AM Morning Report."""
        if not self.sarvam_key or not analyzed_items:
            return {}

        news_list_str = ""
        for i, item in enumerate(analyzed_items):
            if isinstance(item, dict):
                headline = item.get("headline", "N/A")
                source = item.get("source", "N/A")
                url = item.get("url", "#")
                impact = item.get("impact_score", 0)
            else:
                # Legacy tuple support
                headline, _, source, url, impact = item[0], item[1], item[2], item[3], item[4]

            news_list_str += f"{i + 1}. [{source}] {headline} (Impact: {impact}/10) | {url}\n"

        prompt = f"""
You are the Chief Intelligence Officer of a top-tier Indian Hedge Fund.
Synthesize these off-market NSE news events into a "MORNING MARKET INTELLIGENCE BRIEF" for the 09:15 open.

OFF-MARKET EVENTS:
{news_list_str}

REQUIREMENTS:
1. CRITICAL NARRATIVE: The single most important macro/micro theme.
2. SECTOR FOCUS: Which sectors (Banking, IT, Pharma, Defence, Auto) are likely most active.
3. SENTIMENT: Overall bias for the opening bell.
4. TONE: Professional, succinct, institutional. No fluff.

RESPONSE (STRICT JSON ONLY):
{{
  "theme": "Top Theme Headline (5-8 words)",
  "summary": "3-4 sentences of high-density synthesis.",
  "sectors_to_watch": "Sector1, Sector2, Sector3",
  "sentiment": "Positive | Negative | Cautious | Neutral"
}}
"""
        return self._run_prompt(prompt) or {}

    # ── Backward-compatibility wrappers ──────────────────────────────────────
    def analyze_news_batch(self, news_items, market_status="CLOSED"):
        results = []
        for item in news_items:
            res = self.analyze_single_event([item], market_status=market_status, source_name=item.get("source", "NSE"))
            if res and res.get("valid_event", False):
                res["indices"] = [0]
                results.append(res)
        return results

    def analyze_news(self, company, text, source_type="corporate", market_status="CLOSED"):
        item = {"source": source_type, "headline": company, "summary": text}
        result = self.analyze_single_event([item], market_status=market_status, source_name=source_type)
        if result and result.get("valid_event", False):
            return result
        return self._fallback(company, "Rejection/Invalid Event")

    def _fallback(self, company, error=""):
        return {
            "symbol": company,
            "headline": "Analysis Offline",
            "summary": "Could not analyze.",
            "sentiment": "Neutral",
            "impact_score": 0,
            "valid_event": False,
            "is_sme": False,
            "is_big_ticket": False,
            "time_critical": False,
            "global_linkage": False
        }
