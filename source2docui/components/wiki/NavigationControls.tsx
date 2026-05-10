'use client';

import { useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { NavigationItem } from '../../lib/wiki/types';

interface NavigationControlsProps {
  prev: NavigationItem | null;
  next: NavigationItem | null;
}

export function NavigationControls({ prev, next }: NavigationControlsProps) {
  const router = useRouter();

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Ignore if user is typing in an input/textarea
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.target instanceof HTMLSelectElement
      ) {
        return;
      }

      // Left arrow - previous page
      if (event.key === 'ArrowLeft' && prev) {
        event.preventDefault();
        router.push(prev.path);
      }

      // Right arrow - next page
      if (event.key === 'ArrowRight' && next) {
        event.preventDefault();
        router.push(next.path);
      }
    },
    [prev, next, router]
  );

  // Swipe gestures for mobile
  useEffect(() => {
    let touchStartX = 0;
    let touchEndX = 0;
    const minSwipeDistance = 50; // Minimum distance for a swipe

    const handleTouchStart = (event: TouchEvent) => {
      touchStartX = event.changedTouches[0].screenX;
    };

    const handleTouchEnd = (event: TouchEvent) => {
      touchEndX = event.changedTouches[0].screenX;
      handleSwipe();
    };

    const handleSwipe = () => {
      const swipeDistance = touchEndX - touchStartX;

      // Swipe right (previous page)
      if (swipeDistance > minSwipeDistance && prev) {
        router.push(prev.path);
      }

      // Swipe left (next page)
      if (swipeDistance < -minSwipeDistance && next) {
        router.push(next.path);
      }
    };

    // Add keyboard listener
    window.addEventListener('keydown', handleKeyDown);

    // Add touch listeners for swipe gestures
    window.addEventListener('touchstart', handleTouchStart);
    window.addEventListener('touchend', handleTouchEnd);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('touchstart', handleTouchStart);
      window.removeEventListener('touchend', handleTouchEnd);
    };
  }, [handleKeyDown, prev, next, router]);

  // This component doesn't render anything
  return null;
}
