import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    request: NextRequest,
    { params }: { params: { generationId: string } },
) {
    try {
        const { generationId } = params;

        const response = await fetch(
            `${GATEWAY_URL}/api/v1/codetours/generation/${generationId}`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            },
        );

        if (!response.ok) {
            return NextResponse.json(
                { error: "Failed to fetch tours" },
                { status: response.status },
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching tours by generation:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
