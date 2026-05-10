import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: Params) {
    const { id } = await params;
    const reveal = request.nextUrl.searchParams.get("reveal");
    const query = reveal ? `?reveal=${reveal}` : "";
    return proxyToGateway(request, `/api/v1/admin/presets/${id}${query}`, {
        method: "GET",
    });
}

export async function PUT(request: NextRequest, { params }: Params) {
    const { id } = await params;
    const body = await request.text();
    return proxyToGateway(request, `/api/v1/admin/presets/${id}`, {
        method: "PUT",
        body,
    });
}

export async function DELETE(request: NextRequest, { params }: Params) {
    const { id } = await params;
    return proxyToGateway(request, `/api/v1/admin/presets/${id}`, {
        method: "DELETE",
    });
}
