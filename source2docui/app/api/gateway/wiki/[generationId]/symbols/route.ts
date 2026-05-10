import { NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    _request: Request,
    { params }: { params: Promise<{ generationId: string }> },
) {
    try {
        const { generationId } = await params;
        const response = await fetch(
            `${GATEWAY_URL}/api/v1/wiki/${generationId}/symbols`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            },
        );

        if (!response.ok) {
            return NextResponse.json(
                { error: "Failed to fetch wiki symbols from gateway" },
                { status: response.status },
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching wiki symbols from gateway:", error);
        return NextResponse.json(
            { error: "Failed to connect to gateway" },
            { status: 500 },
        );
    }
}
