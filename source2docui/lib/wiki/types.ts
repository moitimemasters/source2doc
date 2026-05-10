export type BlockType =
    | "heading"
    | "paragraph"
    | "code"
    | "list"
    | "table"
    | "image"
    | "quote"
    | "callout"
    | "link"
    | "mermaid"
    | "mermaid_placeholder"
    | "cut"
    | "steps"
    | "text";

export interface Citation {
    span: {
        file_path: string;
        start_line: number;
        end_line: number;
    };
    relevance: string;
    metadata?: Record<string, any>;
}

export interface Block {
    type: BlockType;
    citations?: Citation[];
    metadata?: Record<string, any>;
    [key: string]: any;
}

export interface HeadingBlock extends Block {
    type: "heading";
    level: 1 | 2 | 3 | 4 | 5 | 6;
    text: string;
    id?: string;
}

export interface ParagraphBlock extends Block {
    type: "paragraph";
    text: string;
}

export interface TextBlock extends Block {
    type: "text";
    content: string;
}

export interface CodeBlockData extends Block {
    type: "code";
    lang: string;
    code: string;
}

export interface ListBlock extends Block {
    type: "list";
    ordered: boolean;
    items: Array<{ text: string }>;
}

export interface TableBlock extends Block {
    type: "table";
    headers: string[];
    rows: string[][];
}

export interface ImageBlock extends Block {
    type: "image";
    src: string;
    alt: string;
    caption?: string;
}

export interface QuoteBlock extends Block {
    type: "quote";
    text: string;
    author?: string;
}

export interface CalloutBlock extends Block {
    type: "callout";
    variant: "info" | "warning" | "success" | "error";
    text: string;
}

export interface LinkBlock extends Block {
    type: "link";
    text: string;
    href: string;
}

export interface MermaidBlock extends Block {
    type: "mermaid";
    diagram: string;
}

export interface MermaidPlaceholderBlock extends Block {
    type: "mermaid_placeholder";
    placeholder_id: string;
    kind: string;
    intent: string;
    anchors?: string[];
}

export interface CutBlock extends Block {
    type: "cut";
    title: string;
    blocks: Block[];
    defaultOpen?: boolean;
}

export interface StepItem {
    title: string;
    description: string;
    highlight?: boolean;
}

export interface StepsBlock extends Block {
    type: "steps";
    items: StepItem[];
    dynamic?: boolean;
}

export interface TooltipDefinition {
    term: string;
    definition: string;
}

// B6.5 — source-file ranges that back a page (or page section), used by
// the UI to render "View source" deep-links into the configured git host.
export interface SourceRef {
    file_path: string;
    start_line: number;
    end_line?: number | null;
}

export interface RepositoryRef {
    name: string;
    source_type: string;
    git_url?: string | null;
    git_branch?: string | null;
    commit_sha?: string | null;
}

export interface WikiPage {
    id: string;
    node_id?: string;
    title: string;
    description?: string;
    summary?: string;
    blocks: Block[];
    children?: WikiPage[];
    tooltips?: TooltipDefinition[];
    citations?: Citation[];
    snapshot_hash?: string;
    related?: string[];
    metadata?: {
        lastUpdated?: string;
        generated_at?: string;
        tags?: string[];
        categories?: string[];
        readingTime?: number;
        reading_time?: number;
        commit_sha?: string | null;
        // B6.3 — most-frequent model used by docgen for this generation,
        // surfaced through ``service.get_page`` from generation_metrics.
        llm_model?: string | null;
        // B6.5 — source-file ranges this page references; used for
        // "View source" deep-links.
        source_refs?: SourceRef[];
        [key: string]: any;
    };
    // Source repo associated with the bundle this page belongs to.
    // Populated by the gateway so the metadata panel can build
    // commit deep-links AND view-source URLs.
    repository?: RepositoryRef | null;
    // B6.4 — server-rendered GFM Markdown for the "Download Markdown"
    // button. ``null`` for filesystem-source bundles where we don't have
    // a render path. Closes ТЗ ДОК-10.
    body_markdown?: string | null;
}

export interface NavigationItem {
    id: string;
    title: string;
    path: string;
    icon?: string;
    children?: NavigationItem[];
}

export interface NavigationConfig {
    items: NavigationItem[];
}
