"use client";

import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight } from "lucide-react";
import { getPhaseLabel, getPhaseIcon } from "@/lib/streams/event-grouping";
import * as LucideIcons from "lucide-react";

interface EventGroupHeaderProps {
    phase: string;
    eventCount: number;
    isExpanded: boolean;
    onToggle: () => void;
}

export function EventGroupHeader({
    phase,
    eventCount,
    isExpanded,
    onToggle,
}: EventGroupHeaderProps) {
    const iconName = getPhaseIcon(phase);
    const IconComponent = (LucideIcons as any)[iconName] || LucideIcons.Circle;

    return (
        <button
            className="w-full flex items-center gap-2 p-2 hover:bg-muted/50 transition-colors text-left font-mono"
            onClick={onToggle}
        >
            <div className="flex-shrink-0 text-muted-foreground">
                {isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                ) : (
                    <ChevronRight className="h-4 w-4" />
                )}
            </div>
            <div className="flex-shrink-0">
                <IconComponent className="h-3.5 w-3.5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
                <span className="font-semibold text-sm">
                    {getPhaseLabel(phase)}
                </span>
            </div>
            <Badge variant="secondary" className="text-xs h-5 px-2">
                {eventCount}
            </Badge>
        </button>
    );
}
