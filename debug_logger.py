import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

LOG_ROOT = Path(os.getenv("MOVIE_AGENT_DEBUG_LOG_DIR", "llm_logs"))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_")
    return slug[:40] or "genre"


def start_run(preferred_genre: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{_slugify(preferred_genre)}"
    (LOG_ROOT / run_id).mkdir(parents=True, exist_ok=True)
    return run_id


def format_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def write_debug_file(run_id: str, filename: str, content: str) -> None:
    if not run_id:
        return

    try:
        run_dir = LOG_ROOT / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / filename).write_text(content, encoding="utf-8")
    except OSError:
        logger.exception("Failed to write debug log file: %s/%s", run_id, filename)
