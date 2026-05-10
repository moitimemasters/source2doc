import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

// Polled by the admin health page and the header widget — keep it cheap and
// uncached at the Next layer so the gateway's 5s in-memory cache is the
// single source of throttling.
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
    return proxyToGateway(request, "/api/v1/admin/health/components", {
        method: "GET",
    });
}
