"use client";
import { memo, useEffect, useId, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import { EvidenceBadge } from "@/components/domain/badges";
import type { EvidenceClass } from "@/types/api";

const EVIDENCE = new Set(["DETECTED", "INFERRED", "AI_INTERPRETED", "UNKNOWN"]);

function Mermaid({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = document.documentElement.classList.contains("dark");
        mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "neutral", securityLevel: "strict", fontFamily: "var(--font-sans)" });
        const { svg } = await mermaid.render(`m${id}`, code);
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, id]);
  if (error) {
    return (
      <pre>
        <code>{code}</code>
      </pre>
    );
  }
  return <div ref={ref} className="my-4 overflow-x-auto rounded-xl border border-border bg-surface-2/40 p-4 [&_svg]:mx-auto [&_svg]:max-w-full" aria-label="Diagram" />;
}

const components: Components = {
  code({ className, children, ...props }) {
    const text = String(children ?? "");
    const lang = /language-(\w+)/.exec(className || "")?.[1];
    if (lang === "mermaid") return <Mermaid code={text.trim()} />;
    if (!className && EVIDENCE.has(text)) return <EvidenceBadge value={text as EvidenceClass} />;
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  pre({ children, ...props }) {
    // mermaid renders its own container; avoid wrapping it in <pre>
    const child = Array.isArray(children) ? children[0] : children;
    if (child && typeof child === "object" && "props" in child && /language-mermaid/.test(String((child as { props: { className?: string } }).props.className))) {
      return <>{children}</>;
    }
    return <pre {...props}>{children}</pre>;
  },
  a({ href, children, ...props }) {
    const external = href?.startsWith("http");
    return (
      <a href={href} {...props} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}>
        {children}
      </a>
    );
  },
};

export const Markdown = memo(function Markdown({ source }: { source: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
});
