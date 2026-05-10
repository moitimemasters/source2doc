import { HeadingBlock, TooltipDefinition } from "../../../lib/wiki/types";
import type { SymbolMap } from "../../../lib/wiki/symbols";
import { MarkdownInline } from "../MarkdownInline";
import { HeadingCopyLinkButton } from "./HeadingCopyLinkButton";

interface HeadingProps {
    block: HeadingBlock;
    tooltips?: TooltipDefinition[];
    symbolMap?: SymbolMap;
    currentPageId?: string;
    generationId?: string;
}

type HeadingTag = "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

function clampHeadingLevel(level: number): 1 | 2 | 3 | 4 | 5 | 6 {
    if (level <= 1) return 1;
    if (level >= 6) return 6;
    return level as 1 | 2 | 3 | 4 | 5 | 6;
}

function slugifyHeadingId(text: string) {
    return text
        .toLowerCase()
        .trim()
        .replace(/[^\p{L}\p{N}\s-]/gu, "")
        .replace(/\s+/g, "-");
}

export function Heading({
    block,
    tooltips = [],
    symbolMap,
    currentPageId,
    generationId,
}: HeadingProps) {
    const id = block.id || slugifyHeadingId(String(block.text || ""));

    const headingClasses: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
        1: "text-4xl font-bold mt-12 mb-6",
        2: "text-3xl font-bold mt-10 mb-5",
        3: "text-2xl font-semibold mt-8 mb-4",
        4: "text-xl font-semibold mt-6 mb-3",
        5: "text-lg font-semibold mt-5 mb-2",
        6: "text-base font-semibold mt-4 mb-2",
    };

    const level = clampHeadingLevel(Number(block.level ?? 2));
    const Tag = `h${level}` as HeadingTag;

    return (
        <Tag
            id={id}
            className={`${headingClasses[level]} text-foreground scroll-mt-20 break-words group inline-flex items-center gap-2`}
        >
            <span className="flex-shrink">
                <MarkdownInline
                    text={block.text}
                    tooltips={tooltips}
                    symbolMap={symbolMap}
                    currentPageId={currentPageId}
                    generationId={generationId}
                />
            </span>
            <HeadingCopyLinkButton id={id} />
        </Tag>
    );
}
