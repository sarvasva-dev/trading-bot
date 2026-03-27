import logging
import json
import requests
import time
import os
import re
try:
    from sarvamai import SarvamAI
except ImportError:
    SarvamAI = None
try:
    from nse_monitor.config import SARVAM_API_KEY
except ImportError:
    SARVAM_API_KEY = None

# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class LLMProcessor:
    def __init__(self):
        # Only Sarvam AI (Indian)
        self.sarvam_key = SARVAM_API_KEY
        self.sarvam_client = None
        
        if not SarvamAI:
             logger.error("SarvamAI SDK not installed. Please install 'sarvamai'.")
             return

        if self.sarvam_key:
            try:
                self.sarvam_client = SarvamAI(api_subscription_key=self.sarvam_key)
                logger.info(" AI Engine (Sarvam): Ready")
            except Exception as e:
                logger.error(f"Sarvam Init Error: {e}")
        else:
            logger.error("SARVAM_API_KEY is missing in config.py")

    def analyze_single_event(self, event_group, market_status="CLOSED", source_name="NSE"):
        """
        Analyzes a single event group using the 22-rule High-Precision Engine.
        """
        if not self.sarvam_client: return None

        # RULE #17: Consolidate context
        lead_news = event_group[0]
        context_text = f"HEADLINE: {lead_news['headline']}\nSUMMARY: {lead_news['summary']}"
        
        # RULE #2: Persona | RULES #5-13, #16: Institutional logic
        # RULE #15: Source-Aware Tiered Intelligence
        source_bias = ""
        if source_name != "NSE":
            source_bias = "NOTE: This news is from a MEDIA SOURCE (ET/MC). Be EXTREMELY STRICT. Reject unless it is a definitive market-moving event."
        
        # RULE #22: Crore-Value Injection
        amount_found = self._extract_amount(context_text)
        amount_hint = f"DETECTED AMOUNT: {amount_found}" if amount_found else ""

        prompt = f"""
ROLE: Lead Quantitative Strategist (NSE Institutional Desk)
TASK: Analyze this market news for IMMEDIATE institutional impact.

22-RULE INSTITUTIONAL LOGIC:
1. NO-FOMO POLICY: If the news describes an event that has ALREADY occurred or concluded, reject it (impact_score: 0).
2. FORWARD-LOOKING ONLY: Focus on future triggers (Orders, Deals, Mergers, FDA, Earnings surprises).
3. SOURCE-AWARE THRESHOLD: 
   - NSE Filings (Official): Score >= 5 is considered significant.
   - Media (ET/Moneycontrol): Score >= 8 is mandatory for alert.
4. CRORE-VALUE MULTIPLIER: If the deal value is >500Cr, boost its importance.

{source_bias}
{amount_hint}

EXCLUSIONS (Score 0): Board meets (general), Shareholding updates, Trading window, Resignations (except CEO/CFO).

MARKET STATUS: {market_status}
SOURCE TYPE: {source_name}

FILING/NEWS DATA:
{context_text}

OUTPUT FORMAT (STRICT JSON ONLY):
{{
  "valid_event": boolean,
  "symbol": "STOCK_SYMBOL",
  "trigger": "Short 1-line trigger",
  "impact_score": integer (1-10),
  "is_big_ticket": boolean (True if deal > 100Cr),
  "sentiment": "Bullish/Bearish/Neutral",
  "sector": "SECTOR_NAME",
  "expected_move": "Intraday/Positional",
  "key_insight": "Professional insight",
  "summary": "2-sentence executive summary"
}}
"""
        return self._run_prompt(prompt)

    def _run_prompt(self, prompt):
        try:
            # Call Sarvam
            response = self.sarvam_client.chat.completions(
                model="sarvam-30b",
                messages=[
                    {"role": "system", "content": "You are a financial analyst. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            )
            content_raw = response.choices[0].message.content
            
            if not content_raw: 
                logger.warning("Sarvam returned empty response.")
                return None
            
            # Robust JSON Extraction (Rule #22 Hardening)
            return self._robust_json_parse(content_raw)
            
        except Exception as e:
            logger.error(f"Sarvam AI failed: {e}", exc_info=True)
            return None

    def _robust_json_parse(self, raw_text):
        """Extracts and repairs JSON from LLM output, handling truncation and noise."""
        if not raw_text: return None
        
        cleaned = raw_text.strip()
        
        # 1. Strip Markdown
        if "```" in cleaned:
            cleaned = re.sub(r"```json|```", "", cleaned).strip()
            
        # 2. Find first { and last }
        start = cleaned.find("{")
        if start == -1:
            logger.warning(f"No JSON start found in: {cleaned[:100]}...")
            return None
            
        # Try to find last }
        end = cleaned.rfind("}")
        
        # 3. Handle Truncation: If no closing brace, try to repair
        if end == -1 or end < start:
            logger.warning("Truncated JSON detected. Attempting repair...")
            json_str = cleaned[start:]
            # Basic repair: Add missing closing brace
            json_str += "\n}"
        else:
            json_str = cleaned[start:end+1]
            
        # 4. Clean trailing commas (common in AI output)
        json_str = re.sub(r",\s*([\]\}])", r"\1", json_str)
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 5. Last Resort: Regex Extraction for critical fields
            logger.error("JSON Parse failed after repair. Attempting Regex extraction...")
            return self._regex_extract(json_str)

    def _extract_amount(self, text):
        """Helper to find Crore/Billion values for AI hint."""
        if not text: return None
        matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:Cr|Crore|Billion|Million|Rs|INR)', text, re.IGNORECASE)
        return ", ".join(matches) if matches else None

    def _regex_extract(self, text):
        """Last-ditch effort to get fields if JSON is totally broken."""
        try:
            valid = "true" in text.lower()
            symbol_match = re.search(r'"symbol":\s*"([^"]+)"', text)
            score_match = re.search(r'"impact_score":\s*(\d+)', text)
            trigger_match = re.search(r'"trigger":\s*"([^"]+)"', text)
            
            if symbol_match and score_match:
                return {
                    "valid_event": valid,
                    "symbol": symbol_match.group(1),
                    "impact_score": int(score_match.group(1)),
                    "trigger": trigger_match.group(1) if trigger_match else "Analysis Success (Regex Extracted)",
                    "sentiment": "Neutral",
                    "summary": "Full analysis failed, but critical parameters recovered."
                }
        except: pass
        return None

    def summarize_morning_batch(self, analyzed_items):
        """
        Creates a high-level executive summary of all off-market news (weekend/overnight).
        Used specifically for the 08:30 AM Morning Intel Report.
        """
        if not self.sarvam_client or not analyzed_items:
            return None

        # Build list of news with their scores
        news_list_str = ""
        for i, item in enumerate(analyzed_items):
            # item is a tuple or dict depending on DB query
            if isinstance(item, tuple):
                headline, summary, source, url, impact = item
            else:
                headline = item.get("headline")
                summary = item.get("summary")
                source = item.get("source")
                url = item.get("url")
                impact = item.get("impact_score")

            news_list_str += f"{i+1}. [{source}] {headline} (Impact: {impact}/10) | Source: {url}\n"

        prompt = f"""
You are the Chief Intelligence Officer for a top-tier Indian Hedge Fund.
Task: Synthesize the following off-market news events into a single "EXECUTIVE MARKET PREVIEW" for the 09:15 open.

OFF-MARKET NEWS BACKLOG:
{news_list_str}

REQUIREMENTS:
1. **CRITICAL NARRATIVE**: Identify the single most important theme (e.g., "Macro weakness led by US Fed", "Positive Corporate Earnings week").
2. **SECTOR FOCUS**: Mention which sectors (Banking, IT, Auto, etc.) are likely to see the most action.
3. **TONE**: Professional, urgent, and concise.
4. **FORMAT**: Markdown for Telegram. Use Bold for impact.

RESPONSE FORMAT (JSON):
{{
  "theme": "Top Theme Headline",
  "summary": "3-4 sentences of deep synthesis.",
  "sectors_to_watch": "Sector 1, Sector 2",
  "sentiment": "Positive | Negative | Cautious"
}}
"""
        return self._run_prompt(prompt)

    # Backward compatibility / Batch wrapper (treats single item as event)
    def analyze_news_batch(self, news_items, recent_news=None):
        results = []
        for item in news_items:
             res = self.analyze_single_event([item], recent_news)
             if res and res.get("valid_event", False):
                 res["indices"] = [0] 
                 results.append(res)
        return results

    def analyze_news(self, company, text, source_type="corporate", skip_ai=False, recent_news=None):
        item = {"source": source_type, "headline": company, "summary": text}
        result = self.analyze_single_event([item], recent_news=recent_news)
        if result and result.get("valid_event", False):
             return result
        return self._fallback(company, "Rejection/Invalid Event")

    def _fallback(self, company, error=""):
        return {
            "symbol": company,
            "headline": "Analysis Offline",
            "summary": f"Could not analyze.",
            "sentiment": "Neutral",
            "impact_score": 0,
            "valid_event": False
        }
