import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    from fleet_copilot.synthetic import build

    path = tmp_path_factory.mktemp("data") / "fleet_test.db"
    build(path, seed=7, scale=0.15)
    return path
