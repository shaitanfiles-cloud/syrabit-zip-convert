"""
Transactional email helpers for Syrabit.ai using the Resend Python SDK.
All functions are fire-and-forget — they log warnings on failure and never raise.
"""
import os
import logging
import asyncio

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Syrabit.ai <noreply@syrabit.ai>").strip()

_BRAND = "#7c3aed"
_BG    = "#0d0d1a"
_CARD  = "#1e1b4b"
_MUTED = "#94a3b8"
_TEXT  = "#e2e8f0"
_BORDER = "#4c1d95"


def _base(body_html: str) -> str:
    return f"""
<div style="font-family:sans-serif;max-width:520px;margin:auto;padding:32px;
            background:{_BG};color:{_TEXT};border-radius:12px;">
  <div style="margin-bottom:24px;">
    <span style="font-size:20px;font-weight:700;color:{_BRAND};">Syrabit</span>
    <span style="font-size:20px;font-weight:700;color:{_TEXT};">.ai</span>
  </div>
  {body_html}
  <p style="color:#475569;font-size:11px;margin-top:32px;border-top:1px solid #1e293b;padding-top:16px;">
    You received this email because of account activity on Syrabit.ai.<br>
    Questions? Reply to this email or write to admin@syrabit.ai
  </p>
</div>
"""


def _card(content: str) -> str:
    return f"""<div style="background:{_CARD};border:1px solid {_BORDER};border-radius:8px;
                           padding:20px;margin-bottom:20px;">{content}</div>"""


def _button(label: str, url: str) -> str:
    return (f'<a href="{url}" style="display:inline-block;background:{_BRAND};color:white;'
            f'text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;'
            f'font-size:14px;">{label}</a>')


def _send_sync(to: str, subject: str, html: str):
    """Synchronous Resend API call — run in thread via asyncio.to_thread."""
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        logger.info(f"[Email] RESEND_API_KEY not set — skipping email to {to}: {subject}")
        return
    try:
        import resend as _resend
        _resend.api_key = key
        frm = os.environ.get("EMAIL_FROM", "Syrabit.ai <noreply@syrabit.ai>").strip()
        _resend.Emails.send({"from": frm, "to": [to], "subject": subject, "html": html})
        logger.info(f"[Email] Sent '{subject}' → {to}")
    except Exception as e:
        logger.warning(f"[Email] Send failed to {to}: {e}")


async def _send(to: str, subject: str, html: str):
    await asyncio.to_thread(_send_sync, to, subject, html)


async def send_plan_activation(email: str, name: str, plan: str, credits: int, amount_paise: int):
    """Confirmation email after a successful plan upgrade."""
    plan_cap = plan.capitalize()
    amount_inr = amount_paise / 100
    body = _base(f"""
      <h2 style="color:{_BRAND};margin:0 0 8px;">Welcome to {plan_cap}!</h2>
      <p style="color:{_MUTED};margin:0 0 24px;">
        Hi {name or 'there'}, your plan has been upgraded successfully.
      </p>
      {_card(f'''
        <table style="width:100%;border-collapse:collapse;">
          <tr><td style="color:{_MUTED};padding:6px 0;">Plan</td>
              <td style="text-align:right;font-weight:600;">{plan_cap}</td></tr>
          <tr><td style="color:{_MUTED};padding:6px 0;">Credits added</td>
              <td style="text-align:right;font-weight:600;color:{_BRAND};">+{credits:,}</td></tr>
          <tr><td style="color:{_MUTED};padding:6px 0;">Amount charged</td>
              <td style="text-align:right;font-weight:600;">₹{amount_inr:,.2f}</td></tr>
        </table>
      ''')}
      <p style="margin-bottom:24px;">
        {_button("Open Syrabit.ai", "https://syrabit.ai")}
      </p>
      <p style="color:{_MUTED};font-size:13px;">
        Your credits are ready to use. Start chatting with AI on any subject, 
        access full notes, and unlock important questions.
      </p>
    """)
    await _send(email, f"You're on {plan_cap}! — Syrabit.ai", body)


async def send_topup_confirmation(email: str, name: str, credits: int, amount_paise: int):
    """Confirmation email after a credit top-up."""
    amount_inr = amount_paise / 100
    body = _base(f"""
      <h2 style="color:{_BRAND};margin:0 0 8px;">Credits Added!</h2>
      <p style="color:{_MUTED};margin:0 0 24px;">
        Hi {name or 'there'}, your credit top-up was processed successfully.
      </p>
      {_card(f'''
        <table style="width:100%;border-collapse:collapse;">
          <tr><td style="color:{_MUTED};padding:6px 0;">Credits added</td>
              <td style="text-align:right;font-weight:600;color:{_BRAND};">+{credits:,}</td></tr>
          <tr><td style="color:{_MUTED};padding:6px 0;">Amount charged</td>
              <td style="text-align:right;font-weight:600;">₹{amount_inr:,.2f}</td></tr>
        </table>
      ''')}
      <p style="margin-bottom:24px;">
        {_button("Start Chatting", "https://syrabit.ai/chat")}
      </p>
      <p style="color:{_MUTED};font-size:13px;">
        Your new credits are immediately available. Keep up the great work!
      </p>
    """)
    await _send(email, "Credits topped up — Syrabit.ai", body)


async def send_password_reset(email: str, token: str, reset_url: str):
    """Password reset email — replaces the raw httpx version in server.py."""
    body = _base(f"""
      <h2 style="color:{_BRAND};margin:0 0 8px;">Reset your password</h2>
      <p style="color:{_MUTED};margin:0 0 24px;">
        We received a request to reset your Syrabit.ai password.
        Use the token below on the reset page.
      </p>
      {_card(f'''
        <p style="color:{_MUTED};font-size:12px;margin:0 0 8px;">Your reset token (valid 1 hour)</p>
        <code style="font-size:14px;color:#a78bfa;word-break:break-all;
                     letter-spacing:0.5px;">{token}</code>
      ''')}
      <p style="margin-bottom:24px;">
        {_button("Go to Reset Page", reset_url)}
      </p>
      <p style="color:#475569;font-size:12px;">
        If you didn't request this, ignore this email — your password won't change.
      </p>
    """)
    await _send(email, "Reset your Syrabit.ai password", body)
