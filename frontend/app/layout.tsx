import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";
import { AppShell } from "@/components/layout/app-shell";
import { themeInitScript } from "@/components/layout/theme-toggle";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ContextForge", template: "%s · ContextForge" },
  description: "AI-powered codebase intelligence and universal LLM context generation.",
  icons: { icon: "/icon.svg" },
};

// Runtime configuration: the API URL is read on the server at request time so one image works in any deployment.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const config = {
    apiUrl: process.env.CONTEXTFORGE_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    token: process.env.CONTEXTFORGE_PUBLIC_API_TOKEN || null,
  };
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable} dark`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <script dangerouslySetInnerHTML={{ __html: `window.__CF_CONFIG__=${JSON.stringify(config).replace(/</g, "\\u003c")}` }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
