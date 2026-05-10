import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

export async function POST(
    request: NextRequest,
    { params }: { params: Promise<{ taskId: string }> },
) {
    const { taskId } = await params;
    return proxyToGateway(request, `/api/v1/tasks/${taskId}/retry`, {
        method: "POST",
    });
}
