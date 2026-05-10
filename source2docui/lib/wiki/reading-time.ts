import { Block } from './types';

/**
 * Calculate estimated reading time for wiki content
 * Based on average reading speed of 200-250 words per minute
 */
export function calculateReadingTime(blocks: Block[]): number {
  const WORDS_PER_MINUTE = 225;

  let totalWords = 0;

  const countWords = (text: string): number => {
    if (!text) return 0;
    // Remove markdown syntax and count words
    const cleanText = text
      .replace(/[#*_~`\[\]()]/g, '') // Remove markdown characters
      .replace(/https?:\/\/[^\s]+/g, '') // Remove URLs
      .trim();
    return cleanText.split(/\s+/).filter(word => word.length > 0).length;
  };

  const processBlock = (block: Block): void => {
    switch (block.type) {
      case 'heading':
        totalWords += countWords(block.text);
        break;

      case 'paragraph':
        totalWords += countWords(block.text);
        break;

      case 'list':
        if (block.items && Array.isArray(block.items)) {
          block.items.forEach((item: any) => {
            totalWords += countWords(item.text || '');
          });
        }
        break;

      case 'table':
        if (block.headers && Array.isArray(block.headers)) {
          block.headers.forEach((header: string) => {
            totalWords += countWords(header);
          });
        }
        if (block.rows && Array.isArray(block.rows)) {
          block.rows.forEach((row: string[]) => {
            row.forEach((cell: string) => {
              totalWords += countWords(cell);
            });
          });
        }
        break;

      case 'code':
        // Code blocks are read slower, count as 50% of normal text
        if (block.code) {
          const codeWords = countWords(block.code);
          totalWords += Math.floor(codeWords * 0.5);
        }
        break;

      case 'quote':
        totalWords += countWords(block.text || '');
        if (block.author) {
          totalWords += countWords(block.author);
        }
        break;

      case 'callout':
        totalWords += countWords(block.text || '');
        break;

      case 'link':
        totalWords += countWords(block.text || '');
        break;

      case 'image':
        // Count caption words
        if (block.caption) {
          totalWords += countWords(block.caption);
        }
        break;

      case 'cut':
        // Recursively process blocks inside cut
        if (block.blocks && Array.isArray(block.blocks)) {
          block.blocks.forEach(processBlock);
        }
        break;

      case 'steps':
        if (block.items && Array.isArray(block.items)) {
          block.items.forEach((item: any) => {
            totalWords += countWords(item.title || '');
            totalWords += countWords(item.description || '');
          });
        }
        break;

      case 'mermaid':
        // Diagrams take time to understand, add fixed time
        totalWords += 50; // Equivalent to ~50 words
        break;
    }
  };

  blocks.forEach(processBlock);

  // Calculate reading time in minutes, minimum 1 minute
  const readingTime = Math.max(1, Math.ceil(totalWords / WORDS_PER_MINUTE));

  return readingTime;
}

/**
 * Format reading time for display
 */
export function formatReadingTime(minutes: number): string {
  if (minutes < 1) return 'Less than 1 min read';
  if (minutes === 1) return '1 min read';
  return `${minutes} min read`;
}
