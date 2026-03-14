import argparse
import logging
import sys

from src.nse_alerts.config import Settings
from src.nse_alerts.pipeline import Pipeline
from src.nse_alerts.scheduler import run_loop


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="NSE announcements alert bot")
    parser.add_argument("--once", action="store_true", help="Run a single poll instead of loop")
    args = parser.parse_args()

    configure_logging()
    settings = Settings.load()
    pipeline = Pipeline(settings)

    if args.once:
        pipeline.run_once()
        sys.exit(0)
    run_loop(pipeline, interval_seconds=settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
