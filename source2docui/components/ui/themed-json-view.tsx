"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import JsonView from "@uiw/react-json-view";
import { darkTheme } from "@uiw/react-json-view/dark";
import { lightTheme } from "@uiw/react-json-view/light";

type JsonViewProps = React.ComponentProps<typeof JsonView>;

export function ThemedJsonView(props: JsonViewProps) {
    const { resolvedTheme } = useTheme();
    const [mounted, setMounted] = React.useState(false);
    React.useEffect(() => setMounted(true), []);

    const isDark = mounted && resolvedTheme === "dark";
    const baseStyle = isDark ? darkTheme : lightTheme;

    return (
        <JsonView
            {...props}
            style={{
                ...baseStyle,
                backgroundColor: "transparent",
                fontFamily: "var(--font-mono)",
                ...(props.style as React.CSSProperties | undefined),
            }}
        />
    );
}
