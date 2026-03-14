import logging
import json
import requests
from google import genai
from nse_monitor.config import LLM_API_KEY, LLM_MODEL, LLM_API_URL, GEMINI_API_KEY

logger = logging.getLogger(__name__)

class LLMProcessor:
    def __init__(self):
        self.api_key = LLM_API_KEY
        self.model = LLM_MODEL
        self.api_url = LLM_API_URL
        self.gemini_key = GEMINI_API_KEY

        if self.gemini_key:
            try:
                # Using the new google-genai SDK
                self.client = genai.Client(api_key=self.gemini_key)
                self.gemini_model_name = "gemini-3-flash-preview"
                logger.info(f"Gemini AI initialized with model: {self.gemini_model_name}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client: {e}")
                self.client = None
        else:
            self.client = None
            logger.warning("GEMINI_API_KEY not found. Falling back to xAI if available.")

    def analyze_news(self, company, text):
        """Analyzes announcement text using Gemini (preferred) or Grok."""
        if self.client:
            return self._analyze_with_gemini(company, text)
        elif self.api_key:
            return self._analyze_with_grok(company, text)
        return self._fallback(company, "No API keys provided")

    def _analyze_with_gemini(self, company, text):
        try:
            logger.info(f"Analyzing for {company} using Gemini ({self.gemini_model_name})...")
            prompt = f"""
            You are an expert Institutional Equity Research Analyst. 
            Analyze this NSE announcement for {company} and provide high-conviction financial intelligence.
            
            CONTENT: {text[:15000]}
            
            STRICT RULES:
            - Determine 'Quantum of Impact': (High | Medium | Low) based on historical market reactions to such news.
            - Provide 'Short-term Outlook' (1-5 days) and 'Mid-term Outlook' (1-3 months).
            - Identify if this is a 'Primary Value Driver' (e.g., EBITDA accretive, Debt reduction, Strategic pivot).
            
            Return ONLY a valid JSON object:
            {{
                "company": "{company}",
                "headline": "Punchy, institutional-grade headline",
                "summary": "Concise 3-sentence deep dive",
                "impact": "Bullish | Bearish | Neutral",
                "quantum": "High | Medium | Low",
                "duration": "Short-term / Structural",
                "confidence": "0.0-1.0",
                "key_insight": "One single point why this matters most for the stock price"
            }}
            """
            
            response = self.client.models.generate_content(
                model=self.gemini_model_name,
                contents=prompt
            )
            
            content = response.text.strip()
            
            # Extract JSON if wrapped in markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif content.startswith("```"):
                content = content.split("```")[1].strip()
            
            return json.loads(content)
        except Exception as e:
            logger.error(f"Gemini processing failed: {e}")
            return self._analyze_with_grok(company, text) if self.api_key else self._fallback(company, str(e))

    def _analyze_with_grok(self, company, text):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        prompt = f"Analyze for {company} and return ONLY JSON:\n{text[:4000]}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a financial analyst. Return JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }
        try:
            logger.info(f"Analyzing for {company} using Grok-4 (Fallback)...")
            r = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            
            # Explicitly check for credit issues in Grok response
            if r.status_code != 200 and "credits" in r.text.lower():
                raise Exception("xAI account has NO CREDITS")
            
            r.raise_for_status()
            result = r.json()
            content = result['choices'][0]['message']['content'].strip()
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            
            return json.loads(content)
        except Exception as e:
            logger.error(f"Grok fallback failed: {e}")
            return self._fallback(company, str(e))

    def _fallback(self, company, error=""):
        msg = "AI summary unavailable."
        if "credits" in error.lower():
            msg = "xAI Error: Zero Credits. Please add funds or use Gemini API key."
        elif "api_key" in error.lower() or "not found" in error.lower():
            msg = "AI Error: API credentials missing or invalid."
        
        return {
            "company": company,
            "headline": "Analysis Unavailable",
            "summary": msg,
            "impact": "Neutral",
            "confidence": "0.0"
        }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    proc = LLMProcessor()
    # print(proc.analyze_news("Test Corp", "Profit increased by 50% year on year."))
