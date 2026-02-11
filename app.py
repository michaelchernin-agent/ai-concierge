"""
AI Concierge — Production Backend
===================================
Multi-tenant AI lead qualification platform.

Endpoints:
  POST /api/chat                        — Prospect sends message, gets AI response
  GET  /api/agents/{agent_id}/leads     — List leads for a business
  GET  /api/agents/{agent_id}/leads/{id}— Full lead detail
  POST /api/agents/{agent_id}/leads/{id}/confirm  — Owner confirms meeting
  POST /api/agents/{agent_id}/leads/{id}/reject   — Owner suggests alt times
  GET  /api/agents/{agent_id}/config    — Get agent config (owner dashboard)
  PUT  /api/agents/{agent_id}/config    — Update agent config (agent studio)
  GET  /api/agents/{agent_id}/training  — Get training data (examples, corrections)
  POST /api/agents/{agent_id}/training  — Add training example or correction
  GET  /api/health                      — System health

Quick start:
  pip install -r requirements.txt
  cp .env.example .env  # add your ANTHROPIC_API_KEY
  python -m uvicorn app:app --reload --port 8000
"""

import json
import os
import uuid
import asyncio
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Concierge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


# ---------------------------------------------------------------------------
# Data Layer (file-based for POC — swap for Postgres in production)
# ---------------------------------------------------------------------------
class DataStore:
    """Simple file-based JSON store. Each agent gets a directory."""

    def __init__(self, base_dir: Path):
        self.base = base_dir

    def _agent_dir(self, agent_id: str) -> Path:
        d = self.base / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- Agent Config ---
    def get_config(self, agent_id: str) -> dict:
        path = self._agent_dir(agent_id) / "config.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_config(self, agent_id: str, config: dict):
        path = self._agent_dir(agent_id) / "config.json"
        path.write_text(json.dumps(config, indent=2, default=str))

    # --- Leads ---
    def get_leads(self, agent_id: str) -> list:
        path = self._agent_dir(agent_id) / "leads.json"
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def save_leads(self, agent_id: str, leads: list):
        path = self._agent_dir(agent_id) / "leads.json"
        path.write_text(json.dumps(leads, indent=2, default=str))

    def get_lead(self, agent_id: str, lead_id: str) -> dict:
        leads = self.get_leads(agent_id)
        return next((l for l in leads if l["id"] == lead_id), None)

    def upsert_lead(self, agent_id: str, lead: dict):
        leads = self.get_leads(agent_id)
        idx = next((i for i, l in enumerate(leads) if l["id"] == lead["id"]), None)
        if idx is not None:
            leads[idx] = lead
        else:
            leads.append(lead)
        self.save_leads(agent_id, leads)

    # --- Training Data ---
    def get_training(self, agent_id: str) -> dict:
        path = self._agent_dir(agent_id) / "training.json"
        if not path.exists():
            return {"examples": [], "corrections": [], "rules": [], "faq": []}
        return json.loads(path.read_text())

    def save_training(self, agent_id: str, training: dict):
        path = self._agent_dir(agent_id) / "training.json"
        path.write_text(json.dumps(training, indent=2, default=str))


db = DataStore(DATA_DIR)


