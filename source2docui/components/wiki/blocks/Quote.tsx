import { QuoteBlock, TooltipDefinition } from '../../../lib/wiki/types';
import type { SymbolMap } from '../../../lib/wiki/symbols';
import { MarkdownInline } from '../MarkdownInline';

interface QuoteProps {
  block: QuoteBlock;
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

export function Quote({
  block,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: QuoteProps) {
  const inlineProps = { symbolMap, currentPageId, generationId };
  return (
    <blockquote className="my-6 border-l-4 border-primary/40 pl-4 py-3 italic text-foreground/80 bg-primary/5 rounded-r-lg">
      <p className="mb-2">
        <MarkdownInline text={block.text} tooltips={tooltips} {...inlineProps} />
      </p>

      {block.author && (
        <p className="text-sm font-semibold not-italic text-primary">
          — <MarkdownInline text={block.author} tooltips={tooltips} {...inlineProps} />
        </p>
      )}
    </blockquote>
  );
}
