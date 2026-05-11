"use client";

import { FormEvent, Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function AdminLoginForm() {
    const searchParams = useSearchParams();
    const next = searchParams.get("next") || "/admin";

    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    async function onSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setError(null);
        setSubmitting(true);
        try {
            const response = await fetch("/api/admin/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                setError(body.detail || "Login failed");
                setSubmitting(false);
                return;
            }
            // Hard navigation: avoids Next 16 soft-navigation cache reading
            // the pre-login auth state and bouncing back to /admin/login.
            window.location.assign(next);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Network error");
            setSubmitting(false);
        }
    }

    return (
        <form
            onSubmit={onSubmit}
            className="w-full max-w-sm space-y-4 rounded-lg border bg-card p-6 shadow-sm"
        >
            <div>
                <h1 className="text-2xl font-semibold">Admin sign-in</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                    Use the credentials configured in
                    <code className="mx-1">core/gateway/config.docker.yaml</code>.
                </p>
            </div>
            <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                    id="username"
                    name="username"
                    autoComplete="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    required
                />
            </div>
            <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? "Signing in…" : "Sign in"}
            </Button>
        </form>
    );
}

export default function AdminLoginPage() {
    return (
        <div className="container mx-auto flex min-h-[60vh] items-center justify-center px-4 py-8">
            <Suspense fallback={<div className="text-muted-foreground">Loading…</div>}>
                <AdminLoginForm />
            </Suspense>
        </div>
    );
}