# ---------------------------------------------------------------------------
# System Prompt Builder — THE CORE ENGINE
# This dynamically generates the AI's personality, knowledge, and behavior
# from the business config + training data. This is what owners "tune."
# ---------------------------------------------------------------------------
def build_system_prompt(agent_id: str) -> str:
    config = db.get_config(agent_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    training = db.get_training(agent_id)
    biz = config.get("business", {})
    pricing = config.get("pricing", {})
    qual = config.get("qualification", {})
    booking = config.get("booking", {})
    services = config.get("services", [])

    # --- Tone mapping ---
    tone_instructions = {
        "luxury": "You are warm, polished, and refined — like a luxury hospitality concierge. Confident but never pushy. Premium but approachable.",
        "professional": "You are professional, knowledgeable, and efficient. Friendly but business-focused. Clear and direct.",
        "friendly": "You are upbeat, warm, and genuinely enthusiastic. Like a helpful friend who happens to be an expert.",
        "casual": "You are relaxed, conversational, and approachable. Keep things light and easy. No corporate-speak.",
        "warm": "You are caring, empathetic, and attentive. You listen deeply and respond thoughtfully. Personal and genuine.",
        "bold": "You are confident, energetic, and memorable. You make a strong impression. Dynamic and direct.",
    }
    tone = tone_instructions.get(biz.get("tone", "professional"), tone_instructions["professional"])

    # --- Build services section ---
    services_text = ""
    if services:
        services_text = "## SERVICES OFFERED\n"
        for svc in services:
            name = svc.get("name", "")
            desc = svc.get("description", "")
            price = svc.get("price_display", "")
            services_text += f"- **{name}**"
            if desc:
                services_text += f" — {desc}"
            if price:
                services_text += f" (approximately {price})"
            services_text += "\n"

    # --- Build qualification rules ---
    qual_text = "## QUALIFICATION CRITERIA\n"
    min_budgets = qual.get("minimum_budgets", {})
    if min_budgets:
        qual_text += "Minimum budgets by event type:\n"
        for etype, amount in min_budgets.items():
            qual_text += f"- {etype.title()}: ${amount:,}\n"
    elif qual.get("minimum_budget"):
        qual_text += f"Minimum budget: ${qual['minimum_budget']:,}\n"

    if qual.get("service_areas"):
        qual_text += f"Service areas: {', '.join(qual['service_areas'])}\n"
    if qual.get("advance_booking_days"):
        qual_text += f"Minimum advance booking: {qual['advance_booking_days']} days\n"

    # --- Build custom rules from training ---
    custom_rules = ""
    if training.get("rules"):
        custom_rules = "## CUSTOM BUSINESS RULES\n"
        custom_rules += "The business owner has specified these rules. Follow them precisely:\n"
        for rule in training["rules"]:
            custom_rules += f"- {rule['rule']}\n"

    # --- Build FAQ from training ---
    faq_text = ""
    if training.get("faq"):
        faq_text = "## FREQUENTLY ASKED QUESTIONS\n"
        faq_text += "When prospects ask these questions, use these owner-approved answers:\n\n"
        for item in training["faq"]:
            faq_text += f"Q: {item['question']}\nA: {item['answer']}\n\n"

    # --- Build example conversations from training ---
    examples_text = ""
    if training.get("examples"):
        examples_text = "## EXAMPLE INTERACTIONS (follow these patterns)\n"
        for ex in training["examples"][:5]:  # Limit to 5 to save tokens
            examples_text += f"Scenario: {ex['scenario']}\n"
            examples_text += f"Good response: {ex['good_response']}\n"
            if ex.get("bad_response"):
                examples_text += f"Avoid: {ex['bad_response']}\n"
            examples_text += "\n"

    # --- Build corrections from training ---
    corrections_text = ""
    if training.get("corrections"):
        corrections_text = "## CORRECTIONS FROM OWNER\n"
        corrections_text += "The business owner has corrected these specific behaviors. Adjust accordingly:\n"
        for corr in training["corrections"][-10:]:  # Last 10 corrections
            corrections_text += f"- When: {corr['situation']}\n"
            corrections_text += f"  Instead of: {corr.get('wrong', 'N/A')}\n"
            corrections_text += f"  Do this: {corr['correction']}\n\n"

    # --- Booking instructions ---
    booking_text = "## BOOKING FLOW\n"
    owner_name = biz.get("owner_name", biz.get("name", "our team"))
    if booking.get("mode") == "auto_book":
        booking_text += "When a lead is qualified and interested, check calendar availability and book directly.\n"
    else:
        booking_text += f"""When a lead is qualified and interested:
1. Express genuine excitement about working together
2. Collect name, email, and optionally phone if not already provided
3. Ask for 2-3 preferred consultation time slots
4. Available: {', '.join(booking.get('available_days', ['weekdays']))} {booking.get('available_hours', {}).get('start', '10:00')}-{booking.get('available_hours', {}).get('end', '18:00')} {booking.get('timezone', 'ET')}
5. Explain that {owner_name} will personally confirm within 24 hours
6. Do NOT confirm a specific time yourself\n"""

    # --- Assemble full prompt ---
    prompt = f"""You are the AI concierge for {biz.get('name', 'this business')}. {biz.get('about', '')}

## YOUR PERSONALITY
{tone}
Keep messages concise: 2-4 sentences per response unless explaining services in detail.
Ask ONE question at a time. Build naturally on the prospect's responses.

## CONVERSATION FLOW
The prospect has just watched a personal video introduction from {owner_name}.
Your first message should warmly reference the video and transition into discovery.

Flow:
1. Warm handoff from video — reference {owner_name} and what they said
2. Ask what kind of event/project they're planning
3. Date and location
4. Guest count / scope
5. Which services interest them
6. Budget range (frame naturally)
7. If qualified: quote range + offer consultation
8. Collect contact info + preferred times
9. If not qualified: graceful redirect

{services_text}

## PRICING
Currency: {pricing.get('currency', 'CAD')}
{json.dumps(pricing.get('baseline_rates', {}), indent=2) if pricing.get('baseline_rates') else ''}
{json.dumps(pricing.get('event_type_ranges', {}), indent=2) if pricing.get('event_type_ranges') else ''}

Always quote RANGES. Always say approximate. Final pricing after consultation.

{qual_text}

## HANDLING DISQUALIFICATION
Never dismissive. Always:
1. Thank them genuinely
2. Acknowledge their event sounds wonderful
3. Be honest that premium services may not fit their current budget
4. Frame as wanting to deliver the full experience
5. Wish them well

{booking_text}

{custom_rules}

{faq_text}

{examples_text}

{corrections_text}

## RESPONSE FORMAT
Respond with a JSON object:
{{
  "message": "Your response to the prospect",
  "collected_data": {{"field": "value collected this turn"}},
  "lead_status": "gathering_info|qualified|disqualified|meeting_requested|pending_confirmation",
  "qualification_score": 0-100,
  "qualification_notes": "Internal note",
  "suggested_quote_range": null or [min, max],
  "ready_to_book": false,
  "preferred_times": null or ["slot1", "slot2"]
}}
"""
    return prompt


# ---------------------------------------------------------------------------
# AI Agent
# ---------------------------------------------------------------------------
async def call_agent(agent_id: str, lead: dict, user_message: str) -> dict:
    system_prompt = build_system_prompt(agent_id)

    if not client:
        # Demo mode
        return {
            "message": f"Thanks for reaching out! I'd love to learn about your event. What are you planning?",
            "collected_data": {},
            "lead_status": "gathering_info",
            "qualification_score": 10,
            "qualification_notes": "Demo mode",
            "suggested_quote_range": None,
            "ready_to_book": False,
            "preferred_times": None,
        }

    # Build messages
    messages = []
    for msg in lead.get("messages", []):
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add context
    context = ""
    if lead.get("collected_data"):
        context = f"[SYSTEM: Data collected so far: {json.dumps(lead['collected_data'])}]\n\n"
    messages.append({"role": "user", "content": context + user_message})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        raw = response.content[0].text.strip()

        # Parse JSON
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "message": raw,
                "collected_data": {},
                "lead_status": lead.get("lead_status", "gathering_info"),
                "qualification_score": lead.get("qualification_score", 0),
                "qualification_notes": "JSON parse failed",
                "suggested_quote_range": None,
                "ready_to_book": False,
                "preferred_times": None,
            }
    except Exception as e:
        print(f"Claude API error: {e}")
        return {
            "message": "I appreciate your patience! Could you try that again?",
            "collected_data": {},
            "lead_status": lead.get("lead_status", "gathering_info"),
            "qualification_score": lead.get("qualification_score", 0),
            "qualification_notes": f"Error: {str(e)}",
            "suggested_quote_range": None,
            "ready_to_book": False,
            "preferred_times": None,
        }


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
async def notify_owner(agent_id: str, lead: dict, event: str):
    config = db.get_config(agent_id)
    if not config:
        return
    integrations = config.get("integrations", {})

    data = lead.get("collected_data", {})
    status = lead.get("lead_status", "unknown")
    score = lead.get("qualification_score", 0)
    quote = lead.get("suggested_quote_range")

    emoji = {"gathering_info": "📝", "qualified": "✅", "disqualified": "❌",
             "meeting_requested": "📅", "pending_confirmation": "⏳", "meeting_confirmed": "🎉"}.get(status, "📋")

    lines = [
        f"{emoji} *{config['business']['name']} — {event}*",
        f"Name: {data.get('contact_name', data.get('name', 'Unknown'))}",
        f"Event: {data.get('event_type', 'N/A')}",
        f"Score: {score}/100 | Status: {status.replace('_', ' ').title()}",
    ]
    if quote:
        lines.append(f"Quote: ${quote[0]:,}–${quote[1]:,}")
    if lead.get("preferred_times"):
        lines.append(f"Preferred: {', '.join(lead['preferred_times'])}")

    text = "\n".join(lines)

    async with httpx.AsyncClient() as http:
        # Slack
        webhook = integrations.get("slack", {}).get("webhook_url")
        if webhook:
            try:
                await http.post(webhook, json={"text": text})
            except Exception as e:
                print(f"Slack error: {e}")

        # Telegram
        tg = integrations.get("telegram", {})
        if tg.get("bot_token") and tg.get("chat_id"):
            try:
                await http.post(
                    f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                    json={"chat_id": tg["chat_id"], "text": text, "parse_mode": "Markdown"},
                )
            except Exception as e:
                print(f"Telegram error: {e}")


