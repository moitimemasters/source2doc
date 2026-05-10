import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(request: NextRequest) {
    const { searchParams } = new URL(request.url);
    const s3Key = searchParams.get("s3_key");

    if (!s3Key) {
        return new Response(JSON.stringify({ detail: "s3_key query param is required" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }

    const upstream = await fetch(
        `${GATEWAY_URL}/api/v1/bundles/exports/download?s3_key=${encodeURIComponent(s3Key)}`,
        {
            // download should never be cached
            cache: "no-store",
        },
    );

    if (!upstream.ok) {
        let detail = "Failed to download archive";
        try {
            const data = await upstream.json();
            detail = data.detail || data.error || detail;
        } catch {
            // ignore
        }

        return new Response(JSON.stringify({ detail }), {
            status: upstream.status,
            headers: { "Content-Type": "application/json" },
        });
    }

    // Stream through as-is, keep content-disposition from gateway.
    const headers = new Headers(upstream.headers);
    headers.set("Cache-Control", "no-store");

    return new Response(upstream.body, {
        status: upstream.status,
        headers,
    });
}
