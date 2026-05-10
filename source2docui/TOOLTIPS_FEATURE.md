# Tooltips Feature Implementation

## Overview

The tooltip feature allows you to define contextual hints for abbreviations and technical terms throughout your wiki content. When users hover over these terms, they see a helpful definition in a tooltip.

## How It Works

### 1. JSON Structure

Add a `tooltips` array to your wiki page JSON file:

```json
{
  "id": "page-id",
  "title": "Page Title",
  "tooltips": [
    {
      "term": "API",
      "definition": "Application Programming Interface - a set of rules that allows different software applications to communicate"
    },
    {
      "term": "React",
      "definition": "A JavaScript library for building user interfaces, developed by Facebook"
    }
  ],
  "blocks": [...]
}
```

### 2. Automatic Detection

The system automatically detects and highlights defined terms in:
- Paragraphs
- Headings
- Lists
- Tables
- Quotes
- Callouts
- Links
- Cut sections
- Steps

### 3. Features

- **Case-insensitive matching**: Terms are matched regardless of case
- **Whole word matching**: Only complete words are matched (e.g., "API" won't match "APIC")
- **Longest match first**: Longer terms are prioritized to avoid partial matches
- **Hover interaction**: Tooltips appear on hover with a 200ms delay
- **Accessible**: Uses semantic HTML with `<abbr>` tags and proper ARIA attributes
- **Styled**: Dotted underline decoration that becomes solid on hover

## Example Usage

### In getting-started.json:

```json
{
  "tooltips": [
    {
      "term": "wiki",
      "definition": "A collaborative website that allows users to add, modify, or delete content via a web browser"
    },
    {
      "term": "TypeScript",
      "definition": "A strongly typed programming language that builds on JavaScript"
    }
  ],
  "blocks": [
    {
      "type": "paragraph",
      "text": "This wiki is built with React and TypeScript."
    }
  ]
}
```

When rendered, "React" and "TypeScript" will be automatically highlighted with tooltips showing their definitions.

## Technical Implementation

### Components

1. **TooltipTerm** (`components/wiki/blocks/TooltipTerm.tsx`)
   - Renders individual terms with tooltips
   - Uses shadcn/ui Tooltip component
   - Semantic `<abbr>` tag for accessibility

2. **MarkdownInline** (`components/wiki/MarkdownInline.tsx`)
   - Enhanced to process text and replace terms with TooltipTerm components
   - Handles markdown formatting alongside tooltips
   - Regex-based term detection

3. **ContentRenderer** (`components/wiki/ContentRenderer.tsx`)
   - Passes tooltips to all block components
   - Ensures consistent tooltip availability across all content types

### Type Definitions

```typescript
export interface TooltipDefinition {
  term: string;
  definition: string;
}

export interface WikiPage {
  id: string;
  title: string;
  tooltips?: TooltipDefinition[];
  blocks: Block[];
  // ... other fields
}
```

## Best Practices

1. **Define terms once per page**: Add tooltips at the page level, not per block
2. **Keep definitions concise**: Aim for one or two sentences
3. **Use common abbreviations**: Focus on terms that might be unfamiliar to your audience
4. **Avoid over-definition**: Don't define every term, only those that need clarification
5. **Be consistent**: Use the same term spelling throughout your content

## Styling

The tooltip uses the following CSS classes:
- `cursor-help`: Changes cursor to indicate help is available
- `underline decoration-dotted`: Dotted underline in default state
- `hover:decoration-muted-foreground`: Solid underline on hover
- `transition-colors`: Smooth color transitions

## Browser Support

The feature works in all modern browsers that support:
- CSS hover states
- Flexbox
- CSS transitions
- Modern JavaScript (ES6+)

## Performance

- Tooltips are processed once during render
- Regex matching is optimized for performance
- No runtime overhead for pages without tooltips
- Lazy loading of tooltip content (only shown on hover)
