/**
 * Cross-page symbol map (B6.2 / TЗ ДОК-08).
 *
 * The gateway exposes `/api/v1/wiki/{generation_id}/symbols`, which returns
 * an array of `{ symbol, page_id, kind }` rows. The wiki page-shell fetches
 * this once per page-load and passes the resulting case-insensitive map down
 * to inline renderers. Renderers wrap matching `<code>` and prose text with
 * `<a href="/wiki/{generationId}/{page_id}">` while keeping their existing
 * styling. We intentionally avoid linking the symbol to its own home page
 * (no self-links) to keep the doc readable.
 */

const GATEWAY_PROXY_BASE = "/api/gateway/wiki";

export type SymbolKind = "page_title" | "function" | "class" | "module";

export interface PageSymbol {
    symbol: string;
    page_id: string;
    kind: SymbolKind;
}

export interface SymbolMatch {
    page_id: string;
    kind: SymbolKind;
}

/**
 * Lookup map. Keys are lowercased symbols; ``page_title`` rows win over
 * ``function``/``class``/``module`` if a symbol exists in multiple kinds.
 */
export type SymbolMap = Map<string, SymbolMatch>;

const KIND_PRIORITY: Record<SymbolKind, number> = {
    page_title: 0,
    class: 1,
    function: 2,
    module: 3,
};

export function buildSymbolMap(symbols: PageSymbol[]): SymbolMap {
    const map: SymbolMap = new Map();
    for (const entry of symbols) {
        const key = entry.symbol.toLowerCase();
        const current = map.get(key);
        if (
            !current ||
            KIND_PRIORITY[entry.kind] < KIND_PRIORITY[current.kind]
        ) {
            map.set(key, { page_id: entry.page_id, kind: entry.kind });
        }
    }
    return map;
}

/**
 * Server-side fetch (used in Next.js server components). Returns an empty
 * map on any error so a missing endpoint never blocks page rendering.
 */
export async function fetchSymbolMap(generationId: string): Promise<SymbolMap> {
    try {
        const gatewayUrl = process.env.GATEWAY_URL || "http://localhost:8003";
        const url = `${gatewayUrl}/api/v1/wiki/${generationId}/symbols`;
        const response = await fetch(url, {
            headers: { "Content-Type": "application/json" },
            cache: "no-store",
        });
        if (!response.ok) {
            return new Map();
        }
        const data = (await response.json()) as { symbols?: PageSymbol[] };
        return buildSymbolMap(data.symbols ?? []);
    } catch (error) {
        console.error("Error fetching wiki symbols:", error);
        return new Map();
    }
}

/**
 * Pure helper for unit tests / client-side fetches via the proxy route.
 */
export async function fetchSymbolMapViaProxy(
    generationId: string,
): Promise<SymbolMap> {
    try {
        const response = await fetch(
            `${GATEWAY_PROXY_BASE}/${generationId}/symbols`,
            { cache: "no-store" },
        );
        if (!response.ok) {
            return new Map();
        }
        const data = (await response.json()) as { symbols?: PageSymbol[] };
        return buildSymbolMap(data.symbols ?? []);
    } catch (error) {
        console.error("Error fetching wiki symbols via proxy:", error);
        return new Map();
    }
}

/**
 * Resolve a single symbol against the map. Returns null if no match or if
 * the match would point to ``selfPageId`` (avoid self-links).
 */
export function resolveSymbol(
    map: SymbolMap,
    symbol: string,
    selfPageId?: string,
): SymbolMatch | null {
    if (!symbol) return null;
    const match = map.get(symbol.trim().toLowerCase());
    if (!match) return null;
    if (selfPageId && match.page_id === selfPageId) return null;
    return match;
}

/**
 * Build a wiki link for a resolved match. ``generationId`` is the wiki
 * project segment used in the URL (i.e. ``/wiki/{generationId}/{page_id}``).
 */
export function symbolHref(generationId: string, pageId: string): string {
    return `/wiki/${generationId}/${pageId}`;
}
