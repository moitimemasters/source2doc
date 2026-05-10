'use client';

import { MermaidBlock } from '../../../lib/wiki/types';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import mermaid from 'mermaid';
import Panzoom, { PanzoomObject } from '@panzoom/panzoom';
import { useTheme } from 'next-themes';
import { Download, Maximize2, ZoomIn, ZoomOut } from 'lucide-react';

interface MermaidDiagramProps {
  block: MermaidBlock;
}

const ZOOM_STEP = 1.25;

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a tick so the browser can start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function getSerializedSvg(svg: SVGElement): string {
  // Clone so we can mutate without touching the live DOM.
  const clone = svg.cloneNode(true) as SVGElement;
  // Strip any pan-zoom transform so the saved file is the un-transformed diagram.
  clone.removeAttribute('style');
  clone.removeAttribute('transform');
  if (!clone.getAttribute('xmlns')) {
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  }
  if (!clone.getAttribute('xmlns:xlink')) {
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
  }
  const serializer = new XMLSerializer();
  const xml = serializer.serializeToString(clone);
  return `<?xml version="1.0" encoding="UTF-8"?>\n${xml}`;
}

function svgDimensions(svg: SVGElement): { width: number; height: number } {
  const bbox = (svg as SVGGraphicsElement).getBBox?.();
  const viewBox = svg.getAttribute('viewBox');
  let width = svg.clientWidth || 0;
  let height = svg.clientHeight || 0;
  if (viewBox) {
    const parts = viewBox.split(/\s+/).map(Number);
    if (parts.length === 4 && !parts.some(Number.isNaN)) {
      width = parts[2];
      height = parts[3];
    }
  } else if (bbox) {
    width = bbox.width;
    height = bbox.height;
  }
  // Guardrails — never zero.
  if (!width) width = 800;
  if (!height) height = 600;
  return { width, height };
}

