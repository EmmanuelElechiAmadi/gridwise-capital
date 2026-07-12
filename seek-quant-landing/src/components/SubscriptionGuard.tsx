"use client";

import { useAuth } from "@/lib/auth";
import type { SubscriptionTier } from "@/types";
import UpgradePrompt from "./UpgradePrompt";

interface Props {
  /** The minimum tier required to view the wrapped content */
  requiredTier?: SubscriptionTier;
  /** Children to wrap */
  children: React.ReactNode;
  /** Optional fallback when user isn't authenticated */
  loginFallback?: React.ReactNode;
}

/**
 * Guards content behind a subscription tier.
 * Free users see an UpgradePrompt; unauthenticated users see login fallback.
 */
export default function SubscriptionGuard({
  requiredTier = "starter",
  children,
  loginFallback,
}: Props) {
  const { user, tier, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "60px 0",
        }}
      >
        <div
          style={{
            width: 24,
            height: 24,
            border: "2px solid var(--gold)",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
          }}
        />
      </div>
    );
  }

  if (!user) {
    return loginFallback ? (
      <>{loginFallback}</>
    ) : (
      <UpgradePrompt
        title="Sign in required"
        description="Please sign in to access this feature."
        actionLabel="Sign In"
        actionHref="/login"
      />
    );
  }

  // Tier hierarchy for comparison
  const tierOrder: SubscriptionTier[] = [
    "free",
    "starter",
    "professional",
    "enterprise",
  ];
  const userTierIndex = tierOrder.indexOf(tier);
  const requiredIndex = tierOrder.indexOf(requiredTier);

  if (userTierIndex >= requiredIndex && tier !== "free") {
    return <>{children}</>;
  }

  // User is on free tier or lower than required
  const planName =
    requiredTier.charAt(0).toUpperCase() + requiredTier.slice(1);
  return (
    <UpgradePrompt
      title={`${planName} Plan Required`}
      description={`This feature requires a ${planName} subscription. Upgrade your plan to unlock it.`}
      actionLabel={`Upgrade to ${planName}`}
      actionHref={`/checkout?plan=${requiredTier}`}
    />
  );
}