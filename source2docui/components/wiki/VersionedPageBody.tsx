'use client';

import { useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Button } from '../ui/button';
import { ContentRenderer } from './ContentRenderer';
import { PageMetadata } from './PageMetadata';
import type { Block, RepositoryRef, SourceRef, TooltipDefinition } from '../../lib/wiki/types';
import type { SymbolMap } from '../../lib/wiki/symbols';

// Shape of one page-version entry returned by
// /api/gateway/docs/bundles/{id}/pages/{pageId}/versions
export interface PageVersionListEntry {
  generation_id: string;
  commit_sha: string | null;
  short_sha: string | null;
  created_at: string;
}

// Shape of the snapshot returned by .../versions/{version_generation_id}.
export interface PageVersionDetail {
  page_id: string;
  generation_id: string;
  commit_sha: string | null;
  created_at: string;
  title: string | null;
  summary: string | null;
  metadata: Record<string, unknown> | null;
  blocks: Block[];
  related: string[];
  body_markdown: string | null;
}

interface VersionedPageBodyProps {
  // Latest-page context (used to render PageMetadata in its default
  // mode and as the fallback when the user clicks "Back to latest").
  pageId: string;
  pageTitle: string;
  blocks: Block[];
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  // ``projectId`` doubles as the bundle's generation_id throughout the
  // wiki — it's the slug under /wiki/{projectId}/...
  generationId: string;
  // Latest-page metadata fields (passed through to PageMetadata when
  // we're not in historical mode).
  readingTime?: number;
  lastUpdated?: string;
  tags?: string[];
  categories?: string[];
  commitSha?: string | null;
  repoGitUrl?: string | null;
  generatedAt?: string | null;
  llmModel?: string | null;
  bodyMarkdown?: string | null;
  repository?: RepositoryRef | null;
  sourceRefs?: SourceRef[];
}

function formatDate(input: string): string {
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

export function VersionedPageBody({
  pageId,
  pageTitle,
  blocks,
  tooltips = [],
  symbolMap,
  generationId,
  readingTime,
  lastUpdated,
  tags,
  categories,
  commitSha = null,
  repoGitUrl = null,
  generatedAt = null,
  llmModel = null,
  bodyMarkdown = null,
  repository = null,
  sourceRefs = [],
}: VersionedPageBodyProps) {
  const [historical, setHistorical] = useState<PageVersionDetail | null>(null);
  const [historicalLoading, setHistoricalLoading] = useState(false);
  const [historicalError, setHistoricalError] = useState<string | null>(null);

  const handleSelectVersion = async (versionGenerationId: string) => {
    // Selecting the bundle's own generation_id collapses to the latest
    // view rather than re-fetching the same content via the version
    // endpoint — saves a round-trip and avoids a confusing banner that
    // points at "the current run".
    if (versionGenerationId === generationId) {
      setHistorical(null);
      setHistoricalError(null);
      return;
    }

    setHistoricalLoading(true);
    setHistoricalError(null);
    try {
      const url = `/api/gateway/docs/bundles/${generationId}/pages/${encodeURIComponent(pageId)}/versions/${versionGenerationId}`;
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data: PageVersionDetail = await response.json();
      setHistorical(data);
      // Scroll back to top so readers don't land mid-page after the swap.
      if (typeof window !== 'undefined') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setHistoricalError(msg);
    } finally {
      setHistoricalLoading(false);
    }
  };

  const handleBackToLatest = () => {
    setHistorical(null);
    setHistoricalError(null);
  };

  // Render either the historical snapshot or the latest payload. We
  // pass the same renderer in both cases so a historical view inherits
  // every block-level UX feature without duplication.
  const renderBlocks = historical ? historical.blocks : blocks;
  // ``commitSha`` shown in the metadata strip should reflect what the
  // reader is actually looking at — the historical run's commit when
  // we've swapped in a snapshot.
  const effectiveCommitSha = historical ? historical.commit_sha : commitSha;
  const effectiveBodyMarkdown = historical ? historical.body_markdown : bodyMarkdown;

  return (
    <>
      {historical && (
        <div
          role="status"
          className="mb-6 flex items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100"
        >
          <span>
            Viewing historical version from{' '}
            <strong>{formatDate(historical.created_at)}</strong>
            {historical.commit_sha
              ? ` (commit ${historical.commit_sha.slice(0, 7)})`
              : null}
            .
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleBackToLatest}
            className="border-amber-400 hover:bg-amber-100 dark:border-amber-600 dark:hover:bg-amber-900/40"
          >
            <ArrowLeft className="h-3.5 w-3.5 mr-1" />
            Back to latest
          </Button>
        </div>
      )}

      {historicalError && !historical && (
        <div
          role="alert"
          className="mb-6 rounded-md border border-destructive/40 bg-destructive/5 px-4 py-2 text-sm text-destructive"
        >
          Failed to load historical version: {historicalError}
        </div>
      )}

      <PageMetadata
        readingTime={readingTime}
        lastUpdated={lastUpdated}
        tags={tags}
        categories={categories}
        commitSha={effectiveCommitSha}
        repoGitUrl={repoGitUrl}
        generationId={generationId}
        generatedAt={historical ? historical.created_at : generatedAt}
        llmModel={llmModel}
        bodyMarkdown={effectiveBodyMarkdown}
        pageSlug={pageId}
        repository={repository}
        sourceRefs={historical ? [] : sourceRefs}
        // B11.2 — the version-selector lives inside PageMetadata so it
        // sits with the other inline metadata controls.
        pageVersions={{
          pageId,
          generationId,
          loading: historicalLoading,
          activeVersionGenerationId: historical?.generation_id ?? null,
          onSelect: handleSelectVersion,
        }}
      />

      {/* Historical view shows the snapshot's title above the content
          (the latest path uses block H1s, so we mirror it here). */}
      {historical && historical.title && historical.title !== pageTitle && (
        <h1 className="text-3xl font-semibold mb-6">{historical.title}</h1>
      )}

      <ContentRenderer
        blocks={renderBlocks}
        tooltips={tooltips}
        symbolMap={symbolMap}
        currentPageId={pageId}
        generationId={generationId}
      />
    </>
  );
}
