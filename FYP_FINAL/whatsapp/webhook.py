"""
WHATSAPP/WEBHOOK.PY
====================
Flask webhook server for receiving incoming WhatsApp messages from Twilio.

Run separately:
  python whatsapp/webhook.py

Then expose via ngrok:
  ngrok http 5000
  Copy the https URL → paste in Twilio Sandbox Webhook settings
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Twilio calls this URL when a WhatsApp message is received."""
    incoming_msg = request.values.get("Body", "").strip()
    from_number  = request.values.get("From", "")
    profile_name = request.values.get("ProfileName", "WhatsApp User")

    print(f"[WhatsApp IN] {from_number} ({profile_name}): {incoming_msg}")

    # Process through Orchestrator
    from whatsapp.bot import process_incoming_message
    response_text = process_incoming_message(from_number, incoming_msg, profile_name)

    # Send reply via Twilio TwiML
    resp = MessagingResponse()
    msg  = resp.message()
    msg.body(response_text[:1600])

    return str(resp), 200, {"Content-Type": "text/xml"}


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "FYP WhatsApp Webhook"}, 200


if __name__ == "__main__":
    print("=" * 50)
    print("  WhatsApp Webhook Server — Port 5000")
    print("  Expose with: ngrok http 5000")
    print("  Set Twilio webhook to: https://YOUR_NGROK/whatsapp")
    print("=" * 50)
    app.run(debug=False, port=5000)
