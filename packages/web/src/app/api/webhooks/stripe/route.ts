/**
 * Stripe webhook — PLACEHOLDER (Phase 5).
 *
 * Right now this endpoint only logs incoming webhooks. When we turn on paid
 * self-service signups, fill in:
 *   1. Verify the signature with STRIPE_WEBHOOK_SECRET (using the `stripe` SDK
 *      that's already in package.json).
 *   2. Handle `checkout.session.completed` → set users.approval_status='approved'
 *      → create a row in `activation_codes` → DM the code to the user via Telegram.
 *   3. Handle `customer.subscription.deleted` → revoke worker token for that user.
 *   4. Insert a row into `payments` table for every successful charge.
 *
 * Environment variables to add later:
 *   - STRIPE_SECRET_KEY
 *   - STRIPE_WEBHOOK_SECRET
 */
import { NextRequest } from "next/server";
import { apiSuccess } from "@/lib/api-response";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature") || "";

  console.log("[stripe-webhook placeholder]", {
    sig_present: Boolean(signature),
    body_bytes: body.length,
    ts: new Date().toISOString(),
  });

  // TODO: verify signature, dispatch on event.type, persist to `payments` table.
  return apiSuccess({ received: true, placeholder: true });
}

// Stripe pings this endpoint with GET sometimes during setup — respond 200 OK.
export async function GET() {
  return apiSuccess({ ok: true, placeholder: true });
}
