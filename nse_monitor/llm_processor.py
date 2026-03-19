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

    def analyze_single_event(self, event_items, recent_news=None, market_status="CLOSED"):
        """
        Analyzes a single event grouping (1-3 related news items).
        Performs merging, comparison, and intraday probability calculation.
        """
        if not self.sarvam_client:
            logger.error("Sarvam AI engine not initialized.")
            return None

        if not event_items:
            return None

        # Prepare context
        current_time_str = time.strftime("%H:%M")
        market_context_str = "MARKET IS OPEN - SPEED & ACCURACY CRITICAL" if market_status == "OPEN" else "POST-MARKET ANALYSIS"

        # Prepare news content string
        
        # Prepare news content string
        news_content_str = ""
        sources_list = []
        for i, item in enumerate(event_items):
            s_name = item.get("source", "Unknown")
            sources_list.append(s_name)
            news_content_str += f"""
--- REPORT {i+1} SOURCE: {s_name} ---
HEADLINE: {item.get("headline")}
SUMMARY/TEXT: {item.get("summary")}
URL: {item.get("url")}
-------------------------------------
"""
        
        sources_unique = list(set(sources_list))
        multi_source_flag = "YES" if len(sources_unique) > 1 else "NO"

        # --- PROMPT ENGINEERING ---
        prompt = f"""
You are a Lead Quantitative & Macro Strategist specialized in the Indian Equity Markets.
Task: Analyze this group of news reports representing a SINGLE EVENT.

CONTEXT:
Mode: {market_context_str}
Time: {current_time_str}
Sources Available: {", ".join(sources_unique)}
Multi-Source Cross-Check: {multi_source_flag}

NEWS REPORTS:
{news_content_str}

==================================================
STEP 1: MERGE & EXCLUDE
1. Fuse insights into one "Master Narrative".
2. EXCLUSIONS (CRITICAL):
   - REJECT if "Opinion" / "Market Commentary".
   - REJECT if older than 24h.

==================================================
STEP 2: PROBABILITY CALCULATION LOGIC
Objective: Estimate probability of significant intraday move (1-3%).

A. BASE PROBABILITY (From Impact Score 1-10):
   - Impact 9-10 -> 75%  (High Confidence)
   - Impact 7-8  -> 65%  (Good Setup)
   - Impact 5-6  -> 50%  (Possible Move)
   - Impact < 5  -> 10%  (Avoid)

B. ADJUSTMENTS (Add/Subtract):
   +10% -> If Global Sentiment supports direction
   +10% -> If Sector is Strong
   +5%  -> If multiple sources confirm same news
   +5%  -> If news released before market open (Pre-market)
   
   -10% -> If Market Sentiment is opposite
   -10% -> If Sector is Weak
   -5%  -> If news is already old (>12 hours)

==================================================
STEP 3: CLASSIFICATION (TRADE QUALITY)
   - 80%+   -> HIGH CONFIDENCE TRADE (Significant Move Likely)
   - 65-79% -> GOOD TRADE SETUP (Moderate Move)
   - 50-64% -> POSSIBLE MOVE (Risky but Actionable)
   - < 50%  -> AVOID

==================================================
OUTPUT FORMAT (JSON):
{{
  "symbol": "RELIANCE | TATAMOTORS | NIFTY | MARKET",
  "headline": "Strategic Headline",
  "summary": "1-2 sentence summary.",
  "sentiment": "Bullish | Bearish | Neutral",
  "impact_score": <int 1-10>,
  "probability": <int 0-100>,
  "trade_quality": "HIGH CONFIDENCE | GOOD SETUP | POSSIBLE MOVE | AVOID",
  "expected_move": "Sharp Move | Gradual Move | Low Movement",
  "key_insight": "Reasoning for probability score.",
  "valid_event": true
}}

If Invalid/Junk: "valid_event": false.
(Note: Market News, Expert Analysis, sector updates, and macro news remain VALID events even if not specific stock filings)
"""
        return self._run_prompt(prompt)

    def _run_prompt(self, prompt):
        try:
            # Call Sarvam
            # logger.debug("Attempting AI processing via Sarvam...")
            
            response = self.sarvam_client.chat.completions(
                model="sarvam-30b",
                messages=[
                    {"role": "system", "content": "You are a financial analyst. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            )
            content_raw = response.choices[0].message.content
            
            # Check for empty response
            if not content_raw: 
                logger.warning("Sarvam returned empty response.")
                return None
            
            # Clean markdown code blocks if present
            content_cleaned = content_raw.replace("```json", "").replace("```", "").strip()
            
            # Attempt JSON extraction
            match = re.search(r"\{.*\}", content_cleaned, re.DOTALL)
            if match:
                json_str = match.group(0)
                return json.loads(json_str)
            else:
                logger.warning(f"Sarvam output not valid JSON: {content_cleaned[:50]}...")
                return None
            
        except Exception as e:
            logger.error(f"Sarvam AI failed: {e}")
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
