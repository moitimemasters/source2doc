import { WikiPage, NavigationItem } from "../../lib/wiki/types";
import type { SymbolMap } from "../../lib/wiki/symbols";
import { WikiSidebar } from "./WikiSidebar";
import { ContentRenderer } from "./ContentRenderer";
import { TableOfContents } from "./TableOfContents";
import { PageNavigation } from "./PageNavigation";
import { ReadingProgress } from "./ReadingProgress";
import { PageMetadata } from "./PageMetadata";
import { ScrollToTop } from "./ScrollToTop";
import { NavigationControls } from "./NavigationControls";
import { VersionedPageBody } from "./VersionedPageBody";
import { CodeTourInput } from "../codetour/CodeTourInput";
import { WikiSearchBar } from "./WikiSearchBar";
import {
    Breadcrumb,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
} from "../ui/breadcrumb";
import { Menu } from "lucide-react";

interface HeadingForTOC {
    id: string;
    text: string;
    level: number;
}

interface WikiLayoutProps {
    page: WikiPage;
    navigationItems: NavigationItem[];
    currentPath: string;
    breadcrumbs?: Array<{ title: string; path: string }>;
    prevPage?: NavigationItem | null;
    nextPage?: NavigationItem | null;
    projectId?: string;
    /** B6.2 — cross-page symbol-link index (Map of lowercased symbol → row). */
    symbolMap?: SymbolMap;
}

function slugifyHeadingId(text: string) {
    return text
        .toLowerCase()
        .trim()
        .replace(/[^\p{L}\p{N}\s-]/gu, "")
        .replace(/\s+/g, "-");
}

