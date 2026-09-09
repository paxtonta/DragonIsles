import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DragonIsles",
  description: "A two-player DragonIsles game"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" suppressHydrationWarning><head><script dangerouslySetInnerHTML={{ __html: `try { if (localStorage.getItem("dragonisles-theme") !== "light") document.documentElement.classList.add("dark"); } catch (_) { document.documentElement.classList.add("dark"); }` }} /></head><body>{children}</body></html>;
}
