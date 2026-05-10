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
