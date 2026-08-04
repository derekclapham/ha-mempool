"""Config and options flow for the Mempool integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import MempoolApiError, MempoolClient
from .const import (
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)


def _make_client(hass: HomeAssistant, base_url: str, verify_ssl: bool) -> MempoolClient:
    """Build a client on HA's shared session honouring the SSL choice."""
    return MempoolClient(async_get_clientsession(hass, verify_ssl=verify_ssl), base_url)


async def _probe_currencies(client: MempoolClient) -> list[str]:
    """Return the fiats the instance publishes, or [] if the feed is off.

    The prices payload also carries a non-currency "time" key, so keep only
    3-letter uppercase ISO codes (USD, AUD, ...) with a positive value.
    """
    try:
        prices = await client.prices()
    except MempoolApiError:
        return []
    if not isinstance(prices, dict):
        return []
    return sorted(
        k
        for k, v in prices.items()
        if k.isalpha()
        and len(k) == 3
        and k.isupper()
        and isinstance(v, (int, float))
        and v > 0
    )


def _fast_interval_selector() -> NumberSelector:
    """Slider/box for the fast poll interval (seconds)."""
    return NumberSelector(
        NumberSelectorConfig(
            min=15, max=3600, step=5, unit_of_measurement="s", mode=NumberSelectorMode.BOX
        )
    )


def _currency_default(hass: HomeAssistant, currencies: list[str], current: str | None) -> str:
    """Pick a sensible default currency for the dropdown."""
    for candidate in (current, hass.config.currency, "USD"):
        if candidate in currencies:
            return candidate
    return currencies[0]


class MempoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Carry state between the URL step and the currency step."""
        self._data: dict[str, Any] = {}
        self._currencies: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the instance URL and validate connectivity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            verify_ssl = user_input[CONF_VERIFY_SSL]
            # The base URL is the unique ID, so the same instance can't be
            # added twice (and a re-add updates rather than duplicates).
            await self.async_set_unique_id(base_url)
            self._abort_if_unique_id_configured()

            client = _make_client(self.hass, base_url, verify_ssl)
            try:
                # difficulty-adjustment proves we're really talking to a
                # mempool API at the right path prefix (not just a proxy that
                # happens to answer). Its response is a rich object we can check.
                diff = await client.difficulty_adjustment()
                if "progressPercent" not in diff:
                    raise MempoolApiError("unexpected response shape")
            except MempoolApiError:
                errors["base"] = "cannot_connect"
            else:
                self._data = {
                    CONF_BASE_URL: base_url,
                    CONF_VERIFY_SSL: verify_ssl,
                    CONF_FAST_INTERVAL: int(user_input[CONF_FAST_INTERVAL]),
                }
                # With a price feed, ask which currency; otherwise finish now.
                self._currencies = await _probe_currencies(client)
                if self._currencies:
                    return await self.async_step_currency()
                return self._create()

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Required(
                    CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL
                ): BooleanSelector(),
                vol.Required(
                    CONF_FAST_INTERVAL, default=DEFAULT_FAST_INTERVAL
                ): _fast_interval_selector(),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_currency(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which fiat the price sensor reports."""
        if user_input is not None:
            self._data[CONF_CURRENCY] = user_input[CONF_CURRENCY]
            return self._create()

        default = _currency_default(self.hass, self._currencies, None)
        schema = vol.Schema(
            {
                vol.Required(CONF_CURRENCY, default=default): SelectSelector(
                    SelectSelectorConfig(
                        options=self._currencies, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="currency", data_schema=schema)

    @callback
    def _create(self) -> ConfigFlowResult:
        """Create the entry with a title derived from the host."""
        host = self._data[CONF_BASE_URL].split("//")[-1]
        return self.async_create_entry(title=f"{DEFAULT_NAME} ({host})", data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> MempoolOptionsFlow:
        """Return the options flow handler."""
        return MempoolOptionsFlow()


class MempoolOptionsFlow(OptionsFlow):
    """Change the poll interval, SSL verification and price currency post-setup.

    Currency lives in the sensor's unique_id, so switching it starts a *fresh*
    price series (new statistic_id) rather than mixing units in one history —
    the old currency's entity keeps its stats but stops updating.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        entry = self.config_entry

        # Effective current values: options win over the setup-time data.
        current_interval = entry.options.get(
            CONF_FAST_INTERVAL,
            entry.data.get(CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL),
        )
        current_verify = entry.options.get(
            CONF_VERIFY_SSL, entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        )
        current_currency = entry.options.get(
            CONF_CURRENCY, entry.data.get(CONF_CURRENCY)
        )

        if user_input is not None:
            return self.async_create_entry(data=user_input)

        # Re-probe the instance so the currency dropdown reflects what it serves
        # right now (feeds can be toggled on the node after initial setup).
        client = _make_client(self.hass, entry.data[CONF_BASE_URL], current_verify)
        currencies = await _probe_currencies(client)

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_FAST_INTERVAL, default=current_interval
            ): _fast_interval_selector(),
            vol.Required(CONF_VERIFY_SSL, default=current_verify): BooleanSelector(),
        }
        # Only offer a currency picker when the instance actually has a feed.
        if currencies:
            schema[
                vol.Required(
                    CONF_CURRENCY,
                    default=_currency_default(self.hass, currencies, current_currency),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=currencies, mode=SelectSelectorMode.DROPDOWN
                )
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