# ---------------------------------------------------------------------------
# Email — Confirmation emails to prospects
# ---------------------------------------------------------------------------
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "")


async def send_confirmation_email(config: dict, lead: dict, confirmed_time: str, note: str = None):
    """Send a branded confirmation email to the prospect."""
    biz = config.get("business", {})
    biz_name = biz.get("name", "Our Team")
    owner_name = biz.get("owner_name", biz_name)
    biz_email = biz.get("email", "")
    biz_phone = biz.get("phone", "")
    biz_website = biz.get("website", "")
    primary_color = config.get("appearance", {}).get("primary_color", "#C8A96E")

    data = lead.get("collected_data", {})
    prospect_name = data.get("contact_name", data.get("name", "there"))
    prospect_email = data.get("email")
    event_type = data.get("event_type", "your event")
    quote = lead.get("suggested_quote_range")

    if not prospect_email:
        print("[EMAIL] No prospect email found, skipping")
        return

    subject = f"Your Consultation with {biz_name} is Confirmed! ✨"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0A0A;padding:40px 20px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:16px;overflow:hidden;border:1px solid #2A2A2A;">
      <!-- Header -->
      <tr><td style="background:linear-gradient(135deg,{primary_color},#A68B4B);padding:40px 40px 32px;text-align:center;">
        <h1 style="margin:0;font-size:28px;color:#0A0A0A;font-weight:700;letter-spacing:1px;">{biz_name}</h1>
        <p style="margin:8px 0 0;font-size:14px;color:rgba(10,10,10,0.7);">Consultation Confirmed</p>
      </td></tr>
      <!-- Body -->
      <tr><td style="padding:40px;">
        <p style="font-size:16px;color:#F5F0E8;line-height:1.7;margin:0 0 24px;">
          Hi {prospect_name},
        </p>
        <p style="font-size:15px;color:#B0A898;line-height:1.7;margin:0 0 32px;">
          Great news! {owner_name} has confirmed your consultation. We're looking forward to discussing {event_type} with you and creating something truly unforgettable.
        </p>

        <!-- Appointment Card -->
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1E1E1E;border-radius:12px;border:1px solid #2A2A2A;margin:0 0 32px;">
          <tr><td style="padding:28px;">
            <p style="font-size:11px;font-weight:700;color:#706A60;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px;">📅 Your Consultation</p>
            <p style="font-size:20px;font-weight:700;color:{primary_color};margin:0 0 8px;">{confirmed_time}</p>
            <p style="font-size:14px;color:#B0A898;margin:0 0 4px;">Type: Personal consultation for {event_type}</p>
            <p style="font-size:14px;color:#B0A898;margin:0;">Duration: ~30 minutes</p>
            {f'<p style="font-size:14px;color:#B0A898;margin:8px 0 0;">Note: {note}</p>' if note else ''}
          </td></tr>
        </table>

        {f'''<table width="100%" cellpadding="0" cellspacing="0" style="background:#1E1E1E;border-radius:12px;border:1px solid #2A2A2A;margin:0 0 32px;">
          <tr><td style="padding:28px;">
            <p style="font-size:11px;font-weight:700;color:#706A60;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px;">💰 Estimated Range</p>
            <p style="font-size:20px;font-weight:700;color:{primary_color};margin:0;">${quote[0]:,} – ${quote[1]:,} CAD</p>
            <p style="font-size:13px;color:#706A60;margin:8px 0 0;">Final pricing confirmed after consultation</p>
          </td></tr>
        </table>''' if quote else ''}

        <p style="font-size:15px;color:#B0A898;line-height:1.7;margin:0 0 32px;">
          If you need to reschedule, please don't hesitate to reach out. We're flexible and want to make this as easy as possible for you.
        </p>

        <!-- Contact Info -->
        <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #2A2A2A;padding-top:24px;">
          <tr><td style="padding-top:24px;">
            <p style="font-size:11px;font-weight:700;color:#706A60;text-transform:uppercase;letter-spacing:2px;margin:0 0 12px;">Get in Touch</p>
            {f'<p style="font-size:14px;color:#B0A898;margin:0 0 4px;">📧 {biz_email}</p>' if biz_email else ''}
            {f'<p style="font-size:14px;color:#B0A898;margin:0 0 4px;">📱 {biz_phone}</p>' if biz_phone else ''}
            {f'<p style="font-size:14px;color:#B0A898;margin:0;">🌐 {biz_website}</p>' if biz_website else ''}
          </td></tr>
        </table>
      </td></tr>
      <!-- Footer -->
      <tr><td style="background:#0A0A0A;padding:24px 40px;text-align:center;border-top:1px solid #2A2A2A;">
        <p style="font-size:12px;color:#706A60;margin:0;">© {datetime.now().year} {biz_name} · Powered by AI Concierge</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

    # Send via SMTP
    if not SMTP_USER or not SMTP_PASS:
        print(f"[EMAIL] SMTP not configured. Would send to {prospect_email}:")
        print(f"[EMAIL] Subject: {subject}")
        print(f"[EMAIL] Confirmed time: {confirmed_time}")
        # Store email in lead for dashboard preview
        lead["confirmation_email"] = {
            "to": prospect_email,
            "subject": subject,
            "confirmed_time": confirmed_time,
            "sent": False,
            "html": html,
        }
        db.upsert_lead(config.get("_agent_id", ""), lead)
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME or biz_name} <{SMTP_USER}>"
        msg["To"] = prospect_email
        msg["Reply-To"] = biz_email or SMTP_USER

        plain = f"""Hi {prospect_name},

Your consultation with {biz_name} has been confirmed!

Date & Time: {confirmed_time}
Type: Personal consultation for {event_type}
Duration: ~30 minutes
{f"Note: {note}" if note else ""}
{f"Estimated range: ${quote[0]:,} - ${quote[1]:,} CAD" if quote else ""}

If you need to reschedule, please reach out:
{f"Email: {biz_email}" if biz_email else ""}
{f"Phone: {biz_phone}" if biz_phone else ""}

Looking forward to creating something unforgettable!
— {owner_name}"""

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        print(f"[EMAIL] Confirmation sent to {prospect_email}")

        lead["confirmation_email"] = {
            "to": prospect_email,
            "subject": subject,
            "confirmed_time": confirmed_time,
            "sent": True,
        }
        db.upsert_lead(config.get("_agent_id", ""), lead)

    except Exception as e:
        print(f"[EMAIL] Error sending: {e}")


