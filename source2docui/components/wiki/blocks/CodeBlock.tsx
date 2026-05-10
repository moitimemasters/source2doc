import { CodeBlockData } from '../../../lib/wiki/types';
import { CodeCopyButton } from './CodeCopyButton';
import { getLanguageDisplayName, highlightCodeToHtml } from '../../../lib/wiki/shiki';

interface CodeBlockProps {
  block: CodeBlockData;
}

export async function CodeBlock({ block }: CodeBlockProps) {
  const html = await highlightCodeToHtml(block.code, block.lang);

  return (
    <div className="my-6 relative overflow-hidden rounded-lg border border-border/50 bg-muted/30 wiki-code group">
      {/* Language label in top-right corner */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
        <span className="text-[10px] font-medium uppercase tracking-wider text-foreground/80 bg-background/90 backdrop-blur-sm px-2 py-0.5 rounded border border-border/30">
          {getLanguageDisplayName(block.lang)}
        </span>
        <CodeCopyButton code={block.code} />
      </div>

      {/* Shiki already returns a <pre class="shiki ...">...</pre> */}
      <div className="overflow-x-auto text-sm leading-6" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
