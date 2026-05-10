import json

import httpx


class YandexHTTPTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)

        if response.status_code == 200 and "application/json" in response.headers.get(
            "content-type",
            "",
        ):
            try:
                await response.aread()
                data = json.loads(response.content)

                if "response" in data and isinstance(data["response"], dict):
                    unwrapped_data = data["response"]

                    new_response = httpx.Response(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=json.dumps(unwrapped_data).encode("utf-8"),
                        request=request,
                    )
                    return new_response
            except (json.JSONDecodeError, KeyError):
                pass

        return response
