import type { Metadata } from "next";
import "./globals.css";

import { Suspense } from "react";

import { QueryProvider } from "@/components/providers/QueryProvider";
import { TopBar } from "@/components/layout/TopBar";
import { BottomBar } from "@/components/layout/BottomBar";

export const metadata: Metadata = {
  title: "Prezlab Attendance",
  description: "Live attendance dashboard for the P&C team.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="flex min-h-screen flex-col bg-bg-page font-sans text-text-primary">
        <QueryProvider>
          {/* TopBar reads ?date from useSearchParams, which requires a Suspense
              boundary to keep static prerendering working. */}
          <Suspense fallback={<div className="h-[62px] bg-bg-dark" />}>
            <TopBar />
          </Suspense>
          <div className="flex-1">{children}</div>
          <BottomBar />
        </QueryProvider>
      </body>
    </html>
  );
}
