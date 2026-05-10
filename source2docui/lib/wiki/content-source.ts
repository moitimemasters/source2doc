import fs from "fs";
import path from "path";
import { WikiPage, NavigationItem } from "./types";
import {
    ProjectConfig,
    FileSystemSource,
    ApiSource,
    GatewaySource,
} from "./project-types";

export interface ContentSource {
    loadPage(slug: string[]): Promise<WikiPage | null>;
    loadNavigation(): Promise<NavigationItem[]>;
}

export class FileSystemContentSource implements ContentSource {
    constructor(private config: FileSystemSource) {}

    async loadPage(slug: string[]): Promise<WikiPage | null> {
        try {
            const effectiveSlug = slug.length > 0 ? slug : ["overview"];
            const pageId = effectiveSlug[effectiveSlug.length - 1];

            const indexPath = path.join(
                process.cwd(),
                this.config.dataPath,
                "index.json",
            );
            if (fs.existsSync(indexPath)) {
                const pageFilePath = path.join(
                    process.cwd(),
                    this.config.dataPath,
                    `${pageId}.json`,
                );

                if (fs.existsSync(pageFilePath)) {
                    const content = fs.readFileSync(pageFilePath, "utf-8");
                    const pageData = JSON.parse(content);
                    return this.convertMvpPageToWikiPage(pageData, pageId);
                }

                return null;
            }

            const rootFilePath = this.getWikiFilePath(effectiveSlug[0]);
            if (!fs.existsSync(rootFilePath)) {
                return null;
            }

            const content = fs.readFileSync(rootFilePath, "utf-8");
            const rootPage: WikiPage = JSON.parse(content);

            if (effectiveSlug.length === 1) {
                return rootPage;
            }

            return this.findNestedPage(rootPage, effectiveSlug.slice(1));
        } catch (error) {
            console.error("Error loading wiki page:", error);
            return null;
        }
    }

    async loadNavigation(): Promise<NavigationItem[]> {
        try {
            const indexPath = path.join(
                process.cwd(),
                this.config.dataPath,
                "index.json",
            );

            if (fs.existsSync(indexPath)) {
                const content = fs.readFileSync(indexPath, "utf-8");
                const indexData = JSON.parse(content);
                return this.convertMvpNavigationToItems(indexData.navigation);
            }

            const navPath =
                this.config.navigationPath ||
                path.join(this.config.dataPath, "navigation.json");
            const fullPath = path.join(process.cwd(), navPath);

            if (!fs.existsSync(fullPath)) {
                return [];
            }

            const content = fs.readFileSync(fullPath, "utf-8");
            const config = JSON.parse(content);
            return config.items || [];
        } catch (error) {
            console.error("Error loading navigation:", error);
            return [];
        }
    }

    private convertMvpPageToWikiPage(pageData: any, pageId: string): WikiPage {
        return {
            id: pageId,
            title: pageData.title,
            description: pageData.summary,
            summary: pageData.summary,
            blocks: pageData.blocks || [],
            related: pageData.related,
            metadata: pageData.metadata,
        };
    }

    private convertMvpNavigationToItems(
        navigation: any,
        basePath: string = "/wiki",
    ): NavigationItem[] {
        const items: NavigationItem[] = [];

        for (const [key, value] of Object.entries(navigation)) {
            if (typeof value === "string") {
                items.push({
                    id: key,
                    title: value,
                    path: `${basePath}/${key}`,
                });
            } else if (typeof value === "object" && value !== null) {
                const navObj = value as any;
                const children = navObj.children
                    ? Object.entries(navObj.children).map(
                          ([childKey, childValue]) => ({
                              id: childKey,
                              title:
                                  typeof childValue === "string"
                                      ? childValue
                                      : (childValue as any).title,
                              path: `${basePath}/${childKey}`,
                          }),
                      )
                    : undefined;

                items.push({
                    id: key,
                    title: navObj.title,
                    path: `${basePath}/${key}`,
                    children,
                });
            }
        }

        return items;
    }

    private getWikiFilePath(rootId: string): string {
        const filename = rootId || "getting-started";
        return path.join(
            process.cwd(),
            this.config.dataPath,
            `${filename}.json`,
        );
    }

    private findNestedPage(
        root: WikiPage,
        slugSegments: string[],
    ): WikiPage | null {
        let current: WikiPage = root;

        for (const segment of slugSegments) {
            const next = current.children?.find(
                (child) => child.id === segment,
            );
            if (!next) return null;
            current = next;
        }

        return current;
    }
}

export class ApiContentSource implements ContentSource {
    constructor(private config: ApiSource) {}

    async loadPage(slug: string[]): Promise<WikiPage | null> {
        try {
            const slugPath = slug.join("/");
            const url = `${this.config.baseUrl}${this.config.endpoints.content.replace("{slug}", slugPath)}`;
            const response = await fetch(url, this.getRequestOptions());

            if (!response.ok) {
                return null;
            }

            return await response.json();
        } catch (error) {
            console.error("Error loading wiki page from API:", error);
            return null;
        }
    }

    async loadNavigation(): Promise<NavigationItem[]> {
        try {
            const url = `${this.config.baseUrl}${this.config.endpoints.navigation}`;
            const response = await fetch(url, this.getRequestOptions());

            if (!response.ok) {
                return [];
            }

            const data = await response.json();
            return data.items || data;
        } catch (error) {
            console.error("Error loading navigation from API:", error);
            return [];
        }
    }

