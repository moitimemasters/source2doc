"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { parse as parseYaml } from "yaml";
import { Upload } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

const LLM_PROVIDERS = [
    "openai",
    "openai-compatible",
    "anthropic",
    "yandex",
    "ollama",
];

const EMBEDDING_PROVIDERS = ["openai", "openai-compatible"];

const AGENT_ROLES = [
    "planner",
    "subplanner",
    "writer",
    "diagrammer",
    "critic",
    "normalizer",
] as const;
type AgentRole = (typeof AGENT_ROLES)[number];

type AgentOverrideForm = {
    enabled: boolean;
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
    temperature: number;
    max_tokens: number;
    max_sessions: number | null;
};

type PresetForm = {
    name: string;
    description: string;
    is_default: boolean;
    llm: {
        provider: string;
        model: string;
        api_key: string;
        base_url: string;
        temperature: number;
        max_tokens: number;
        max_sessions: number | null;
    };
    embeddings: {
        provider: string;
        model: string;
        api_key: string;
        base_url: string;
        dimensions: number;
        batch_size: number;
        concurrency: number;
    };
    qdrant: {
        url: string;
        api_key: string;
    };
    agents: Record<AgentRole, AgentOverrideForm>;
};

const emptyAgentOverride: AgentOverrideForm = {
    enabled: false,
    provider: "openai-compatible",
    model: "",
    api_key: "",
    base_url: "",
    temperature: 0.3,
    max_tokens: 4000,
    max_sessions: null,
};

function emptyAgents(): Record<AgentRole, AgentOverrideForm> {
    return Object.fromEntries(
        AGENT_ROLES.map((role) => [role, { ...emptyAgentOverride }])
    ) as Record<AgentRole, AgentOverrideForm>;
}

const empty: PresetForm = {
    name: "",
    description: "",
    is_default: false,
    llm: {
        provider: "openai-compatible",
        model: "",
        api_key: "",
        base_url: "",
        temperature: 0.3,
        max_tokens: 4000,
        max_sessions: null,
    },
    embeddings: {
        provider: "openai",
        model: "text-embedding-3-small",
        api_key: "",
        base_url: "",
        dimensions: 1536,
        batch_size: 100,
        concurrency: 4,
    },
    qdrant: { url: "http://qdrant:6333", api_key: "" },
    agents: emptyAgents(),
};

interface PresetEditorProps {
    presetId?: number;
    onSaved?: () => void;
    onCancel?: () => void;
}

