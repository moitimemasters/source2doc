"""Yandex Cloud OpenAI-compat transport.

Yandex's internal OpenAI-compatible endpoint (and the Anthropic gateway it
exposes at ``/anthropic/v1/``) sometimes wraps the response JSON in an extra
``{"response": {...}}`` envelope. The Pydantic-AI / OpenAI / Anthropic SDKs
don't know about that; this transport peeks at successful JSON responses and
unwraps the envelope before passing them upstream — without it the SDK fails
with "No embedding data received" / similar parse errors.

Lives in source2doc-shared so both ``docgen_core`` and ``codetour_core`` can
use the same instance via :func:`source2doc.llm_providers.build_pydantic_ai_model`.
"""

import json

import httpx


class YandexHTTPTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)

        if response.status_code != 200:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        try:
            await response.aread()
            data = json.loads(response.content)
        except (json.JSONDecodeError, KeyError):
            return response

        if "response" in data and isinstance(data["response"], dict):
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=json.dumps(data["response"]).encode("utf-8"),
                request=request,
            )

        return response
