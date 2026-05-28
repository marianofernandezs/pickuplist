import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "VIGE Generator",
  description: "Consolidador de productos desde PDFs"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
