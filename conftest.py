"""Root conftest: load the Home Assistant custom-component test plugin.

Lives at the repository root (outside ``custom_components/mempool/``) so it is
never part of the HACS release zip.
"""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Load ``custom_components/`` for every test.

    Resolved through ``getfixturevalue`` rather than by declaring
    ``enable_custom_integrations`` as a parameter, purely for ordering.
    ``enable_custom_integrations`` depends on ``hass``, and being autouse it
    would otherwise always create ``hass`` first — while ``recorder_mock``
    asserts that ``hass`` has *not* been set up yet, so no test could ever use
    the real recorder. Pulling ``recorder_mock`` in first when a test asks for
    it keeps both usable.
    """
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_mock")
    request.getfixturevalue("enable_custom_integrations")
    yield
