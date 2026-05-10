import { NextResponse } from "next/server";

export async function GET() {
    // Legacy endpoint (task status from Postgres) has been removed.
    return NextResponse.json(
        {
            detail:
                "Deprecated: task status is derived from stream events. Use /api/gateway/streams/{id}/events or SSE stream.",
        },
        { status: 410 },
    );
}
