import { NextRequest, NextResponse } from "next/server";
import { StreamEventSchema } from "@/lib/gateway/types";
import { z } from "zod";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ streamId: string }> },
) {
    try {
        const { streamId } = await params;

        const response = await fetch(
            `${GATEWAY_URL}/api/v1/streams/${streamId}/events`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
            },
        );

        if (!response.ok) {
            return NextResponse.json(
                { error: "Failed to fetch stream events" },
                { status: response.status },
            );
        }

        const data = await response.json();
        const validated = z.array(StreamEventSchema).parse(data);

        // Wrap in { events: [] } so the saga can do `data.events || []`
        return NextResponse.json({ events: validated });
    } catch (error) {
        console.error("Error fetching stream events:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
