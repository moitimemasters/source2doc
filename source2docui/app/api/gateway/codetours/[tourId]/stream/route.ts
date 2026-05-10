import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    _req: NextRequest,
    { params }: { params: Promise<{ tourId: string }> }
) {
    const { tourId } = await params;
    const upstream = await fetch(
        `${GATEWAY_URL}/api/v1/codetours/${tourId}/stream`,
        { headers: { Accept: "text/event-stream" } }
    );

    return new Response(upstream.body, {
        status: upstream.status,
        headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            Connection: "keep-alive",
            "X-Accel-Buffering": "no",
        },
    });
}
