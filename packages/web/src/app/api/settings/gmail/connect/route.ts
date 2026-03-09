import { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { authenticateRequest, isAuthError } from "@/lib/auth";
import { apiError } from "@/lib/api-response";
import crypto from "crypto";

export async function GET(request: NextRequest) {
  const auth = await authenticateRequest(request);
  if (isAuthError(auth)) return apiError("unauthorized");

  const clientId = process.env.GOOGLE_CLIENT_ID!;
  const redirectUri = `${process.env.NEXT_PUBLIC_APP_URL}/api/settings/gmail/callback`;
  const scope = encodeURIComponent(
    "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
  );

  // State is a random nonce for CSRF protection only — user identity comes from cookies on callback
  const state = crypto.randomBytes(16).toString("hex");

  const url =
    `https://accounts.google.com/o/oauth2/v2/auth` +
    `?client_id=${clientId}` +
    `&redirect_uri=${encodeURIComponent(redirectUri)}` +
    `&response_type=code` +
    `&scope=${scope}` +
    `&access_type=offline` +
    `&prompt=consent` +
    `&state=${state}`;

  return NextResponse.redirect(url);
}
