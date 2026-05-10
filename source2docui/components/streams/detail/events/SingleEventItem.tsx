"use client";

import { useState } from "react";
import { StreamEvent } from "@/lib/gateway/types";
import { getEventLabel, getEventIcon } from "@/lib/gateway/stream-utils";
import {
    getEventSummary,
    shouldShowDataInline,
    getEventColor,
} from "@/lib/streams/event-formatting";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight } from "lucide-react";
import * as LucideIcons from "lucide-react";
import JsonView from "@uiw/react-json-view";

interface SingleEventItemProps {
    event: StreamEvent;
    index: number;
}

export function SingleEventItem({ event, index }: SingleEventItemProps) {
    const [isExpanded, setIsExpanded] = useState(false);

    const hasData = event.data && Object.keys(event.data).length > 0;
    const showInline = shouldShowDataInline(event);
    const summary = getEventSummary(event);
    const colorClass = getEventColor(event.type);

    const iconName = getEventIcon(event.type);
    const IconComponent = (LucideIcons as any)[iconName] || LucideIcons.Circle;

    const isToggleable = Boolean(hasData) && !showInline;

    return (
        <div className="rounded border bg-card font-mono text-sm">
            <div
                className={`flex items-start gap-2.5 p-2.5 ${
                    isToggleable
                        ? "cursor-pointer hover:bg-muted/30 transition-colors"
                        : ""
                }`}
                role={isToggleable ? "button" : undefined}
                tabIndex={isToggleable ? 0 : undefined}
                aria-expanded={isToggleable ? isExpanded : undefined}
                onClick={
                    isToggleable
                        ? () => setIsExpanded(!isExpanded)
                        : undefined
                }
                onKeyDown={
                    isToggleable
                        ? (e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  setIsExpanded(!isExpanded);
                              }
                          }
                        : undefined
                }
            >
                <div className="flex-shrink-0 mt-0.5">
                    <IconComponent className={`h-3.5 w-3.5 ${colorClass}`} />
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                        <span className={`font-semibold text-xs ${colorClass}`}>
                            {getEventLabel(event.type)}
                        </span>
                        <Badge variant="outline" className="text-[10px] h-4 px-1">
                            #{index + 1}
                        </Badge>
                    </div>

                    <div className="text-xs text-muted-foreground">
                        {summary}
                    </div>

                    {showInline && hasData && (
                        <div className="flex gap-2 mt-1.5 flex-wrap text-[11px]">
                            {Object.entries(event.data).map(([key, value]) => (
                                <div
                                    key={key}
                                    className="bg-muted px-1.5 py-0.5 rounded"
                                >
                                    <span className="text-muted-foreground">
                                        {key}:
                                    </span>{" "}
                                    <span className="font-medium">
                                        {String(value)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {hasData && !showInline && (
                    <div className="flex-shrink-0 text-muted-foreground mt-0.5">
                        {isExpanded ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                        )}
                    </div>
                )}
            </div>

            {isExpanded && hasData && !showInline && (
                <div
                    className="px-2.5 pb-2.5 pt-0 border-t"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                >
                    <div className="mt-2">
                        <JsonView
                            value={event.data}
                            collapsed={false}
                            displayDataTypes={false}
                            style={{
                                fontSize: "11px",
                                fontFamily: "var(--font-mono)",
                            }}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
