import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

type Params = { params: Promise<{ repositoryId: string }> };

export async function POST(request: NextRequest, { params }: Params) {
    const { repositoryId } = await params;
    const body = await request.text();
    return proxyToGateway(
        request,
        `/api/v1/projects/${encodeURIComponent(repositoryId)}/search`,
        {
            method: "POST",
            body,
            headers: { "content-type": "application/json" },
        },
    );
}
