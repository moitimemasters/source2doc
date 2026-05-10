import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(request: NextRequest) {
    try {
        const { searchParams } = new URL(request.url);
        const bundleId = searchParams.get("bundle_id");

        if (!bundleId) {
            return NextResponse.json(
                { detail: "bundle_id query param is required" },
                { status: 400 },
            );
        }

        const response = await fetch(
            `${GATEWAY_URL}/api/v1/bundles/exports?bundle_id=${encodeURIComponent(bundleId)}`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            },
        );

        const data = await response.json();

        if (!response.ok) {
            return NextResponse.json(
                { detail: data.detail || "Failed to fetch bundle exports" },
                { status: response.status },
            );
        }

        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching bundle exports:", error);
        return NextResponse.json(
            { detail: "Failed to connect to gateway" },
            { status: 500 },
        );
    }
}
