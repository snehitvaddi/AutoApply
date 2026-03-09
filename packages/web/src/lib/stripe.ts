import Stripe from "stripe";

let stripeInstance: Stripe | null = null;

export function getStripe(): Stripe {
  if (!stripeInstance) {
    stripeInstance = new Stripe(process.env.STRIPE_SECRET_KEY!);
  }
  return stripeInstance;
}

export const TIERS = {
  free: { priceId: null, dailyLimit: 5, name: "Free" },
  starter: { priceId: process.env.STRIPE_STARTER_PRICE_ID, dailyLimit: 25, name: "Starter" },
  pro: { priceId: process.env.STRIPE_PRO_PRICE_ID, dailyLimit: 50, name: "Pro" },
} as const;

export type Tier = keyof typeof TIERS;
