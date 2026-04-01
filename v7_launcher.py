import asyncio
import logging
import os
import sys

# Allow local imports when launched via watchdog on Windows.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from migrate_v7 import migrate
from nse_monitor.main import main as core_main


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("V7_Launcher")


def run():
    logger.info("Initializing Market Pulse launcher...")
    try:
        migrate()
    except Exception as exc:
        logger.error("Migration error: %s", exc)

    asyncio.run(core_main())


if __name__ == "__main__":
    run()
