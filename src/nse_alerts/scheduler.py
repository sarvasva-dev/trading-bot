import logging
import time

from .pipeline import Pipeline


def run_loop(pipeline: Pipeline, interval_seconds: int = 60) -> None:
    while True:
        try:
            pipeline.run_once()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Pipeline run failed", exc_info=exc)
        time.sleep(interval_seconds)
