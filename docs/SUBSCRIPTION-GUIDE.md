# ApplyLoop — Subscription & Tools Guide

What you need (and what you don't) to use ApplyLoop.

---

## For Users (Clients)

You only need a Google account and a resume. Everything else runs on our infrastructure.

| What | Required? | Cost | Purpose |
|------|-----------|------|---------|
| **ApplyLoop Account** | Yes | Free or paid tier (DM for pricing) | The app itself |
| **Google Account** | Yes | Free | Sign in with Google OAuth |
| **Resume (PDF)** | Yes | Free | Uploaded during onboarding |
| **Telegram App** | Recommended | Free | Real-time notifications when applications are submitted |

### Optional Tools

| Tool | Purpose | Cost |
|------|---------|------|
| **AgentMail** | Disposable email inboxes for ATS email verification | Free (3 inboxes, 3K emails/mo) |
| **Himalaya CLI** | Read Gmail from terminal for security codes (self-hosted users) | Free |

### You do NOT need:
- OpenClaw, Claude Code, or any AI subscriptions
- A VPS or server
- Any API keys
- Technical knowledge beyond basic web browsing

---

## Pricing Tiers

| Tier | Daily Application Limit | Features |
|------|------------------------|----------|
| **Free** | 5 per day | Manual approval of each job, Greenhouse only |
| **Starter** | 25 per day | Auto-apply, all ATS platforms (Greenhouse, Ashby, Lever, SmartRecruiters), Telegram notifications |
| **Pro** | 50 per day | Everything in Starter + Gmail verification code reading, priority queue |

> **Pricing:** DM for current pricing — we offer flexible plans based on your needs.

All tiers include:
- Unlimited job discovery (new jobs surfaced every 6 hours)
- Application history with screenshots
- Profile and preference management
- Multiple resume support with smart routing

---

## For Operators (Self-Hosting)

If you want to run your own ApplyLoop instance, here's what you need:

| Service | Required? | Cost | Purpose |
|---------|-----------|------|---------|
| **Hetzner VPS** (CX21) | Yes | $18/mo | Runs Python worker + job scanner |
| **OpenClaw Pro** | Yes | $20/mo | Browser automation engine (`openclaw browser` commands) |
| **Supabase** | Yes | Free tier | PostgreSQL database, auth, file storage |
| **Vercel** | Yes | Free tier | Hosts the Next.js web app |
| **Google Cloud Console** | Yes | Free | OAuth credentials for "Sign in with Google" |
| **Domain** (optional) | No | ~$12/yr | Custom domain instead of `*.vercel.app` |
| **Stripe** (optional) | No | Free + 2.9% per txn | Only if charging users |
| **Telegram Bot** (optional) | No | Free | Create via @BotFather for notifications |
| **OpenAI API** (optional) | No | ~$5-15/mo | Only if using OpenAI models in OpenClaw config |
| **Upstash Redis** (optional) | No | Free tier | Rate limiting (can use in-memory fallback) |
| **AgentMail** (optional) | No | Free tier | Disposable inboxes for ATS email verification |
| **Himalaya CLI** (optional) | No | Free | Gmail reading from terminal for security codes |

### Monthly Cost Breakdown (Operator)

| Item | Cost |
|------|------|
| Hetzner CX21 (2 vCPU, 4 GB RAM) | $18 |
| OpenClaw Pro subscription | $20 |
| Supabase (free tier) | $0 |
| Vercel (free tier) | $0 |
| Upstash Redis (free tier) | $0 |
| Domain (optional) | ~$1 |
| OpenAI API (optional) | ~$5-15 |
| **Total** | **~$38-54/mo** |

### Why OpenClaw Pro?

OpenClaw is the browser automation engine that fills out job application forms. The worker calls these commands:

- `openclaw browser navigate` — open application URLs
- `openclaw browser snapshot` — capture page state for field detection
- `openclaw browser fill` — fill text fields
- `openclaw browser click` — click buttons and dropdowns
- `openclaw browser upload` — upload resume files
- `openclaw browser screenshot` — capture proof of submission

The Pro plan ($20/mo) is required for the `browser` command family and the `gateway` service.

### What About Claude Code?

Claude Code is **not needed for running ApplyLoop**. It's only used during development. The worker interacts with OpenClaw CLI directly — no AI API calls are made at runtime from the worker itself.
