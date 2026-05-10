'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

interface CodeCopyButtonProps {
  code: string;
}

export function CodeCopyButton({ code }: CodeCopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={copyToClipboard}
      className="p-1.5 hover:bg-muted rounded-md transition-colors text-muted-foreground hover:text-foreground"
      aria-label="Copy code"
      type="button"
    >
      {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}
