'use client';

import { useEffect, useState } from 'react';

export function ReadingProgress() {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const updateProgress = () => {
      // Get the total scrollable height
      const windowHeight = window.innerHeight;
      const documentHeight = document.documentElement.scrollHeight;
      const scrollTop = window.scrollY || document.documentElement.scrollTop;

      // Calculate progress percentage
      const totalScrollableHeight = documentHeight - windowHeight;
      const scrollProgress = totalScrollableHeight > 0
        ? (scrollTop / totalScrollableHeight) * 100
        : 0;

      setProgress(Math.min(100, Math.max(0, scrollProgress)));
    };

    // Update on mount
    updateProgress();

    // Update on scroll with throttling for performance
    let ticking = false;
    const handleScroll = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          updateProgress();
          ticking = false;
        });
        ticking = true;
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('resize', updateProgress, { passive: true });

    return () => {
      window.removeEventListener('scroll', handleScroll);
      window.removeEventListener('resize', updateProgress);
    };
  }, []);

  return (
    <div
      className="fixed top-0 left-0 right-0 z-[100] h-1 bg-transparent pointer-events-none"
      role="progressbar"
      aria-valuenow={Math.round(progress)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Reading progress"
    >
      <div
        className="h-full bg-primary transition-all duration-150 ease-out"
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}
