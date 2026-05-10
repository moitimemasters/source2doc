import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(_request: NextRequest) {
    try {
        const response = await fetch(`${GATEWAY_URL}/api/v1/pipelines`, {
            headers: { "Content-Type": "application/json" },
        });
        if (!response.ok) {
            return NextResponse.json(
                { error: `Failed to list pipelines (${response.status})` },
                { status: response.status },
            );
        }
        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error listing pipelines:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
