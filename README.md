# NSE Announcements Monitor (AI-Powered)

Robust, high-frequency corporate announcement scanner for the National Stock Exchange of India (NSE). This tool fetches announcements in real-time, extracts text from PDFs, and uses Google Gemini / xAI Grok to provide deep financial intelligence.

## 🚀 Features

- **Real-time Scanning**: Monitors NSE corporate filings with high frequency.
- **Stealth Scraper**: Uses advanced session warming and header rotation to bypass bot detection.
- **Deep AI Analysis**:
    - **Quantum of Impact**: High/Medium/Low assessment.
    - **Duration**: Short-term vs. Structural outlook.
    - **Key Insight**: Institutional-grade "takeaways" for traders.
- **Multi-LLM Support**: Primary support for Google Gemini (Free) with xAI Grok fallback.
- **Telegram Integration**: Instant alerts with clean, readable formatting and direct PDF links.
- **Duplicate Prevention**: SQLite-backed tracking to ensure no repeat alerts.

## 🛠️ Setup Instructions

### 1. Prerequisites
- Python 3.10+
- A Telegram Bot Token (from @BotFather)
- A Gemini API Key (from [Google AI Studio](https://aistudio.google.com/app/apikey))

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/sitekraft/Trading-bot.git
cd Trading-bot

# Install dependencies
pip install -r nse_monitor/requirements.txt
```

### 3. Configuration
Create a `.env` file in the `nse_monitor` directory:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
GEMINI_API_KEY=your_gemini_api_key
LLM_API_KEY=your_xai_api_key (optional)
LLM_MODEL=grok-4-latest
```

### 4. Running the Monitor
Simply run the batch file:
```bash
start.bat
```

## 🛠️ Troubleshooting
- **No Alerts?**: Check if your Chat ID is correct using `python nse_monitor/get_chat_id.py`.
- **AI Errors?**: Ensure your API keys are active and have sufficient credits (for xAI). Gemini is recommended for free tier usage.
- **Hanging?**: NSE sometimes temporarily blocks IPs. The script includes auto-retry and session warming to minimize this.

## 📜 License
MIT License
