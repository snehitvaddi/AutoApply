import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

const RATE_LIMITS = {
  free: { requests: 30, window: "1 m" as const },
  starter: { requests: 60, window: "1 m" as const },
  pro: { requests: 60, window: "1 m" as const },
} as const;

export type RateLimitTier = keyof typeof RATE_LIMITS;

export interface RateLimitResult {
  success: boolean;
  limit: number;
  remaining: number;
  reset: number;
}

let redis: Redis | null = null;
const rateLimiters: Map<string, Ratelimit> = new Map();

function getRedis(): Redis | null {
  if (redis) return redis;
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;
  redis = new Redis({ url, token });
  return redis;
}

function getRateLimiter(tier: RateLimitTier): Ratelimit | null {
  const existing = rateLimiters.get(tier);
  if (existing) return existing;
  const redisClient = getRedis();
  if (!redisClient) return null;
  const config = RATE_LIMITS[tier];
  const limiter = new Ratelimit({
    redis: redisClient,
    limiter: Ratelimit.slidingWindow(config.requests, config.window),
    prefix: `aa_ratelimit_${tier}`,
  });
  rateLimiters.set(tier, limiter);
  return limiter;
}

export async function checkRateLimit(
  userId: string,
  tier: RateLimitTier = "free"
): Promise<RateLimitResult> {
  const config = RATE_LIMITS[tier];
  const limiter = getRateLimiter(tier);
  if (!limiter) {
    return { success: true, limit: config.requests, remaining: config.requests, reset: 0 };
  }
  try {
    const result = await limiter.limit(userId);
    return {
      success: result.success,
      limit: result.limit,
      remaining: result.remaining,
      reset: Math.ceil((result.reset - Date.now()) / 1000),
    };
  } catch {
    return { success: true, limit: config.requests, remaining: config.requests, reset: 0 };
  }
}