function stripMarkdownForToc(text: string) {
    // Keep this lightweight (no markdown parser) — just remove the most common markers.
    // Examples:
    // - **bold** -> bold
    // - `code` -> code
    // - [Label](url) -> Label
    return String(text || "")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
        .replace(/[`*_~]/g, "")
        .trim();
}

export function WikiLayout({
    page,
    navigationItems,
    currentPath,
    breadcrumbs = [],
    prevPage = null,
    nextPage = null,
    projectId,
    symbolMap,
}: WikiLayoutProps) {
    const headings: HeadingForTOC[] = page.blocks
        .filter((block) => block.type === "heading")
        .map((block: any) => ({
            id: block.id || slugifyHeadingId(String(block.text || "")),
            text: stripMarkdownForToc(block.text),
            level: Number(block.level || 2),
        }))
        .filter((h) => Boolean(h.id) && Boolean(h.text));

    const hasTableOfContents = headings.length > 0;

    // CSS-only mobile sidebar (no client state => faster navigation + less hydration).
    const sidebarToggleId = "wiki-sidebar-toggle";

    return (
        <div className="flex min-h-screen bg-card">
            <ReadingProgress />
            <ScrollToTop />
            <NavigationControls prev={prevPage} next={nextPage} />
            <input
                id={sidebarToggleId}
                type="checkbox"
                className="peer sr-only md:hidden"
            />

            {/* Mobile Sidebar Overlay */}
            <label
                htmlFor={sidebarToggleId}
                className="fixed inset-0 z-40 bg-black/50 opacity-0 pointer-events-none transition-opacity peer-checked:opacity-100 peer-checked:pointer-events-auto md:hidden"
                aria-label="Close sidebar"
            />

            {/* Sidebar */}
            <aside
                className={[
                    "fixed inset-y-0 left-0 z-50 w-64 -translate-x-full transition-transform duration-200",
                    "peer-checked:translate-x-0",
                    "md:sticky md:top-0 md:inset-auto md:translate-x-0 md:h-screen",
                ].join(" ")}
            >
                <WikiSidebar
                    items={navigationItems}
                    currentPath={currentPath}
                />
            </aside>

            {/* Main Content */}
            <main className="flex-1 bg-card">
                {/* Wiki Header Bar — sidebar toggle (mobile) + project search */}
                <div className="sticky top-0 z-30 border-b border-border/50 bg-background/80 backdrop-blur-md">
                    <div className="flex items-center gap-3 px-4 py-3 md:px-8">
                        <label
                            htmlFor={sidebarToggleId}
                            className="inline-flex items-center justify-center rounded-md p-2 text-foreground hover:bg-muted transition-colors cursor-pointer md:hidden"
                            aria-label="Toggle sidebar"
                        >
                            <Menu className="h-5 w-5" />
                        </label>
                        <div className="ml-auto">
                            <WikiSearchBar repositoryId={projectId} />
                        </div>
                    </div>
                </div>

                {/* Content Area */}
                <div className="flex gap-8 px-4 sm:px-6 md:px-8 py-8 md:py-12">
                    {/* Article */}
                    <article className="flex-1 min-w-0 max-w-3xl mx-auto pb-20">
                        {/* Breadcrumbs */}
                        {breadcrumbs.length > 0 && (
                            <div className="mb-8">
                                <Breadcrumb>
                                    <BreadcrumbList>
                                        {breadcrumbs.map((crumb, idx) => (
                                            <div
                                                key={crumb.path}
                                                className="flex items-center gap-2"
                                            >
                                                {idx > 0 && (
                                                    <BreadcrumbSeparator />
                                                )}
                                                {idx ===
                                                breadcrumbs.length - 1 ? (
                                                    <BreadcrumbPage className="text-sm">
                                                        {crumb.title}
                                                    </BreadcrumbPage>
                                                ) : (
                                                    <BreadcrumbLink
                                                        href={crumb.path}
                                                        className="text-sm"
                                                    >
                                                        {crumb.title}
                                                    </BreadcrumbLink>
                                                )}
                                            </div>
                                        ))}
                                    </BreadcrumbList>
                                </Breadcrumb>
                            </div>
                        )}

                        {/* Page Metadata + content area. The metadata
                            strip and content live inside a client
                            wrapper so the "Versions ▾" selector can
                            swap the rendered body for a historical
                            snapshot without a full navigation. */}
                        {projectId ? (
                            <VersionedPageBody
                                pageId={page.id}
                                pageTitle={page.title}
                                blocks={page.blocks}
                                tooltips={page.tooltips}
                                symbolMap={symbolMap}
                                generationId={projectId}
                                readingTime={
                                    page.metadata?.readingTime ??
                                    page.metadata?.reading_time
                                }
                                lastUpdated={page.metadata?.lastUpdated}
                                tags={page.metadata?.tags}
                                categories={page.metadata?.categories}
                                // B11.1 — commit hash deep-link.
                                commitSha={
                                    page.metadata?.commit_sha ??
                                    page.repository?.commit_sha ??
                                    null
                                }
                                repoGitUrl={page.repository?.git_url ?? null}
                                // B6.3 — server-side date + dominant LLM model.
                                generatedAt={
                                    page.metadata?.generated_at ?? null
                                }
                                llmModel={page.metadata?.llm_model ?? null}
                                // B6.4 — raw markdown for "Download Markdown".
                                bodyMarkdown={page.body_markdown ?? null}
                                // B6.5 — repository (full ref) + source ranges
                                // for "View source" deep-link.
                                repository={page.repository ?? null}
                                sourceRefs={page.metadata?.source_refs ?? []}
                            />
                        ) : (
                            // No projectId means we don't have a
                            // bundle to scope the version history
                            // against (e.g. local-fs preview). Drop
                            // the selector and render the content
                            // straight through.
                            <FallbackPageBody page={page} symbolMap={symbolMap} />
                        )}

                        <PageNavigation prev={prevPage} next={nextPage} />
                    </article>

                    {/* Table of Contents */}
                    {hasTableOfContents && (
                        <aside className="hidden xl:block flex-shrink-0 w-64">
                            <TableOfContents headings={headings} />
                        </aside>
                    )}
                </div>
            </main>

            {/* CodeTour Input - Fixed at bottom */}
            <CodeTourInput generationId={projectId} />
        </div>
    );
}

// Renders the existing metadata strip + content without the version
// selector (B11.2). Used when ``projectId`` is missing — e.g. local-fs
// previews where no bundle exists, so there's no version history to
// query. Keeping this as a small inline fallback avoids spreading
// projectId-conditional logic into VersionedPageBody itself.
function FallbackPageBody({
    page,
    symbolMap,
}: {
    page: WikiPage;
    symbolMap?: SymbolMap;
}) {
    return (
        <>
            <PageMetadata
                readingTime={
                    page.metadata?.readingTime ?? page.metadata?.reading_time
                }
                lastUpdated={page.metadata?.lastUpdated}
                tags={page.metadata?.tags}
                categories={page.metadata?.categories}
                commitSha={
                    page.metadata?.commit_sha ??
                    page.repository?.commit_sha ??
                    null
                }
                repoGitUrl={page.repository?.git_url ?? null}
                generatedAt={page.metadata?.generated_at ?? null}
                llmModel={page.metadata?.llm_model ?? null}
                bodyMarkdown={page.body_markdown ?? null}
                pageSlug={page.id}
                repository={page.repository ?? null}
                sourceRefs={page.metadata?.source_refs ?? []}
            />
            <ContentRenderer
                blocks={page.blocks}
                tooltips={page.tooltips}
                symbolMap={symbolMap}
                currentPageId={page.id}
            />
        </>
    );
}
