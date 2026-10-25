import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Decentra — a factory run by six negotiating agents",
  description: "Live control panel of the decentralised MRPII simulation: the factory, the agents' conversation, the orders.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
