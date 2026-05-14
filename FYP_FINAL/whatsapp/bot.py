"""
WHATSAPP/BOT.PY
================
WhatsApp Bot using Twilio — sends and receives messages.
Routes incoming messages through the Orchestrator.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def send_whatsapp(to_number: str, message: str,
                  content_sid: str = None,
                  content_variables: dict = None) -> dict:
    """
    Send a WhatsApp message via Twilio.
    Uses plain body — works after sandbox join.
    Falls back to template if body fails.
    """
    try:
        from twilio.rest import Client
        from config import (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
                            TWILIO_WHATSAPP_FROM)

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Normalize number
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        # Clean and truncate message for WhatsApp
        body = _format_for_whatsapp(message)[:1600]

        # Send as plain body — works once sandbox is joined
        msg = client.messages.create(
            from_ = TWILIO_WHATSAPP_FROM,
            body  = body,
            to    = to_number,
        )

        # Log to DB
        try:
            from database.sqlite_db import log_whatsapp
            log_whatsapp(
                direction   = "outbound",
                from_number = TWILIO_WHATSAPP_FROM,
                to_number   = to_number,
                message     = message[:500],
                status      = msg.status,
            )
        except Exception:
            pass

        return {"success": True, "sid": msg.sid, "status": msg.status}

    except Exception as e:
        return {"success": False, "error": str(e)}


def send_whatsapp_to_default(message: str) -> dict:
    """Send to the configured default number in config.py."""
    from config import TWILIO_WHATSAPP_TO
    return send_whatsapp(TWILIO_WHATSAPP_TO, message)


def process_incoming_message(from_number: str, body: str,
                              user_name: str = "WhatsApp User") -> str:
    """
    Process an incoming WhatsApp message through the Orchestrator.
    Returns the response text to send back.
    """
    try:
        from Orchestrator.orchestrator_brain import orchestrator
        result   = orchestrator.route(body, user_name)
        response = result.get("final_answer", "Sorry, I could not process your request.")

        # Log to DB
        try:
            from database.sqlite_db import log_whatsapp, log_task
            log_whatsapp(
                direction="inbound",
                from_number=from_number,
                to_number="system",
                message=body[:500],
                agents_used=result.get("agents_used", []),
            )
            log_task(
                user_name=user_name, user_role="WhatsApp",
                user_input=body,
                agents_used=result.get("agents_used", []),
                response=response[:2000],
                elapsed_ms=result.get("elapsed_ms", 0),
                source="whatsapp",
            )
        except Exception:
            pass

        return response

    except Exception as e:
        return f"System error: {e}. Please try again."


def send_agent_response_to_whatsapp(user_input: str, recipient_number: str,
                                     also_email: bool = False,
                                     email_address: str = "",
                                     user_name: str = "User") -> dict:
    """
    Full pipeline:
      1. Route user_input through Orchestrator
      2. Send response to WhatsApp number
      3. Optionally send email too

    Returns full result dict.
    """
    result = {"whatsapp": None, "email": None, "agent_response": ""}

    try:
        from Orchestrator.orchestrator_brain import orchestrator
        orch_result = orchestrator.route(user_input, user_name)
        response    = orch_result.get("final_answer", "No response")
        result["agent_response"] = response
        result["agents_used"]    = orch_result.get("agents_used", [])

        # Format and send as plain WhatsApp message
        wa_text   = _format_for_whatsapp(response)
        wa_result = send_whatsapp(
            to_number = recipient_number,
            message   = wa_text,
        )
        result["whatsapp"] = wa_result

        # Send Email if requested
        if also_email and email_address:
            try:
                from tools.gmail_send import send_email
                email_result = send_email({
                    "recipient": email_address,
                    "subject":   f"Agent Response: {user_input[:60]}",
                    "body":      response,
                })
                result["email"] = email_result.get("send_status", "Sent")

                # Log email
                from database.sqlite_db import log_email
                log_email(
                    direction="sent",
                    from_addr=__import__("config").GMAIL_EMAIL,
                    to_addr=email_address,
                    subject=f"Agent Response: {user_input[:60]}",
                    body=response[:1000],
                )
            except Exception as e:
                result["email"] = f"Email error: {e}"

        # Log to DB
        try:
            from database.sqlite_db import log_task
            log_task(
                user_name=user_name, user_role="WhatsApp+Email",
                user_input=user_input,
                agents_used=orch_result.get("agents_used", []),
                response=response[:2000],
                elapsed_ms=orch_result.get("elapsed_ms", 0),
                source="whatsapp",
            )
        except Exception:
            pass

    except Exception as e:
        result["error"] = str(e)

    return result


def _format_for_whatsapp(text: str) -> str:
    """Convert markdown to WhatsApp-friendly format."""
    import re
    # Bold: **text** → *text*
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    # Remove headers ##
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Keep bullet points
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r'\n---+\n', '\n\n', text)
    # Truncate
    if len(text) > 1500:
        text = text[:1450] + "\n\n_(message truncated)_"
    return text.strip()


def test_connection() -> dict:
    """Test if Twilio credentials are valid."""
    try:
        from twilio.rest import Client
        from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
        # Validate format first
        if not TWILIO_ACCOUNT_SID.startswith("AC"):
            return {"success": False, "error": "Account SID must start with 'AC'"}
        if len(TWILIO_AUTH_TOKEN) < 20:
            return {"success": False, "error": "Auth Token looks too short — copy full token from Twilio console"}
        client  = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        account = client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
        return {
            "success":  True,
            "account":  account.friendly_name,
            "status":   account.status,
            "sid":      TWILIO_ACCOUNT_SID,
            "token_len": len(TWILIO_AUTH_TOKEN),
        }
    except Exception as e:
        err = str(e)
        hint = ""
        if "20003" in err or "Authenticate" in err:
            hint = " → Auth Token is wrong. Go to console.twilio.com → Account → Keys & Credentials → copy the FULL Auth Token (32 chars)"
        elif "20404" in err:
            hint = " → Account SID not found"
        return {"success": False, "error": err + hint}
