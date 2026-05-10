import { LinkBlock, TooltipDefinition } from '../../../lib/wiki/types';
import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { MarkdownInline } from '../MarkdownInline';

interface LinkBlockProps {
  block: LinkBlock;
  tooltips?: TooltipDefinition[];
}

export function LinkComponent({ block, tooltips = [] }: LinkBlockProps) {
  const isExternal = block.href.startsWith('http');

  if (isExternal) {
    return (
      <a
        href={block.href}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 text-primary font-medium hover:text-primary/80 transition-colors"
      >
        <span className="inline-flex">
          <MarkdownInline text={block.text} allowLinks={false} tooltips={tooltips} />
        </span>
        <ExternalLink className="h-4 w-4" />
      </a>
    );
  }

  return (
    <Link href={block.href} className="inline text-primary font-medium hover:text-primary/80 transition-colors">
      <MarkdownInline text={block.text} allowLinks={false} tooltips={tooltips} />
    </Link>
  );
}
