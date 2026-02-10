# AI Concierge — Deployment Guide

## Overview

This guide deploys the AI Concierge backend to **Railway** (recommended for POC).  
Once deployed, you'll have a live public URL like `https://ai-concierge-production.up.railway.app`.

**Total time: ~15 minutes.**

---

## Prerequisites

Before starting, you need:

1. **GitHub account** — [github.com](https://github.com) (free)
2. **Railway account** — [railway.app](https://railway.app) (sign up with GitHub, free $5 credit)
3. **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com) (sign up, $5 free credit)
4. **Git installed** on your computer — [git-scm.com](https://git-scm.com/downloads)

---

## Step 1: Push Code to GitHub

Open your terminal (Mac: Terminal app, Windows: Git Bash or PowerShell):

```bash
# 1. Create a folder and copy your project files into it
mkdir ai-concierge && cd ai-concierge

# 2. Initialize git
git init

# 3. Copy these files into the folder:
#    - app.py
#    - requirements.txt
#    - Dockerfile
#    - Procfile
#    - railway.toml
#    - .gitignore
#    - .env.example
#    - data/vamos-events/config.json
#    - data/vamos-events/training.json

# 4. Add and commit
git add .
git commit -m "Initial deploy — AI Concierge"

# 5. Create repo on GitHub
#    Go to github.com → New Repository → Name it "ai-concierge" → Create
#    Then push:
git remote add origin https://github.com/YOUR_USERNAME/ai-concierge.git
git branch -M main
git push -u origin main
```

---

## Step 2: Deploy to Railway

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **"New Project"**
3. Select **"Deploy from GitHub Repo"**
4. Find and select your `ai-concierge` repository
5. Railway will auto-detect the Dockerfile and start building

### Add Environment Variables

While it's building, click on the service → **Variables** tab → Add these:

| Variable | Value |
|----------|-------|
| `ANTHROPIC_API_KEY` | Your key from console.anthropic.com |
| `DATA_DIR` | `/app/data` |
| `PORT` | `8000` |

Optional (add later):
| Variable | Value |
|----------|-------|
| `SLACK_WEBHOOK_URL` | Your Slack webhook |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### Generate a Public URL

1. Click on the service → **Settings** tab
2. Under **Networking** → **Public Networking**
3. Click **"Generate Domain"**
4. Railway gives you a URL like: `https://ai-concierge-production.up.railway.app`

### Verify It's Working

Visit: `https://YOUR-URL.up.railway.app/api/health`

You should see:
```json
{
  "status": "ok",
  "api_configured": true,
  "data_dir": "/app/data",
  "agents": ["vamos-events"]
}
```

---

## Step 3: Test the API

Test the chat endpoint (replace YOUR-URL):

```bash
curl -X POST https://YOUR-URL.up.railway.app/api/chat \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "vamos-events", "message": "Hi, I am planning a wedding!", "source": "website"}'
```

You should get a JSON response with the AI's reply, a session_id, and lead_status.

### Other Useful Endpoints

```bash
# List all leads
curl https://YOUR-URL.up.railway.app/api/agents/vamos-events/leads

# View agent config
curl https://YOUR-URL.up.railway.app/api/agents/vamos-events/config

# Preview the system prompt (debug — see exactly what the AI receives)
curl https://YOUR-URL.up.railway.app/api/agents/vamos-events/prompt-preview

# View training data
curl https://YOUR-URL.up.railway.app/api/agents/vamos-events/training
```

---

## Step 4: Connect the Frontend

### Option A: Replace contact page (simplest)

Your friend changes his "Contact Us" or "Inquire" link to point to your hosted chat page.  
The frontend chat page needs to be configured to call your Railway backend URL.

In the frontend code, set:
```javascript
const API_BASE = "https://YOUR-URL.up.railway.app";
const AGENT_ID = "vamos-events";
```

The frontend can be hosted on:
- **Vercel** (free) — best for React/Next.js
- **Netlify** (free) — drag-and-drop HTML
- **Railway** (same project) — add a second service
- **GitHub Pages** (free) — static HTML

### Option B: Embed chat widget

Add to any website:
```html
<script src="https://YOUR-FRONTEND-URL/widget.js" data-agent="vamos-events"></script>
```

---

## Step 5: Set Up Telegram Notifications (Optional, 10 min)

This gives your friend instant lead alerts on his phone.

1. Open Telegram → search for **@BotFather**
2. Send `/newbot`
3. Name it: `Vamos Events Leads` (or anything)
4. Username: `vamos_leads_bot` (must be unique and end in "bot")
5. BotFather gives you a **token** — copy it
6. Send any message to your new bot (this starts the chat)
7. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
8. Find the `chat.id` number in the response
9. Add to Railway environment variables:
   - `TELEGRAM_BOT_TOKEN` = the token from step 5
   - `TELEGRAM_CHAT_ID` = the chat ID from step 8

Now your friend gets notifications like:
```
✅ Vamos Events — Lead qualified
Name: Sarah Mitchell
Event: Wedding
Score: 85/100
Quote: $7,500–$11,000
Preferred: Tues 2pm, Thurs 10am
```

---

## Step 6: Set Up Slack Notifications (Alternative, 5 min)

1. Go to [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks)
2. Create a Slack App → Add Incoming Webhooks → Create webhook for a channel
3. Copy the webhook URL
4. Add to Railway: `SLACK_WEBHOOK_URL` = the webhook URL

---

## Persistent Data (Important for Production)

Railway's filesystem resets on each deploy. For the POC this is fine since the seed data gets re-loaded on startup. But for production with real leads, you need persistent storage.

### Quick fix: Railway Volume
1. In Railway, click your service → **Volumes** tab
2. Add a volume, mount path: `/app/data`
3. Your leads and config now persist across deploys

### Production fix: Database
Replace the file-based DataStore with PostgreSQL. Railway has a one-click Postgres add-on.

---

## Updating the Agent

### Add a new business rule
```bash
curl -X POST https://YOUR-URL.up.railway.app/api/agents/vamos-events/training \
  -H "Content-Type: application/json" \
  -d '{
    "type": "rule",
    "data": {"rule": "Always mention our 5-star Google rating when discussing why clients choose us"}
  }'
```

### Add an FAQ
```bash
curl -X POST https://YOUR-URL.up.railway.app/api/agents/vamos-events/training \
  -H "Content-Type: application/json" \
  -d '{
    "type": "faq",
    "data": {
      "question": "What is your cancellation policy?",
      "answer": "We require a 50% deposit to secure your date. Cancellations more than 60 days out receive a full refund minus a $250 administrative fee. Within 60 days, the deposit is non-refundable."
    }
  }'
```

### Add a correction
```bash
curl -X POST https://YOUR-URL.up.railway.app/api/agents/vamos-events/training \
  -H "Content-Type: application/json" \
  -d '{
    "type": "correction",
    "data": {
      "situation": "When someone asks about our Greek/Middle Eastern music selection",
      "wrong": "Giving a generic answer about being genre-versatile",
      "correction": "Specifically mention that we have DJs who specialize in Greek, Arabic, and Persian music with extensive libraries. Mention live percussion and dabke options."
    }
  }'
```

---

## Alternative: Deploy to Render

If Railway doesn't work for you:

1. Go to [render.com](https://render.com) → New Web Service
2. Connect your GitHub repo
3. Settings:
   - Runtime: Docker
   - Instance type: Free or Starter ($7/mo)
4. Add environment variables (same as Railway)
5. Deploy

---

## Alternative: Deploy to Fly.io

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Launch (from your project directory)
fly launch --name ai-concierge

# Set secrets
fly secrets set ANTHROPIC_API_KEY=your_key_here
fly secrets set DATA_DIR=/app/data

# Deploy
fly deploy
```

---

## Cost Summary

| Component | Cost |
|-----------|------|
| Railway hosting | $5/month (after free tier) |
| Anthropic API | ~$5–15/month (200-600 conversations) |
| Telegram notifications | Free |
| Domain (optional) | $12/year |
| **Total** | **~$10–20/month** |

---

## Troubleshooting

**"Agent not found" error**: The seed data didn't load. Check that `data/vamos-events/config.json` exists in your repo.

**Empty API responses**: Check Railway logs (click service → **Deployments** → **View Logs**). Look for `Claude API error` messages. Usually means the API key is wrong or missing.

**CORS errors in browser**: The backend allows all origins (`*`) for POC. In production, restrict to your frontend domain.

**Railway build fails**: Make sure `Dockerfile`, `requirements.txt`, and `app.py` are all in the repo root (not in a subdirectory).
