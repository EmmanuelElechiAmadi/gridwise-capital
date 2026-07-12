"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Check,
  CreditCard,
  Calendar,
  AlertTriangle,
  ArrowRight,
  Loader2,
} from "lucide-react";
import { useAuth, AuthProvider } from "@/lib/auth";
import { getPlan } from "@/types";
import UpgradePrompt from "@/components/UpgradePrompt";

function CurrentPlan() {
  const { user, tier, planLabel, refreshSubscription, isLoading } = useAuth();

  if (isLoading) {
    return <div className="loading-pulse">Loading…</div>;
  }

  if (!user) {
    return (
      <UpgradePrompt
        title="Sign in to manage billing"
        description="You need to be signed in to view your subscription plan."
        actionLabel="Sign In"
        actionHref="/login"
      />
    );
  }

  const plan = getPlan(tier);
  const sub = user.subscription;
  const periodEnd = sub.currentPeriodEnd
    ? new Date(sub.currentPeriodEnd).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : "N/A";

  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    if (!confirm("Are you sure you want to cancel your subscription?")) return;
    setCancelling(true);
    await new Promise((r) => setTimeout(r, 1000));

    const subs = JSON.parse(localStorage.getItem("seekquant_subs") || "{}");
    if (subs[user.id]) {
      subs[user.id].status = "canceled";
      localStorage.setItem("seekquant_subs", JSON.stringify(subs));
    }
    await refreshSubscription();
    setCancelling(false);
  };

  const isFree = tier === "free";
  const isCanceled = sub.status === "canceled";

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        padding: "80px 24px 40px",
      }}
    >
      <div style={{ maxWidth: 640, margin: "0 auto" }}>
        <Link
          href="/dashboard"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
            color: "var(--text-muted)",
            textDecoration: "none",
            marginBottom: 24,
          }}
        >
          <ArrowLeft size={14} />
          Back to Dashboard
        </Link>

        <h1
          style={{
            fontSize: 26,
            fontWeight: 800,
            color: "var(--text)",
            marginBottom: 4,
          }}
        >
          Billing & Plan
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 32 }}>
          Manage your subscription plan and payment details.
        </p>

        {/* Current Plan Card */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 16,
            padding: "28px",
            marginBottom: 20,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              marginBottom: 20,
            }}
          >
            <div>
              <div
                style={{
                  fontSize: 11,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--text-muted)",
                  marginBottom: 4,
                }}
              >
                Current Plan
              </div>
              <div
                style={{
                  fontSize: 22,
                  fontWeight: 800,
                  color: isFree ? "var(--text-muted)" : "var(--gold)",
                }}
              >
                {plan.name}
              </div>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 12px",
                borderRadius: 20,
                fontSize: 11,
                fontWeight: 600,
                textTransform: "capitalize",
                background:
                  sub.status === "active"
                    ? "rgba(34,197,94,0.12)"
                    : sub.status === "trialing"
                    ? "rgba(59,130,246,0.12)"
                    : "rgba(239,68,68,0.12)",
                color:
                  sub.status === "active"
                    ? "#22c55e"
                    : sub.status === "trialing"
                    ? "#3b82f6"
                    : "#ef4444",
              }}
            >
              {sub.status}
            </div>
          </div>

          {/* Details */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 13,
                color: "var(--text-muted)",
              }}
            >
              <span>Period end</span>
              <span style={{ color: "var(--text)" }}>{periodEnd}</span>
            </div>
            {isCanceled && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 14px",
                  borderRadius: 8,
                  background: "rgba(239,68,68,0.08)",
                  fontSize: 12,
                  color: "#ef4444",
                }}
              >
                <AlertTriangle size={14} />
                Your subscription is canceled. Access ends on {periodEnd}.
              </div>
            )}
          </div>

          {/* Actions */}
          <div
            style={{
              display: "flex",
              gap: 12,
              marginTop: 24,
              flexWrap: "wrap",
            }}
          >
            {isFree ? (
              <Link
                href="/pricing"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 24px",
                  borderRadius: 10,
                  background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
                  color: "#000",
                  fontWeight: 600,
                  fontSize: 13,
                  textDecoration: "none",
                }}
              >
                Upgrade Now
                <ArrowRight size={14} />
              </Link>
            ) : isCanceled ? (
              <Link
                href="/pricing"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 24px",
                  borderRadius: 10,
                  background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
                  color: "#000",
                  fontWeight: 600,
                  fontSize: 13,
                  textDecoration: "none",
                }}
              >
                Reactivate
                <ArrowRight size={14} />
              </Link>
            ) : (
              <button
                onClick={handleCancel}
                disabled={cancelling}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 24px",
                  borderRadius: 10,
                  border: "1px solid rgba(239,68,68,0.3)",
                  background: "transparent",
                  color: "#ef4444",
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: cancelling ? "not-allowed" : "pointer",
                }}
              >
                {cancelling ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Cancelling…
                  </>
                ) : (
                  "Cancel Subscription"
                )}
              </button>
            )}
          </div>
        </div>

        {/* Features */}
        {!isFree && (
          <div
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 16,
              padding: "28px",
              marginBottom: 20,
            }}
          >
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text)",
                marginBottom: 16,
              }}
            >
              Plan Features
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 10,
              }}
            >
              {plan.features.map((f) => (
                <div
                  key={f}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12,
                    color: "var(--text-muted)",
                  }}
                >
                  <Check size={12} color="var(--gold)" />
                  {f}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Payment Method placeholder */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 16,
            padding: "28px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 12,
            }}
          >
            <CreditCard size={18} color="var(--gold)" />
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text)",
              }}
            >
              Payment Method
            </div>
          </div>
          <p
            style={{
              fontSize: 12,
              color: "var(--text-muted)",
              lineHeight: 1.5,
            }}
          >
            No payment method saved yet. You will be prompted to add one when
            your free trial ends or when you upgrade.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function BillingPage() {
  return (
    <AuthProvider>
      <CurrentPlan />
    </AuthProvider>
  );
}