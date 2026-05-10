import { NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET() {
    try {
        const response = await fetch(`${GATEWAY_URL}/api/v1/repos`, {
            headers: {
                "Content-Type": "application/json",
            },
            cache: "no-store",
        });

        if (!response.ok) {
            console.error("Failed to fetch repositories:", response.status);
            return NextResponse.json(
                { error: "Failed to fetch repositories" },
                { status: response.status },
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching repositories:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
