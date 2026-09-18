"use client";

import DOMPurify, { type Config as DOMPurifyConfig } from "dompurify";
import { useEffect, useRef, useState } from "react";

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

// Same-origin image URLs the slide HTML references (e.g. "/app_data/images/...").
const SAME_ORIGIN_IMG_SRC = /src="(\/[^"]+)"/g;

// This iframe is sandboxed WITHOUT allow-same-origin, so it has an opaque
// origin - the browser treats it as cross-site no matter what it contains.
// The session cookie is SameSite=Lax, so it is never sent on that iframe's
// own <img> requests, and every same-origin image silently 401s. Fetch each
// one here, in the real page's own origin (where the cookie DOES apply),
// and inline it as a data URI before handing the HTML to the iframe -
// avoids ever needing the sandboxed context to authenticate anything.
const inlinedImageCache = new Map<string, Promise<string>>();

async function fetchAsDataUrl(src: string): Promise<string> {
  const cached = inlinedImageCache.get(src);
  if (cached) return cached;

  const promise = fetch(src, { credentials: "include" })
    .then((response) => {
      if (!response.ok) throw new Error(`${response.status}`);
      return response.blob();
    })
    .then(
      (blob) =>
        new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(reader.error);
          reader.readAsDataURL(blob);
        })
    )
    .catch(() => src); // fall back to the original src on any failure

  inlinedImageCache.set(src, promise);
  return promise;
}

async function inlineSameOriginImages(html: string): Promise<string> {
  const srcs = new Set<string>();
  for (const match of html.matchAll(SAME_ORIGIN_IMG_SRC)) {
    srcs.add(match[1]);
  }
  if (srcs.size === 0) return html;

  const entries = await Promise.all(
    Array.from(srcs, async (src) => [src, await fetchAsDataUrl(src)] as const)
  );

  let result = html;
  for (const [src, dataUrl] of entries) {
    if (dataUrl === src) continue;
    result = result.split(`src="${src}"`).join(`src="${dataUrl}"`);
  }
  return result;
}

function previewDocument(html: string, fonts: unknown) {
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
}: {
  html: string;
  fonts?: unknown;
  fixedSize: boolean;
  title: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [srcDoc, setSrcDoc] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    inlineSameOriginImages(html).then((inlinedHtml) => {
      if (!cancelled) setSrcDoc(previewDocument(inlinedHtml, fonts));
    });
    return () => {
      cancelled = true;
    };
  }, [fonts, html]);

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
        className="absolute left-1/2 top-0"
        style={{
          width: SLIDE_WIDTH,
          height: SLIDE_HEIGHT,
          transform: `translateX(-50%) scale(${scale || 1})`,
          transformOrigin: "top center",
          opacity: scale ? 1 : 0,
        }}
      >
        {srcDoc !== null && (
          <iframe
            className="block h-[720px] w-[1280px] border-0 bg-white"
            sandbox="allow-scripts"
            srcDoc={srcDoc}
            tabIndex={-1}
            title={title}
          />
        )}
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
}: {
  html: string;
  fonts?: unknown;
  fixedSize?: boolean;
  title?: string;
  executeScripts?: boolean;
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
    />
  );
}
