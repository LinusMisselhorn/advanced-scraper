import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "indeed_salzgitter_sample.json"


@pytest.fixture
def settings():
    from scraper.config import Settings

    return Settings()


@pytest.fixture
def fixture_path():
    return FIXTURE
