import { NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

// B11.2 / ТЗ ГЕН-08 — list past versions of a single page.
// Mirrors the .../pages/{pageId} proxy above; the response is forwarded
// verbatim so the wiki UI can deserialize the same shape the gateway
// emits. We deliberately disable caching — version history is small
// but mutates on each new generation; a stale list would mask new
// snapshots until a hard refresh.
export async function GET(
    request: Request,
    {
        params,
    }: { params: Promise<{ bundleId: string; pageId: string }> },
) {
    try {
        const { bundleId, pageId } = await params;
        const response = await fetch(
            `${GATEWAY_URL}/api/v1/docs/bundles/${bundleId}/pages/${pageId}/versions`,
            {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            },
        );

        if (!response.ok) {
            return NextResponse.json(
                { error: "Failed to fetch page versions from gateway" },
                { status: response.status },
            );
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error("Error fetching page versions from gateway:", error);
        return NextResponse.json(
            { error: "Failed to connect to gateway" },
            { status: 500 },
        );
    }
}
