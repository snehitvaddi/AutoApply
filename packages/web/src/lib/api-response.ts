import { NextResponse } from "next/server";
import { createId } from "@paralleldrive/cuid2";

export const API_ERROR_CODES = {
  validation_error: { statusCode: 400, message: "Invalid request parameters" },
  unauthorized: { statusCode: 401, message: "Authentication required" },
  forbidden: { statusCode: 403, message: "Insufficient permissions" },
  not_found: { statusCode: 404, message: "Resource not found" },
  rate_limit_exceeded: { statusCode: 429, message: "Rate limit exceeded" },
  daily_limit_exceeded: { statusCode: 429, message: "Daily application limit reached" },
  conflict: { statusCode: 409, message: "Resource was modified by another client" },
  invite_invalid: { statusCode: 400, message: "Invalid or expired invite code" },
  max_users_reached: { statusCode: 403, message: "Maximum user limit reached" },
  internal_server_error: { statusCode: 500, message: "An unexpected error occurred" },
} as const;

export type ApiErrorCode = keyof typeof API_ERROR_CODES;

export function generateRequestId(): string {
  return `req_${createId()}`;
}

export function apiSuccess<T>(
  data: T,
  status: number = 200
): NextResponse {
  return NextResponse.json({ data }, {
    status,
    headers: { "X-Request-Id": generateRequestId() },
  });
}

export function apiError(
  code: ApiErrorCode,
  message?: string,
  details?: Record<string, unknown>
): NextResponse {
  const errorDef = API_ERROR_CODES[code];
  const body: Record<string, unknown> = {
    statusCode: errorDef.statusCode,
    name: code,
    message: message || errorDef.message,
  };
  if (details) body.details = details;

  return NextResponse.json(body, {
    status: errorDef.statusCode,
    headers: { "X-Request-Id": generateRequestId() },
  });
}

export function apiList<T>(data: T[], hasMore: boolean = false): NextResponse {
  return NextResponse.json(
    { object: "list" as const, data, has_more: hasMore },
    { status: 200, headers: { "X-Request-Id": generateRequestId() } }
  );
}
