// Build a browser-openable URL pointing at file_path at commit_sha in the
// configured git repository. Mirrors core/shared/source2doc/git_context.py
// `build_source_url` so the UI can render "View source" deep-links.
//
// Returns null when:
//  - any of git_url, commit_sha, file_path is missing/empty;
//  - git_url is not parseable as https://<host>/<owner>/<repo> — notably
//    SSH URLs like git@github.com:owner/repo.git;
//  - line numbers are non-positive.

const HTTPS_GIT_URL =
    /^https?:\/\/(?<host>[^/]+)\/(?<owner>[^/]+)\/(?<repo>[^/?#]+?)(?:\.git)?\/?$/;

export interface SourceUrlInputs {
    gitUrl?: string | null;
    commitSha?: string | null;
    filePath?: string | null;
    startLine?: number | null;
    endLine?: number | null;
}

export function buildSourceUrl({
    gitUrl,
    commitSha,
    filePath,
    startLine,
    endLine,
}: SourceUrlInputs): string | null {
    if (!gitUrl || !commitSha || !filePath) {
        return null;
    }

    const match = HTTPS_GIT_URL.exec(gitUrl.trim());
    if (!match || !match.groups) {
        return null;
    }

    const { host, owner, repo } = match.groups;
    if (!host || !owner || !repo) {
        return null;
    }

    let cleanPath = filePath;
    while (cleanPath.startsWith("./")) cleanPath = cleanPath.slice(2);
    while (cleanPath.startsWith("/")) cleanPath = cleanPath.slice(1);
    if (!cleanPath) return null;

    const base = `https://${host}/${owner}/${repo}/blob/${commitSha}/${cleanPath}`;

    let fragment = "";
    if (typeof startLine === "number" && startLine > 0) {
        if (typeof endLine === "number" && endLine > startLine) {
            fragment = `#L${startLine}-L${endLine}`;
        } else {
            fragment = `#L${startLine}`;
        }
    }

    return base + fragment;
}
