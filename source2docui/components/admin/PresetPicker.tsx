"use client";

import { useEffect, useState } from "react";

import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";

export type PresetMeta = {
    id: number;
    name: string;
    is_default: boolean;
    description: string | null;
};

interface PresetPickerProps {
    value: string | null;
    onChange: (name: string) => void;
    placeholder?: string;
    disabled?: boolean;
}

export function PresetPicker({
    value,
    onChange,
    placeholder = "Use default preset",
    disabled,
}: PresetPickerProps) {
    const [presets, setPresets] = useState<PresetMeta[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        fetch("/api/admin/presets", { cache: "no-store" })
            .then(async (response) => {
                if (!response.ok) return;
                const body = await response.json();
                if (cancelled) return;
                setPresets(body.presets ?? []);
                if (!value) {
                    const fallback = (body.presets ?? []).find(
                        (preset: PresetMeta) => preset.is_default,
                    );
                    if (fallback) onChange(fallback.name);
                }
            })
            .finally(() => {
                if (cancelled) return;
                setLoading(false);
            });
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <Select
            value={value ?? ""}
            onValueChange={onChange}
            disabled={disabled || loading || presets.length === 0}
        >
            <SelectTrigger>
                <SelectValue
                    placeholder={
                        loading
                            ? "Loading presets…"
                            : presets.length === 0
                              ? "No presets configured"
                              : placeholder
                    }
                />
            </SelectTrigger>
            <SelectContent>
                {presets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.name}>
                        <div className="flex items-center gap-2">
                            <span>{preset.name}</span>
                            {preset.is_default && (
                                <span className="text-xs text-muted-foreground">
                                    (default)
                                </span>
                            )}
                        </div>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}
