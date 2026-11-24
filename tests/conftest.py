import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("ingest", "tests", "load", "scripts"):
    sys.path.insert(0, str(ROOT / p))


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory) -> Path:
    from make_fixtures import write_all

    out = tmp_path_factory.mktemp("fixtures")
    write_all(out)
    return out
