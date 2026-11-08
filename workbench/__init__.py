"""Strategy workbench: YouTube/description/.pine -> Pine Script + backtested Python strategy."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# Every entry point (CLI, UI, tests) sees WORKBENCH_DB, API keys, ... .env wins over OS variables (e.g. an old
# DHAN_ACCESS_TOKEN set in Windows), so the project file is the one place to change them.
load_dotenv(ROOT / ".env", override=True)
