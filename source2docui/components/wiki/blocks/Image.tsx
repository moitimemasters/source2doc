import { ImageBlock, TooltipDefinition } from '../../../lib/wiki/types';
import { MarkdownInline } from '../MarkdownInline';

interface ImageBlockProps {
  block: ImageBlock;
  tooltips?: TooltipDefinition[];
}

export function ImageComponent({ block, tooltips = [] }: ImageBlockProps) {
  return (
    <figure className="my-6 flex flex-col items-center">
      <div className="relative w-full max-w-2xl h-auto">
        <img
          src={block.src}
          alt={block.alt}
          className="w-full h-auto rounded-lg border border-border"
        />
      </div>
      {block.caption && (
        <figcaption className="mt-3 text-sm text-muted-foreground text-center max-w-2xl">
          <MarkdownInline text={block.caption} tooltips={tooltips} />
        </figcaption>
      )}
    </figure>
  );
}
