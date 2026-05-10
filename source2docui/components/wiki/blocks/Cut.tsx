import { CutBlock, TooltipDefinition } from '../../../lib/wiki/types';
import type { SymbolMap } from '../../../lib/wiki/symbols';
import { ContentRenderer } from '../ContentRenderer';
import { CutToggle } from './CutToggle';

interface CutProps {
  block: CutBlock;
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

export function Cut({
  block,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: CutProps) {
  return (
    <CutToggle title={block.title} defaultOpen={block.defaultOpen ?? (block as any).default_open} tooltips={tooltips}>
      <ContentRenderer
        blocks={block.blocks}
        tooltips={tooltips}
        symbolMap={symbolMap}
        currentPageId={currentPageId}
        generationId={generationId}
      />
    </CutToggle>
  );
}
