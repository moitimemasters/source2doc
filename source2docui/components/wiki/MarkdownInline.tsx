import type { ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TooltipTerm } from './blocks/TooltipTerm';
import type { TooltipDefinition } from '../../lib/wiki/types';
import { resolveSymbol, symbolHref, type SymbolMap } from '../../lib/wiki/symbols';

interface MarkdownInlineProps {
  text: string;
  allowLinks?: boolean;
  tooltips?: TooltipDefinition[];
  /** Cross-page link map. When provided, prose mentions and inline `<code>`
   * matching a known symbol are wrapped in `<a>` linking to its home page. */
  symbolMap?: SymbolMap;
  /** Avoid wrapping mentions of the page's own id (no self-links). */
  currentPageId?: string;
  /** Wiki project segment used in the link href (`/wiki/{generationId}/...`). */
  generationId?: string;
}

type PProps = { children?: ReactNode };
type AProps = { href?: string; children?: ReactNode };
type CodeProps = { children?: ReactNode };

function extractTextContent(node: ReactNode): string {
  if (node == null) return '';
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractTextContent).join('');
  if (typeof node === 'object' && node !== null && 'props' in node) {
    // ReactElement
    return extractTextContent((node as { props: { children?: ReactNode } }).props.children);
  }
  return '';
}

