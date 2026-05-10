import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function POST(
    _req: NextRequest,
    { params }: { params: Promise<{ tourId: string }> }
) {
    const { tourId } = await params;
    const upstream = await fetch(
        `${GATEWAY_URL}/api/v1/codetours/${tourId}/cancel`,
        { method: "POST" }
    );
    const body = await upstream.text();
    return new Response(body, {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
    });
}
