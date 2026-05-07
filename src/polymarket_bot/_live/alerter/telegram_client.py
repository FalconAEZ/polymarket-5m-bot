"""httpx-backed Telegram Bot API client. design/alerter.md §5.2.

Two methods are used by the alerter:
  - send_message(text, chat_id) → POST /sendMessage
  - get_updates(offset, timeout) → long-poll /getUpdates with timeout=25

The class swallows nothing — it raises httpx errors so the calling loop can
implement its own retry / DLQ policy. Per design, we use long-poll (not
webhooks) to avoid opening a public TLS endpoint on the VPS. The client
holds a single AsyncClient; reuse across calls keeps the connection pool
warm.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

LOG = logging.getLogger("polymarket_bot._live.alerter.telegram_client")

DEFAULT_BASE_URL = "https://api.telegram.org"
LONG_POLL_TIMEOUT_S = 25
HTTP_TIMEOUT_S = LONG_POLL_TIMEOUT_S + 5


class TelegramClientImpl:
    def __init__(
        self,
        *,
        bot_token: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._base = f"{base_url}/bot{bot_token}"
        self._client = client if client is not None else httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        self._owns_client = client is None

    async def send_message(self, text: str, *, chat_id: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"{self._base}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise httpx.HTTPError("telegram sendMessage returned non-dict")
        return data

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout: int = LONG_POLL_TIMEOUT_S,  # noqa: ASYNC109
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resp = await self._client.get(f"{self._base}/getUpdates", params=params)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        if not isinstance(result, list):
            return []
        out: list[dict[str, Any]] = []
        for r in result:
            if isinstance(r, dict):
                out.append(r)
        return out

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
