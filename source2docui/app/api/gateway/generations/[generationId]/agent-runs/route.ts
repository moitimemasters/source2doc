import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ generationId: string }> },
) {
    try {
        const { generationId } = await params;

        // Forward `limit` / `offset` verbatim so the table can paginate
        // without the proxy having to know the upstream contract.
        const incoming = request.nextUrl.searchParams;
        const forwarded = new URLSearchParams();
        for (const key of ["limit", "offset"]) {
            const v = incoming.get(key);
            if (v) forwarded.set(key, v);
        }
        const qs = forwarded.toString();
        const upstream = `${GATEWAY_URL}/api/v1/generations/${generationId}/agent-runs${
            qs ? `?${qs}` : ""
        }`;

        const response = await fetch(upstream);

        if (!response.ok) {
            return new Response(
                JSON.stringify({ error: "Failed to fetch agent runs" }),
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
        console.error("Error fetching agent runs:", error);
        return new Response(
            JSON.stringify({ error: "Internal server error" }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            },
        );
    }
}
