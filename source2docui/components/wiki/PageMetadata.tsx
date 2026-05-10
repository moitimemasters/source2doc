'use client';

import { useEffect, useState } from 'react';
import {
  Clock,
  Calendar,
  Tag,
  GitCommit,
  Coins,
  Cpu,
  Download,
  Printer,
  ExternalLink,
  History,
  Loader2,
} from 'lucide-react';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../ui/popover';
import type { RepositoryRef, SourceRef } from '../../lib/wiki/types';
import { buildSourceUrl } from '../../lib/wiki/source-url';

interface PageMetadataProps {
  readingTime?: number;
  lastUpdated?: string;
  tags?: string[];
  categories?: string[];
  commitSha?: string | null;
  repoGitUrl?: string | null;
  // generationId is the bundle's generation_id; when provided, the
  // component fetches /api/gateway/generations/{id}/metrics on mount and
  // renders a token / cost badge. Skipped silently on error or when
  // totals are zero — the wiki has plenty of bundles from before B3.1
  // landed and we don't want a noisy zero badge for those.
  generationId?: string | null;
  // B6.3 — server-supplied "Generated <date>" (ISO 8601). When absent,
  // we fall back to ``lastUpdated`` so older bundles still render
  // something. Closes ТЗ ДОК-09.
  generatedAt?: string | null;
  // B6.3 — dominant LLM model name aggregated from generation_metrics.
  llmModel?: string | null;
  // B6.4 — raw markdown for the "Download Markdown" button. ``null``
  // when the route doesn't expose it (e.g. filesystem source) so we
  // hide the button. The page slug is needed for the filename.
  bodyMarkdown?: string | null;
  pageSlug?: string;
  // B6.5 — repository (full ref) + source ranges this page references.
  // The first source ref is treated as the "primary" — used for the
  // top-level "View source" button.
  repository?: RepositoryRef | null;
  sourceRefs?: SourceRef[];
  // B11.2 / ТЗ ГЕН-08 — opt-in version selector. When supplied, a
  // "Versions ▾" popover is rendered next to the toolbar; clicking an
  // entry calls ``onSelect`` with that snapshot's generation_id and the
  // parent component handles the body swap. Omit this prop to hide the
  // selector entirely (used on bundle-listing pages where there's no
  // history concept).
  pageVersions?: {
    pageId: string;
    generationId: string;
    loading: boolean;
    activeVersionGenerationId: string | null;
    onSelect: (versionGenerationId: string) => void | Promise<void>;
  };
}

interface PageVersionEntry {
  generation_id: string;
  commit_sha: string | null;
  short_sha: string | null;
  created_at: string;
}

interface PageVersionsResponse {
  versions: PageVersionEntry[];
}

function formatVersionDate(input: string): string {
  try {
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(input));
  } catch {
    return input;
  }
}

interface MetricsTotals {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
}

interface MetricsStep {
  step: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
}

interface MetricsResponse {
  generation_id: string;
  totals: MetricsTotals;
  steps: MetricsStep[];
}

// Strips a trailing `.git` suffix and any trailing slash so we can build
// `<repo>/commit/<sha>` for the common Git host conventions (GitHub,
// GitLab, Bitbucket, Gitea — all use the same path).
function buildCommitUrl(repoUrl: string, sha: string): string | null {
  try {
    const trimmed = repoUrl.trim().replace(/\.git$/i, '').replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(trimmed)) {
      // SSH URLs (`git@github.com:foo/bar.git`) cannot be deep-linked —
      // surfacing the hash as plain text is the right fallback.
      return null;
    }
    return `${trimmed}/commit/${sha}`;
  } catch {
    return null;
  }
}

function formatCost(cost: number | null): string | null {
  if (cost === null || cost === undefined) return null;
  if (cost === 0) return '$0.00';
  // Show four decimals for sub-dollar values, two for >= $1.
  const decimals = cost < 1 ? 4 : 2;
  return `$${cost.toFixed(decimals)}`;
}

