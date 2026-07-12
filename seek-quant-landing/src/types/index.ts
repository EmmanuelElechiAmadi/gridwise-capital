// ── Subscription Plans ──────────────────────────────────────────────

export type SubscriptionTier = "free" | "starter" | "professional" | "enterprise";

export interface SubscriptionPlan {
  id: SubscriptionTier;
  name: string;
  price: number;       // monthly in USD
  priceYearly?: number; // annually in USD (discounted)
  description: string;
  badge?: string;
  features: string[];
  highlighted?: boolean;
  cta: string;
}

export const SUBSCRIPTION_PLANS: SubscriptionPlan[] = [
  {
    id: "free",
    name: "Free",
    price: 0,
    description: "Explore Seek Quant's capabilities",
    features: [
      "Strategy overview & methodology",
      "Monthly performance snapshot",
      "Up to 5 recent trades visible",
      "Public market data access",
    ],
    cta: "Get Started",
  },
  {
    id: "starter",
    name: "Starter",
    price: 49,
    priceYearly: 490,
    description: "For individual traders going live",
    badge: "Popular",
    highlighted: true,
    features: [
      "Real-time portfolio dashboard",
      "Full trade history & export",
      "Basic performance analytics",
      "Email alerts & notifications",
      "Community access",
    ],
    cta: "Start Free Trial",
  },
  {
    id: "professional",
    name: "Professional",
    price: 149,
    priceYearly: 1490,
    description: "For serious quantitative traders",
    features: [
      "Everything in Starter",
      "ML model insights & regime detection",
      "Advanced risk analytics (VaR, Monte Carlo)",
      "API access (read-only)",
      "Backtest engine access",
      "Priority support (4h response)",
    ],
    cta: "Subscribe",
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: 0, // custom
    description: "For institutions and funds",
    features: [
      "Everything in Professional",
      "Full bot control & auto-trading",
      "White-label dashboard option",
      "Dedicated account manager",
      "Custom integrations & API (read/write)",
      "SLA guarantee",
    ],
    cta: "Contact Sales",
  },
];

export function getPlan(id: SubscriptionTier): SubscriptionPlan {
  return SUBSCRIPTION_PLANS.find((p) => p.id === id) ?? SUBSCRIPTION_PLANS[0];
}

// ── Subscription Account ────────────────────────────────────────────

export interface Subscription {
  tier: SubscriptionTier;
  status: "active" | "trialing" | "past_due" | "canceled" | "expired";
  currentPeriodStart: string; // ISO date
  currentPeriodEnd: string;   // ISO date
  trialEndsAt?: string;
  canceledAt?: string;
}

// ── User Profile (augments auth user) ──────────────────────────────

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  investorType: "individual" | "accredited" | "institutional";
  subscription: Subscription;
  createdAt: string;
}

// ── Feature Flags ───────────────────────────────────────────────────

export type FeatureFlag =
  | "dashboard:realtime"
  | "dashboard:full-trades"
  | "dashboard:export"
  | "analytics:basic"
  | "analytics:advanced"
  | "ml:insights"
  | "ml:regime"
  | "api:read"
  | "api:read-write"
  | "backtest:access"
  | "bot:control"
  | "support:priority"
  | "support:dedicated"
  | "white-label"
  | "custom-integrations";

export const TIER_FEATURES: Record<SubscriptionTier, FeatureFlag[]> = {
  free: [],
  starter: [
    "dashboard:realtime",
    "dashboard:full-trades",
    "dashboard:export",
    "analytics:basic",
    "support:priority",
  ],
  professional: [
    "dashboard:realtime",
    "dashboard:full-trades",
    "dashboard:export",
    "analytics:basic",
    "analytics:advanced",
    "ml:insights",
    "ml:regime",
    "api:read",
    "backtest:access",
    "support:priority",
  ],
  enterprise: [
    "dashboard:realtime",
    "dashboard:full-trades",
    "dashboard:export",
    "analytics:basic",
    "analytics:advanced",
    "ml:insights",
    "ml:regime",
    "api:read",
    "api:read-write",
    "backtest:access",
    "bot:control",
    "support:priority",
    "support:dedicated",
    "white-label",
    "custom-integrations",
  ],
};

export function hasFeature(tier: SubscriptionTier, feature: FeatureFlag): boolean {
  return TIER_FEATURES[tier]?.includes(feature) ?? false;
}