import { TableBlock, TooltipDefinition } from '../../../lib/wiki/types';
import type { SymbolMap } from '../../../lib/wiki/symbols';
import { MarkdownInline } from '../MarkdownInline';

interface TableProps {
  block: TableBlock;
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

export function Table({
  block,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: TableProps) {
  const inlineProps = { symbolMap, currentPageId, generationId };
  return (
    <div className="my-6 overflow-x-auto rounded-lg border border-border/50">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-muted/50 border-b border-border/50">
            {block.headers.map((header, idx) => (
              <th key={idx} className="px-4 py-3 text-left font-semibold text-foreground text-sm">
                <MarkdownInline text={header} tooltips={tooltips} {...inlineProps} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIdx) => (
            <tr key={rowIdx} className="hover:bg-muted/30 border-b border-border/30 transition-colors">
              {row.map((cell, cellIdx) => (
                <td key={cellIdx} className="px-4 py-3 text-foreground/90 text-sm">
                  <MarkdownInline text={cell} tooltips={tooltips} {...inlineProps} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
