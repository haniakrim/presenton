"use client";

import { useLayoutEffect, useState, type CSSProperties } from "react";
import { cn } from "@/lib/utils";

interface ForgeSplashLoaderProps {
  message?: string;
  className?: string;
}

export const FORGE_SPLASH_MIN_DURATION_MS = 3000;

const SPLASH_ANIMATION_MS = 2600;

let splashSessionStartedAt: number | null = null;

function markSplashSessionStart(): number {
  if (splashSessionStartedAt === null) {
    splashSessionStartedAt = Date.now();
  }
  return splashSessionStartedAt;
}

function getSplashAnimationDelayMs(): number {
  const elapsed = Date.now() - markSplashSessionStart();
  return -Math.min(elapsed, SPLASH_ANIMATION_MS);
}

export function ForgeSplashLoader({
  message = "Preparing your workspace",
  className,
}: ForgeSplashLoaderProps) {
  const [animationDelayMs, setAnimationDelayMs] = useState(0);

  useLayoutEffect(() => {
    setAnimationDelayMs(getSplashAnimationDelayMs());
  }, []);

  const containerStyle: CSSProperties = {
    position: "fixed",
    inset: 0,
    zIndex: 2147483000,
    display: "flex",
    minHeight: "100vh",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    background: "#0a0d18",
  };

  const surfaceStyle: CSSProperties = {
    position: "absolute",
    top: "50%",
    left: "50%",
    width: "142vmax",
    height: "142vmax",
    borderRadius: "50%",
    background:
      "radial-gradient(circle at 35% 30%, #7c5cff 0%, #5b3fe0 55%, #33269e 100%)",
    transform: "translate3d(-50%, -50%, 0) scale(0.001)",
    animation: `forge-splash-surface-grow ${SPLASH_ANIMATION_MS}ms linear ${animationDelayMs}ms both`,
    willChange: "transform",
    backfaceVisibility: "hidden",
  };

  const wordmarkStyle: CSSProperties = {
    position: "relative",
    zIndex: 1,
    transform: "translateZ(0)",
    fontFamily: "var(--font-syne, 'Syne', sans-serif)",
    fontWeight: 800,
    fontSize: "min(14vw, 128px)",
    letterSpacing: "-0.02em",
    lineHeight: 1,
    display: "inline-block",
  };

  const wordmarkRevealStyle: CSSProperties = {
    position: "absolute",
    inset: 0,
    display: "block",
  };

  return (
    <main
      aria-busy="true"
      aria-label={message}
      className={cn("forge-splash-loader", className)}
      role="status"
      style={containerStyle}
    >
      <div
        className="forge-splash-surface"
        aria-hidden="true"
        style={surfaceStyle}
      />
      <div className="forge-splash-wordmark" aria-hidden="true" style={wordmarkStyle}>
        <span
          className="forge-splash-wordmark-layer forge-splash-wordmark-base"
          style={{ color: "#5b3fe0" }}
        >
          Forge
        </span>
        <span
          className="forge-splash-wordmark-layer forge-splash-wordmark-reveal"
          style={{
            ...wordmarkRevealStyle,
            color: "#ffffff",
            clipPath: "circle(0 at 50% 50%)",
            animation: `forge-splash-text-reveal ${SPLASH_ANIMATION_MS}ms linear ${animationDelayMs}ms both`,
            willChange: "clip-path",
          }}
        >
          Forge
        </span>
      </div>
    </main>
  );
}
