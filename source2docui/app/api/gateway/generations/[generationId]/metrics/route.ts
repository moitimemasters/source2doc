import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ generationId: string }> },
) {
    try {
        const { generationId } = await params;
        const upstream = `${GATEWAY_URL}/api/v1/generations/${generationId}/metrics`;

        const response = await fetch(upstream);

        if (!response.ok) {
            return new Response(
                JSON.stringify({ error: "Failed to fetch metrics" }),
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
        console.error("Error fetching generation metrics:", error);
        return new Response(
            JSON.stringify({ error: "Internal server error" }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            },
        );
    }
}
