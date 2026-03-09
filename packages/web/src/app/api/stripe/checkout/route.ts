import { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiError } from "@/lib/api-response";
import { getStripe, TIERS, Tier } from "@/lib/stripe";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const tier = request.nextUrl.searchParams.get("tier") as Tier | null;

  if (!tier || !["starter", "pro"].includes(tier)) {
    return apiError("validation_error", "tier must be 'starter' or 'pro'");
  }

  const priceId = TIERS[tier].priceId;
  if (!priceId) {
    return apiError("validation_error", "Invalid tier configuration");
  }

  const stripe = getStripe();

  // Get or create Stripe customer
  const { data: user } = await supabase
    .from("users")
    .select("stripe_customer_id, email")
    .eq("id", auth.userId)
    .single();

  let customerId = user?.stripe_customer_id;

  if (!customerId) {
    const customer = await stripe.customers.create({
      email: user?.email || auth.email,
      metadata: { user_id: auth.userId },
    });
    customerId = customer.id;

    await supabase
      .from("users")
      .update({ stripe_customer_id: customerId })
      .eq("id", auth.userId);
  }

  const appUrl = process.env.NEXT_PUBLIC_APP_URL!;
  const session = await stripe.checkout.sessions.create({
    customer: customerId,
    mode: "subscription",
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${appUrl}/settings?checkout=success`,
    cancel_url: `${appUrl}/settings?checkout=cancelled`,
    metadata: { user_id: auth.userId },
  });

  return NextResponse.redirect(session.url!);
}
