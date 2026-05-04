import logging
import json
import aiohttp
import asyncio
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

# Keep model pinned to 30B unless an intentional code change is made.
SARVAM_MODEL = "sarvam-30b"

# ── INSTITUTIONAL PROMPT TEMPLATE (v1.0) ──────────────────────────────────────
INSTITUTIONAL_PROMPT = """
ROLE: Lead Quantitative Strategist, Bulkbeat TV Institutional Desk (Top-Tier Hedge Fund)
TASK: Analyze this market news/filing for ACTIONABLE INTELLIGENCE.

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

RULE 23 — MOMENTUM & PRICE ACTION SHOCK:
  If the {momentum_found} or text confirms a "jump > 10%", "Upper Circuit", "52-week High", or "Multi-fold rally":
  - YOU MUST assign impact_score: 8 or 9 (Crucial for potential news).
  - This overrides Rule #3 (media skepticism). Real price action is the ultimate confirmation.
  - sentiment: Bullish (if positive) or Bearish (if negative).

══════════════════════════════════════════════════════════════
CONTEXT VARIABLES
══════════════════════════════════════════════════════════════
MARKET STATUS: {market_status}
SOURCE TYPE:   {source_name}
{source_bias}
DETECTED DEAL AMOUNT: {amount_found}
DETECTED MOMENTUM:    {momentum_found}

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
        self.session = None
        self.lock = asyncio.Lock()
        if self.sarvam_key:
            logger.info("✅ AI Engine (Sarvam Async Core): Ready — 22-Rule Mode Active")
        else:
            logger.error("SARVAM_API_KEY is missing in .env")

    async def ensure_session(self):
        """Ensures a pooled aiohttp session is active."""
        if self.session is None or self.session.closed:
            async with self.lock:
                if self.session is None or self.session.closed:
                    self.session = aiohttp.ClientSession()
                    logger.debug("AI Engine: Persistent session created.")
        return self.session

    async def close(self):
        """Closes the persistent session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("AI Engine: Persistent session closed.")

    async def analyze_single_event(self, event_group, market_status="CLOSED", source_name="NSE"):
        """Analyzes a single event using the full 22-Rule Institutional Engine (Async)."""
        if not self.sarvam_key:
            return None

        lead_news = event_group[0]
        headline = self._sanitize_for_prompt(lead_news.get('headline', ''))
        summary = self._sanitize_for_prompt(lead_news.get('summary', ''), max_len=1000)
        context_text = f"HEADLINE: {headline}\nSUMMARY: {summary}"

        source_bias = ""
        # Rule: Only NSE/Official sources bypass the strictly-skeptical media filter
        if (source_name or "NSE").upper() not in ["NSE", "NSE_SME", "NSE_BULK"]:
            source_bias = (
                "⚠️ MEDIA SOURCE DETECTED: Be EXTREMELY STRICT. "
                "Only score >= 8 if event is definitively confirmed by the article."
            )

        amount_found = self._extract_amount(context_text)
        amount_hint = (
            f"Detected amounts in filing: {amount_found}. Apply Rule #4 accordingly."
            if amount_found
            else "No specific amount detected."
        )

        momentum_found = self._extract_momentum(context_text)
        momentum_hint = (
            f"Detected momentum signals: {momentum_found}. Apply Rule #23 (Booster) immediately."
            if momentum_found
            else "No specific price action momentum detected."
        )

        # Inject Symbol into Context for better Rule #4 and Rule #20 application
        symbol = lead_news.get('symbol', 'UNKNOWN')
        context_text = f"TICKER/SYMBOL: {symbol}\n{context_text}"

        prompt = INSTITUTIONAL_PROMPT.format(
            market_status=market_status,
            source_name=source_name,
            source_bias=source_bias,
            amount_found=amount_found or "None detected",
            amount_hint=amount_hint,
            momentum_found=momentum_hint,
            context_text=context_text
        )

        return await self._run_prompt(prompt)

    async def _run_prompt(self, prompt):
        """v1.5.0: Async implementation for Sarvam AI Core."""
        if not self.sarvam_key:
            return None
            
        url = "https://api.sarvam.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.sarvam_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": SARVAM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Senior Quant Analyst Mode. Output ONLY valid JSON.\n"
                        "Rules:\n"
                        "1. Start response with '{' and end with '}'. No prose.\n"
                        "2. Strict 22-rule institutional logic.\n"
                        "3. If news is routine/minor, score=0.\n\n"
                        "JSON STRUCTURE:\n"
                        "{\n"
                        "  \"valid_event\": true,\n"
                        "  \"symbol\": \"TICKER\",\n"
                        "  \"trigger\": \"Short 1-line trigger\",\n"
                        "  \"impact_score\": 1-10,\n"
                        "  \"sentiment\": \"Bullish|Bearish|Neutral\",\n"
                        "  \"summary\": \"Executive summary\"\n"
                        "}"
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 4096
        }
        
        await self.ensure_session()
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                logger.info(f"📡 AI Dispatch: Sarvam Async Core (Attempt {attempt + 1}/{max_attempts})...")
                async with self.session.post(url, headers=headers, json=payload, timeout=120) as r:
                    status = r.status
                    text = await r.text()

                    if status != 200:
                        snippet = text[:1000] if text else "<no-body>"
                        logger.error(f"Sarvam API Error: {status} - body: {snippet}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep((2 ** attempt) + 0.5)
                        continue

                    # Try to parse JSON body safely and log raw response for debugging
                    try:
                        data = json.loads(text)
                    except Exception:
                        logger.warning("Sarvam returned non-JSON body; storing raw text for inspection.")
                        logger.debug(f"Sarvam raw response body (truncated 2000): {text[:2000]}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep((2 ** attempt) + 0.5)
                            continue
                        return None

                    # Navigate into expected structure, but guard against missing keys
                    try:
                        message = data['choices'][0]['message']
                        content_raw = message.get('content') or ''
                        reasoning = message.get('reasoning_content') or ''
                        
                        # v1.5.1: If content is empty but reasoning has content (common in thinking models), use reasoning
                        if not content_raw.strip() and reasoning and reasoning.strip():
                            content_raw = reasoning
                        
                        # Noisy warning moved to debug; regex fallback handles it
                        if "{" not in content_raw:
                           logger.debug("No JSON brackets found in raw output; relying on regex fallback.")
                           
                    except Exception:
                        logger.error("Sarvam response JSON missing expected keys.")
                        logger.debug(f"Sarvam JSON keys: {list(data.keys())} | raw: {text[:2000]}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep((2 ** attempt) + 0.5)
                            continue
                        return None

                    if not content_raw or not content_raw.strip():
                        logger.warning("Sarvam returned empty response content.")
                        logger.debug(f"Sarvam full JSON (truncated 2000): {text[:2000]}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep((2 ** attempt) + 0.5)
                            continue
                        return None

                    logger.debug(f"Sarvam content_raw (truncated 2000): {content_raw[:2000]}")
                    parsed = self._robust_json_parse(content_raw)
                    if parsed is None:
                        logger.warning("Sarvam content could not be parsed to JSON.")
                        logger.debug(f"Content causing parse failure (truncated 2000): {content_raw[:2000]}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep((2 ** attempt) + 0.5)
                            continue
                        return None

                    return parsed

            except asyncio.TimeoutError:
                logger.error(f"Sarvam AI attempt {attempt + 1} timed out.")
                if attempt < max_attempts - 1:
                    await asyncio.sleep((2 ** attempt) + 0.5)
                continue
            except Exception as e:
                logger.exception(f"Sarvam AI attempt {attempt + 1} failed with exception: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep((2 ** attempt) + 0.5)
                continue

        return None

    def _sanitize_for_prompt(self, text, max_len=500):
        """Rule #22: Security Sanitization to prevent LLM Prompt Injection."""
        if not text: return ""
        # 1. Remove control characters (prevent whitespace manipulation)
        text = re.sub(r'[\x00-\x1f\x7f]', ' ', str(text))
        # 2. Block known prompt injection keywords (case-insensitive)
        text = re.sub(r'(?i)(ignore|forget|override|disregard|system|instruction).{0,30}(rule|prompt|instruction|guideline)', '[FILTERED]', text)
        return text[:max_len].strip()

    def _robust_json_parse(self, raw_text):
        """Extracts and repairs JSON from LLM output."""
        if not raw_text: return None
        
        try:
            # Clean possible markdown and thinking tags
            cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
            cleaned = re.sub(r'```json|```', '', cleaned).strip()
            
            # Find the actual JSON block
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            
            if start != -1:
                if end != -1 and end > start:
                    json_str = cleaned[start:end+1]
                else:
                    # Truncated recovery
                    json_str = cleaned[start:]
                    if not json_str.endswith('}'):
                        json_str += ' }'
                
                # Cleanup trailing commas and common errors
                json_str = re.sub(r',\s*([\]\}])', r'\1', json_str)
                
                try:
                    return json.loads(json_str)
                except:
                    # Final attempt: manual regex extraction
                    return self._regex_extract(cleaned)
            
            return self._regex_extract(cleaned)
        except Exception:
            return self._regex_extract(raw_text)

    def _extract_amount(self, text):
        """Finds Crore/Billion values in filing text."""
        if not text: return None
        matches = re.findall(
            r'([\d,]+(?:\.\d+)?)\s*(?:Cr|Crore|Billion|Million|Rs\.?|INR|Lakh)',
            text, re.IGNORECASE
        )
        return ", ".join(matches[:5]) if matches else None

    def _extract_momentum(self, text):
        """v2.1: Deterministic extraction of price-action shocks (% move, circuits)."""
        if not text: return None
        signals = []
        
        # 1. Percentage jumps (Focus on >10%)
        percent_matches = re.findall(r'(\d+)\s*%', text)
        for p in percent_matches:
            if int(p) >= 10:
                signals.append(f"{p}% jump")
        
        # 2. Key momentum terminology
        keywords = ["upper circuit", "lower circuit", "52-week high", "52-week low", "multi-year high", "record high", "jumped", "surged"]
        for kw in keywords:
            if kw in text.lower():
                signals.append(kw.title())
                
        return ", ".join(signals) if signals else None

    def _regex_extract(self, text):
        """Last-ditch regex extraction when JSON is broken."""
        try:
            # More aggressive regex extraction for cutoff texts
            sym = re.search(r'"symbol"\s*:\s*"([^"]+)"|symbol[:\s]+([A-Z0-9_]+)', text, re.IGNORECASE)
            sco = re.search(r'"impact_score"\s*:\s*"?(\d+)"?|impact_score[:\s]+"?(\d+)"?|score[:\s]+"?(\d+)"?', text, re.IGNORECASE)
            
            sen_match = re.search(r'Bullish|Bearish|Neutral', text, re.IGNORECASE)
            sentiment = sen_match.group(0).capitalize() if sen_match else "Neutral"
            
            valid = "valid_event" in text and ("true" in text[text.find("valid_event"):].lower()[:20] or "1" in text[text.find("valid_event"):].lower()[:20])
            if not valid and sco:
                 if int(sco.group(1) or sco.group(2) or sco.group(3)) > 0:
                     valid = True

            symbol_val = (sym.group(1) or sym.group(2)).strip() if sym else "UNKNOWN"
            score_val = int(sco.group(1) or sco.group(2) or sco.group(3)) if sco else 0

            return {
                "valid_event": valid,
                "symbol": symbol_val,
                "impact_score": score_val,
                "trigger": "Extracted via regex from partial response",
                "sentiment": sentiment,
                "is_big_ticket": False, "is_sme": False, "time_critical": False,
                "global_linkage": False, "sector": "Unknown", "expected_move": "Intraday",
                "key_insight": "Regex extraction fallback.", "summary": "Full analysis failed but core metrics extracted."
            }
        except Exception as e:
            logger.debug(f"Regex extract failed: {e}")
            pass
        
        # Prevent infinite retries by returning a safe neutral fallback
        return {
             "valid_event": False,
             "symbol": "UNKNOWN",
             "impact_score": 0,
             "trigger": "Unparseable LLM output",
             "sentiment": "Neutral",
             "is_big_ticket": False, "is_sme": False, "time_critical": False,
             "global_linkage": False, "sector": "Unknown", "expected_move": "Intraday",
             "key_insight": "Failed to parse.", "summary": "LLM output was completely unparseable."
        }

    async def summarize_morning_batch(self, analyzed_items):
        """v4.0: Creates an executive summary with hard caps and deterministic fallback (Async)."""
        if not self.sarvam_key or not analyzed_items: return {}

        # 1. Capping: Top 15 items only (by impact score)
        sorted_items = sorted(analyzed_items, key=lambda x: int(x.get("impact_score") or 0), reverse=True)[:15]

        news_list_str = ""
        for i, item in enumerate(sorted_items):
            # 2. Truncation: 300 chars max per item to save context
            headline = item.get("headline", "N/A")[:200]
            summary = item.get("summary", "N/A")[:300]
            source = item.get("source", "N/A")
            impact = item.get("impact_score", 0)
            news_list_str += f"{i + 1}. [{source}] {headline} (Impact: {impact}/10)\n   Summary: {summary}\n"

        prompt = f"""
        You are the Chief Intelligence Officer of a top-tier Indian Hedge Fund.
        Synthesize these off-market NSE news events into a "MORNING MARKET INTELLIGENCE BRIEF" for the 09:15 open.
        
        OFF-MARKET EVENTS (TOP {len(sorted_items)}):
        {news_list_str}
        
        RESPONSE (STRICT JSON):
        {{ "theme": "...", "summary": "...", "sectors_to_watch": "...", "sentiment": "..." }}
        """
        
        res = await self._run_prompt(prompt)
        
        # 3. Deterministic Fallback
        if not res:
            logger.warning("LLM Batch Summary failed. Using deterministic fallback.")
            top_headlines = [item.get("headline", "N/A") for item in sorted_items[:3]]
            return {
                "theme": "High-Impact Data Flow",
                "summary": f"Focus on {', '.join(top_headlines)} and related sector movements.",
                "sectors_to_watch": "Varies by ticker",
                "sentiment": "Mixed/Data-Driven"
            }
            
        return res

    # ── Backward-compatibility wrappers ──────────────────────────────────────
    async def analyze_news_batch(self, news_items, market_status="CLOSED"):
        results = []
        for item in news_items:
            res = await self.analyze_single_event([item], market_status=market_status, source_name=item.get("source", "NSE"))
            if res and res.get("valid_event", False):
                res["indices"] = [0]
                results.append(res)
        return results

    async def analyze_news(self, company, text, source_type="corporate", market_status="CLOSED"):
        item = {"source": source_type, "headline": company, "summary": text}
        result = await self.analyze_single_event([item], market_status=market_status, source_name=source_type)
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
