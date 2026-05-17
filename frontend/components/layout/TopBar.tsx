"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const NAV = [
  { label: "Dashboard", href: "/" },
  { label: "Employees", href: "/employees" },
  { label: "Reports", href: "#" },
  { label: "Settings", href: "#" },
];

export function TopBar() {
  const pathname = usePathname();
  const params = useSearchParams();
  // Carry the current view state across tabs. ?date= keeps a historic
  // view when switching pages; ?mode= keeps weekly/daily so the user
  // isn't kicked back to daily on the new page.
  const qs = params.toString();
  const suffix = qs ? `?${qs}` : "";

  return (
    <div className="flex items-center justify-between bg-bg-dark px-10 py-[18px] text-text-on-dark">
      <div className="flex items-center gap-[10px] text-[14px] font-medium tracking-[-0.01em]">
        <div className="h-2 w-2 rounded-[2px] bg-accent" />
        <span>Prezlab · Attendance</span>
      </div>
      <nav className="flex gap-6 text-[13px] text-text-on-dark-muted">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const className = active
            ? "cursor-pointer text-text-on-dark"
            : "cursor-pointer";
          return item.href.startsWith("#") ? (
            <span key={item.label} className={className}>
              {item.label}
            </span>
          ) : (
            <Link key={item.label} href={`${item.href}${suffix}`} className={className}>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="flex items-center gap-[10px] text-[13px] text-text-on-dark-muted">
        <span>P&amp;C team</span>
        <div className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-white/10 text-[11px] font-medium text-text-on-dark">
          PC
        </div>
      </div>
    </div>
  );
}
