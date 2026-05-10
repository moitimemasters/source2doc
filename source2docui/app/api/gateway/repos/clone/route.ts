import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

export async function POST(request: NextRequest) {
    const body = await request.text();
    return proxyToGateway(request, "/api/v1/repos/clone", {
        method: "POST",
        body,
    });
}
