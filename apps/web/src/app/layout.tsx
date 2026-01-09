import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Discord Community Intelligence",
  description: "Control Plane for Discord Analytics",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-discord-darkest">{children}</body>
    </html>
  );
}
