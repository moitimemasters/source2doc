import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ tourId: string }> },
) {
    try {
        const { tourId } = await params;

        const response = await fetch(
            `${GATEWAY_URL}/api/v1/codetours/${tourId}`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            },
        );

        if (!response.ok) {
            if (response.status === 404) {
                return NextResponse.json(
                    { error: "Tour not found" },
                    { status: 404 },
                );
            }
            return NextResponse.json(
                { error: "Failed to fetch tour" },
                { status: response.status },
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching tour:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
