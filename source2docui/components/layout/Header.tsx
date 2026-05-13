"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Activity, FileText, Map, Settings } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { HealthHeaderIndicator } from "@/components/admin/HealthHeaderIndicator";

export function Header() {
    const pathname = usePathname();

    const isActive = (path: string) => {
        if (path === "/") {
            return pathname === "/";
        }
        return pathname.startsWith(path);
    };

    return (
        <header className="sticky top-0 z-30 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="container flex h-14 max-w-screen-2xl items-center gap-2 px-3 sm:px-4">
                <Link
                    href="/"
                    className="flex items-center space-x-2 mr-2 sm:mr-6"
                    aria-label="Source2Doc home"
                >
                    <FileText className="h-6 w-6" />
                    <span className="hidden font-bold sm:inline-block">
                        Source2Doc
                    </span>
                </Link>
                <nav className="flex items-center gap-1 sm:gap-6 text-sm font-medium min-w-0">
                    <Link
                        href="/"
                        aria-label="Home"
                        className={`transition-colors hover:text-foreground/80 ${
                            isActive("/") &&
                            !pathname.includes("/wiki") &&
                            !pathname.includes("/streams") &&
                            !pathname.includes("/admin") &&
                            !pathname.includes("/tour")
                                ? "text-foreground"
                                : "text-foreground/60"
                        }`}
                    >
                        <span className="flex items-center gap-2 px-2 py-1 sm:px-0 sm:py-0">
                            <Home className="h-4 w-4" />
                            <span className="hidden sm:inline">Home</span>
                        </span>
                    </Link>
                    <Link
                        href="/streams"
                        aria-label="Streams"
                        className={`transition-colors hover:text-foreground/80 ${
                            isActive("/streams")
                                ? "text-foreground"
                                : "text-foreground/60"
                        }`}
                    >
                        <span className="flex items-center gap-2 px-2 py-1 sm:px-0 sm:py-0">
                            <Activity className="h-4 w-4" />
                            <span className="hidden sm:inline">Streams</span>
                        </span>
                    </Link>
                    <Link
                        href="/tour"
                        aria-label="Tours"
                        className={`transition-colors hover:text-foreground/80 ${
                            isActive("/tour")
                                ? "text-foreground"
                                : "text-foreground/60"
                        }`}
                    >
                        <span className="flex items-center gap-2 px-2 py-1 sm:px-0 sm:py-0">
                            <Map className="h-4 w-4" />
                            <span className="hidden sm:inline">Tours</span>
                        </span>
                    </Link>
                    <Link
                        href="/admin"
                        aria-label="Admin"
                        className={`transition-colors hover:text-foreground/80 ${
                            isActive("/admin")
                                ? "text-foreground"
                                : "text-foreground/60"
                        }`}
                    >
                        <span className="flex items-center gap-2 px-2 py-1 sm:px-0 sm:py-0">
                            <Settings className="h-4 w-4" />
                            <span className="hidden sm:inline">Admin</span>
                        </span>
                    </Link>
                    <Link href="/admin/generate">
                        <Button
                            variant={
                                isActive("/admin/generate") ? "default" : "outline"
                            }
                            size="sm"
                            className="px-2 sm:px-3"
                        >
                            <span className="sm:hidden">+ Docs</span>
                            <span className="hidden sm:inline">
                                Generate Docs
                            </span>
                        </Button>
                    </Link>
                </nav>
                <div className="ml-auto flex items-center space-x-2">
                    {pathname.startsWith("/admin") &&
                        pathname !== "/admin/login" && <HealthHeaderIndicator />}
                    <ThemeToggle />
                </div>
            </div>
        </header>
    );
}
