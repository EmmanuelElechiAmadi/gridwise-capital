"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, X, ArrowRight } from "lucide-react";
import { SUBSCRIPTION_PLANS, getPlan } from "@/types";
import type { SubscriptionTier } from "@/types";

/**
 * Landing page pricing section.
 * Can also be embedded as a standalone pricing /plans block.
 */
export default function PricingSection() {
  const [annual, setAnnual] = useState(false);

  return (
    <section id="pricing" className="section-padding bg-black relative overflow-hidden">
      {/* Background accents */}
      <div className="absolute top-1/3 right-0 w-[400px] h-[400px] bg-amber-500/5 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/3 left-0 w-[300px] h-[300px] bg-amber-500/3 rounded-full blur-[100px] pointer-events-none" />

      <div className="max-w-7xl mx-auto px-6 relative z-10">
        {/* Section header */}
        <div className="text-center max-w-2xl mx-auto mb-16">
          <span className="inline-block text-xs uppercase tracking-[0.2em] text-amber-400/80 font-medium mb-4">
            Pricing
          </span>
          <h2 className="text-3xl md:text-5xl font-bold mb-4">
            Choose Your{" "}
            <span className="bg-gradient-to-r from-amber-200 via-amber-400 to-amber-500 bg-clip-text text-transparent">
              Trading Plan
            </span>
          </h2>
          <p className="text-zinc-400 text-sm md:text-base leading-relaxed">
            Start with a 7-day free trial. Upgrade anytime. No hidden fees.
          </p>
        </div>

        {/* Toggle */}
        <div className="flex items-center justify-center gap-4 mb-12">
          <span
            className={`text-sm font-medium transition-colors ${
              !annual ? "text-zinc-100" : "text-zinc-500"
            }`}
          >
            Monthly
          </span>
          <button
            onClick={() => setAnnual(!annual)}
            className={`relative w-14 h-7 rounded-full transition-colors ${
              annual ? "bg-amber-500" : "bg-zinc-700"
            }`}
          >
            <div
              className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-all shadow-sm ${
                annual ? "left-8" : "left-1"
              }`}
            />
          </button>
          <span
            className={`text-sm font-medium transition-colors ${
              annual ? "text-zinc-100" : "text-zinc-500"
            }`}
          >
            Annual{" "}
            <span className="text-amber-400 text-xs">(save ~17%)</span>
          </span>
        </div>

        {/* Cards */}
        <div className="grid md:grid-cols-4 gap-6 items-start">
          {SUBSCRIPTION_PLANS.map((plan) => {
            const isFree = plan.id === "free";
            const isEnterprise = plan.id === "enterprise";
            const price = annual && plan.priceYearly
              ? plan.priceYearly
              : plan.price;
            const periodLabel = annual ? "year" : "month";

            return (
              <div
                key={plan.id}
                className={`relative rounded-2xl border transition-all duration-300 flex flex-col ${
                  plan.highlighted
                    ? "border-amber-500/40 bg-gradient-to-b from-amber-500/10 to-zinc-900 shadow-xl shadow-amber-500/10 scale-[1.02]"
                    : "border-zinc-800 bg-zinc-900/60 hover:border-zinc-700"
                }`}
              >
                {/* Badge */}
                {plan.badge && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="inline-block px-4 py-1 text-xs font-semibold tracking-wide text-black bg-gradient-to-r from-amber-400 to-amber-500 rounded-full shadow-lg">
                      {plan.badge}
                    </span>
                  </div>
                )}

                <div className="p-6 flex-1 flex flex-col">
                  {/* Header */}
                  <div className="mb-6">
                    <h3 className="text-lg font-bold text-zinc-100">
                      {plan.name}
                    </h3>
                    <p className="text-xs text-zinc-400 mt-1">
                      {plan.description}
                    </p>
                    <div className="mt-4 flex items-baseline gap-1">
                      {isEnterprise ? (
                        <span className="text-3xl font-bold text-zinc-100">
                          Custom
                        </span>
                      ) : (
                        <>
                          <span className="text-4xl font-bold text-zinc-100">
                            ${isFree ? "0" : price}
                          </span>
                          <span className="text-sm text-zinc-500">
                            /{periodLabel}
                          </span>
                        </>
                      )}
                    </div>
                    {!isFree && !isEnterprise && annual && (
                      <p className="text-xs text-amber-400/80 mt-1">
                        ${plan.price}/mo if paid monthly
                      </p>
                    )}
                  </div>

                  {/* Features */}
                  <ul className="space-y-3 mb-8 flex-1">
                    {plan.features.map((feat) => (
                      <li
                        key={feat}
                        className="flex items-start gap-3 text-sm text-zinc-300"
                      >
                        <Check
                          size={16}
                          className="text-amber-400 mt-0.5 shrink-0"
                        />
                        <span>{feat}</span>
                      </li>
                    ))}
                  </ul>

                  {/* CTA */}
                  {isEnterprise ? (
                    <Link
                      href="/contact"
                      className="w-full text-center py-3 rounded-xl border border-zinc-700 text-sm font-medium text-zinc-300 hover:bg-zinc-800 transition-all"
                    >
                      {plan.cta}
                    </Link>
                  ) : isFree ? (
                    <Link
                      href="/signup"
                      className="w-full text-center py-3 rounded-xl border border-zinc-700 text-sm font-medium text-zinc-300 hover:bg-zinc-800 transition-all"
                    >
                      {plan.cta}
                    </Link>
                  ) : (
                    <Link
                      href={`/checkout?plan=${plan.id}&billing=${
                        annual ? "annual" : "monthly"
                      }`}
                      className={`w-full text-center py-3 rounded-xl text-sm font-semibold transition-all flex items-center justify-center gap-2 ${
                        plan.highlighted
                          ? "bg-gradient-to-r from-amber-400 to-amber-500 text-black hover:from-amber-300 hover:to-amber-400 shadow-lg shadow-amber-500/20"
                          : "bg-zinc-800 text-zinc-200 hover:bg-zinc-700"
                      }`}
                    >
                      {plan.cta}
                      <ArrowRight size={14} />
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer note */}
        <p className="text-center text-xs text-zinc-600 mt-10">
          All plans include a 7-day free trial. Cancel anytime.
          Enterprise plans are custom-priced based on requirements.
        </p>
      </div>
    </section>
  );
}