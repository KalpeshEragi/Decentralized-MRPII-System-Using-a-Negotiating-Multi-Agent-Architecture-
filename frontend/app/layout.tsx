import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Decentralized MRPII — Simulation",
  description: "SmartPhone X1: planning, autonomous agent negotiation and human approval",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
