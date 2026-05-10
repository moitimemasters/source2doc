import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

// Pure proxy: full validation lives in the gateway (Pydantic). The client is
// responsible for assembling a complete CodetourRequest, including llm/embeddings.
export async function POST(request: NextRequest) {
    try {
        const bodyText = await request.text();
        const response = await fetch(`${GATEWAY_URL}/api/v1/codetours`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: bodyText,
        });

        const text = await response.text();
        return new NextResponse(text, {
            status: response.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        console.error("Error creating codetour:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}

export async function GET(request: NextRequest) {
    try {
        const { searchParams } = new URL(request.url);
        const limit = searchParams.get("limit") || "100";
        const offset = searchParams.get("offset") || "0";

        const response = await fetch(
            `${GATEWAY_URL}/api/v1/codetours?limit=${limit}&offset=${offset}`,
            { cache: "no-store" },
        );

        const text = await response.text();
        return new NextResponse(text, {
            status: response.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        console.error("Error fetching codetours:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
