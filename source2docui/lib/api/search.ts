export type SearchMode = "semantic" | "fulltext";

export interface SearchFilters {
    file_path?: string;
    directory?: string;
    language?: string;
}

export interface SearchRequest {
    query: string;
    mode?: SearchMode;
    filters?: SearchFilters;
    limit?: number;
}

export interface SearchResultSource {
    file_path: string;
    start_line: number;
    end_line: number;
    language?: string;
}

export interface SearchResultMetadata {
    repository_id: string;
    chunk_id: string;
}

export interface SearchResult {
    text: string;
    score: number;
    source: SearchResultSource;
    metadata: SearchResultMetadata;
}

export interface SearchResponse {
    mode: SearchMode;
    total: number;
    results: SearchResult[];
}

export class SearchError extends Error {
    status: number;
    constructor(message: string, status: number) {
        super(message);
        this.name = "SearchError";
        this.status = status;
    }
}

export async function searchProject(
    repositoryId: string,
    body: SearchRequest,
    init?: { signal?: AbortSignal },
): Promise<SearchResponse> {
    const url = `/api/gateway/projects/${encodeURIComponent(repositoryId)}/search`;

    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: init?.signal,
    });

    if (!response.ok) {
        let detail = "";
        try {
            const json = await response.json();
            detail =
                json?.error ||
                json?.detail ||
                json?.message ||
                JSON.stringify(json);
        } catch {
            try {
                detail = await response.text();
            } catch {
                detail = "";
            }
        }
        throw new SearchError(
            detail || `Search failed (HTTP ${response.status})`,
            response.status,
        );
    }

    return (await response.json()) as SearchResponse;
}
