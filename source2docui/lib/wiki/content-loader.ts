import { WikiPage, NavigationItem } from "./types";
import { projectLoader } from "./project-loader";
import { ContentSourceFactory } from "./content-source";

export async function loadWikiPage(
    slug: string[],
    projectId?: string,
): Promise<WikiPage | null> {
    const project = projectId
        ? await projectLoader.getProject(projectId)
        : await projectLoader.getDefaultProject();

    if (!project) {
        return null;
    }

    const source = ContentSourceFactory.create(project);
    return source.loadPage(slug);
}

function prefixNavigationPaths(
    items: NavigationItem[],
    projectId: string,
): NavigationItem[] {
    return items.map((item) => ({
        ...item,
        path: `/wiki/${projectId}${item.path.replace(/^\/wiki/, "")}`,
        children: item.children
            ? prefixNavigationPaths(item.children, projectId)
            : undefined,
    }));
}

export async function loadNavigationConfig(
    projectId?: string,
): Promise<NavigationItem[]> {
    const project = projectId
        ? await projectLoader.getProject(projectId)
        : await projectLoader.getDefaultProject();

    if (!project) {
        return [];
    }

    const source = ContentSourceFactory.create(project);
    const items = await source.loadNavigation();

    if (projectId) {
        return prefixNavigationPaths(items, projectId);
    }

    return items;
}

// Find a navigation item by path
export function findNavigationItem(
    items: NavigationItem[],
    path: string,
): NavigationItem | null {
    for (const item of items) {
        if (item.path === path) {
            return item;
        }
        if (item.children) {
            const found = findNavigationItem(item.children, path);
            if (found) {
                return found;
            }
        }
    }
    return null;
}

// Build breadcrumbs from navigation structure
export function buildBreadcrumbs(
    items: NavigationItem[],
    currentPath: string,
    breadcrumbs: Array<{ title: string; path: string }> = [],
): Array<{ title: string; path: string }> {
    for (const item of items) {
        const newBreadcrumbs = [
            ...breadcrumbs,
            { title: item.title, path: item.path },
        ];

        if (item.path === currentPath) {
            return newBreadcrumbs;
        }

        if (item.children) {
            const result = buildBreadcrumbs(
                item.children,
                currentPath,
                newBreadcrumbs,
            );
            // If we found the path in children, return the result
            if (
                result.length > 0 &&
                result[result.length - 1]?.path === currentPath
            ) {
                return result;
            }
        }
    }

    return breadcrumbs;
}

// Flatten navigation items into a linear array for prev/next navigation.
// Parent items that only group children (no own page content) are skipped:
// the MVP nav format encodes those as objects with `title` + `children` and
// the section header isn't a real wiki page, so prev/next must walk the
// leaves only.
function flattenNavigationItems(items: NavigationItem[]): NavigationItem[] {
    const result: NavigationItem[] = [];

    function traverse(items: NavigationItem[]) {
        for (const item of items) {
            const hasChildren = !!item.children?.length;
            if (!hasChildren) {
                result.push(item);
            }
            if (hasChildren) {
                traverse(item.children!);
            }
        }
    }

    traverse(items);
    return result;
}

// Get previous and next pages for navigation
export function getAdjacentPages(
    items: NavigationItem[],
    currentPath: string,
): { prev: NavigationItem | null; next: NavigationItem | null } {
    const flatItems = flattenNavigationItems(items);
    const currentIndex = flatItems.findIndex(
        (item) => item.path === currentPath,
    );

    if (currentIndex === -1) {
        return { prev: null, next: null };
    }

    return {
        prev: currentIndex > 0 ? flatItems[currentIndex - 1] : null,
        next:
            currentIndex < flatItems.length - 1
                ? flatItems[currentIndex + 1]
                : null,
    };
}
