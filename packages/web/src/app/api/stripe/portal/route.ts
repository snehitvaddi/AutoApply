import { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiError } from "@/lib/api-response";
import { getStripe } from "@/lib/stripe";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const { data: user } = await supabase
    .from("users")
    .select("stripe_customer_id")
    .eq("id", auth.userId)
    .single();

  if (!user?.stripe_customer_id) {
    return apiError("not_found", "No billing account found");
  }

  const stripe = getStripe();
  const appUrl = process.env.NEXT_PUBLIC_APP_URL!;

  const session = await stripe.billingPortal.sessions.create({
    customer: user.stripe_customer_id,
    return_url: `${appUrl}/settings`,
  });

  return NextResponse.redirect(session.url);
}
