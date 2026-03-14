# NSE Corporate Announcements Monitor

## Setup

1. **Environment Variables**: Create a `.env` file in the `nse_monitor` directory:
   ```env
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   LLM_API_KEY=your_gemini_api_key_here
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run**:
   ```bash
   python -m nse_monitor.main
   ```

## Directory Structure
- `data/`: SQLite database for processed alerts.
- `downloads/`: Cached PDF announcements.
- `logs/`: Application logs.
- `nse_monitor/`: Core Python modules.
