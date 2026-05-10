import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

type Params = { params: Promise<{ repoId: string }> };

export async function DELETE(request: NextRequest, { params }: Params) {
    const { repoId } = await params;
    return proxyToGateway(
        request,
        `/api/v1/repos/${encodeURIComponent(repoId)}`,
        { method: "DELETE" },
    );
}
