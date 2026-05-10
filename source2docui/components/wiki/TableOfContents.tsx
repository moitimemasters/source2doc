'use client';

import { useEffect, useState } from 'react';

interface Heading {
  id: string;
  text: string;
  level: number;
}

interface TableOfContentsProps {
  headings: Heading[];
}

export function TableOfContents({ headings }: TableOfContentsProps) {
  const [activeId, setActiveId] = useState<string>('');
  const [headingElements, setHeadingElements] = useState<HTMLElement[]>([]);

  useEffect(() => {
    if (headings.length === 0) {
      setActiveId('');
      setHeadingElements([]);
      return;
    }

    // Wait a tick so the article headings are in the DOM (important on navigation).
    const raf = window.requestAnimationFrame(() => {
      const elements = headings
        .map((h) => document.getElementById(h.id))
        .filter((el): el is HTMLElement => Boolean(el));
      setHeadingElements(elements);
    });

    // If user opened a URL with #hash, prefer it as the initial active item.
    const hashId = window.location.hash.replace(/^#/, '');
    if (hashId) {
      setActiveId(hashId);
    } else if (headings[0]?.id) {
      setActiveId(headings[0].id);
    }

    return () => window.cancelAnimationFrame(raf);
  }, [headings]);

  useEffect(() => {
    if (headingElements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Prefer the top-most intersecting heading in the viewport.
        const intersecting = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => (a.boundingClientRect.top ?? 0) - (b.boundingClientRect.top ?? 0));

        if (intersecting.length > 0) {
          setActiveId(intersecting[0]!.target.id);
        }
      },
      // Keep the "active" state stable with a central band.
      { root: null, rootMargin: '-30% 0px -65% 0px' }
    );

    headingElements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [headingElements]);

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    setActiveId(id);
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      // Update URL hash without triggering scroll
      window.history.pushState(null, '', `#${id}`);
    }
  };

  return (
    <nav className="sticky top-20 w-56">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground uppercase tracking-wide">On this page</h3>
        <ul className="space-y-2 text-sm">
          {headings.map((heading) => {
            const indentPx = Math.max(0, (heading.level - 2) * 12);
            return (
              <li key={heading.id} style={{ paddingLeft: `${indentPx}px` }}>
                <a
                  href={`#${heading.id}`}
                  onClick={(e) => handleClick(e, heading.id)}
                  className={`transition-colors duration-200 ${
                    activeId === heading.id ? 'text-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {heading.text}
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
