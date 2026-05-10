import { NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    request: Request,
    { params }: { params: Promise<{ bundleId: string; pageId: string }> },
) {
    try {
        const { bundleId, pageId } = await params;
        const response = await fetch(
            `${GATEWAY_URL}/api/v1/docs/bundles/${bundleId}/pages/${pageId}`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            },
        );

        if (!response.ok) {
            return NextResponse.json(
                { error: "Failed to fetch page from gateway" },
                { status: response.status },
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching page from gateway:", error);
        return NextResponse.json(
            { error: "Failed to connect to gateway" },
            { status: 500 },
        );
    }
}
