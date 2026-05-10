import { Block, TooltipDefinition } from '../../lib/wiki/types';
import type { SymbolMap } from '../../lib/wiki/symbols';
import { Heading } from './blocks/Heading';
import { Paragraph } from './blocks/Paragraph';
import { CodeBlock } from './blocks/CodeBlock';
import { List } from './blocks/List';
import { Table } from './blocks/Table';
import { ImageComponent } from './blocks/Image';
import { Quote } from './blocks/Quote';
import { Callout } from './blocks/Callout';
import { LinkComponent } from './blocks/Link';
import { MermaidDiagram } from './blocks/MermaidDiagram';
import { Cut } from './blocks/Cut';
import { Steps } from './blocks/Steps';

interface ContentRendererProps {
  blocks: Block[];
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

export function ContentRenderer({
  blocks,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: ContentRendererProps) {
  // Inline blocks (paragraph / list / table / quote / callout / cut)
  // forward the symbol map so MarkdownInline can promote mentions to links.
  // Atomic blocks (code / image / mermaid / steps / link) keep their
  // existing renderers untouched — code blocks are full <pre>, not inline,
  // so we deliberately don't wrap them.
  const linkProps = { symbolMap, currentPageId, generationId };
  return (
    <div className="space-y-6">
      {blocks.map((block, idx) => {
        switch (block.type) {
          case 'heading':
            return <Heading key={idx} block={block as any} tooltips={tooltips} {...linkProps} />;
          case 'paragraph':
            return (
              <Paragraph key={idx} block={block as any} tooltips={tooltips} {...linkProps} />
            );
          case 'code':
            return <CodeBlock key={idx} block={block as any} />;
          case 'list':
            return <List key={idx} block={block as any} tooltips={tooltips} {...linkProps} />;
          case 'table':
            return <Table key={idx} block={block as any} tooltips={tooltips} {...linkProps} />;
          case 'image':
            return <ImageComponent key={idx} block={block as any} tooltips={tooltips} />;
          case 'quote':
            return <Quote key={idx} block={block as any} tooltips={tooltips} {...linkProps} />;
          case 'callout':
            return (
              <Callout key={idx} block={block as any} tooltips={tooltips} {...linkProps} />
            );
          case 'link':
            return <LinkComponent key={idx} block={block as any} tooltips={tooltips} />;
          case 'mermaid':
            return <MermaidDiagram key={idx} block={block as any} />;
          case 'mermaid_placeholder': {
            const ph = block as any;
            const fallback = {
              type: 'callout',
              variant: 'warning',
              text: `Diagram unavailable: ${ph.intent ?? ph.placeholder_id ?? ''}`,
            };
            return (
              <Callout key={idx} block={fallback as any} tooltips={tooltips} {...linkProps} />
            );
          }
          case 'cut':
            return <Cut key={idx} block={block as any} tooltips={tooltips} {...linkProps} />;
          case 'steps':
            return <Steps key={idx} block={block as any} tooltips={tooltips} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
