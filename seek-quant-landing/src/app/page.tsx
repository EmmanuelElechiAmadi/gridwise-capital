"use client";

import HeroSection from "@/components/HeroSection";
import StrategySection from "@/components/StrategySection";
import PerformanceSection from "@/components/PerformanceSection";
import PricingSection from "@/components/PricingSection";
import Footer from "@/components/Footer";
import { AuthProvider } from "@/lib/auth";

export default function HomePage() {
  return (
    <AuthProvider>
      <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <HeroSection />
        <StrategySection />
        <PerformanceSection />
        <PricingSection />
        <Footer />
      </main>
    </AuthProvider>
  );
}
