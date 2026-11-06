import os
import time

import pytest

from agent_janitor.config import Config

DAY = 86400


@pytest.fixture
def make_ws(tmp_path):
    """Create a fake workspace with a file of `size` bytes, aged `age_days`."""

    def _make(name, age_days=0.0, size=1024, root=tmp_path):
        ws = root / name
        ws.mkdir(parents=True)
        (ws / "build.log").write_bytes(b"x" * size)
        ts = time.time() - age_days * DAY
        for p in (ws / "build.log", ws):
            os.utime(p, (ts, ts))
        return ws

    return _make


@pytest.fixture
def cfg(tmp_path):
    return Config(roots=[tmp_path], max_age_days=3, min_free_percent=0)
