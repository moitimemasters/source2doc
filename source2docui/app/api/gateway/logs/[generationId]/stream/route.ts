import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ generationId: string }> },
) {
    try {
        const { generationId } = await params;

        const response = await fetch(
            `${GATEWAY_URL}/api/v1/logs/${generationId}/stream`,
            {
                headers: {
                    Accept: "text/event-stream",
                },
            },
        );

        if (!response.ok) {
            return new Response(
                JSON.stringify({ error: "Failed to connect to log stream" }),
                {
                    status: response.status,
                    headers: { "Content-Type": "application/json" },
                },
            );
        }

        return new Response(response.body, {
            headers: {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                Connection: "keep-alive",
            },
        });
    } catch (error) {
        console.error("Error streaming logs:", error);
        return new Response(
            JSON.stringify({ error: "Internal server error" }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            },
        );
    }
}
