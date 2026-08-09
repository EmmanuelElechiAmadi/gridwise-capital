"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export default function Header() {
  const { user, isAdmin, logout, planLabel, hasAccess } = useAuth();

  return (
    <header className="fixed top-0 left-0 right-0 z-50">
      <div className="glass border-b border-white/[0.06]">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center">
              <span className="text-black font-bold text-sm">SQ</span>
            </div>
            <span className="font-semibold text-lg tracking-tight">
              Seek <span className="gradient-text">Quant</span>
            </span>
          </Link>

          {/* Navigation */}
          <nav className="hidden md:flex items-center gap-8">
            <Link
              href="/"
              className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
            >
              Home
            </Link>
            <Link
              href="/#strategy"
              className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
            >
              Strategy
            </Link>
            <Link
              href="/#performance"
              className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
            >
              Performance
            </Link>
            <Link
              href="/#pricing"
              className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
            >
              Pricing
            </Link>
          </nav>

          {/* Auth buttons */}
          <div className="flex items-center gap-3">
            {user ? (
              <>
                {/* Plan badge */}
                <Link
                  href="/billing"
                  className={`text-xs px-3 py-1 rounded-full font-medium transition-all ${
                    hasAccess
                      ? "bg-amber-500/10 text-amber-400 hover:bg-amber-500/20"
                      : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                  }`}
                >
                  {planLabel}
                </Link>

                {isAdmin ? (
                  <Link
                    href="/admin"
                    className="text-sm px-4 py-2 rounded-lg bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-all"
                  >
                    Admin
                  </Link>
                ) : (
                  <>
                    <Link
                      href="/dashboard"
                      className="text-sm px-4 py-2 rounded-lg bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-all"
                    >
                      Dashboard
                    </Link>
                    <Link
                      href="/intelligence"
                      className="hidden sm:inline text-sm px-3 py-2 text-zinc-400 hover:text-zinc-100 transition-colors"
                    >
                      Intelligence
                    </Link>
                  </>
                )}

                <Link
                  href="/billing"
                  className="hidden sm:inline text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Billing
                </Link>

                <div className="flex items-center gap-2 pl-3 border-l border-white/[0.06]">
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center">
                    <span className="text-black text-xs font-bold">
                      {user.name.charAt(0)}
                    </span>
                  </div>
                  <span className="text-sm text-zinc-300">{user.name}</span>
                  <button
                    onClick={logout}
                    className="text-xs text-zinc-500 hover:text-zinc-300 ml-2 transition-colors"
                  >
                    Logout
                  </button>
                </div>
              </>
            ) : (
              <>
                <Link
                  href="/#pricing"
                  className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors px-3 py-2"
                >
                  Pricing
                </Link>
                <Link
                  href="/login"
                  className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors px-4 py-2"
                >
                  Login
                </Link>
                <Link
                  href="/signup"
                  className="text-sm px-4 py-2 rounded-lg bg-amber-500 text-black font-medium hover:bg-amber-400 transition-all"
                >
                  Get Started
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
