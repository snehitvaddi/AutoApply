import { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { getStripe, TIERS } from "@/lib/stripe";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

const TIER_LIMITS: Record<string, { tier: string; dailyLimit: number }> = {
  free: { tier: "free", dailyLimit: TIERS.free.dailyLimit },
  starter: { tier: "starter", dailyLimit: TIERS.starter.dailyLimit },
  pro: { tier: "pro", dailyLimit: TIERS.pro.dailyLimit },
};

async function updateUserTier(
  customerId: string,
  tier: string,
  subscriptionFields?: {
    stripe_subscription_id?: string;
    subscription_status?: string;
    subscription_current_period_end?: string | null;
  }
) {
  const limits = TIER_LIMITS[tier] || TIER_LIMITS.free;
  await supabase
    .from("users")
    .update({
      tier: limits.tier,
      daily_apply_limit: limits.dailyLimit,
      ...subscriptionFields,
    })
    .eq("stripe_customer_id", customerId);
}

function tierFromPriceId(priceId: string): string {
  if (priceId === TIERS.starter.priceId) return "starter";
  if (priceId === TIERS.pro.priceId) return "pro";
  return "free";
}

export async function POST(request: NextRequest) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature");

  if (!signature) {
    return NextResponse.json({ error: "Missing signature" }, { status: 400 });
  }

  const stripe = getStripe();

  let event;
  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch {
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object;
      if (session.subscription && session.customer) {
        const sub = await stripe.subscriptions.retrieve(
          session.subscription as string
        );
        const priceId = sub.items.data[0]?.price.id;
        const tier = tierFromPriceId(priceId);
        const periodEnd = (sub as unknown as { current_period_end: number }).current_period_end;
        await updateUserTier(session.customer as string, tier, {
          stripe_subscription_id: sub.id,
          subscription_status: sub.status,
          subscription_current_period_end: periodEnd ? new Date(periodEnd * 1000).toISOString() : null,
        });
      }
      break;
    }

    case "customer.subscription.updated": {
      const sub = event.data.object;
      const priceId = sub.items.data[0]?.price.id;
      const tier = tierFromPriceId(priceId);
      const periodEnd = (sub as unknown as { current_period_end: number }).current_period_end;
      await updateUserTier(sub.customer as string, tier, {
        stripe_subscription_id: sub.id,
        subscription_status: sub.status,
        subscription_current_period_end: periodEnd ? new Date(periodEnd * 1000).toISOString() : null,
      });
      break;
    }

    case "customer.subscription.deleted": {
      const sub = event.data.object;
      await updateUserTier(sub.customer as string, "free", {
        subscription_status: "cancelled",
        subscription_current_period_end: null,
      });
      break;
    }

    case "invoice.payment_failed": {
      // Keep current tier but could notify user
      break;
    }
  }

  return NextResponse.json({ received: true });
}
