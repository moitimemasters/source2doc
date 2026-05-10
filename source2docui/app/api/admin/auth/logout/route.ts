import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

export async function POST(request: NextRequest) {
    return proxyToGateway(request, "/api/v1/admin/auth/logout", {
        method: "POST",
    });
}
