"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Check, ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { AuthProvider } from "@/lib/auth";
import { SUBSCRIPTION_PLANS, getPlan } from "@/types";
import type { SubscriptionTier } from "@/types";

function CheckoutForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, tier, refreshSubscription } = useAuth();

  const planId = (searchParams.get("plan") as SubscriptionTier) || "starter";
  const billing = searchParams.get("billing") || "monthly";
  const plan = getPlan(planId);

  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Redirect if not logged in
  useEffect(() => {
    if (!user && !loading) {
      router.push(`/login?redirect=/checkout?plan=${planId}&billing=${billing}`);
    }
  }, [user, router, planId, billing, loading]);

  const handleConfirm = async () => {
    setLoading(true);
    setError(null);

    // Simulate subscription activation
    await new Promise((r) => setTimeout(r, 1500));

    try {
      // In demo mode, save subscription to localStorage
      const subs = JSON.parse(localStorage.getItem("seekquant_subs") || "{}");
      const now = new Date();
      const end = new Date(now);
      end.setMonth(end.getMonth() + 1);
      subs[user!.id] = {
        tier: planId,
        status: "active" as const,
        currentPeriodStart: now.toISOString(),
        currentPeriodEnd: end.toISOString(),
      };
      localStorage.setItem("seekquant_subs", JSON.stringify(subs));

      await refreshSubscription();
      setSuccess(true);
    } catch (err) {
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg)",
          padding: 24,
        }}
      >
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 16,
            padding: "48px 40px",
            textAlign: "center",
            maxWidth: 420,
            width: "100%",
          }}
        >
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: "50%",
              background: "rgba(34, 197, 94, 0.15)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 20px",
            }}
          >
            <Check size={28} color="#22c55e" />
          </div>
          <h2
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: "var(--text)",
              marginBottom: 8,
            }}
          >
            Subscription Active!
          </h2>
          <p style={{ fontSize: 14, color: "var(--text-muted)", marginBottom: 24 }}>
            You are now on the <strong style={{ color: "var(--gold)" }}>{plan.name}</strong> plan.
            Welcome aboard.
          </p>
          <Link
            href="/dashboard"
            style={{
              display: "inline-block",
              padding: "12px 32px",
              borderRadius: 10,
              background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
              color: "#000",
              fontWeight: 600,
              fontSize: 14,
              textDecoration: "none",
            }}
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg)",
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

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        padding: "80px 24px 40px",
      }}
    >
      <div style={{ maxWidth: 520, margin: "0 auto" }}>
        <Link
          href="/pricing"
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
          Back to plans
        </Link>

        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 16,
            padding: "32px",
          }}
        >
          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: "var(--text)",
              marginBottom: 4,
            }}
          >
            Confirm Subscription
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-muted)",
              marginBottom: 28,
            }}
          >
            You are about to start the{" "}
            <strong style={{ color: "var(--gold)" }}>{plan.name}</strong> plan.
          </p>

          {/* Plan summary */}
          <div
            style={{
              background: "rgba(201,168,76,0.05)",
              border: "1px solid rgba(201,168,76,0.15)",
              borderRadius: 12,
              padding: "16px 20px",
              marginBottom: 24,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: 15,
                    color: "var(--text)",
                  }}
                >
                  {plan.name} Plan
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  {billing === "annual" ? "Annual" : "Monthly"} billing
                </div>
              </div>
              <div
                style={{
                  fontSize: 24,
                  fontWeight: 800,
                  color: "var(--gold)",
                }}
              >
                ${plan.price}
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  /{billing === "annual" ? "yr" : "mo"}
                </span>
              </div>
            </div>
          </div>

          {/* Features summary */}
          <div style={{ marginBottom: 28 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text)",
                marginBottom: 12,
              }}
            >
              What's included:
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 8,
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
                  <span>{f}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Confirm button */}
          {error && (
            <div
              style={{
                padding: "10px 16px",
                borderRadius: 8,
                background: "rgba(239,68,68,0.1)",
                border: "1px solid rgba(239,68,68,0.2)",
                fontSize: 12,
                color: "#ef4444",
                marginBottom: 16,
              }}
            >
              {error}
            </div>
          )}

          <button
            onClick={handleConfirm}
            disabled={loading}
            style={{
              width: "100%",
              padding: "14px 24px",
              borderRadius: 12,
              border: "none",
              background: loading
                ? "var(--border)"
                : "linear-gradient(135deg, #e8c97a, #c9a84c)",
              color: loading ? "var(--text-muted)" : "#000",
              fontWeight: 700,
              fontSize: 15,
              cursor: loading ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              transition: "opacity 0.2s",
            }}
          >
            {loading ? (
              <>
                <div
                  style={{
                    width: 16,
                    height: 16,
                    border: "2px solid currentColor",
                    borderTopColor: "transparent",
                    borderRadius: "50%",
                    animation: "spin 0.8s linear infinite",
                  }}
                />
                Processing…
              </>
            ) : (
              <>
                <ShieldCheck size={18} />
                Confirm & Activate
              </>
            )}
          </button>

          <p
            style={{
              textAlign: "center",
              fontSize: 11,
              color: "var(--text-muted)",
              marginTop: 16,
            }}
          >
            By confirming, you agree to our Terms of Service.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function CheckoutPage() {
  return (
    <AuthProvider>
      <Suspense
        fallback={
          <div
            style={{
              minHeight: "100vh",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--bg)",
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
        }
      >
        <CheckoutForm />
      </Suspense>
    </AuthProvider>
  );
}