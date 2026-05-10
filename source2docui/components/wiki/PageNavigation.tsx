import Link from 'next/link';
import { NavigationItem } from '../../lib/wiki/types';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PageNavigationProps {
  prev: NavigationItem | null;
  next: NavigationItem | null;
}

export function PageNavigation({ prev, next }: PageNavigationProps) {
  if (!prev && !next) {
    return null;
  }

  return (
    <nav className="mt-12 pt-8 border-t border-border/50">
      <div className="grid grid-cols-2 gap-4">
        {/* Previous Page */}
        {prev ? (
          <Link
            href={prev.path}
            className="group flex items-center gap-3 py-4 px-4 rounded-lg transition-colors hover:bg-muted/50"
          >
            <ChevronLeft className="h-5 w-5 flex-shrink-0 text-muted-foreground/60 transition-colors group-hover:text-muted-foreground" />
            <div className="flex-1 min-w-0">
              <div className="text-xs text-muted-foreground/60 mb-0.5 transition-colors group-hover:text-muted-foreground">
                Previous
              </div>
              <div className="text-sm text-muted-foreground transition-colors group-hover:text-foreground truncate">
                {prev.title}
              </div>
            </div>
          </Link>
        ) : (
          <div />
        )}

        {/* Next Page */}
        {next ? (
          <Link
            href={next.path}
            className="group flex items-center gap-3 py-4 px-4 rounded-lg transition-colors hover:bg-muted/50 text-right justify-end col-start-2"
          >
            <div className="flex-1 min-w-0">
              <div className="text-xs text-muted-foreground/60 mb-0.5 transition-colors group-hover:text-muted-foreground">
                Next
              </div>
              <div className="text-sm text-muted-foreground transition-colors group-hover:text-foreground truncate">
                {next.title}
              </div>
            </div>
            <ChevronRight className="h-5 w-5 flex-shrink-0 text-muted-foreground/60 transition-colors group-hover:text-muted-foreground" />
          </Link>
        ) : (
          <div />
        )}
      </div>
    </nav>
  );
}
