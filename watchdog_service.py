import subprocess
import time
import sys
import os
import logging

# Ensure logs directory exists before initializing logging handlers
os.makedirs("logs", exist_ok=True)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [WATCHDOG] - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/watchdog.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def start_bot():
    """Starts the bot process and waits for it to exit."""
    cmd = [sys.executable, "v7_launcher.py"]
    logger.info(f"Starting Market Intelligence Bot: {' '.join(cmd)}")
    
    try:
        # Start the process
        process = subprocess.Popen(cmd)
        
        # Wait for the process to complete
        process.wait()
        
        if process.returncode != 0:
            logger.error(f"Bot crashed with exit code {process.returncode}. Restarting in 10 seconds...")
        else:
            logger.warning("Bot exited normally. Restarting in 5 seconds...")
            
    except Exception as e:
        logger.exception(f"Failed to launch bot: {e}")

if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)
    logger.info("Watchdog Service Active. Monitoring Market Intelligence Bot v7.0...")
    
    restart_count = 0
    while True:
        start_bot()
        restart_count += 1
        logger.info(f"Restart Cycle #{restart_count}")
        time.sleep(10) # Cooling period before restart
