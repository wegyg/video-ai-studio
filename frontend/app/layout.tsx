import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Video AI Studio — Reels & Shorts Generator",
  description: "Generate promotional Reels/Shorts from a topic or product photos.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="text-white antialiased">{children}</body>
    </html>
  );
}