    private getRequestOptions(): RequestInit {
        const headers: HeadersInit = {
            "Content-Type": "application/json",
        };

        if (this.config.auth) {
            switch (this.config.auth.type) {
                case "bearer":
                    if (this.config.auth.token) {
                        headers["Authorization"] =
                            `Bearer ${this.config.auth.token}`;
                    }
                    break;
                case "basic":
                    if (
                        this.config.auth.username &&
                        this.config.auth.password
                    ) {
                        const credentials = btoa(
                            `${this.config.auth.username}:${this.config.auth.password}`,
                        );
                        headers["Authorization"] = `Basic ${credentials}`;
                    }
                    break;
                case "apikey":
                    if (this.config.auth.apiKey) {
                        headers["X-API-Key"] = this.config.auth.apiKey;
                    }
                    break;
            }
        }

        return { headers };
    }
}

export class GatewayContentSource implements ContentSource {
    private gatewayUrl: string;

    constructor(private config: GatewaySource) {
        this.gatewayUrl = process.env.GATEWAY_URL || "http://localhost:8003";
    }

    async loadPage(slug: string[]): Promise<WikiPage | null> {
        try {
            // For gateway, the first slug is the project ID, rest is the page path
            // e.g., /wiki/3/overview -> pageId = "overview"
            const pageId = slug.length > 0 ? slug[0] : "overview";

            const url = `${this.gatewayUrl}/api/v1/docs/bundles/${this.config.bundleId}/pages/${pageId}`;

            const response = await fetch(url, {
                headers: {
                    "Content-Type": "application/json",
                },
                cache: "no-store",
            });

            if (!response.ok) {
                console.error(
                    `Failed to fetch page ${pageId} from bundle ${this.config.bundleId}:`,
                    response.status,
                );
                return null;
            }

            const data = await response.json();

            // Convert gateway response to WikiPage format
            return {
                id: pageId,
                title: data.title,
                description: data.summary,
                summary: data.summary,
                blocks: data.blocks || [],
                related: data.related,
                metadata: data.metadata,
                repository: data.repository ?? null,
                // B6.4 — gateway populates this from the rendered blocks
                // so the UI can offer a "Download Markdown" button without
                // a second fetch. ``null`` is acceptable (button is
                // hidden in that case).
                body_markdown: data.body_markdown ?? null,
            };
        } catch (error) {
            console.error("Error loading page from gateway:", error);
            return null;
        }
    }

    async loadNavigation(): Promise<NavigationItem[]> {
        try {
            const indexUrl = `${this.gatewayUrl}/api/v1/docs/bundles/${this.config.bundleId}/index`;
            const pagesUrl = `${this.gatewayUrl}/api/v1/docs/bundles/${this.config.bundleId}/pages`;

            const [indexResponse, pagesResponse] = await Promise.all([
                fetch(indexUrl, {
                    headers: { "Content-Type": "application/json" },
                    cache: "no-store",
                }),
                fetch(pagesUrl, {
                    headers: { "Content-Type": "application/json" },
                    cache: "no-store",
                }),
            ]);

            if (!indexResponse.ok) {
                console.error("Failed to fetch navigation:", indexResponse.status);
                return [];
            }

            const indexData = await indexResponse.json();
            const pagesData = pagesResponse.ok ? await pagesResponse.json() : null;

            const completedPageIds = new Set<string>(
                (pagesData?.pages ?? [])
                    .filter(
                        (p: { status?: string }) =>
                            !p.status || p.status === "completed",
                    )
                    .map((p: { page_id: string }) => p.page_id),
            );

            return this.convertNavigationToItems(indexData.navigation, "/wiki", completedPageIds);
        } catch (error) {
            console.error("Error loading navigation from gateway:", error);
            return [];
        }
    }

    private convertNavigationToItems(
        navigation: Record<string, any>,
        basePath: string,
        completedPageIds: Set<string>,
    ): NavigationItem[] {
        const items: NavigationItem[] = [];

        for (const [key, value] of Object.entries(navigation)) {
            if (typeof value === "string") {
                if (!completedPageIds.has(key)) continue;
                items.push({
                    id: key,
                    title: value,
                    path: `${basePath}/${key}`,
                });
            } else if (typeof value === "object" && value !== null) {
                const children = value.children
                    ? Object.entries(value.children)
                          .filter(([childKey]) => completedPageIds.has(childKey))
                          .map(([childKey, childValue]) => ({
                              id: childKey,
                              title:
                                  typeof childValue === "string"
                                      ? childValue
                                      : (childValue as any).title,
                              path: `${basePath}/${childKey}`,
                          }))
                    : undefined;

                if (!children || children.length === 0) {
                    if (!completedPageIds.has(key)) continue;
                }

                items.push({
                    id: key,
                    title: value.title || key,
                    path:
                        children && children.length > 0
                            ? children[0].path
                            : `${basePath}/${key}`,
                    children: children && children.length > 0 ? children : undefined,
                });
            }
        }

        return items;
    }
}

export class ContentSourceFactory {
    static create(config: ProjectConfig): ContentSource {
        switch (config.source.type) {
            case "filesystem":
                return new FileSystemContentSource(config.source);
            case "api":
                return new ApiContentSource(config.source);
            case "gateway":
                return new GatewayContentSource(config.source);
            default:
                throw new Error(
                    `Unknown source type: ${(config.source as any).type}`,
                );
        }
    }
}
