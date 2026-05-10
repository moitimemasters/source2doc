import { ParagraphBlock, TooltipDefinition } from '../../../lib/wiki/types';
import type { SymbolMap } from '../../../lib/wiki/symbols';
import { MarkdownInline } from '../MarkdownInline';

interface ParagraphProps {
  block: ParagraphBlock;
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

export function Paragraph({
  block,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: ParagraphProps) {
  return (
    <p className="text-base leading-7 text-foreground/90">
      <MarkdownInline
        text={block.text}
        tooltips={tooltips}
        symbolMap={symbolMap}
        currentPageId={currentPageId}
        generationId={generationId}
      />
    </p>
  );
}
