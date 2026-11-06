"""Strategy workbench: YouTube/description/.pine -> Pine Script + backtested Python strategy."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # every entry point (CLI, UI, tests) sees WORKBENCH_DB, API keys, ...
