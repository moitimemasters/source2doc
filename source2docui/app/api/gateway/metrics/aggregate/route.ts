// Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4).
//
// Thin proxy: forwards `from`, `to`, `group_by` query params to the
// gateway's /api/v1/metrics/aggregate route. Errors are surfaced 1:1 so
// the dashboard can show the gateway's HTTP status verbatim.
import { NextRequest } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

const ALLOWED_PARAMS = new Set(["from", "to", "group_by"]);

export async function GET(request: NextRequest) {
    try {
        // Whitelist params so a stray ?garbage=... doesn't cache-bust the
        // gateway and so we don't accidentally proxy auth headers.
        const incoming = new URL(request.url).searchParams;
        const params = new URLSearchParams();
        for (const [key, value] of incoming.entries()) {
            if (ALLOWED_PARAMS.has(key)) {
                params.set(key, value);
            }
        }
        const qs = params.toString();
        const upstream =
            `${GATEWAY_URL}/api/v1/metrics/aggregate` +
            (qs ? `?${qs}` : "");

        const response = await fetch(upstream, {
            // Metrics dashboards refresh frequently; bypass any
            // intermediate cache layer.
            cache: "no-store",
        });

        const body = await response.text();
        return new Response(body, {
            status: response.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        console.error("Error fetching metrics aggregate:", error);
        return new Response(
            JSON.stringify({ error: "Internal server error" }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            },
        );
    }
}
