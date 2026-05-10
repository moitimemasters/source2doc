import { z } from "zod";

const UUID_RE =
    /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export const gitCloneSchema = z.object({
    gitUrl: z.string().url("Must be a valid URL"),
    branch: z.string().optional().default(""),
    // Tag, branch, or full SHA. Worker runs ``git checkout --detach <ref>``
    // after the clone so the tarball is captured at this exact revision.
    // Useful for iterative-mode demos: clone at OLD ref, full-gen, then
    // refresh the same repoId at NEW ref via replaceExisting.
    commitSha: z.string().optional().default(""),
    name: z.string().optional(),
    description: z.string().optional(),
    repoId: z
        .string()
        .optional()
        .refine(
            (v) => !v || UUID_RE.test(v),
            "Must be a valid UUID (or leave empty)",
        ),
    // When true and a repo with this ``repoId`` already exists, the
    // tarball is overwritten in place (re-clone + re-upload) instead of
    // 409'ing.
    replaceExisting: z.boolean().optional().default(false),
});

export type GitCloneFormData = z.infer<typeof gitCloneSchema>;

export const defaultGitCloneValues: GitCloneFormData = {
    gitUrl: "",
    branch: "",
    commitSha: "",
    name: "",
    description: "",
    repoId: "",
    replaceExisting: false,
};

export const fileUploadSchema = z.object({
    name: z.string().min(1, "Repository name is required"),
    description: z.string().optional(),
});

export type FileUploadFormData = z.infer<typeof fileUploadSchema>;

export const defaultFileUploadValues: FileUploadFormData = {
    name: "",
    description: "",
};

export interface RepositoryInfo {
    repo_id: string;
    name: string;
    source_type: string;
    git_url?: string | null;
    git_branch?: string | null;
    s3_key?: string | null;
    description?: string | null;
    created_at: string;
    updated_at: string;
}

export interface RepositoryListResponse {
    repositories: RepositoryInfo[];
    count: number;
}
