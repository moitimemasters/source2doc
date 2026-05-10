import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function POST(request: NextRequest) {
    try {
        const body = await request.json();

        const response = await fetch(`${GATEWAY_URL}/api/v1/bundles/export`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(body),
        });

        const data = await response.json();

        if (!response.ok) {
            return NextResponse.json(
                { detail: data.detail || "Failed to create bundle export task" },
                { status: response.status },
            );
        }

        return NextResponse.json(data);
    } catch (error) {
        console.error("Error creating bundle export task:", error);
        return NextResponse.json(
            { detail: "Internal server error" },
            { status: 500 },
        );
    }
}