export function MermaidDiagram({ block }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const panzoomRef = useRef<PanzoomObject | null>(null);
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // Bumped on every successful render so we can re-bind panzoom and download
  // handlers to the freshly-emitted <svg> node.
  const [renderToken, setRenderToken] = useState(0);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Render diagram and re-render on theme switch.
  useEffect(() => {
    if (!mounted || !stageRef.current) return;

    const isDark = resolvedTheme === 'dark';
    mermaid.initialize({
      startOnLoad: false,
      theme: isDark ? 'dark' : 'default',
      securityLevel: 'loose',
    });

    let cancelled = false;

    const renderDiagram = async () => {
      if (!stageRef.current) return;
      try {
        // Reset content so mermaid.run picks up the new theme.
        stageRef.current.innerHTML = block.diagram;
        stageRef.current.removeAttribute('data-processed');
        await mermaid.run({ nodes: [stageRef.current] });
        if (!cancelled) {
          setRenderToken((t) => t + 1);
        }
      } catch (error) {
        // eslint-disable-next-line no-console
        console.error('[MermaidDiagram] render error:', error);
      }
    };

    renderDiagram();
    return () => {
      cancelled = true;
    };
  }, [block.diagram, resolvedTheme, mounted]);

  // Bind panzoom to the rendered stage element.
  useEffect(() => {
    if (!mounted || !stageRef.current) return;
    // Destroy a previous instance if theme/diagram changed.
    if (panzoomRef.current) {
      panzoomRef.current.destroy();
      panzoomRef.current = null;
    }
    const stage = stageRef.current;
    const instance = Panzoom(stage, {
      maxScale: 8,
      minScale: 0.2,
      step: 0.3,
      cursor: 'grab',
      // Block panning when starting on toolbar buttons (they live outside the
      // stage already, but keep this for safety).
      excludeClass: 'mermaid-toolbar-btn',
      animate: false,
    });
    panzoomRef.current = instance;

    const wheelHandler = (e: WheelEvent) => {
      // Hold shift/ctrl-meta-free wheel to zoom by default.
      instance.zoomWithWheel(e);
    };
    const parent = stage.parentElement;
    parent?.addEventListener('wheel', wheelHandler, { passive: false });

    return () => {
      parent?.removeEventListener('wheel', wheelHandler);
      instance.destroy();
      if (panzoomRef.current === instance) {
        panzoomRef.current = null;
      }
    };
  }, [mounted, renderToken]);

  const handleZoomIn = useCallback(() => {
    panzoomRef.current?.zoomIn();
  }, []);

  const handleZoomOut = useCallback(() => {
    panzoomRef.current?.zoomOut();
  }, []);

  const handleReset = useCallback(() => {
    panzoomRef.current?.reset();
  }, []);

  const handleSaveSvg = useCallback(() => {
    const svg = stageRef.current?.querySelector('svg');
    if (!svg) return;
    const xml = getSerializedSvg(svg);
    const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
    triggerDownload(blob, `diagram-${Date.now()}.svg`);
  }, []);

  const handleSavePng = useCallback(() => {
    const svg = stageRef.current?.querySelector('svg');
    if (!svg) return;
    const xml = getSerializedSvg(svg);
    const { width, height } = svgDimensions(svg as SVGElement);
    // Bump for crispness on hi-DPI screens.
    const scale = Math.max(2, window.devicePixelRatio || 1);

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(width * scale);
      canvas.height = Math.ceil(height * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      // Match background to the surrounding card so transparent diagrams stay
      // legible when opened standalone.
      const isDark = resolvedTheme === 'dark';
      ctx.fillStyle = isDark ? '#0a0a0a' : '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.drawImage(img, 0, 0, width, height);
      canvas.toBlob((blob) => {
        if (blob) triggerDownload(blob, `diagram-${Date.now()}.png`);
      }, 'image/png');
    };
    img.onerror = (err) => {
      // eslint-disable-next-line no-console
      console.error('[MermaidDiagram] PNG render error:', err);
    };
    // Use a UTF-8-safe base64 encoding for non-ASCII content in the SVG.
    const b64 = btoa(unescape(encodeURIComponent(xml)));
    img.src = `data:image/svg+xml;base64,${b64}`;
  }, [resolvedTheme]);

  const toolbar = useMemo(
    () => (
      <div className="absolute top-2 right-2 z-10 flex items-center gap-0.5 rounded-md border border-border/60 bg-background/80 p-0.5 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <ToolbarButton onClick={handleZoomIn} label="Zoom in">
          <ZoomIn className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton onClick={handleZoomOut} label="Zoom out">
          <ZoomOut className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton onClick={handleReset} label="Reset view">
          <Maximize2 className="h-4 w-4" />
        </ToolbarButton>
        <span aria-hidden className="mx-0.5 h-4 w-px bg-border/70" />
        <ToolbarButton onClick={handleSaveSvg} label="Save as SVG">
          <Download className="h-4 w-4" />
          <span className="text-[10px] font-medium leading-none">SVG</span>
        </ToolbarButton>
        <ToolbarButton onClick={handleSavePng} label="Save as PNG">
          <Download className="h-4 w-4" />
          <span className="text-[10px] font-medium leading-none">PNG</span>
        </ToolbarButton>
      </div>
    ),
    [handleZoomIn, handleZoomOut, handleReset, handleSaveSvg, handleSavePng],
  );

  if (!mounted) {
    return (
      <div className="my-6 overflow-hidden rounded-lg border border-border/50 bg-muted/30 p-6">
        <div className="flex justify-center items-center h-32 text-muted-foreground">
          Loading diagram...
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative my-6 overflow-hidden rounded-lg border border-border/50 bg-muted/30"
      role="img"
      aria-label="Mermaid diagram"
    >
      {toolbar}
      <div className="overflow-hidden touch-none">
        <div
          ref={stageRef}
          className="mermaid flex justify-center p-6 select-none"
          // panzoom handles its own transform-origin
          style={{ transformOrigin: '0 0' }}
        >
          {block.diagram}
        </div>
      </div>
    </div>
  );
}

interface ToolbarButtonProps {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}

function ToolbarButton({ onClick, label, children }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="mermaid-toolbar-btn inline-flex h-7 items-center gap-1 rounded px-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}
