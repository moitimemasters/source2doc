import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ runId: string }> },
) {
    try {
        const { runId } = await params;
        const upstream = `${GATEWAY_URL}/api/v1/generations/agent-runs/${runId}`;

        const response = await fetch(upstream);

        if (!response.ok) {
            return new Response(
                JSON.stringify({ error: "Failed to fetch agent run" }),
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
        console.error("Error fetching agent run detail:", error);
        return new Response(
            JSON.stringify({ error: "Internal server error" }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            },
        );
    }
}
