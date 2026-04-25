# Email Services — Verification Code Reading

## AgentMail (Disposable Inboxes)

**API:** `https://api.agentmail.to/v0`
**Python SDK:** `pip3 install agentmail` (v0.2.24)

### Create Inbox
```python
from agentmail import AgentMail
client = AgentMail(api_key=API_KEY)
inbox = client.inboxes.create()
email = inbox.inbox_id  # e.g., "clumsynews296@agentmail.to"
```

### Read Messages
```python
messages = client.inboxes.messages.list(inbox_id="user@agentmail.to")
# Or via REST:
# GET https://api.agentmail.to/v0/inboxes/{email}/messages
# Authorization: Bearer {API_KEY}
```

### Delete Inbox
```
DELETE https://api.agentmail.to/v0/inboxes/{id}
Authorization: Bearer {API_KEY}
```

### Free Tier Limits
- 3 inboxes max
- 3,000 emails/month
- Error: `LimitExceededError: Inbox limit exceeded` (HTTP 403)

### Known Issues
- LinkedIn may have blacklisted `agentmail.to` domain for verification emails
- Rotate inboxes by deleting old ones to free up slots

---

## Gmail via Himalaya CLI (Primary)

Himalaya is the unified email layer for reading OTPs and reset links.
No OAuth required — uses `gmail_email` + `gmail_app_password` from the profile.

**Gmail prerequisites:**
1. IMAP enabled (Gmail Settings → Forwarding and POP/IMAP → Enable IMAP)
2. 2FA on (myaccount.google.com/security)
3. App password at myaccount.google.com/apppasswords (16-char code)

**Config paths:**
- macOS: `~/Library/Application Support/himalaya/config.toml`
- Linux: `~/.config/himalaya/config.toml`

Config is **auto-written** by `himalaya_reader.ensure_configured(email, app_password)`
at apply time — no manual TOML editing needed. `install.sh` also writes it on setup.

### Python API (`packages/worker/himalaya_reader.py`)

```python
from himalaya_reader import ensure_configured, find_otp, find_link

ensure_configured(email, app_password)  # write config, returns bool

# Read an OTP code (polls up to timeout seconds)
code = find_otp("greenhouse-mail.io", subject_pattern="security code", timeout=60)

# Read a reset/verification link
link = find_link("workday", r"passwordreset", timeout=30)
```

### MCP Tools (for PTY Claude)

```
email_read_otp(sender_pattern, subject_pattern="", timeout=60)
  → "A1B2C3D4" or "error: ..."

email_read_link(sender_pattern, link_regex, timeout=60)
  → "https://..." or "error: ..."
```

### CLI Commands (used internally by himalaya_reader.py)

```bash
# List recent envelopes — JSON format
himalaya envelope list --account gmail --folder INBOX --page-size 10 --output json
# Returns: [{"id": "123", "from": {"addr": "no-reply@greenhouse-mail.io"}, "subject": "...", "date": "..."}]

# Read email body by ID
himalaya message read --account gmail --folder INBOX 123

# Check spam folder
himalaya envelope list --account gmail --folder "[Gmail]/Spam" --page-size 5 --output json
```

### Use Cases
1. **Greenhouse security codes** — from `greenhouse-mail.io`, subject "Security code"
   - 8-character alphanumeric code, entered character by character
2. **Workday password reset** — from `otp.workday.com` / `workday`
   - Contains `passwordreset` or `myworkdayjobs.com/reset` URL
3. **ATS account verification** — various senders; use `email_read_otp` MCP tool

---

## Gmail OAuth (Deprecated — SaaS-only)

> **Deprecated for local installs.** Only available to SaaS users who have
> completed the Gmail OAuth flow and have tokens in the `gmail_tokens` Supabase table.
> All new code uses `himalaya_reader.py` instead.

For the multi-user SaaS, each user connects their Gmail via OAuth:
1. User clicks "Connect Gmail" in Settings → Google OAuth consent screen
2. Tokens stored encrypted in `gmail_tokens` Supabase table
3. `gmail_reader.get_latest_verification_code(user_id, ...)` reads via Gmail API

The `gmail_reader.py` module is **kept** for AgentMail disposable inbox functions
and for any SaaS users who completed OAuth. No new code should import it for OTPs.

---

## ATS API Scouting (No Auth Required)

### Greenhouse Boards API
```
GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}
```
- 271+ boards, ~2-3 min per scan cycle
- Filter by `updated_at` within 24h
- Rate: ~10 req/s
- Apply URL: `https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}`

### Ashby API
```
GET https://api.ashbyhq.com/posting-api/job-board/{slug}
```
- 102-147 boards
- Returns: `publishedAt`, `updatedAt`, title, location, id

### Lever API (Mostly Dead)
```
GET https://api.lever.co/v0/postings/{company}?mode=json
```
- 75/82 companies return 404 (migrated off)
- Only ~7 still active: Spotify, Mistral, Plaid, Neon, Zilliz, Brilliant, Anyscale
