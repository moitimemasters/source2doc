"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";

export function LogoutButton() {
    const router = useRouter();
    const [submitting, setSubmitting] = useState(false);

    async function onClick() {
        setSubmitting(true);
        try {
            await fetch("/api/admin/auth/logout", { method: "POST" });
        } finally {
            setSubmitting(false);
            router.replace("/admin/login");
            router.refresh();
        }
    }

    return (
        <Button
            variant="outline"
            size="sm"
            onClick={onClick}
            disabled={submitting}
        >
            <LogOut className="mr-2 h-4 w-4" />
            {submitting ? "Signing out…" : "Sign out"}
        </Button>
    );
}
