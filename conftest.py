"""Root conftest: load the Home Assistant custom-component test plugin.

Lives at the repository root (outside ``custom_components/mempool/``) so it is
never part of the HACS release zip.
"""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load ``custom_components/`` for every test."""
    yield
