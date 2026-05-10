import { ListBlock, TooltipDefinition } from '../../../lib/wiki/types';
import type { SymbolMap } from '../../../lib/wiki/symbols';
import { MarkdownInline } from '../MarkdownInline';

interface ListProps {
  block: ListBlock;
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

export function List({
  block,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: ListProps) {
  const Tag = block.ordered ? 'ol' : 'ul';
  const className = block.ordered ? 'list-decimal' : 'list-disc';

  return (
    <Tag className={`${className} ml-6 space-y-2 text-foreground/90`}>
      {block.items.map((item, idx) => (
        <li key={idx} className="leading-7 pl-1">
          <MarkdownInline
            text={item.text}
            tooltips={tooltips}
            symbolMap={symbolMap}
            currentPageId={currentPageId}
            generationId={generationId}
          />
        </li>
      ))}
    </Tag>
  );
}
