import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ generationId: string }> },
) {
    try {
        const { generationId } = await params;

        // Forward `from`/`to` (and any future) query params verbatim — they
        // belong to the upstream contract (`GET /api/v1/logs/{id}?from&to`).
        const incoming = request.nextUrl.searchParams;
        const forwarded = new URLSearchParams();
        for (const key of ["from", "to"]) {
            const v = incoming.get(key);
            if (v) forwarded.set(key, v);
        }
        const qs = forwarded.toString();
        const upstream = `${GATEWAY_URL}/api/v1/logs/${generationId}${qs ? `?${qs}` : ""}`;

        const response = await fetch(upstream);

        if (!response.ok) {
            return new Response(
                JSON.stringify({ error: "Failed to fetch logs" }),
                {
                    status: response.status,
                    headers: { "Content-Type": "application/json" },
                },
            );
        }

        const data = await response.json();
        return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        console.error("Error fetching logs:", error);
        return new Response(
            JSON.stringify({ error: "Internal server error" }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            },
        );
    }
}
