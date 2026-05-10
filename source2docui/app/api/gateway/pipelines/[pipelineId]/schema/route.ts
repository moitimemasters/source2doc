import { NextRequest, NextResponse } from "next/server";
import { PipelineSchema } from "@/lib/pipelines/schema";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ pipelineId: string }> },
) {
    const { pipelineId } = await params;
    try {
        const response = await fetch(
            `${GATEWAY_URL}/api/v1/pipelines/${encodeURIComponent(pipelineId)}/schema`,
            { headers: { "Content-Type": "application/json" } },
        );

        if (!response.ok) {
            return NextResponse.json(
                { error: `Failed to fetch pipeline schema (${response.status})` },
                { status: response.status },
            );
        }

        const data = await response.json();
        const validated = PipelineSchema.parse(data);
        return NextResponse.json(validated);
    } catch (error) {
        console.error("Error fetching pipeline schema:", error);
        return NextResponse.json(
            { error: "Internal server error" },
            { status: 500 },
        );
    }
}