# ---------------------------------------------------------------------------
# Email preview endpoint (for dashboard demo)
# ---------------------------------------------------------------------------
@app.get("/api/agents/{agent_id}/leads/{lead_id}/email-preview")
async def email_preview(agent_id: str, lead_id: str):
    """Preview the confirmation email HTML (for demo purposes)."""
    lead = db.get_lead(agent_id, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    config = db.get_config(agent_id)
    if not config:
        raise HTTPException(404, "Agent not found")

    from fastapi.responses import HTMLResponse
    # Generate preview
    biz = config.get("business", {})
    data = lead.get("collected_data", {})
    confirmed_time = lead.get("confirmed_time", "Tuesday, March 4th at 2:00 PM ET")
    prospect_name = data.get("contact_name", data.get("name", "there"))
    event_type = data.get("event_type", "your event")
    quote = lead.get("suggested_quote_range")
    primary_color = config.get("appearance", {}).get("primary_color", "#C8A96E")
    biz_name = biz.get("name", "")
    owner_name = biz.get("owner_name", biz_name)
    note = lead.get("confirmation_note", "")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0A0A;padding:40px 20px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:16px;overflow:hidden;border:1px solid #2A2A2A;">
      <tr><td style="background:linear-gradient(135deg,{primary_color},#A68B4B);padding:40px 40px 32px;text-align:center;">
        <h1 style="margin:0;font-size:28px;color:#0A0A0A;font-weight:700;">{biz_name}</h1>
        <p style="margin:8px 0 0;font-size:14px;color:rgba(10,10,10,0.7);">Consultation Confirmed</p>
      </td></tr>
      <tr><td style="padding:40px;">
        <p style="font-size:16px;color:#F5F0E8;line-height:1.7;margin:0 0 24px;">Hi {prospect_name},</p>
        <p style="font-size:15px;color:#B0A898;line-height:1.7;margin:0 0 32px;">
          Great news! {owner_name} has confirmed your consultation. We're looking forward to discussing {event_type} with you.
        </p>
        <table width="100%" style="background:#1E1E1E;border-radius:12px;border:1px solid #2A2A2A;margin:0 0 32px;">
          <tr><td style="padding:28px;">
            <p style="font-size:11px;font-weight:700;color:#706A60;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px;">📅 Your Consultation</p>
            <p style="font-size:20px;font-weight:700;color:{primary_color};margin:0 0 8px;">{confirmed_time}</p>
            <p style="font-size:14px;color:#B0A898;margin:0;">Duration: ~30 minutes</p>
            {f'<p style="font-size:14px;color:#B0A898;margin:8px 0 0;">Note: {note}</p>' if note else ''}
          </td></tr>
        </table>
        {f'<table width="100%" style="background:#1E1E1E;border-radius:12px;border:1px solid #2A2A2A;margin:0 0 32px;"><tr><td style="padding:28px;"><p style="font-size:11px;font-weight:700;color:#706A60;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px;">💰 Estimated Range</p><p style="font-size:20px;font-weight:700;color:{primary_color};margin:0;">${quote[0]:,} – ${quote[1]:,} CAD</p></td></tr></table>' if quote else ''}
        <p style="font-size:15px;color:#B0A898;line-height:1.7;margin:0 0 32px;">If you need to reschedule, please reach out anytime.</p>
      </td></tr>
      <tr><td style="background:#0A0A0A;padding:24px 40px;text-align:center;border-top:1px solid #2A2A2A;">
        <p style="font-size:12px;color:#706A60;margin:0;">© {datetime.now().year} {biz_name} · Powered by AI Concierge</p>
      </td></tr>
    </table>
  </td></tr>
</table></body></html>"""
    return HTMLResponse(content=html)
class ChatRequest(BaseModel):
    agent_id: str
    session_id: Optional[str] = None
    message: str
    source: str = "website"

class ChatResponse(BaseModel):
    session_id: str
    message: str
    lead_status: str
    qualification_score: int
    suggested_quote_range: Optional[list] = None
    ready_to_book: bool

class ConfirmRequest(BaseModel):
    confirmed_time: str
    note: Optional[str] = None

class RejectRequest(BaseModel):
    alternative_times: Optional[List[str]] = None
    reason: Optional[str] = None

class TrainingExample(BaseModel):
    type: str  # "example" | "correction" | "rule" | "faq"
    data: Dict[str, Any]

class ConfigUpdate(BaseModel):
    config: Dict[str, Any]


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

# --- Chat ---
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    config = db.get_config(req.agent_id)
    if not config:
        raise HTTPException(404, f"Agent '{req.agent_id}' not found")

    # Get or create lead
    session_id = req.session_id or str(uuid.uuid4())
    lead = db.get_lead(req.agent_id, session_id)
    if not lead:
        lead = {
            "id": session_id,
            "source": req.source,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "messages": [],
            "collected_data": {},
            "lead_status": "new",
            "qualification_score": 0,
            "qualification_notes": "",
            "suggested_quote_range": None,
            "ready_to_book": False,
            "preferred_times": None,
        }

    # Call AI
    resp = await call_agent(req.agent_id, lead, req.message)

    # Update lead
    lead["messages"].append({"role": "user", "content": req.message, "ts": datetime.now(timezone.utc).isoformat()})
    lead["messages"].append({"role": "assistant", "content": resp["message"], "ts": datetime.now(timezone.utc).isoformat()})

    if resp.get("collected_data"):
        lead["collected_data"].update(resp["collected_data"])

    prev_status = lead["lead_status"]
    lead["lead_status"] = resp.get("lead_status", lead["lead_status"])
    lead["qualification_score"] = resp.get("qualification_score", lead["qualification_score"])
    lead["qualification_notes"] = resp.get("qualification_notes", "")
    lead["suggested_quote_range"] = resp.get("suggested_quote_range") or lead["suggested_quote_range"]
    lead["ready_to_book"] = resp.get("ready_to_book", False)
    lead["updated_at"] = datetime.now(timezone.utc).isoformat()
    if resp.get("preferred_times"):
        lead["preferred_times"] = resp["preferred_times"]

    db.upsert_lead(req.agent_id, lead)

    # Notify on status change
    if lead["lead_status"] != prev_status:
        asyncio.create_task(notify_owner(req.agent_id, lead, f"Lead {lead['lead_status'].replace('_', ' ')}"))

    return ChatResponse(
        session_id=session_id,
        message=resp["message"],
        lead_status=lead["lead_status"],
        qualification_score=lead["qualification_score"],
        suggested_quote_range=lead["suggested_quote_range"],
        ready_to_book=lead["ready_to_book"],
    )


# --- Leads ---
@app.get("/api/agents/{agent_id}/leads")
async def list_leads(agent_id: str):
    leads = db.get_leads(agent_id)
    # Return summary (no full messages)
    summaries = []
    for l in leads:
        s = {k: v for k, v in l.items() if k != "messages"}
        s["message_count"] = len(l.get("messages", []))
        summaries.append(s)
    summaries.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"leads": summaries, "total": len(summaries)}

@app.get("/api/agents/{agent_id}/leads/{lead_id}")
async def get_lead(agent_id: str, lead_id: str):
    lead = db.get_lead(agent_id, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead

@app.post("/api/agents/{agent_id}/leads/{lead_id}/confirm")
async def confirm_meeting(agent_id: str, lead_id: str, req: ConfirmRequest):
    lead = db.get_lead(agent_id, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead["confirmed_time"] = req.confirmed_time
    lead["confirmation_note"] = req.note
    lead["lead_status"] = "meeting_confirmed"
    lead["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.upsert_lead(agent_id, lead)

    # Send confirmation email to prospect
    config = db.get_config(agent_id)
    prospect_email = lead.get("collected_data", {}).get("email")
    if prospect_email and config:
        asyncio.create_task(send_confirmation_email(
            config=config,
            lead=lead,
            confirmed_time=req.confirmed_time,
            note=req.note,
        ))

    return {"status": "confirmed", "confirmed_time": req.confirmed_time, "email_sent": bool(prospect_email)}

@app.post("/api/agents/{agent_id}/leads/{lead_id}/reject")
async def reject_meeting(agent_id: str, lead_id: str, req: RejectRequest):
    lead = db.get_lead(agent_id, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead["lead_status"] = "meeting_requested"
    lead["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.upsert_lead(agent_id, lead)
    return {"status": "alternatives_sent", "times": req.alternative_times}


# --- Agent Config (for owner dashboard / agent studio) ---
@app.get("/api/agents/{agent_id}/config")
async def get_config(agent_id: str):
    config = db.get_config(agent_id)
    if not config:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return config

@app.put("/api/agents/{agent_id}/config")
async def update_config(agent_id: str, req: ConfigUpdate):
    existing = db.get_config(agent_id)
    if existing:
        # Deep merge
        def merge(base, update):
            for k, v in update.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    merge(base[k], v)
                else:
                    base[k] = v
            return base
        config = merge(existing, req.config)
    else:
        config = req.config
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.save_config(agent_id, config)
    return {"status": "updated", "agent_id": agent_id}

@app.post("/api/agents/{agent_id}/config")
async def create_agent(agent_id: str, req: ConfigUpdate):
    if db.get_config(agent_id):
        raise HTTPException(409, f"Agent '{agent_id}' already exists")
    config = req.config
    config["created_at"] = datetime.now(timezone.utc).isoformat()
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.save_config(agent_id, config)
    return {"status": "created", "agent_id": agent_id}


# --- Training Data (Agent Studio) ---
@app.get("/api/agents/{agent_id}/training")
async def get_training(agent_id: str):
    return db.get_training(agent_id)

@app.post("/api/agents/{agent_id}/training")
async def add_training(agent_id: str, req: TrainingExample):
    training = db.get_training(agent_id)

    item = {**req.data, "added_at": datetime.now(timezone.utc).isoformat()}

    if req.type == "example":
        training["examples"].append(item)
    elif req.type == "correction":
        training["corrections"].append(item)
    elif req.type == "rule":
        training["rules"].append(item)
    elif req.type == "faq":
        training["faq"].append(item)
    else:
        raise HTTPException(400, f"Unknown training type: {req.type}")

    db.save_training(agent_id, training)
    return {"status": "added", "type": req.type, "total": len(training[req.type + "s"] if req.type != "faq" else training["faq"])}

@app.delete("/api/agents/{agent_id}/training/{training_type}/{index}")
async def delete_training(agent_id: str, training_type: str, index: int):
    training = db.get_training(agent_id)
    key = training_type + "s" if training_type != "faq" else "faq"
    if key not in training or index >= len(training[key]):
        raise HTTPException(404, "Training item not found")
    training[key].pop(index)
    db.save_training(agent_id, training)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# WhatsApp Cloud API Webhooks
# ---------------------------------------------------------------------------
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "concierge-verify-token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# Agent ID mapping: which WhatsApp number maps to which agent
# In production, this would be a DB lookup. For POC, use env var.
WHATSAPP_AGENT_ID = os.getenv("WHATSAPP_AGENT_ID", "vamos-events")


@app.get("/api/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification (Meta sends GET to verify your endpoint)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print(f"[WHATSAPP] Webhook verified")
        return int(challenge)
    raise HTTPException(403, "Verification failed")


@app.post("/api/webhook/whatsapp")
async def whatsapp_incoming(request: Request):
    """Receive incoming WhatsApp messages and respond via AI agent."""
    body = await request.json()

    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "no_messages"}

        msg = messages[0]
        sender = msg.get("from", "")  # Phone number (e.g. "14165551234")
        msg_type = msg.get("type", "")

        # Only handle text messages for now
        if msg_type != "text":
            # Send a polite reply for non-text messages
            await whatsapp_send(sender, "Thanks for reaching out! I work best with text messages. Could you type out what you're looking for? 😊")
            return {"status": "non_text_skipped"}

        text = msg["text"]["body"]
        print(f"[WHATSAPP] Message from {sender}: {text[:100]}")

        # Use phone number as session ID for WhatsApp (conversations persist per number)
        session_id = f"wa-{sender}"
        agent_id = WHATSAPP_AGENT_ID

        # Get or create lead
        lead = db.get_lead(agent_id, session_id)
        is_new = lead is None
        if not lead:
            lead = {
                "id": session_id,
                "source": "whatsapp",
                "phone": sender,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "messages": [],
                "collected_data": {"phone": sender},
                "lead_status": "new",
                "qualification_score": 0,
                "qualification_notes": "",
                "suggested_quote_range": None,
                "ready_to_book": False,
                "preferred_times": None,
            }

        # If new conversation, optionally send video first
        # (WhatsApp supports sending video messages via the API)
        config = db.get_config(agent_id)
        if is_new and config:
            video_url = config.get("business", {}).get("video_url")
            if video_url:
                await whatsapp_send_video(sender, video_url, 
                    f"👋 Welcome to {config['business']['name']}! Watch this quick personal intro from our team.")

        # Call AI agent
        resp = await call_agent(agent_id, lead, text)

        # Update lead
        lead["messages"].append({"role": "user", "content": text, "ts": datetime.now(timezone.utc).isoformat()})
        lead["messages"].append({"role": "assistant", "content": resp["message"], "ts": datetime.now(timezone.utc).isoformat()})
        if resp.get("collected_data"):
            lead["collected_data"].update(resp["collected_data"])
        prev_status = lead["lead_status"]
        lead["lead_status"] = resp.get("lead_status", lead["lead_status"])
        lead["qualification_score"] = resp.get("qualification_score", lead["qualification_score"])
        lead["qualification_notes"] = resp.get("qualification_notes", "")
        lead["suggested_quote_range"] = resp.get("suggested_quote_range") or lead["suggested_quote_range"]
        lead["ready_to_book"] = resp.get("ready_to_book", False)
        lead["updated_at"] = datetime.now(timezone.utc).isoformat()
        if resp.get("preferred_times"):
            lead["preferred_times"] = resp["preferred_times"]
        db.upsert_lead(agent_id, lead)

        # Notify owner on status change
        if lead["lead_status"] != prev_status:
            asyncio.create_task(notify_owner(agent_id, lead, f"WhatsApp lead {lead['lead_status'].replace('_', ' ')}"))

        # Send AI response back via WhatsApp
        await whatsapp_send(sender, resp["message"])
        return {"status": "replied"}

    except Exception as e:
        print(f"[WHATSAPP] Error processing webhook: {e}")
        return {"status": "error", "detail": str(e)}


async def whatsapp_send(to: str, text: str):
    """Send a text message via WhatsApp Cloud API."""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print(f"[WHATSAPP] Would send to {to}: {text[:80]}...")
        return

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    async with httpx.AsyncClient() as http:
        try:
            r = await http.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                print(f"[WHATSAPP] Send error: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[WHATSAPP] Send exception: {e}")


async def whatsapp_send_video(to: str, video_url: str, caption: str = ""):
    """Send a video message via WhatsApp Cloud API."""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print(f"[WHATSAPP] Would send video to {to}: {video_url}")
        return

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "video",
        "video": {"link": video_url, "caption": caption}
    }
    async with httpx.AsyncClient() as http:
        try:
            await http.post(url, headers=headers, json=payload)
        except Exception as e:
            print(f"[WHATSAPP] Video send exception: {e}")


# ---------------------------------------------------------------------------
# Instagram Messaging API Webhooks
# ---------------------------------------------------------------------------
INSTAGRAM_VERIFY_TOKEN = os.getenv("INSTAGRAM_VERIFY_TOKEN", "concierge-verify-token")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_AGENT_ID = os.getenv("INSTAGRAM_AGENT_ID", "vamos-events")


@app.get("/api/webhook/instagram")
async def instagram_verify(request: Request):
    """Instagram webhook verification."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == INSTAGRAM_VERIFY_TOKEN:
        print(f"[INSTAGRAM] Webhook verified")
        return int(challenge)
    raise HTTPException(403, "Verification failed")


@app.post("/api/webhook/instagram")
async def instagram_incoming(request: Request):
    """Receive incoming Instagram DMs and respond via AI agent."""
    body = await request.json()

    try:
        entry = body.get("entry", [{}])[0]
        messaging = entry.get("messaging", [])

        if not messaging:
            return {"status": "no_messages"}

        event = messaging[0]
        sender_id = event.get("sender", {}).get("id", "")
        recipient_id = event.get("recipient", {}).get("id", "")

        # Skip if it's our own message (echo)
        if event.get("message", {}).get("is_echo"):
            return {"status": "echo_skipped"}

        message = event.get("message", {})
        text = message.get("text", "")

        if not text:
            # Handle non-text (sticker, image, etc.)
            await instagram_send(sender_id, "Thanks for reaching out! Could you tell me a bit about what you're looking for? 😊")
            return {"status": "non_text_handled"}

        print(f"[INSTAGRAM] DM from {sender_id}: {text[:100]}")

        session_id = f"ig-{sender_id}"
        agent_id = INSTAGRAM_AGENT_ID

        # Get or create lead
        lead = db.get_lead(agent_id, session_id)
        if not lead:
            lead = {
                "id": session_id,
                "source": "instagram",
                "instagram_id": sender_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "messages": [],
                "collected_data": {},
                "lead_status": "new",
                "qualification_score": 0,
                "qualification_notes": "",
                "suggested_quote_range": None,
                "ready_to_book": False,
                "preferred_times": None,
            }

        # Call AI agent
        resp = await call_agent(agent_id, lead, text)

        # Update lead (same pattern as WhatsApp)
        lead["messages"].append({"role": "user", "content": text, "ts": datetime.now(timezone.utc).isoformat()})
        lead["messages"].append({"role": "assistant", "content": resp["message"], "ts": datetime.now(timezone.utc).isoformat()})
        if resp.get("collected_data"):
            lead["collected_data"].update(resp["collected_data"])
        prev_status = lead["lead_status"]
        lead["lead_status"] = resp.get("lead_status", lead["lead_status"])
        lead["qualification_score"] = resp.get("qualification_score", lead["qualification_score"])
        lead["qualification_notes"] = resp.get("qualification_notes", "")
        lead["suggested_quote_range"] = resp.get("suggested_quote_range") or lead["suggested_quote_range"]
        lead["ready_to_book"] = resp.get("ready_to_book", False)
        lead["updated_at"] = datetime.now(timezone.utc).isoformat()
        if resp.get("preferred_times"):
            lead["preferred_times"] = resp["preferred_times"]
        db.upsert_lead(agent_id, lead)

        if lead["lead_status"] != prev_status:
            asyncio.create_task(notify_owner(agent_id, lead, f"Instagram lead {lead['lead_status'].replace('_', ' ')}"))

        # Send reply via Instagram
        await instagram_send(sender_id, resp["message"])
        return {"status": "replied"}

    except Exception as e:
        print(f"[INSTAGRAM] Error: {e}")
        return {"status": "error", "detail": str(e)}


async def instagram_send(recipient_id: str, text: str):
    """Send a message via Instagram Messaging API."""
    if not INSTAGRAM_ACCESS_TOKEN:
        print(f"[INSTAGRAM] Would send to {recipient_id}: {text[:80]}...")
        return

    url = f"https://graph.facebook.com/v21.0/me/messages"
    headers = {"Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    async with httpx.AsyncClient() as http:
        try:
            r = await http.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                print(f"[INSTAGRAM] Send error: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[INSTAGRAM] Send exception: {e}")


# --- Debug: Preview system prompt ---
@app.get("/api/agents/{agent_id}/prompt-preview")
async def preview_prompt(agent_id: str):
    prompt = build_system_prompt(agent_id)
    return {"prompt": prompt, "token_estimate": len(prompt.split()) * 1.3}


# --- Health ---
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "api_configured": bool(ANTHROPIC_API_KEY),
        "data_dir": str(DATA_DIR),
        "agents": [d.name for d in DATA_DIR.iterdir() if d.is_dir()],
    }


@app.on_event("startup")
async def startup():
    """Seed Vamos Events config if not present."""
    if not db.get_config("vamos-events"):
        seed_config = Path(__file__).parent / "data" / "vamos-events" / "config.json"
        seed_training = Path(__file__).parent / "data" / "vamos-events" / "training.json"
        if seed_config.exists():
            db.save_config("vamos-events", json.loads(seed_config.read_text()))
            print("[STARTUP] Seeded vamos-events config")
        if seed_training.exists():
            db.save_training("vamos-events", json.loads(seed_training.read_text()))
            print("[STARTUP] Seeded vamos-events training data")
    agents = [d.name for d in DATA_DIR.iterdir() if d.is_dir()]
    print(f"[STARTUP] AI Concierge ready — {len(agents)} agent(s): {agents}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
