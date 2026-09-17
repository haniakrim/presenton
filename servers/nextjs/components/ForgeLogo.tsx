"use client";

import React from "react";

/**
 * Forge brand mark: gradient badge + sparkle glyph, matching the app's
 * violet-to-cyan accent pair. `ForgeWordmark` pairs it with the "Forge"
 * name for full lockups (sidebars, marketing header); `ForgeMark` is the
 * icon alone for tight spaces (dashboard headers, editor toolbars).
 */

let gradientIdCounter = 0;

function useGradientId(prefix: string) {
  const [id] = React.useState(() => `${prefix}-${gradientIdCounter++}`);
  return id;
}

export interface ForgeMarkProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "className"> {
  className?: string;
  /** Disable the ambient glow pulse (e.g. inside an already-busy toolbar). */
  animated?: boolean;
}

export const ForgeMark: React.FC<ForgeMarkProps> = ({
  className,
  animated = true,
  ...rest
}) => {
  const gradientId = useGradientId("forge-mark-gradient");

  return (
    <span
      className={`forge-mark ${animated ? "forge-mark--animated" : ""} ${className ?? ""}`}
      {...rest}
    >
      <svg
        viewBox="0 0 40 40"
        role="img"
        aria-label="Forge"
        className="forge-mark__svg"
      >
        <defs>
          <linearGradient id={gradientId} x1="4" y1="4" x2="36" y2="36" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#7C5CFF" />
            <stop offset="1" stopColor="#33D6FF" />
          </linearGradient>
        </defs>
        <circle cx="20" cy="20" r="20" fill={`url(#${gradientId})`} />
        <path
          d="M20 8c0 6 2 10 8 12-6 2-8 6-8 12 0-6-2-10-8-12 6-2 8-6 8-12Z"
          fill="#FFFFFF"
        />
      </svg>
      <style jsx>{`
        .forge-mark {
          display: inline-flex;
          flex: none;
          line-height: 0;
        }
        .forge-mark__svg {
          width: 100%;
          height: 100%;
          display: block;
        }
        .forge-mark--animated .forge-mark__svg {
          filter: drop-shadow(0 0 0px rgba(124, 92, 255, 0.55));
          animation: forge-mark-glow 3.2s ease-in-out infinite;
        }
        @keyframes forge-mark-glow {
          0%,
          100% {
            filter: drop-shadow(0 0 0px rgba(124, 92, 255, 0.45));
          }
          50% {
            filter: drop-shadow(0 0 6px rgba(51, 214, 255, 0.65));
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .forge-mark--animated .forge-mark__svg {
            animation: none;
          }
        }
      `}</style>
    </span>
  );
};

export interface ForgeWordmarkProps {
  className?: string;
  /** Text color; defaults to dark ink for light headers. Pass "#FFFFFF" for dark surfaces. */
  textColor?: string;
  animated?: boolean;
}

export const ForgeWordmark: React.FC<ForgeWordmarkProps> = ({
  className,
  textColor = "#12162A",
  animated = true,
}) => {
  return (
    <span className={`forge-wordmark ${className ?? ""}`}>
      <ForgeMark className="forge-wordmark__mark" animated={animated} />
      <span className="forge-wordmark__text" style={{ color: textColor }}>
        Forge
      </span>
      <style jsx>{`
        .forge-wordmark {
          display: inline-flex;
          align-items: center;
          gap: 0.5em;
          line-height: 1;
        }
        .forge-wordmark :global(.forge-wordmark__mark) {
          width: 1em;
          height: 1em;
        }
        .forge-wordmark__text {
          font-family: var(--font-syne, "Syne", sans-serif);
          font-weight: 700;
          font-size: 1em;
          letter-spacing: -0.01em;
        }
      `}</style>
    </span>
  );
};

export default ForgeMark;
