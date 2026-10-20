import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def new_york(monkeypatch):
    """Pin local time to America/New_York so UTC conversions are deterministic."""
    monkeypatch.setenv("EARLY_TIMEZONE", "America/New_York")
