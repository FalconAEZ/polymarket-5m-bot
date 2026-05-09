"""Tests for polymarket_bot.dashboard.provider_rtt configuration.

The RTT measurement itself runs client-side in JavaScript; these tests
verify the Python-side config is well-formed: every provider has a name
and url, the widget HTML includes each provider's URL, and the laptop-
caveat label is present so operators can't mistake browser RTT for bot
RTT. Per design/dashboard-v2.md §10.
"""

from __future__ import annotations

import json
import re

from polymarket_bot.dashboard.provider_rtt import (
    HISTORY_LENGTH,
    PROVIDERS,
    SAMPLE_INTERVAL_MS,
    provider_rtt_config,
    rtt_widget_html,
)

EXPECTED_PROVIDERS = {"Binance", "Coinbase", "Chainlink", "PM-Gamma", "PM-CLOB"}


def test_provider_list_matches_design_doc() -> None:
    assert {p.name for p in provider_rtt_config()} == EXPECTED_PROVIDERS


def test_every_provider_has_url() -> None:
    for p in PROVIDERS:
        assert p.url.startswith("https://")


def test_widget_includes_caveat_label() -> None:
    out = rtt_widget_html()
    assert "RTT measured from this laptop" in out
    assert "not from the bot's VPS" in out


def test_widget_html_includes_each_provider_url() -> None:
    out = rtt_widget_html()
    for p in PROVIDERS:
        assert p.url in out


def test_widget_includes_sample_cadence() -> None:
    out = rtt_widget_html()
    assert str(SAMPLE_INTERVAL_MS) in out
    assert str(HISTORY_LENGTH) in out


def test_widget_embeds_valid_json_payload() -> None:
    out = rtt_widget_html()
    match = re.search(r"const PROVIDERS = (\[.+?\]);", out)
    assert match is not None
    payload = json.loads(match.group(1))
    assert {p["name"] for p in payload} == EXPECTED_PROVIDERS