// Best-effort filename slugifier for the Markdown download — strips path
// separators and characters that some browsers refuse to download.
function safeFilenameSlug(slug: string): string {
  return slug.replace(/[^a-z0-9_.-]+/gi, '-').replace(/^-+|-+$/g, '') || 'page';
}

function downloadMarkdown(slug: string, sha: string | null, body: string) {
  const shortSha = sha ? sha.slice(0, 7) : null;
  const filename = shortSha
    ? `${safeFilenameSlug(slug)}-${shortSha}.md`
    : `${safeFilenameSlug(slug)}.md`;
  const blob = new Blob([body], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  // Clean up: revoke the object URL on the next tick so the click has time
  // to register before the URL becomes invalid.
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 0);
}

export function PageMetadata({
  readingTime,
  lastUpdated,
  tags = [],
  categories = [],
  commitSha = null,
  repoGitUrl = null,
  generationId = null,
  generatedAt = null,
  llmModel = null,
  bodyMarkdown = null,
  pageSlug,
  repository = null,
  sourceRefs = [],
  pageVersions,
}: PageMetadataProps) {
  // B6.5 — primary "View source" deep-link. Only renders when the repo
  // has an HTTPS git_url + commit_sha and the page declared a source ref.
  const primaryRef = sourceRefs[0];
  const sourceUrl = primaryRef
    ? buildSourceUrl({
        gitUrl: repository?.git_url ?? null,
        commitSha: repository?.commit_sha ?? null,
        filePath: primaryRef.file_path,
        startLine: primaryRef.start_line,
        endLine: primaryRef.end_line ?? undefined,
      })
    : null;
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [versionList, setVersionList] = useState<PageVersionEntry[] | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState<string | null>(null);

  // Lazy-load version history the first time the popover opens. We
  // don't fetch on mount because most readers never look at the
  // history — paying the round-trip eagerly would be wasteful.
  const handleVersionsOpenChange = async (open: boolean) => {
    if (!open || !pageVersions || versionList || versionsLoading) {
      return;
    }
    setVersionsLoading(true);
    setVersionsError(null);
    try {
      const url = `/api/gateway/docs/bundles/${pageVersions.generationId}/pages/${encodeURIComponent(pageVersions.pageId)}/versions`;
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data: PageVersionsResponse = await response.json();
      setVersionList(data.versions ?? []);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setVersionsError(msg);
      setVersionList([]);
    } finally {
      setVersionsLoading(false);
    }
  };

  useEffect(() => {
    if (!generationId) {
      setMetrics(null);
      return;
    }
    // Mounted-flag guard so a fast nav between pages doesn't set state on
    // an unmounted component.
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(
          `/api/gateway/generations/${generationId}/metrics`,
        );
        if (!response.ok) {
          return;
        }
        const data: MetricsResponse = await response.json();
        if (!cancelled) {
          setMetrics(data);
        }
      } catch {
        // Silent — metrics are decorative. The page still renders.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [generationId]);

  const totalTokens = metrics?.totals.total_tokens ?? 0;
  const showMetrics = metrics !== null && totalTokens > 0;
  const costLabel = showMetrics ? formatCost(metrics?.totals.cost_usd ?? null) : null;
  const tokenLabel = showMetrics
    ? `Total tokens: ${new Intl.NumberFormat('en-US').format(totalTokens)}`
    : null;
  const stepsTooltip = showMetrics && metrics
    ? metrics.steps
        .map((s) => {
          const cost = formatCost(s.cost_usd);
          const tokens = new Intl.NumberFormat('en-US').format(s.total_tokens);
          return `${s.step} (${s.model}): ${tokens} tokens${cost ? ` / ${cost}` : ''}`;
        })
        .join('\n')
    : undefined;

  // B6.3 — prefer the server-supplied generation date; fall back to the
  // legacy lastUpdated for filesystem-source bundles.
  const generationDate = generatedAt || lastUpdated || null;

  // B6.4 — only show the markdown button when we actually have content
  // to download. The print button is always available because every
  // wiki page can be print-rendered.
  const canDownloadMarkdown = Boolean(bodyMarkdown && pageSlug);
  // ``typeof window`` differs between server (false) and client (true) and
  // would render different button counts on each pass — React hydration
  // error #418. Gate behind a useEffect-set flag so SSR and the first
  // client render agree.
  const [canPrint, setCanPrint] = useState(false);
  useEffect(() => {
    setCanPrint(true);
  }, []);

  // Don't render if no metadata is provided. Note: the print button
  // alone isn't enough to keep the bar visible — the bar is metadata-
  // forward, with toolbar buttons as a side-feature.
  // The versions selector is treated like the toolbar buttons: it can
  // keep the strip alive on its own when other metadata is missing
  // (every wiki page has a history once B11.2 is rolled out).
  if (
    !readingTime &&
    !generationDate &&
    tags.length === 0 &&
    categories.length === 0 &&
    !commitSha &&
    !llmModel &&
    !showMetrics &&
    !canDownloadMarkdown &&
    !sourceUrl &&
    !pageVersions
  ) {
    return null;
  }

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }).format(date);
    } catch {
      return dateString;
    }
  };

  const shortSha = commitSha ? commitSha.slice(0, 7) : null;
  const commitUrl =
    commitSha && repoGitUrl ? buildCommitUrl(repoGitUrl, commitSha) : null;

  // ``no-print`` is intercepted by the @media print rules in
  // app/globals.css — it lets us hide the toolbar from the printable
  // view while keeping the metadata strip itself in the printout.
  return (
    <div className="page-metadata flex flex-wrap items-center gap-4 py-4 mb-8 text-sm text-muted-foreground border-b border-border">
      {/* Reading Time */}
      {readingTime && (
        <div className="flex items-center gap-1.5">
          <Clock className="h-4 w-4" />
          <span>{readingTime} min read</span>
        </div>
      )}

      {/* Generation date (B6.3 — closes ТЗ ДОК-09) */}
      {generationDate && (
        <div className="flex items-center gap-1.5">
          <Calendar className="h-4 w-4" />
          <span>Generated {formatDate(generationDate)}</span>
        </div>
      )}

      {/* Commit hash */}
      {commitSha && shortSha && (
        <div className="flex items-center gap-1.5">
          <GitCommit className="h-4 w-4" />
          {commitUrl ? (
            <a
              href={commitUrl}
              target="_blank"
              rel="noopener noreferrer"
              title={commitSha}
              className="font-mono text-xs hover:text-foreground hover:underline"
            >
              {shortSha}
            </a>
          ) : (
            <span title={commitSha} className="font-mono text-xs">
              {shortSha}
            </span>
          )}
        </div>
      )}

      {/* LLM model badge (B6.3 — closes ТЗ ДОК-09) */}
      {llmModel && (
        <div
          className="flex items-center gap-1.5"
          title="Dominant model used during this generation"
        >
          <Cpu className="h-4 w-4" />
          <Badge variant="secondary" className="text-xs font-mono">
            {llmModel}
          </Badge>
        </div>
      )}

      {/* Token usage / cost (B3.1 — closes ТЗ LLM-03/04, МТР-03) */}
      {showMetrics && tokenLabel && (
        <div
          className="flex items-center gap-1.5"
          title={stepsTooltip}
        >
          <Coins className="h-4 w-4" />
          <span>
            {tokenLabel}
            {costLabel ? ` (${costLabel})` : null}
          </span>
        </div>
      )}

      {/* Tags */}
      {tags.length > 0 && (
        <div className="flex items-center gap-2">
          <Tag className="h-4 w-4" />
          <div className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-xs">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Categories */}
      {categories.length > 0 && (
        <div className="flex items-center gap-2">
          <div className="flex flex-wrap gap-1.5">
            {categories.map((category) => (
              <Badge key={category} variant="outline" className="text-xs">
                {category}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* View source (B6.5 / ТЗ ДОК-11) — page-level deep-link to the
          primary source file in the configured git host, pinned to the
          commit the docs were generated from. Only rendered when
          git_url + commit_sha + a source ref are all present and the
          URL is parseable as HTTPS. */}
      {sourceUrl && primaryRef && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          title={`Open ${primaryRef.file_path} on the source host`}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          <span>View source</span>
        </a>
      )}

      {/* Toolbar — Versions / Download MD / Print PDF (B11.2 — closes
          ТЗ ГЕН-08; B6.4 — closes ТЗ ДОК-10). Pushed to the right with
          ml-auto so it doesn't fight the metadata badges for visual
          weight. The ``no-print`` class is captured by the @media
          print stylesheet to hide it from the PDF output (the printed
          view doesn't need a "print" button). */}
      {(canDownloadMarkdown || canPrint || pageVersions) && (
        <div className="ml-auto flex items-center gap-1.5 no-print">
          {pageVersions && (
            <Popover onOpenChange={handleVersionsOpenChange}>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  title="Show previously generated versions of this page"
                >
                  {pageVersions.loading ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <History className="h-3.5 w-3.5 mr-1" />
                  )}
                  Versions
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80 p-0">
                <div className="p-3 border-b border-border text-xs font-medium">
                  Page version history
                </div>
                <div className="max-h-72 overflow-y-auto">
                  {versionsLoading && (
                    <div className="p-3 text-xs text-muted-foreground flex items-center gap-2">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Loading versions…
                    </div>
                  )}
                  {!versionsLoading && versionsError && (
                    <div className="p-3 text-xs text-destructive">
                      Failed to load: {versionsError}
                    </div>
                  )}
                  {!versionsLoading && !versionsError && versionList && versionList.length === 0 && (
                    <div className="p-3 text-xs text-muted-foreground">
                      No previous versions recorded yet.
                    </div>
                  )}
                  {!versionsLoading && versionList && versionList.length > 0 && (
                    <ul className="py-1">
                      {versionList.map((entry) => {
                        const isActiveVersion =
                          pageVersions.activeVersionGenerationId === entry.generation_id;
                        const isCurrent =
                          entry.generation_id === pageVersions.generationId;
                        return (
                          <li key={entry.generation_id}>
                            <button
                              type="button"
                              onClick={() => pageVersions.onSelect(entry.generation_id)}
                              className={[
                                'w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-3 hover:bg-muted transition-colors',
                                isActiveVersion ? 'bg-muted/60' : '',
                              ].join(' ')}
                            >
                              <span className="flex flex-col">
                                <span className="font-medium">
                                  {formatVersionDate(entry.created_at)}
                                  {isCurrent ? (
                                    <span className="ml-2 text-[10px] uppercase tracking-wide text-muted-foreground">
                                      latest
                                    </span>
                                  ) : null}
                                </span>
                                {entry.short_sha && (
                                  <span className="font-mono text-[11px] text-muted-foreground">
                                    {entry.short_sha}
                                  </span>
                                )}
                              </span>
                              {isActiveVersion && (
                                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                  viewing
                                </span>
                              )}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </PopoverContent>
            </Popover>
          )}
          {canDownloadMarkdown && bodyMarkdown && pageSlug && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => downloadMarkdown(pageSlug, commitSha, bodyMarkdown)}
              title="Download this page as Markdown"
            >
              <Download className="h-3.5 w-3.5 mr-1" />
              Markdown
            </Button>
          )}
          {canPrint && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => window.print()}
              title="Open the browser's print dialog (Save as PDF)"
            >
              <Printer className="h-3.5 w-3.5 mr-1" />
              PDF
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
