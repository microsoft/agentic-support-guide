import type { ReactNode } from "react";
import { Header } from "./Header";
import { MobileNav, Sidebar } from "./Sidebar";
import { PrototypeBanner } from "./PrototypeBanner";

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <PrototypeBanner />
      <div className="flex flex-1 min-h-0">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Header />
          <MobileNav />
          <main className="flex-1 overflow-y-auto p-6 bg-slate-900/60">{children}</main>
        </div>
      </div>
    </div>
  );
}
