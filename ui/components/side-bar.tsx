"use client";

import React, { ReactNode, useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation"; // Use usePathname from App Router
import {
  LayoutDashboard,
  Bot,
  ClipboardPlus,
  Dumbbell,
  LogOut,
  HandHelping,
  Video,
  Frame,
  Minimize,
  Captions,
  ZoomIn,
} from "lucide-react";

interface SidebarLink {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}

const sidebarLinks: SidebarLink[] = [
  {
    title: "Shorts Generator",
    href: "/innerpage/aigen",
    icon: Video,
    color: "text-pink-500",
  },
  {
    title: "Minimize",
    href: "/innerpage/minimize",
    icon: Minimize,
    color: "text-pink-500",
  },
  {
    title: "Auto Zoom",
    href: "/innerpage/zoom",
    icon: ZoomIn,
    color: "text-pink-500",
  },
  {
    title: "Frame Aspects",
    href: "/innerpage/frame",
    icon: Frame,
    color: "text-pink-500",
  },
  {
    title: "Caption",
    href: "/innerpage/caption",
    icon: Captions,
    color: "text-pink-500",
  },
];

interface SidebarProps {
  children: ReactNode;
}

const Sidebar: React.FC<SidebarProps> = ({ children }) => {
  const pathname = usePathname(); // Get the current path using usePathname
  const [activeLink, setActiveLink] = useState<string>("");

  useEffect(() => {
    setActiveLink(pathname); // Set active link based on the current pathname
  }, [pathname]);

  return (
    <div className="flex min-h-screen">
      <aside className="hidden md:flex md:flex-col w-64 bg-white shadow-lg h-screen fixed top-0 left-0 z-50">
        <div className="p-6 border-b border-pink-100">
          <Link href="/">
            <h1 className="text-xl font-bold bg-gradient-to-r from-pink-500 to-purple-500 bg-clip-text text-transparent">
              MediaMind
            </h1>
          </Link>
        </div>
        <nav className="flex-1 px-4 pb-4 pt-4">
          {sidebarLinks.map(({ title, href, icon: Icon, color }) => (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-4 py-3 text-gray-700 rounded-lg hover:bg-pink-50 ${activeLink === href ? 'bg-pink-100' : ''}`}
            >
              <Icon className={`h-5 w-5 ${color}`} />
              <span>{title}</span>
            </Link>
          ))}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col md:ml-64 relative z-10 bg-slate-50 text-black">
        {children}
      </div>
    </div>
  );
};

export default Sidebar;
