'use client';

import { useState, ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { MarkdownInline } from '../MarkdownInline';
import type { TooltipDefinition } from '../../../lib/wiki/types';

interface CutToggleProps {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
  tooltips?: TooltipDefinition[];
}

export function CutToggle({ title, defaultOpen = false, children, tooltips = [] }: CutToggleProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="my-4 border-l-2 border-border/40">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group"
        aria-expanded={isOpen}
      >
        <ChevronRight
          className={`h-3.5 w-3.5 flex-shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
        />
        <span className="group-hover:underline decoration-dotted underline-offset-4">
          <MarkdownInline text={title} tooltips={tooltips} />
        </span>
      </button>
      {isOpen && (
        <div className="pl-6 pr-3 pb-2">
          {children}
        </div>
      )}
    </div>
  );
}
