"use client";

import DOMPurify, { type Config as DOMPurifyConfig } from "dompurify";
import { useEffect, useMemo, useRef, useState } from "react";

import { useTailwindRuntimeReady } from "@/components/runtime/TailwindBrowserRuntime";
import {
  localFontOptionsFromUnknown,
  renderLocalFontFaceCss,
} from "@/components/slide-editor/text/local-fonts";
import {
  CHART_BROWSER_SCRIPT_URL,
  CHART_DATALABELS_SCRIPT_URL,
} from "@/lib/chart-browser";
import { TAILWIND_BROWSER_SCRIPT_URL } from "@/lib/tailwind-browser";
import { useSmartChartInjection } from "./useSmartChartInjection";

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
const USE_LINUX_IN_PAGE_RENDERER =
  process.env.NEXT_PUBLIC_PRESENTON_ELECTRON_PLATFORM === "linux";

const SANITIZE_CONFIG: DOMPurifyConfig = {
  USE_PROFILES: { html: true, svg: true, svgFilters: true },
  FORBID_TAGS: [
    "base",
    "embed",
    "form",
    "iframe",
    "link",
    "meta",
    "object",
    "script",
    "style",
  ],
  FORBID_ATTR: ["autofocus", "contenteditable", "srcdoc"],
  ALLOW_DATA_ATTR: true,
};

function fontAssets(fonts: unknown) {
  const css = localFontOptionsFromUnknown(fonts)
    .map(renderLocalFontFaceCss)
    .join("");
  return css ? `<style>${css.replaceAll("</style", "<\\/style")}</style>` : "";
}

function previewDocument(html: string, fonts: unknown, zoom = 1) {
  // `zoom` on html/body (not a CSS transform on an ancestor) makes the
  // iframe reflow and rerender text natively at the smaller physical size -
  // a transform/zoom applied outside the iframe can only bitmap-scale its
  // already-rendered surface, which washes out thinner text at small sizes.
  const zoomCss = zoom !== 1 ? `html,body{zoom:${zoom}}` : "";
  return `<!doctype html>
  <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=1280, initial-scale=1">
      ${fontAssets(fonts)}
      <script src="${TAILWIND_BROWSER_SCRIPT_URL}"></script>
      <script src="${CHART_BROWSER_SCRIPT_URL}"></script>
      <script src="${CHART_DATALABELS_SCRIPT_URL}"></script>
      <script>
        if (window.Chart && window.ChartDataLabels) {
          window.Chart.register(window.ChartDataLabels);
        }
      </script>
      <style>
        html,body{width:1280px;height:720px;min-width:1280px;min-height:720px;margin:0;overflow:hidden;background:#fff}
        *{box-sizing:border-box}
        ${zoomCss}
      </style>
    </head>
    <body>${html}</body>
  </html>`;
}

function useSlideFontAssets(fonts: unknown, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const css = localFontOptionsFromUnknown(fonts)
      .map(renderLocalFontFaceCss)
      .join("");
    if (!css) return;

    const style = document.createElement("style");
    style.dataset.slideFontAssets = "true";
    style.textContent = css;
    document.head.appendChild(style);
    return () => style.remove();
  }, [enabled, fonts]);
}

