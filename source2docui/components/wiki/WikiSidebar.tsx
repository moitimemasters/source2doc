import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { cn } from "../../lib/utils";
import { NavigationItem } from "../../lib/wiki/types";

interface WikiSidebarProps {
    items: NavigationItem[];
    currentPath: string;
}

function isActivePath(currentPath: string, itemPath: string) {
    return currentPath === itemPath || currentPath.startsWith(itemPath + "/");
}

function NavItem({
    item,
    level,
    currentPath,
}: {
    item: NavigationItem;
    level: number;
    currentPath: string;
}) {
    const hasChildren = Boolean(item.children && item.children.length > 0);
    const active = isActivePath(currentPath, item.path);

    // Expand if parent is active OR any child is active
    const hasActiveChild =
        hasChildren &&
        item.children!.some((child) => isActivePath(currentPath, child.path));
    const expandedByDefault = hasChildren && (active || hasActiveChild);

    // CSS-only expand/collapse; resets naturally on navigation (good for mobile).
    const toggleId = `wiki-nav-toggle-${item.id}`;

    return (
        <div className="w-full">
            {hasChildren && (
                <input
                    id={toggleId}
                    type="checkbox"
                    className="peer sr-only"
                    defaultChecked={expandedByDefault}
                />
            )}

            <div
                className={cn(
                    "flex items-center gap-1.5",
                    hasChildren && "peer-checked:[&_[data-chevron]]:rotate-90",
                )}
                style={{ paddingLeft: `${level * 12}px` }}
            >
                {hasChildren ? (
                    <label
                        htmlFor={toggleId}
                        className={cn(
                            "flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors",
                            "hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        )}
                        aria-label="Toggle submenu"
                    >
                        <ChevronRight
                            data-chevron
                            className="h-4 w-4 transition-transform"
                        />
                    </label>
                ) : (
                    <div className="size-7" aria-hidden />
                )}

                <Link
                    href={item.path}
                    className={cn(
                        "relative flex-1 rounded-md px-2.5 py-1.5 text-sm leading-5 transition-colors",
                        "hover:bg-muted/60",
                        "before:absolute before:left-0 before:top-1 before:bottom-1 before:w-0.5 before:rounded-full before:content-['']",
                        active
                            ? "bg-primary/10 text-foreground font-medium before:bg-primary"
                            : "text-foreground/90 before:bg-transparent",
                    )}
                >
                    <span className="break-words">{item.title}</span>
                </Link>
            </div>

            {hasChildren && (
                <div className="mt-0.5 hidden peer-checked:block">
                    {item.children!.map((child) => (
                        <NavItem
                            key={child.id}
                            item={child}
                            level={level + 1}
                            currentPath={currentPath}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

export function WikiSidebar({ items, currentPath }: WikiSidebarProps) {
    return (
        <nav className="w-64 border-r border-border bg-card h-screen overflow-y-auto flex flex-col">
            <div className="px-4 py-6 border-b border-border/50">
                <p className="text-lg font-bold text-foreground">Wiki</p>
                <p className="text-xs text-muted-foreground mt-1">
                    Documentation
                </p>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
                <div className="space-y-1">
                    {items.map((item) => (
                        <NavItem
                            key={item.id}
                            item={item}
                            level={0}
                            currentPath={currentPath}
                        />
                    ))}
                </div>
            </div>
        </nav>
    );
}