export function PresetEditor({ presetId, onSaved, onCancel }: PresetEditorProps) {
    const [form, setForm] = useState<PresetForm>(empty);
    const [loading, setLoading] = useState(Boolean(presetId));
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const yamlInputRef = useRef<HTMLInputElement | null>(null);

    async function onYamlSelected(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0];
        if (!file) return;
        try {
            const text = await file.text();
            const parsed: any = parseYaml(text);
            const llm = parsed?.llm ?? {};
            const emb = parsed?.embeddings ?? {};
            const qd = parsed?.qdrant ?? {};
            const agentsRaw = parsed?.agents ?? {};
            setForm((prev) => ({
                ...prev,
                llm: {
                    provider: llm.provider ?? prev.llm.provider,
                    model: llm.model ?? prev.llm.model,
                    api_key: llm.api_key ?? prev.llm.api_key,
                    base_url: llm.base_url ?? prev.llm.base_url,
                    temperature: llm.temperature ?? prev.llm.temperature,
                    max_tokens: llm.max_tokens ?? prev.llm.max_tokens,
                    max_sessions: llm.max_sessions ?? prev.llm.max_sessions,
                },
                embeddings: {
                    provider: emb.provider ?? prev.embeddings.provider,
                    model: emb.model ?? prev.embeddings.model,
                    api_key: emb.api_key ?? prev.embeddings.api_key,
                    base_url: emb.base_url ?? prev.embeddings.base_url,
                    dimensions: emb.dimensions ?? prev.embeddings.dimensions,
                    batch_size: emb.batch_size ?? prev.embeddings.batch_size,
                    concurrency: emb.concurrency ?? prev.embeddings.concurrency,
                },
                qdrant: {
                    url: qd.url ?? prev.qdrant.url,
                    api_key: qd.api_key ?? prev.qdrant.api_key,
                },
                agents: AGENT_ROLES.reduce((acc, role) => {
                    const cfg = agentsRaw?.[role];
                    if (cfg) {
                        acc[role] = {
                            enabled: true,
                            provider: cfg.provider ?? prev.agents[role].provider,
                            model: cfg.model ?? prev.agents[role].model,
                            api_key: cfg.api_key ?? prev.agents[role].api_key,
                            base_url: cfg.base_url ?? prev.agents[role].base_url,
                            temperature:
                                cfg.temperature ?? prev.agents[role].temperature,
                            max_tokens: cfg.max_tokens ?? prev.agents[role].max_tokens,
                        };
                    } else {
                        acc[role] = prev.agents[role];
                    }
                    return acc;
                }, {} as Record<AgentRole, AgentOverrideForm>),
            }));
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? `YAML parse error: ${err.message}` : "YAML parse error");
        } finally {
            if (yamlInputRef.current) yamlInputRef.current.value = "";
        }
    }

    useEffect(() => {
        if (!presetId) return;
        let cancelled = false;
        fetch(`/api/admin/presets/${presetId}?reveal=true`, { cache: "no-store" })
            .then(async (response) => {
                if (!response.ok) {
                    setError("Failed to load preset");
                    return;
                }
                const body = await response.json();
                if (cancelled) return;
                if (body.config) {
                    const agentsCfg = body.config.agents ?? {};
                    setForm({
                        name: body.name,
                        description: body.description ?? "",
                        is_default: body.is_default,
                        llm: {
                            provider: body.config.llm.provider,
                            model: body.config.llm.model,
                            api_key: body.config.llm.api_key ?? "",
                            base_url: body.config.llm.base_url ?? "",
                            temperature: body.config.llm.temperature ?? 0.3,
                            max_tokens: body.config.llm.max_tokens ?? 4000,
                            max_sessions: body.config.llm.max_sessions ?? null,
                        },
                        embeddings: {
                            provider: body.config.embeddings.provider,
                            model: body.config.embeddings.model,
                            api_key: body.config.embeddings.api_key ?? "",
                            base_url: body.config.embeddings.base_url ?? "",
                            dimensions: body.config.embeddings.dimensions ?? 1536,
                            batch_size: body.config.embeddings.batch_size ?? 100,
                            concurrency: body.config.embeddings.concurrency ?? 4,
                        },
                        qdrant: {
                            url: body.config.qdrant?.url ?? "http://qdrant:6333",
                            api_key: body.config.qdrant?.api_key ?? "",
                        },
                        agents: AGENT_ROLES.reduce((acc, role) => {
                            const cfg = agentsCfg?.[role];
                            acc[role] = cfg
                                ? {
                                      enabled: true,
                                      provider:
                                          cfg.provider ??
                                          emptyAgentOverride.provider,
                                      model: cfg.model ?? "",
                                      api_key: cfg.api_key ?? "",
                                      base_url: cfg.base_url ?? "",
                                      temperature: cfg.temperature ?? 0.3,
                                      max_tokens: cfg.max_tokens ?? 4000,
                                  }
                                : { ...emptyAgentOverride };
                            return acc;
                        }, {} as Record<AgentRole, AgentOverrideForm>),
                    });
                }
            })
            .finally(() => {
                if (cancelled) return;
                setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [presetId]);

    async function onSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setSubmitting(true);
        setError(null);
        const payload = {
            name: form.name,
            description: form.description || undefined,
            is_default: form.is_default,
            config: {
                llm: {
                    provider: form.llm.provider,
                    model: form.llm.model,
                    api_key: form.llm.api_key,
                    base_url: form.llm.base_url || undefined,
                    temperature: form.llm.temperature,
                    max_tokens: form.llm.max_tokens,
                    max_sessions: form.llm.max_sessions,
                },
                embeddings: {
                    provider: form.embeddings.provider,
                    model: form.embeddings.model,
                    api_key: form.embeddings.api_key,
                    base_url: form.embeddings.base_url || undefined,
                    dimensions: form.embeddings.dimensions,
                    batch_size: form.embeddings.batch_size,
                    concurrency: form.embeddings.concurrency,
                },
                qdrant: {
                    url: form.qdrant.url,
                    api_key: form.qdrant.api_key || undefined,
                },
                agents: (() => {
                    const out: Record<string, unknown> = {};
                    for (const role of AGENT_ROLES) {
                        const a = form.agents[role];
                        if (!a.enabled) continue;
                        out[role] = {
                            provider: a.provider,
                            model: a.model,
                            api_key: a.api_key,
                            base_url: a.base_url || undefined,
                            temperature: a.temperature,
                            max_tokens: a.max_tokens,
                        };
                    }
                    return Object.keys(out).length > 0 ? out : undefined;
                })(),
            },
        };
        try {
            const url = presetId
                ? `/api/admin/presets/${presetId}`
                : "/api/admin/presets";
            const response = await fetch(url, {
                method: presetId ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                throw new Error(body?.detail || `Gateway returned ${response.status}`);
            }
            onSaved?.();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save preset");
        } finally {
            setSubmitting(false);
        }
    }

    if (loading) {
        return <p className="text-muted-foreground">Loading…</p>;
    }

    return (
        <form onSubmit={onSubmit} className="space-y-6">
            <Card>
                <CardHeader className="flex flex-row items-start justify-between gap-4">
                    <div>
                        <CardTitle>Preset</CardTitle>
                        <CardDescription>
                            Stored encrypted in Postgres using the gateway encryption key.
                        </CardDescription>
                    </div>
                    <div>
                        <input
                            ref={yamlInputRef}
                            type="file"
                            accept=".yaml,.yml"
                            onChange={onYamlSelected}
                            className="hidden"
                        />
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => yamlInputRef.current?.click()}
                        >
                            <Upload className="mr-2 h-4 w-4" />
                            Load YAML
                        </Button>
                    </div>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-2">
                        <Label htmlFor="name">Name</Label>
                        <Input
                            id="name"
                            value={form.name}
                            onChange={(event) =>
                                setForm({ ...form, name: event.target.value })
                            }
                            required
                        />
                    </div>
                    <div className="space-y-2">
                        <Label htmlFor="description">Description</Label>
                        <Textarea
                            id="description"
                            rows={2}
                            value={form.description}
                            onChange={(event) =>
                                setForm({ ...form, description: event.target.value })
                            }
                        />
                    </div>
                    <div className="flex items-center gap-3">
                        <Switch
                            id="is_default"
                            checked={form.is_default}
                            onCheckedChange={(checked) =>
                                setForm({ ...form, is_default: checked })
                            }
                        />
                        <Label htmlFor="is_default">Use as default preset</Label>
                    </div>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>LLM</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                        <Label>Provider</Label>
                        <Select
                            value={form.llm.provider}
                            onValueChange={(value) =>
                                setForm({
                                    ...form,
                                    llm: { ...form.llm, provider: value },
                                })
                            }
                        >
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {LLM_PROVIDERS.map((provider) => (
                                    <SelectItem key={provider} value={provider}>
                                        {provider}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-2">
                        <Label>Model</Label>
                        <Input
                            value={form.llm.model}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    llm: { ...form.llm, model: event.target.value },
                                })
                            }
                            required
                        />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                        <Label>API key</Label>
                        <Input
                            type="password"
                            value={form.llm.api_key}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    llm: { ...form.llm, api_key: event.target.value },
                                })
                            }
                            required
                        />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                        <Label>Base URL (optional)</Label>
                        <Input
                            value={form.llm.base_url}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    llm: { ...form.llm, base_url: event.target.value },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Temperature</Label>
                        <Input
                            type="number"
                            min={0}
                            max={2}
                            step={0.05}
                            value={form.llm.temperature}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    llm: {
                                        ...form.llm,
                                        temperature: Number(event.target.value),
                                    },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Max tokens</Label>
                        <Input
                            type="number"
                            min={1}
                            value={form.llm.max_tokens}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    llm: {
                                        ...form.llm,
                                        max_tokens: Number(event.target.value),
                                    },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="llm-max-sessions">
                            Max sessions{" "}
                            <span className="text-muted-foreground font-normal">
                                (cluster-wide, optional)
                            </span>
                        </Label>
                        <Input
                            id="llm-max-sessions"
                            type="number"
                            min={1}
                            placeholder="leave empty for no limit"
                            value={form.llm.max_sessions ?? ""}
                            onChange={(event) => {
                                const v = event.target.value.trim();
                                setForm({
                                    ...form,
                                    llm: {
                                        ...form.llm,
                                        max_sessions: v === "" ? null : Number(v),
                                    },
                                });
                            }}
                        />
                        <p className="text-xs text-muted-foreground">
                            Cap on parallel agent runs across all workers and
                            tasks that share this API key. Set to your provider&apos;s
                            inflight limit (Eliza default: 5) to avoid HTTP 429.
                            Empty = unlimited (uses per-worker fallback).
                        </p>
                    </div>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>Embeddings</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                        <Label>Provider</Label>
                        <Select
                            value={form.embeddings.provider}
                            onValueChange={(value) =>
                                setForm({
                                    ...form,
                                    embeddings: { ...form.embeddings, provider: value },
                                })
                            }
                        >
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {EMBEDDING_PROVIDERS.map((provider) => (
                                    <SelectItem key={provider} value={provider}>
                                        {provider}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-2">
                        <Label>Model</Label>
                        <Input
                            value={form.embeddings.model}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    embeddings: {
                                        ...form.embeddings,
                                        model: event.target.value,
                                    },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                        <Label>API key</Label>
                        <Input
                            type="password"
                            value={form.embeddings.api_key}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    embeddings: {
                                        ...form.embeddings,
                                        api_key: event.target.value,
                                    },
                                })
                            }
                            required
                        />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                        <Label>Base URL (optional)</Label>
                        <Input
                            value={form.embeddings.base_url}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    embeddings: {
                                        ...form.embeddings,
                                        base_url: event.target.value,
                                    },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Dimensions</Label>
                        <Input
                            type="number"
                            min={1}
                            value={form.embeddings.dimensions}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    embeddings: {
                                        ...form.embeddings,
                                        dimensions: Number(event.target.value),
                                    },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Batch size</Label>
                        <Input
                            type="number"
                            min={1}
                            value={form.embeddings.batch_size}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    embeddings: {
                                        ...form.embeddings,
                                        batch_size: Number(event.target.value),
                                    },
                                })
                            }
                        />
                    </div>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>Qdrant</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2 md:col-span-2">
                        <Label>URL</Label>
                        <Input
                            value={form.qdrant.url}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    qdrant: { ...form.qdrant, url: event.target.value },
                                })
                            }
                        />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                        <Label>API key (optional)</Label>
                        <Input
                            type="password"
                            value={form.qdrant.api_key}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    qdrant: {
                                        ...form.qdrant,
                                        api_key: event.target.value,
                                    },
                                })
                            }
                        />
                    </div>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>Per-agent LLM overrides</CardTitle>
                    <CardDescription>
                        Override the default LLM for individual pipeline stages.
                        Disabled rows fall back to the top-level LLM above.
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    {AGENT_ROLES.map((role) => {
                        const agent = form.agents[role];
                        return (
                            <div
                                key={role}
                                className="rounded-md border p-3 space-y-3"
                            >
                                <div className="flex items-center justify-between">
                                    <Label className="capitalize">{role}</Label>
                                    <Switch
                                        checked={agent.enabled}
                                        onCheckedChange={(checked) =>
                                            setForm((prev) => ({
                                                ...prev,
                                                agents: {
                                                    ...prev.agents,
                                                    [role]: {
                                                        ...prev.agents[role],
                                                        enabled: checked,
                                                    },
                                                },
                                            }))
                                        }
                                    />
                                </div>
                                {agent.enabled && (
                                    <div className="grid gap-3 md:grid-cols-2">
                                        <div className="space-y-2">
                                            <Label>Provider</Label>
                                            <Select
                                                value={agent.provider}
                                                onValueChange={(value) =>
                                                    setForm((prev) => ({
                                                        ...prev,
                                                        agents: {
                                                            ...prev.agents,
                                                            [role]: {
                                                                ...prev.agents[role],
                                                                provider: value,
                                                            },
                                                        },
                                                    }))
                                                }
                                            >
                                                <SelectTrigger>
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {LLM_PROVIDERS.map((p) => (
                                                        <SelectItem key={p} value={p}>
                                                            {p}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Model</Label>
                                            <Input
                                                value={agent.model}
                                                onChange={(event) =>
                                                    setForm((prev) => ({
                                                        ...prev,
                                                        agents: {
                                                            ...prev.agents,
                                                            [role]: {
                                                                ...prev.agents[role],
                                                                model: event.target.value,
                                                            },
                                                        },
                                                    }))
                                                }
                                                required
                                            />
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>API key</Label>
                                            <Input
                                                type="password"
                                                value={agent.api_key}
                                                onChange={(event) =>
                                                    setForm((prev) => ({
                                                        ...prev,
                                                        agents: {
                                                            ...prev.agents,
                                                            [role]: {
                                                                ...prev.agents[role],
                                                                api_key: event.target.value,
                                                            },
                                                        },
                                                    }))
                                                }
                                                required
                                            />
                                        </div>
                                        <div className="space-y-2 md:col-span-2">
                                            <Label>Base URL (optional)</Label>
                                            <Input
                                                value={agent.base_url}
                                                onChange={(event) =>
                                                    setForm((prev) => ({
                                                        ...prev,
                                                        agents: {
                                                            ...prev.agents,
                                                            [role]: {
                                                                ...prev.agents[role],
                                                                base_url: event.target.value,
                                                            },
                                                        },
                                                    }))
                                                }
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Temperature</Label>
                                            <Input
                                                type="number"
                                                min={0}
                                                max={2}
                                                step={0.05}
                                                value={agent.temperature}
                                                onChange={(event) =>
                                                    setForm((prev) => ({
                                                        ...prev,
                                                        agents: {
                                                            ...prev.agents,
                                                            [role]: {
                                                                ...prev.agents[role],
                                                                temperature: Number(event.target.value),
                                                            },
                                                        },
                                                    }))
                                                }
                                            />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Max tokens</Label>
                                            <Input
                                                type="number"
                                                min={1}
                                                value={agent.max_tokens}
                                                onChange={(event) =>
                                                    setForm((prev) => ({
                                                        ...prev,
                                                        agents: {
                                                            ...prev.agents,
                                                            [role]: {
                                                                ...prev.agents[role],
                                                                max_tokens: Number(event.target.value),
                                                            },
                                                        },
                                                    }))
                                                }
                                            />
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </CardContent>
            </Card>

            {error && (
                <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}

            <div className="flex justify-end gap-2">
                {onCancel && (
                    <Button type="button" variant="outline" onClick={onCancel}>
                        Cancel
                    </Button>
                )}
                <Button type="submit" disabled={submitting}>
                    {submitting ? "Saving…" : presetId ? "Save changes" : "Create preset"}
                </Button>
            </div>
        </form>
    );
}
