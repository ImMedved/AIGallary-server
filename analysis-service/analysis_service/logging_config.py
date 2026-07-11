from __future__ import annotations

import logging
import os

from .settings import Settings

APP_LOGGER = "smart_gallery_analysis"
JOB_LOGGER = "smart_gallery_analysis.jobs"


def configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.log_mode == "debug" else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )

    logging.getLogger(APP_LOGGER).setLevel(logging.DEBUG if settings.log_mode == "debug" else logging.WARNING)

    # Production keeps only errors plus aggregated job lifecycle events.
    logging.getLogger(JOB_LOGGER).setLevel(logging.DEBUG if settings.log_mode == "debug" else logging.INFO)

    access_log_enabled = os.getenv("ANALYSIS_ACCESS_LOG", "false").strip().lower() in {"1", "true", "yes", "on"}
    logging.getLogger("uvicorn.access").disabled = not access_log_enabled
    if not access_log_enabled:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
