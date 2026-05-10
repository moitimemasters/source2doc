import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/gateway/proxy";

// Static segment ``incremental`` beats the catch-all ``[taskId]`` route in
// Next.js routing precedence, so this proxy is what the AdminGenerateForm
// hits when submitting iterative-mode tasks. Kept as a tiny pass-through —
// the gateway does all the validation and base-bundle resolution.
export async function POST(request: NextRequest) {
    const body = await request.text();
    return proxyToGateway(request, "/api/v1/tasks/incremental", {
        method: "POST",
        body,
    });
}