function buildComponents(
  options: {
    allowLinks: boolean;
    symbolMap?: SymbolMap;
    currentPageId?: string;
    generationId?: string;
  },
): Components {
  const { allowLinks, symbolMap, currentPageId, generationId } = options;

  const renderCode = ({ children }: CodeProps) => {
    const codeText = extractTextContent(children);
    if (symbolMap && generationId && codeText) {
      const match = resolveSymbol(symbolMap, codeText, currentPageId);
      if (match) {
        return (
          <a
            href={symbolHref(generationId, match.page_id)}
            className="text-primary hover:underline"
            data-symbol-link={match.kind}
          >
            <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-foreground">
              {children}
            </code>
          </a>
        );
      }
    }
    return (
      <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-foreground">
        {children}
      </code>
    );
  };

  if (allowLinks) {
    return {
      p: ({ children }: PProps) => <>{children}</>,
      a: ({ href, children }: AProps) => {
        const isExternal = typeof href === 'string' && /^https?:\/\//i.test(href);
        // Writers frequently produce raw markdown links like
        // `[text](compatibility.md)` or `[text](./compatibility.md)`. The
        // app routes wiki pages by id (no .md), so rewrite any local .md
        // link to /wiki/<generationId>/<pageId>.
        let resolved = href;
        if (
          generationId &&
          typeof href === 'string' &&
          !isExternal &&
          /\.mdx?(#.*)?$/i.test(href)
        ) {
          const cleaned = href
            .replace(/^\.?\//, '')
            .replace(/\.mdx?$/i, '');
          // Drop a leading wiki/ if a writer already prefixed one.
          const pageId = cleaned.replace(/^wiki\//, '');
          resolved = `/wiki/${generationId}/${pageId}`;
        }
        return (
          <a
            href={resolved}
            target={isExternal ? '_blank' : undefined}
            rel={isExternal ? 'noopener noreferrer' : undefined}
            className="text-primary underline underline-offset-4 hover:text-primary/80 transition-colors"
          >
            {children}
          </a>
        );
      },
      code: renderCode,
    };
  }

  return {
    p: ({ children }: PProps) => <>{children}</>,
    a: ({ children }: AProps) => <>{children}</>,
    code: renderCode,
  };
}

/**
 * Wrap occurrences of known page titles in plain text with anchor tags
 * pointing to the title's home page. Operates on a string only (after
 * markdown has been split around tooltip terms / formatting markers),
 * so we never touch text inside `<code>` or formatting wrappers.
 */
function linkifyPlainText(
  text: string,
  symbolMap: SymbolMap,
  currentPageId: string | undefined,
  generationId: string,
): ReactNode {
  // Build a regex of all page-title symbols (longest first, escaped).
  const titleEntries: Array<{ symbol: string; page_id: string }> = [];
  for (const [key, match] of symbolMap) {
    if (match.kind !== 'page_title') continue;
    if (currentPageId && match.page_id === currentPageId) continue;
    titleEntries.push({ symbol: key, page_id: match.page_id });
  }
  if (titleEntries.length === 0) return text;
  titleEntries.sort((a, b) => b.symbol.length - a.symbol.length);

  const escaped = titleEntries
    .map(t => t.symbol.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|');
  if (!escaped) return text;

  const pattern = new RegExp(`(\\b(?:${escaped})\\b)`, 'gi');
  const parts = text.split(pattern);
  if (parts.length === 1) return text;

  return parts.map((part, idx) => {
    if (!part) return null;
    const lower = part.toLowerCase();
    const match = symbolMap.get(lower);
    if (match && match.kind === 'page_title' && match.page_id !== currentPageId) {
      return (
        <a
          key={`sym-${idx}`}
          href={symbolHref(generationId, match.page_id)}
          className="text-primary hover:underline"
          data-symbol-link="page_title"
        >
          {part}
        </a>
      );
    }
    return <span key={`txt-${idx}`}>{part}</span>;
  });
}

export function MarkdownInline({
  text,
  allowLinks = true,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: MarkdownInlineProps) {
  const allowedElements = allowLinks
    ? (['a', 'strong', 'em', 'del', 'code', 'span', 'br', 'sup', 'sub'] as const)
    : (['strong', 'em', 'del', 'code', 'span', 'br', 'sup', 'sub'] as const);

  const components = buildComponents({
    allowLinks,
    symbolMap,
    currentPageId,
    generationId,
  });

  // Helper: render a markdown chunk.
  const renderMarkdown = (input: string) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={allowedElements as any}
      unwrapDisallowed
      components={components}
    >
      {input ?? ''}
    </ReactMarkdown>
  );

  // No tooltips: split plain prose for symbol-link wrapping, then run
  // ReactMarkdown over the rest. We can't safely run linkifyPlainText
  // *after* ReactMarkdown because it would scan inside <code> blocks.
  // Strategy: split input around backtick spans first (those become inline
  // <code>), let ReactMarkdown handle each segment, and linkify only the
  // non-code segments.
  const processWithSymbols = (inputText: string): ReactNode => {
    if (!symbolMap || !generationId || symbolMap.size === 0) {
      return renderMarkdown(inputText);
    }
    // Split around inline-code spans: backticks. Also avoid touching links
    // (markdown link syntax inside text). ReactMarkdown will still parse
    // the segments containing markdown markup; we only linkify *plain*
    // segments that hold no markdown special chars.
    const codeRe = /(`[^`\n]+`)/g;
    const segments = inputText.split(codeRe);
    return (
      <>
        {segments.map((seg, idx) => {
          if (!seg) return null;
          if (seg.startsWith('`') && seg.endsWith('`')) {
            // Inline code: ReactMarkdown's code renderer applies link wrap.
            return <span key={`seg-${idx}`}>{renderMarkdown(seg)}</span>;
          }
          // Plain segment: if it contains markdown markup, defer to RM
          // (we won't linkify titles inside, but we still linkify code).
          if (/[*_~\[\]]/.test(seg)) {
            return <span key={`seg-${idx}`}>{renderMarkdown(seg)}</span>;
          }
          return (
            <span key={`seg-${idx}`}>
              {linkifyPlainText(seg, symbolMap, currentPageId, generationId)}
            </span>
          );
        })}
      </>
    );
  };

  // Process text to replace terms with tooltips
  const processTextWithTooltips = (inputText: string): ReactNode => {
    if (!tooltips || tooltips.length === 0) {
      return processWithSymbols(inputText);
    }

    // Sort tooltips by term length (longest first) to avoid partial matches
    const sortedTooltips = [...tooltips].sort((a, b) => b.term.length - a.term.length);

    // Create a regex pattern that matches any of the terms (case-insensitive, whole word)
    const pattern = sortedTooltips
      .map(t => t.term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|');

    if (!pattern) {
      return processWithSymbols(inputText);
    }

    const regex = new RegExp(`(\\b(?:${pattern})\\b)`, 'gi');
    const parts = inputText.split(regex);

    if (parts.length === 1) {
      // No matches found, render normally
      return processWithSymbols(inputText);
    }

    // Process each part - render inline with preserved spacing
    return (
      <>
        {parts.map((part, index) => {
          if (!part) return null;

          // Check if this part matches a tooltip term
          const tooltip = sortedTooltips.find(
            t => t.term.toLowerCase() === part.toLowerCase()
          );

          if (tooltip) {
            return (
              <TooltipTerm
                key={`tooltip-${index}`}
                term={part}
                definition={tooltip.definition}
              />
            );
          }

          // For text parts, defer to symbol-aware renderer (handles code +
          // page-title prose links). Avoids touching inside <code>.
          return <span key={`text-${index}`}>{processWithSymbols(part)}</span>;
        })}
      </>
    );
  };

  return <>{processTextWithTooltips(text)}</>;
}
