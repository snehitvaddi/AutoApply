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

## Gmail via Himalaya CLI

**Config:** `~/Library/Application Support/himalaya/config.toml`

### Commands
```bash
# List recent emails
himalaya envelope list --account gmail --folder INBOX --page-size 5 -o json

# Read email by ID
himalaya message read --account gmail --folder INBOX {id}

# Check spam
himalaya envelope list --account gmail --folder "[Gmail]/Spam" --page-size 5
```

### Use Cases
1. **Greenhouse security codes** — from `no-reply@us.greenhouse-mail.io`
   - Subject: "Security code for your application to {Company}"
   - 8-character alphanumeric code
2. **Workday password reset** — from `{company}@otp.workday.com`
   - Contains reset link
3. **ATS account verification** — various senders

### Flow
1. Submit application / create account → ATS sends email
2. Wait 10-15 seconds
3. List recent emails → find from ATS sender
4. Read email body → extract OTP code or verification link
5. Enter OTP or navigate to link in browser

---

## Gmail OAuth (SaaS — Per-User)

For the multi-user SaaS, each user connects their Gmail via OAuth:
1. User clicks "Connect Gmail" in Settings
2. Redirect to Google OAuth consent screen
3. User grants `gmail.readonly` scope
4. Store OAuth tokens encrypted in `gmail_tokens` table
5. Worker reads verification emails via Gmail API on behalf of user

**Search patterns:**
- Greenhouse: `from:no-reply@us.greenhouse-mail.io newer_than:5m`
- Workday: `from:otp.workday.com newer_than:5m`

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
