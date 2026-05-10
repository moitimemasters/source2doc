'use client';

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../../ui/tooltip';

interface TooltipTermProps {
  term: string;
  definition: string;
}

export function TooltipTerm({ term, definition }: TooltipTermProps) {
  return (
    <span className="inline">
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <abbr
              className="cursor-help underline decoration-dotted decoration-muted-foreground/50 hover:decoration-muted-foreground transition-colors no-underline"
              title={definition}
            >
              {term}
            </abbr>
          </TooltipTrigger>
          <TooltipContent
            side="top"
            className="max-w-xs text-sm"
            sideOffset={5}
          >
            <p>{definition}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </span>
  );
}
