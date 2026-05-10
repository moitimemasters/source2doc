import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

export async function GET(request: NextRequest) {
    return proxyToGateway(request, "/api/v1/admin/llm-sessions", {
        method: "GET",
    });
}
