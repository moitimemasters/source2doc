"use client";

import * as React from "react";
import { Search as SearchIcon } from "lucide-react";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";
import { WikiSearchPanel } from "./WikiSearchPanel";

interface WikiSearchBarProps {
    repositoryId?: string;
    className?: string;
}

export function WikiSearchBar({
    repositoryId,
    className,
}: WikiSearchBarProps) {
    const [open, setOpen] = React.useState(false);
    const [query, setQuery] = React.useState("");
    const [submission, setSubmission] = React.useState<{
        query: string;
        token: number;
    } | null>(null);

    function submit() {
        const trimmed = query.trim();
        if (!trimmed) return;
        // Bump the token on every submit so the panel re-runs the search,
        // even if the query string is unchanged.
        setSubmission((prev) => ({
            query: trimmed,
            token: (prev?.token ?? 0) + 1,
        }));
        setOpen(true);
    }

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
        if (e.key === "Enter") {
            e.preventDefault();
            submit();
        }
    }

    const disabled = !repositoryId;

    return (
        <div
            className={cn(
                "flex items-center gap-2",
                className,
            )}
        >
            {/* Compact (inline) search input — visible on >= sm */}
            <div className="hidden items-center gap-2 sm:flex">
                <div className="relative">
                    <SearchIcon
                        className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                        aria-hidden
                    />
                    <Input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={handleKeyDown}
                        onFocus={(e) => e.currentTarget.select()}
                        placeholder={
                            disabled
                                ? "Select a project to search"
                                : "Search project…"
                        }
                        className="h-8 w-44 pl-8 text-sm md:w-64 lg:w-72"
                        aria-label="Search project"
                        disabled={disabled}
                    />
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={submit}
                    disabled={disabled || !query.trim()}
                >
                    Search
                </Button>
            </div>

            {/* Icon-only collapsed button — visible on < sm */}
            <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                aria-label="Open project search"
                onClick={() => setOpen(true)}
                disabled={disabled}
                className="sm:hidden"
            >
                <SearchIcon className="size-4" />
            </Button>

            <WikiSearchPanel
                open={open}
                onOpenChange={setOpen}
                repositoryId={repositoryId}
                submission={submission}
            />
        </div>
    );
}
