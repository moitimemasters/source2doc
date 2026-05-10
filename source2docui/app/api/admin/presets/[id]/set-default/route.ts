import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: NextRequest, { params }: Params) {
    const { id } = await params;
    return proxyToGateway(
        request,
        `/api/v1/admin/presets/${id}/set-default`,
        { method: "POST" },
    );
}
