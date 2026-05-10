import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

export async function GET(request: NextRequest) {
    return proxyToGateway(request, "/api/v1/admin/presets", { method: "GET" });
}

export async function POST(request: NextRequest) {
    const body = await request.text();
    return proxyToGateway(request, "/api/v1/admin/presets", {
        method: "POST",
        body,
    });
}
