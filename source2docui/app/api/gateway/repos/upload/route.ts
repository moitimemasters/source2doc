import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

const HOP_BY_HOP = new Set([
    "connection",
    "keep-alive",
    "transfer-encoding",
    "host",
    "content-length",
]);

export async function POST(request: NextRequest) {
    const formData = await request.formData();
    const headers = new Headers();
    const cookie = request.headers.get("cookie");
    if (cookie) headers.set("cookie", cookie);

    const upstream = await fetch(`${GATEWAY_URL}/api/v1/repos/upload`, {
        method: "POST",
        headers,
        body: formData,
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
