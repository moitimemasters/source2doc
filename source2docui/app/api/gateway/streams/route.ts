import { NextRequest, NextResponse } from "next/server";
import { StreamListResponseSchema } from "@/lib/gateway/types";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(request: NextRequest) {
    try {
        const response = await fetch(`${GATEWAY_URL}/api/v1/streams`, {
            headers: {
                "Content-Type": "application/json",
            },
        });

        if (!response.ok) {
            return NextResponse.json(
                { error: "Failed to fetch streams" },
                { status: response.status },
            );
        }

        const data = await response.json();
        const validated = StreamListResponseSchema.parse(data);

        return NextResponse.json(validated);
    } catch (error) {
        console.error("Error fetching streams:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
