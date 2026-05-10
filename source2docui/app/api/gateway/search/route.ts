import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function POST(request: NextRequest) {
    try {
        const body = await request.text();
        const response = await fetch(`${GATEWAY_URL}/api/v1/search`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
        });
        const text = await response.text();
        return new NextResponse(text, {
            status: response.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        console.error("Search proxy error:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
