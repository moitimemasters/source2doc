"use client";

import { useRef } from "react";
import { RepositoryList } from "@/components/admin/RepositoryList";
import { RepositoryUploadContainer } from "@/components/repos/RepositoryUploadContainer";

export default function AdminReposPage() {
    const refetchRef = useRef<(() => void) | null>(null);

    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mx-auto max-w-6xl space-y-6">
                <div>
                    <h1 className="text-2xl font-semibold">Repositories</h1>
                    <p className="text-muted-foreground">
                        Clone or upload a codebase to make it available for docgen / codetour.
                    </p>
                </div>
                <RepositoryUploadContainer
                    onSuccess={() => refetchRef.current?.()}
                />
                <RepositoryList
                    bindRefetch={(fn) => {
                        refetchRef.current = fn;
                    }}
                />
            </div>
        </div>
    );
}
