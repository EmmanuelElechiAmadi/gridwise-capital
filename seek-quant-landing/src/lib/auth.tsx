"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import type { SubscriptionTier, Subscription } from "@/types";
import { isSupabaseConfigured, getSupabaseClient } from "./supabase";

export type UserRole = "admin" | "trader";

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  subscription: Subscription;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (
    email: string,
    password: string
  ) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  isAdmin: boolean;
  register: (
    name: string,
    email: string,
    password: string
  ) => Promise<{ success: boolean; error?: string }>;
  /** Update the local subscription state (called after admin assigns a plan) */
  refreshSubscription: () => Promise<void>;
  /** Get a readable label for the current plan */
  planLabel: string;
  /** Check if user has access to a paid feature */
  hasAccess: boolean;
  /** The current subscription tier */
  tier: SubscriptionTier;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// ── Demo mode defaults ─────────────────────────────────────────────

const ADMIN_EMAIL = "admin@seekquant.com";
const ADMIN_PASSWORD = "admin123";

const DEFAULT_TRADERS: Record<
  string,
  { password: string; name: string; tier?: SubscriptionTier }
> = {
  "john@example.com": {
    password: "trader123",
    name: "John Carter",
    tier: "professional",
  },
  "sarah@example.com": {
    password: "trader123",
    name: "Sarah Chen",
    tier: "starter",
  },
  "mike@example.com": { password: "trader123", name: "Mike Torres" },
  "emma@example.com": { password: "trader123", name: "Emma Wilson" },
};

function defaultSubscription(tier: SubscriptionTier = "free"): Subscription {
  const now = new Date();
  const end = new Date(now);
  end.setMonth(end.getMonth() + 1);
  return {
    tier,
    status: "active",
    currentPeriodStart: now.toISOString(),
    currentPeriodEnd: end.toISOString(),
  };
}

// ── Helpers ────────────────────────────────────────────────────────

function loadSubscriptions(): Record<string, Subscription> {
  try {
    const raw = localStorage.getItem("seekquant_subs");
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveSubscriptions(subs: Record<string, Subscription>) {
  localStorage.setItem("seekquant_subs", JSON.stringify(subs));
}

// ── Provider ───────────────────────────────────────────────────────

export function AuthProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Restore session on mount
  useEffect(() => {
    const stored = localStorage.getItem("seekquant_user");
    if (stored) {
      try {
        setUser(JSON.parse(stored));
      } catch {
        localStorage.removeItem("seekquant_user");
      }
    }
    setIsLoading(false);
  }, []);

  /** Persist user + subscription to localStorage (demo mode) */
  const persistUser = (u: User) => {
    setUser(u);
    localStorage.setItem("seekquant_user", JSON.stringify(u));
    // Also persist subscription separately
    const subs = loadSubscriptions();
    subs[u.id] = u.subscription;
    saveSubscriptions(subs);
  };

  /** Load subscription from storage / assign default */
  const resolveSubscription = (
    userId: string,
    email: string,
    preferredTier?: SubscriptionTier
  ): Subscription => {
    const subs = loadSubscriptions();
    if (subs[userId]) return subs[userId];
    if (preferredTier) return defaultSubscription(preferredTier);
    // Check if a default tier was set for this email
    for (const [e, data] of Object.entries(DEFAULT_TRADERS)) {
      if (e === email && data.tier) {
        return defaultSubscription(data.tier);
      }
    }
    return defaultSubscription("free");
  };

  /** Build a User object */
  const buildUser = (
    id: string,
    name: string,
    email: string,
    role: UserRole,
    tier?: SubscriptionTier
  ): User => ({
    id,
    name,
    email,
    role,
    subscription: resolveSubscription(id, email, tier),
  });

  const register = async (
    name: string,
    email: string,
    password: string
  ): Promise<{ success: boolean; error?: string }> => {
    await new Promise((r) => setTimeout(r, 800));

    const emailLower = email.toLowerCase();

    // Check if email already in default traders
    if (DEFAULT_TRADERS[emailLower] || emailLower === ADMIN_EMAIL) {
      return {
        success: false,
        error: "An account with this email already exists.",
      };
    }

    // Check localStorage registered users
    const existing = localStorage.getItem("seekquant_users");
    if (existing) {
      try {
        const users = JSON.parse(existing);
        if (users[emailLower]) {
          return {
            success: false,
            error: "An account with this email already exists.",
          };
        }
      } catch {
        /* ignore */
      }
    }

    // Store
    const storedUsers = existing ? JSON.parse(existing) : {};
    storedUsers[emailLower] = { name, password };
    localStorage.setItem("seekquant_users", JSON.stringify(storedUsers));

    // Auto-login (free tier)
    const newUser = buildUser(
      "trader-" + Date.now(),
      name,
      emailLower,
      "trader",
      "free"
    );
    // Give a 7-day trial
    const trialEnd = new Date();
    trialEnd.setDate(trialEnd.getDate() + 7);
    newUser.subscription = {
      ...newUser.subscription,
      status: "trialing",
      trialEndsAt: trialEnd.toISOString(),
    };
    persistUser(newUser);
    return { success: true };
  };

  const login = async (
    email: string,
    password: string
  ): Promise<{ success: boolean; error?: string }> => {
    await new Promise((r) => setTimeout(r, 800));

    // Admin login
    if (email.toLowerCase() === ADMIN_EMAIL && password === ADMIN_PASSWORD) {
      persistUser(buildUser("admin-001", "Admin", ADMIN_EMAIL, "admin"));
      return { success: true };
    }

    // Default trader login
    const trader = DEFAULT_TRADERS[email.toLowerCase()];
    if (trader && trader.password === password) {
      const idx = Object.keys(DEFAULT_TRADERS).indexOf(email.toLowerCase());
      persistUser(
        buildUser(
          "trader-" + (idx + 1),
          trader.name,
          email.toLowerCase(),
          "trader",
          trader.tier
        )
      );
      return { success: true };
    }

    // Registered users in localStorage
    const storedUsersRaw = localStorage.getItem("seekquant_users");
    if (storedUsersRaw) {
      try {
        const storedUsers = JSON.parse(storedUsersRaw);
        const storedUser = storedUsers[email.toLowerCase()];
        if (storedUser && storedUser.password === password) {
          persistUser(
            buildUser(
              "trader-" + email.toLowerCase().replace(/[^a-z0-9]/g, ""),
              storedUser.name,
              email.toLowerCase(),
              "trader",
              "free"
            )
          );
          return { success: true };
        }
      } catch {
        /* ignore */
      }
    }

    return { success: false, error: "Invalid email or password." };
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem("seekquant_user");
  };

  const refreshSubscription = useCallback(async () => {
    if (!user) return;
    const subs = loadSubscriptions();
    const updated = subs[user.id];
    if (updated) {
      const updatedUser = { ...user, subscription: updated };
      setUser(updatedUser);
      localStorage.setItem("seekquant_user", JSON.stringify(updatedUser));
    }
  }, [user]);

  const isAdmin = user?.role === "admin";
  const tier = user?.subscription?.tier ?? "free";
  const planLabel =
    tier.charAt(0).toUpperCase() + tier.slice(1); // "Free", "Starter", etc.
  const hasAccess = tier !== "free";

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        login,
        logout,
        isAdmin,
        register,
        refreshSubscription,
        planLabel,
        hasAccess,
        tier,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}