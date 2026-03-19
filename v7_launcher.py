import logging
import sys
import os

# Add the current directory to sys.path to allow imports from nse_monitor
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nse_monitor.main import MarketIntelligenceSystem
from nse_monitor.scheduler import MarketScheduler
from migrate_v7 import migrate

# Standardized Logging for V7
from nse_monitor.config import LOGS_DIR
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOGS_DIR, 'app.log'))
    ]
)
logger = logging.getLogger("V7_Launcher")

import time

def main():
    logger.info("Initializing Market Pulse v1.0...")
    # Run migration/wipe check on every start
    try:
        migrate()
    except Exception as e:
        logger.error(f"Migration error: {e}")
        
    system = MarketIntelligenceSystem()
    scheduler = MarketScheduler(system)
    scheduler.start()

if __name__ == "__main__":
    main()
