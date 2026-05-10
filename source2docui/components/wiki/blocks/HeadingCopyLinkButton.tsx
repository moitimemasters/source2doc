'use client';

import { useState } from 'react';
import { Link as LinkIcon } from 'lucide-react';

interface HeadingCopyLinkButtonProps {
  id: string;
}

export function HeadingCopyLinkButton({ id }: HeadingCopyLinkButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopyLink = async () => {
    const url = `${window.location.origin}${window.location.pathname}#${id}`;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopyLink}
      className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
      title={copied ? 'Copied' : 'Copy link'}
      aria-label="Copy link to heading"
      type="button"
    >
      <LinkIcon className="w-4 h-4" />
    </button>
  );
}
