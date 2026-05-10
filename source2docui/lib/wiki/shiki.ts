import { bundledLanguages, codeToHtml, type BundledLanguage } from 'shiki';

const shikiLangAliases: Record<string, BundledLanguage> = {
  js: 'javascript',
  jsx: 'jsx',
  ts: 'typescript',
  tsx: 'tsx',
  py: 'python',
  html: 'html',
  css: 'css',
  bash: 'bash',
  sh: 'bash',
  json: 'json',
  sql: 'sql',
  md: 'markdown',
  yml: 'yaml',
  yaml: 'yaml',
};

export function normalizeShikiLang(lang: string | undefined | null): BundledLanguage {
  const raw = String(lang || '').trim().toLowerCase();

  // Shiki accepts `text` at runtime, but some versions don't include it in BundledLanguage typings.
  if (!raw) return 'text' as unknown as BundledLanguage;

  const aliased = shikiLangAliases[raw] ?? (raw as BundledLanguage);
  if (aliased in bundledLanguages) return aliased;
  // Unknown language (LLM-hallucinated, e.g. "paragraph"): fall back to plain text
  // instead of letting Shiki throw and break the whole page render.
  return 'text' as unknown as BundledLanguage;
}

/**
 * Server-side syntax highlighting with dual themes (light/dark).
 * Shiki output is HTML containing a <pre class="shiki ...">...</pre>.
 */
export async function highlightCodeToHtml(code: string, lang: string) {
  try {
    return await codeToHtml(code ?? '', {
      lang: normalizeShikiLang(lang),
      themes: {
        light: 'github-light',
        dark: 'github-dark',
      },
      cssVariablePrefix: '--shiki-',
    });
  } catch (err) {
    console.warn('shiki_highlight_failed_falling_back_to_text', { lang, err });
    return codeToHtml(code ?? '', {
      lang: 'text' as unknown as BundledLanguage,
      themes: { light: 'github-light', dark: 'github-dark' },
      cssVariablePrefix: '--shiki-',
    });
  }
}

export function getLanguageDisplayName(lang: string) {
  const raw = String(lang || '').trim().toLowerCase();
  const map: Record<string, string> = {
    js: 'JavaScript',
    javascript: 'JavaScript',
    ts: 'TypeScript',
    typescript: 'TypeScript',
    jsx: 'JSX',
    tsx: 'TSX',
    py: 'Python',
    python: 'Python',
    html: 'HTML',
    css: 'CSS',
    bash: 'Bash',
    sh: 'Bash',
    json: 'JSON',
    sql: 'SQL',
    markdown: 'Markdown',
    md: 'Markdown',
    yaml: 'YAML',
    yml: 'YAML',
    text: 'Text',
  };

  return map[raw] || raw.toUpperCase();
}
