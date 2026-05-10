import { NextRequest, NextResponse } from "next/server";

export const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

const HOP_BY_HOP = new Set([
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
]);

function copyCookies(request: NextRequest, headers: Headers) {
    const cookie = request.headers.get("cookie");
    if (cookie) headers.set("cookie", cookie);
}

export async function proxyToGateway(
    request: NextRequest,
    targetPath: string,
    init?: RequestInit,
): Promise<NextResponse> {
    const headers = new Headers(init?.headers);
    copyCookies(request, headers);
    if (!headers.has("content-type") && init?.body) {
        headers.set("content-type", "application/json");
    }

    const upstream = await fetch(`${GATEWAY_URL}${targetPath}`, {
        method: init?.method ?? request.method,
        headers,
        body: init?.body,
        redirect: "manual",
    });

    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
        if (HOP_BY_HOP.has(key.toLowerCase())) return;
        responseHeaders.append(key, value);
    });

    const buffer = await upstream.arrayBuffer();
    return new NextResponse(buffer, {
        status: upstream.status,
        headers: responseHeaders,
    });
}
