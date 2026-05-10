import { CalloutBlock, TooltipDefinition } from '../../../lib/wiki/types';
import type { SymbolMap } from '../../../lib/wiki/symbols';
import { MarkdownInline } from '../MarkdownInline';
import { AlertCircle, CheckCircle2, InfoIcon, AlertTriangle } from 'lucide-react';

interface CalloutProps {
  block: CalloutBlock;
  tooltips?: TooltipDefinition[];
  symbolMap?: SymbolMap;
  currentPageId?: string;
  generationId?: string;
}

const variantConfig = {
  info: {
    bgClass: 'bg-muted/60 border-muted-foreground/20',
    textClass: 'text-foreground',
    icon: InfoIcon,
  },
  warning: {
    bgClass: 'bg-yellow-100/40 border-yellow-300/50 dark:bg-yellow-950/30 dark:border-yellow-800/50',
    textClass: 'text-yellow-900 dark:text-yellow-100',
    icon: AlertTriangle,
  },
  success: {
    bgClass: 'bg-green-100/40 border-green-300/50 dark:bg-green-950/30 dark:border-green-800/50',
    textClass: 'text-green-900 dark:text-green-100',
    icon: CheckCircle2,
  },
  error: {
    bgClass: 'bg-red-100/40 border-red-300/50 dark:bg-red-950/30 dark:border-red-800/50',
    textClass: 'text-red-900 dark:text-red-100',
    icon: AlertCircle,
  },
};

export function Callout({
  block,
  tooltips = [],
  symbolMap,
  currentPageId,
  generationId,
}: CalloutProps) {
  const config = variantConfig[block.variant];
  const Icon = config.icon;

  return (
    <div className={`my-6 flex gap-3 p-4 rounded-lg border ${config.bgClass}`}>
      <Icon className={`h-5 w-5 flex-shrink-0 mt-0.5 ${config.textClass}`} />
      <p className={`text-sm leading-6 ${config.textClass}`}>
        <MarkdownInline
          text={block.text}
          tooltips={tooltips}
          symbolMap={symbolMap}
          currentPageId={currentPageId}
          generationId={generationId}
        />
      </p>
    </div>
  );
}
