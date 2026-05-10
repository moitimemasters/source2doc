"use client";

import { useEffect, useState } from "react";
import { Plus, Star, StarOff, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { PresetEditor } from "@/components/admin/PresetEditor";

type Preset = {
    id: number;
    name: string;
    is_default: boolean;
    description: string | null;
    created_at: string;
    updated_at: string;
};

export default function AdminPresetsPage() {
    const [presets, setPresets] = useState<Preset[]>([]);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState<{ id?: number } | null>(null);

    async function refetch() {
        setLoading(true);
        const response = await fetch("/api/admin/presets", { cache: "no-store" });
        if (response.ok) {
            const body = await response.json();
            setPresets(body.presets ?? []);
        }
        setLoading(false);
    }

    useEffect(() => {
        refetch();
    }, []);

    async function setDefault(id: number) {
        const response = await fetch(`/api/admin/presets/${id}/set-default`, {
            method: "POST",
        });
        if (!response.ok) {
            toast.error("Failed to set default");
            return;
        }
        toast.success("Default preset updated");
        await refetch();
    }

    async function deletePreset(id: number, name: string) {
        if (!window.confirm(`Delete preset "${name}"?`)) return;
        const response = await fetch(`/api/admin/presets/${id}`, {
            method: "DELETE",
        });
        if (!response.ok && response.status !== 204) {
            toast.error("Failed to delete preset");
            return;
        }
        toast.success(`Deleted ${name}`);
        await refetch();
    }

    if (editing) {
        return (
            <div className="container mx-auto px-4 py-8">
                <div className="mx-auto max-w-3xl space-y-6">
                    <h1 className="text-2xl font-semibold">
                        {editing.id ? "Edit preset" : "New preset"}
                    </h1>
                    <PresetEditor
                        presetId={editing.id}
                        onSaved={async () => {
                            await refetch();
                            setEditing(null);
                        }}
                        onCancel={() => setEditing(null)}
                    />
                </div>
            </div>
        );
    }

    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mx-auto max-w-5xl space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-2xl font-semibold">Presets</h1>
                        <p className="text-muted-foreground">
                            One named preset = full LLM + embeddings + Qdrant stack.
                            End-users always use the default preset.
                        </p>
                    </div>
                    <Button onClick={() => setEditing({})}>
                        <Plus className="mr-2 h-4 w-4" /> New preset
                    </Button>
                </div>

                {loading && <p className="text-muted-foreground">Loading…</p>}
                {!loading && presets.length === 0 && (
                    <Card>
                        <CardHeader>
                            <CardTitle>No presets configured</CardTitle>
                            <CardDescription>
                                Create one and mark it as default to enable end-user
                                code-tour requests and the generation form.
                            </CardDescription>
                        </CardHeader>
                    </Card>
                )}

                <div className="grid gap-4">
                    {presets.map((preset) => (
                        <Card key={preset.id}>
                            <CardHeader className="flex flex-row items-start justify-between gap-4">
                                <div>
                                    <CardTitle className="flex items-center gap-2">
                                        {preset.name}
                                        {preset.is_default && (
                                            <span className="text-xs uppercase tracking-wide text-muted-foreground">
                                                default
                                            </span>
                                        )}
                                    </CardTitle>
                                    {preset.description && (
                                        <CardDescription>
                                            {preset.description}
                                        </CardDescription>
                                    )}
                                </div>
                                <div className="flex items-center gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setEditing({ id: preset.id })}
                                    >
                                        Edit
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setDefault(preset.id)}
                                        disabled={preset.is_default}
                                    >
                                        {preset.is_default ? (
                                            <Star className="mr-2 h-4 w-4" />
                                        ) : (
                                            <StarOff className="mr-2 h-4 w-4" />
                                        )}
                                        {preset.is_default ? "Default" : "Make default"}
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => deletePreset(preset.id, preset.name)}
                                    >
                                        <Trash2 className="h-4 w-4" />
                                    </Button>
                                </div>
                            </CardHeader>
                            <CardContent>
                                <p className="text-xs text-muted-foreground">
                                    Updated {new Date(preset.updated_at).toLocaleString()}
                                </p>
                            </CardContent>
                        </Card>
                    ))}
                </div>
            </div>
        </div>
    );
}
