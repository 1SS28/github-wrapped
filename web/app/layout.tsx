import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Tinos } from "next/font/google";
import { SITE_URL } from "@/lib/brand";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const tinos = Tinos({ variable: "--font-tinos", subsets: ["latin"], weight: ["400", "700"] });

export const metadata: Metadata = {
  metadataBase: new URL(`https://${SITE_URL}`),
  title: "GitHub Wrapped",
  description: "Your year on GitHub, roasted by a famous voice and ranked F to SSS. Illustrated and voiced with Magic Hour.",
};

export const viewport: Viewport = { themeColor: "#0b0d10", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${tinos.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
