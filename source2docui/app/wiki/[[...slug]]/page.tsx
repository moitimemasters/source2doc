import { notFound, redirect } from "next/navigation";
import { WikiLayout } from "@/components/wiki/WikiLayout";
import {
    loadWikiPage,
    loadNavigationConfig,
    buildBreadcrumbs,
    getAdjacentPages,
} from "@/lib/wiki/content-loader";
import { fetchSymbolMap } from "@/lib/wiki/symbols";
import type { NavigationItem } from "@/lib/wiki/types";

interface WikiPageProps {
    params: Promise<{
        slug?: string[];
    }>;
}

export async function generateMetadata(props: WikiPageProps) {
    const params = await props.params;
    const slug = params.slug || ["getting-started"];

    const projectId = slug.length > 0 ? slug[0] : undefined;
    const contentSlug = slug.length > 1 ? slug.slice(1) : ["getting-started"];

    const page = await loadWikiPage(contentSlug, projectId);

    if (!page) {
        return {
            title: "Not Found",
        };
    }

    return {
        title: `${page.title} | Wiki`,
        description: page.description || "Wiki documentation",
    };
}

function firstNavigationLeaf(items: NavigationItem[]): string | null {
    for (const item of items) {
        if (item.children && item.children.length > 0) {
            const childLeaf = firstNavigationLeaf(item.children);
            if (childLeaf) return childLeaf;
        }
        if (item.path) return item.path;
    }
    return null;
}

export default async function WikiPage(props: WikiPageProps) {
    const params = await props.params;
    if (!params.slug || params.slug.length === 0) {
        redirect("/");
    }
    const slug = params.slug;

    const projectId = slug.length > 0 ? slug[0] : undefined;

    if (slug.length === 1) {
        const navigationItems = await loadNavigationConfig(projectId);
        const target = firstNavigationLeaf(navigationItems);
        if (target) {
            redirect(target);
        }
        notFound();
    }

    const contentSlug = slug.slice(1);

    const page = await loadWikiPage(contentSlug, projectId);
    if (!page) {
        notFound();
    }

    const navigationItems = await loadNavigationConfig(projectId);

    const currentPath = `/wiki/${slug.join("/")}`;
    const breadcrumbs = buildBreadcrumbs(navigationItems, currentPath);

    const { prev, next } = getAdjacentPages(navigationItems, currentPath);

    // Cross-page link map (B6.2 / ТЗ ДОК-08). The map lives at the wiki
    // level — one fetch per page-load, then it's threaded through inline
    // renderers to wrap matching <code> and prose mentions in <a>.
    const symbolMap = projectId ? await fetchSymbolMap(projectId) : new Map();

    return (
        <WikiLayout
            page={page}
            navigationItems={navigationItems}
            currentPath={currentPath}
            breadcrumbs={breadcrumbs}
            prevPage={prev}
            nextPage={next}
            projectId={projectId}
            symbolMap={symbolMap}
        />
    );
}
