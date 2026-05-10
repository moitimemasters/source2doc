import { z } from "zod";

/**
 * Backend bundler currently supports only these formats.
 * See [process_bundle_export()](core/worker/worker/bundler/processor.py:21).
 */
export const bundleExportSchema = z.object({
    bundleId: z.number().int().positive("Pick a bundle to export"),
    generationId: z.string().uuid("Pick a bundle to export"),
    format: z.enum(["mkdocs", "nextra", "sphinx", "gfm", "yfm"], {
        errorMap: () => ({ message: "Please select a valid format" }),
    }),
    channel: z.string().default("bundler"),
    /**
     * How to handle ```mermaid``` blocks in the bundle.
     *  - "default" lets the gateway pick a per-format default
     *    (GFM/Sphinx → svg, MkDocs/Nextra → fence).
     *  - "fence" keeps the source fence (themes with JS renderers).
     *  - "svg"/"png" pre-renders diagrams via mermaid-cli.
     */
    mermaidRender: z.enum(["default", "fence", "svg", "png"]).default("default"),
});

export type BundleExportFormData = z.infer<typeof bundleExportSchema>;

export const defaultBundleExportValues: BundleExportFormData = {
    bundleId: 0,
    generationId: "",
    format: "mkdocs",
    channel: "bundler",
    mermaidRender: "default",
};

export const MERMAID_RENDER_OPTIONS = [
    {
        value: "default",
        label: "Auto",
        description: "Format-aware default (GFM/Sphinx → SVG, MkDocs/Nextra → fence)",
    },
    {
        value: "fence",
        label: "Keep fence",
        description: "Emit ```mermaid``` source — for themes with a JS renderer",
    },
    {
        value: "svg",
        label: "Pre-render SVG",
        description: "Replace fences with static SVG images (mermaid-cli)",
    },
    {
        value: "png",
        label: "Pre-render PNG",
        description: "Replace fences with static PNG images (mermaid-cli)",
    },
] as const;

export type MermaidRenderMode = (typeof MERMAID_RENDER_OPTIONS)[number]["value"];

export const SUPPORTED_FORMATS = [
    { value: "mkdocs", label: "MkDocs", description: "Markdown documentation" },
    {
        value: "nextra",
        label: "Nextra",
        description: "Next.js based documentation",
    },
    {
        value: "sphinx",
        label: "Sphinx",
        description: "Python documentation generator",
    },
    {
        value: "gfm",
        label: "GitHub Markdown",
        description: "Plain GFM bundle, renders directly on github.com",
    },
    {
        value: "yfm",
        label: "Yandex Flavored Markdown",
        description: "Diplodoc-compatible bundle (toc.yaml + YFM extensions)",
    },
] as const;

export type BundleExportFormat = (typeof SUPPORTED_FORMATS)[number]["value"];

export interface BundleExportArtifact {
    bundle_id: number;
    format: string;
    s3_key: string;
    size?: number;
    last_modified?: string;
}

export interface BundleExportArtifactListResponse {
    exports: BundleExportArtifact[];
}