function LinuxInPageSmartHtmlSlide({
  html,
  fonts,
  fixedSize,
  title,
  executeScripts,
}: {
  html: string;
  fonts?: unknown;
  fixedSize: boolean;
  title: string;
  executeScripts: boolean;
}) {
  const tailwindReady = useTailwindRuntimeReady();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const slideRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [instanceId] = useState(
    () => `smart-slide-preview-${Math.random().toString(36).slice(2)}`
  );
  const [sanitizedHtml, setSanitizedHtml] = useState("");

  useEffect(() => {
    setSanitizedHtml(DOMPurify.sanitize(html, SANITIZE_CONFIG));
  }, [html]);

  useSlideFontAssets(fonts, executeScripts);
  useSmartChartInjection({
    html: executeScripts && tailwindReady && sanitizedHtml ? html : "",
    instanceId,
    domRevision: sanitizedHtml,
    containerRef: slideRef,
  });

  useEffect(() => {
    if (fixedSize) return;
    const element = containerRef.current;
    if (!element) return;
    const update = () => setWidth(element.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [fixedSize]);

  const scale = fixedSize ? 1 : width ? Math.min(width / SLIDE_WIDTH, 1) : 0;

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden bg-white"
      style={{
        width: fixedSize ? SLIDE_WIDTH : undefined,
        height: fixedSize ? SLIDE_HEIGHT : SLIDE_HEIGHT * (scale || 1),
      }}
    >
      <div
        ref={slideRef}
        data-smart-slide-instance={instanceId}
        className="pointer-events-none absolute left-1/2 top-0 h-[720px] w-[1280px] select-none overflow-hidden bg-white"
        aria-label={title}
        style={{
          transform: `translateX(-50%) scale(${scale || 1})`,
          transformOrigin: "top center",
          opacity: scale ? 1 : 0,
        }}
        dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
      />
    </div>
  );
}

function IframeSmartHtmlSlide({
  html,
  fonts,
  fixedSize,
  title,
  renderScale,
}: {
  html: string;
  fonts?: unknown;
  fixedSize: boolean;
  title: string;
  renderScale?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (fixedSize) return;
    const element = containerRef.current;
    if (!element) return;
    const update = () => setWidth(element.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [fixedSize]);

  const scale = fixedSize
    ? renderScale ?? 1
    : width
    ? Math.min(width / SLIDE_WIDTH, 1)
    : 0;
  const srcDoc = useMemo(
    () => previewDocument(html, fonts, scale || 1),
    [fonts, html, scale]
  );

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden bg-white"
      style={{
        width: fixedSize ? SLIDE_WIDTH * (scale || 1) : undefined,
        height: SLIDE_HEIGHT * (scale || 1),
      }}
    >
      <div
        className="absolute left-1/2 top-0"
        style={{
          width: SLIDE_WIDTH * (scale || 1),
          height: SLIDE_HEIGHT * (scale || 1),
          transform: "translateX(-50%)",
          opacity: scale ? 1 : 0,
        }}
      >
        {/* The iframe is sized to the actual rendered pixels, and `zoom`
            is applied inside its own document (see previewDocument) so it
            reflows and rerenders text natively at that size, instead of
            being bitmap-scaled down from a full 1280x720 render. */}
        <iframe
          className="block border-0 bg-white"
          style={{
            width: SLIDE_WIDTH * (scale || 1),
            height: SLIDE_HEIGHT * (scale || 1),
          }}
          sandbox="allow-scripts"
          srcDoc={srcDoc}
          tabIndex={-1}
          title={title}
        />
      </div>
    </div>
  );
}

export default function SmartHtmlSlide({
  html,
  fonts,
  fixedSize = false,
  title = "Smart presentation slide",
  executeScripts = true,
  renderScale,
}: {
  html: string;
  fonts?: unknown;
  fixedSize?: boolean;
  title?: string;
  executeScripts?: boolean;
  // Only meaningful with fixedSize: renders at this fraction of native
  // 1280x720 by applying `zoom` inside the iframe's own document, instead
  // of the caller bitmap-scaling a full-size render from outside (which
  // washes out thinner text at small sizes - see previewDocument).
  renderScale?: number;
}) {
  if (USE_LINUX_IN_PAGE_RENDERER) {
    return (
      <LinuxInPageSmartHtmlSlide
        fixedSize={fixedSize}
        fonts={fonts}
        html={html}
        title={title}
        executeScripts={executeScripts}
      />
    );
  }

  return (
    <IframeSmartHtmlSlide
      fixedSize={fixedSize}
      fonts={fonts}
      html={html}
      title={title}
      renderScale={renderScale}
    />
  );
}
