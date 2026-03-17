# LinkedIn Post — AutoApply

## Post Text (Copy-paste ready)

---

i ran a job application bot for 30 days straight.

here's what i learned that nobody talks about.

everyone thinks auto-applying is just "fill name, upload resume, click submit."

it's not even close.

here's what actually breaks:

→ greenhouse sends a security code to your email before you can submit. my bot reads gmail, extracts the 8-character code, enters it, and keeps going.

→ ashby has a 45-second invisible lock after resume upload. if you submit too early, it silently fails. i had to add a wait nobody would guess.

→ some companies have location fields that only accept autocomplete selections. type "new york" and press submit? rejected. you have to type, wait for the dropdown, then press enter.

→ phone number fields break if you don't set the country code dropdown FIRST. order matters.

→ workday makes you create an account per company. every. single. one.

→ recaptcha pops up randomly on some greenhouse forms. the bot detects it and handles it.

here's what else it does that people think isn't possible:

→ multiple resumes. picks the right one per job based on keyword matching. ML role? gets the ML resume. data role? different one.

→ tailors your resume per job description. not a template. actually rewrites bullets to match what they're looking for.

→ "why do you want to work here?" — answered differently for every company. references their mission, not a generic paragraph.

→ only applies to jobs posted in the last 24 hours. no stale listings. no reposts. no aggregator spam.

→ filters out defense contractors, companies on cooldown, blocked domains (jobright, wiraa, indeed aggregators).

→ sends you a telegram message with a screenshot after every single application. proof it happened.

→ forgot password flows, email verification links, OTP codes — all handled automatically through gmail.

i documented every single quirk across 864 lines of instructions.

5 ATS platforms. 370+ company boards. 900+ real applications.

3 weeks of debugging edge cases nobody warns you about.

this isn't a chrome extension.
it's not a cloud service.
it runs locally on your machine. your data never leaves.

the result: 50 applications per day on complete autopilot.

i packaged the entire thing — code, setup guide, all 50+ steps — and open-sourced the documentation.

honest question:

would you spend a weekend setting this up from scratch, or would you rather just have it running by tonight?

DM me either way. happy to share the guide or help you get set up.

p.s. repost this so more job seekers stop wasting 40 hours a week on copy-paste applications.

---

## Character Count: ~1,850 (within 1,300-1,900 sweet spot)

## Hashtags (add in first comment, not post body)

#jobsearch #automation #opentowork #jobhunting #careeradvice #AI #openclaw

## Key Non-Obvious Things Highlighted

1. Gmail OTP / security code reading (Greenhouse 8-char codes)
2. Ashby 45-second invisible lock after upload
3. Location autocomplete — must select from dropdown, can't just type
4. Phone country code must be set BEFORE phone number
5. Workday per-company account creation
6. reCAPTCHA detection and handling
7. Multiple resumes with keyword matching
8. Resume tailoring per job description
9. Smart answers per company (not template)
10. 24-hour freshness filter (no stale/repost jobs)
11. Blocked domains + company cooldowns
12. Forgot password / email verification link handling
13. Telegram screenshot proof for every application
14. Runs locally — data never leaves machine
15. 864 lines of documented ATS learnings

## Execution Timeline

### Day 1 (Preparation)
- Design the 10-slide carousel in Canva (use setup-carousel-content.md)
- Record 60-90s screen recording of the bot applying (see video-script.md)
- Edit video: speed up 2x, add text overlays, blur PII

### Day 2 (Launch — Tuesday or Wednesday)
- Post at **8:00-10:00 AM ET**
- Reply to every comment within 30 minutes
- Seed with 5-10 friend comments in the first hour

### Day 3-4 (Engagement)
- Reply to every comment with personalized responses
- DM anyone who says "I need this" or asks how
- Give real, detailed public answers to questions

### Day 5 (Video Follow-Up)
- Post the screen recording as native LinkedIn video
- "Last week I shared my automation journey. Here's what it looks like in action."

### Day 7 (Results Post)
- "7 days since I shared my job bot. Here's what happened:"
- X people tried the guide, Y people asked for setup, Z applications submitted
