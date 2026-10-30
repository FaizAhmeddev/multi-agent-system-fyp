"""Email auto-reply (Settings > Connections > Email auto-reply).

Modes:
  off    nothing happens (default)
  draft  new unread emails get a drafted reply as an approval card; nothing is sent until approved
  send   replies are sent automatically, through the tool gateway, as the user who switched it on

Safety rules in both modes:
  - only emails that arrived after auto-reply was switched on (never the whole old inbox)
  - never to yourself, no-reply/mailer/notification addresses, or bulk mail (List-Unsubscribe or
    "unsubscribe" in the text)
  - each email is answered once (remembered by its Gmail id)
  - an email with text addressed to an AI assistant is never answered automatically: it becomes an
    approval card even in send mode
  - at most `max_per_run` replies per check and `max_per_day` sends per day
Every send is recorded as an approval (approved by the user who turned auto-reply on) and audited.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import UTC, datetime
from email.utils import parseaddr
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

log = logging.getLogger("agentsmind.autoreply")

ROW_ID = 2  # hr_settings row 2 holds application settings (row 1 is the HR policy)
MODES = ("off", "draft", "send")
DEFAULTS: dict[str, Any] = {
    "mode": "off",
    "interval_minutes": 5,
    "instructions": "Thank the sender, confirm the email was received and say a proper reply will follow soon.",
    "max_per_run": 5,
    "max_per_day": 40,
    "user_id": None,
    "enabled_at": None,
}
SKIP_SENDER = re.compile(r"(no-?reply|do-?not-?reply|mailer-daemon|postmaster|notifications?@|newsletter|bounce|"
                         r"alerts?@|calendar-notification|accounts\.google\.com)", re.I)
BULK = re.compile(r"\bunsubscribe\b", re.I)


def _row(db: Session):
    from ..db.hr_models import HRSettings

    row = db.get(HRSettings, ROW_ID)
    if row is None:
        row = HRSettings(id=ROW_ID, data={})
        db.add(row)
        db.commit()
    return row


def get_config(db: Session) -> dict[str, Any]:
    data = dict(_row(db).data or {})
    cfg = {**DEFAULTS, **(data.get("auto_reply") or {})}
    cfg["state"] = {"last_run": None, "last_result": "", "handled": 0, "sent_today": 0, "day": "",
                    **(data.get("auto_reply_state") or {})}
    cfg["state"]["handled"] = len(data.get("auto_reply_handled") or [])
    return cfg


def save_config(db: Session, user, changes: dict[str, Any]) -> dict[str, Any]:
    from ..audit import audit

    row = _row(db)
    data = dict(row.data or {})
    cur = {**DEFAULTS, **(data.get("auto_reply") or {})}
    mode = changes.get("mode", cur["mode"])
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if mode != "off" and cur["mode"] == "off":
        cur["enabled_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        cur["user_id"] = user.id
    if mode != "off":
        cur["user_id"] = user.id  # replies go out as the user who set it
    cur["mode"] = mode
    if "interval_minutes" in changes:
        cur["interval_minutes"] = max(1, min(int(changes["interval_minutes"]), 240))
    if "instructions" in changes:
        cur["instructions"] = str(changes["instructions"] or "")[:1000]
    for k in ("max_per_run", "max_per_day"):
        if k in changes:
            cur[k] = max(1, min(int(changes[k]), 200))
    data["auto_reply"] = cur
    row.data = data
    db.commit()
    audit(db, "settings.auto_reply", actor_user_id=user.id, actor_email=user.email, target_type="settings",
          target_id=ROW_ID, detail={"mode": mode, "interval_minutes": cur["interval_minutes"]})
    return get_config(db)


def _save_state(db: Session, state: dict[str, Any], handled: list[str]) -> None:
    row = _row(db)
    data = dict(row.data or {})
    data["auto_reply_state"] = {k: v for k, v in state.items() if k != "handled"}
    data["auto_reply_handled"] = handled[-2000:]
    row.data = data
    db.commit()


def _after(date_iso: str, enabled_at: str | None) -> bool:
    if not enabled_at:
        return False
    try:
        return datetime.fromisoformat(date_iso) >= datetime.fromisoformat(enabled_at)
    except (TypeError, ValueError):
        return False


def run_once(db: Session, *, force: bool = False) -> dict[str, Any]:
    """Check the inbox once. Returns a short summary (also kept as the last result)."""
    from ..agents.gateway import call_tool
    from ..agents.llm import get_llm
    from ..agents.untrusted import injection_signals
    from ..db.models import User
    from .agents.email import EmailAgent

    cfg = get_config(db)
    state, mode = cfg["state"], cfg["mode"]
    if mode == "off" and not force:
        return {"status": "off"}
    user = db.get(User, cfg["user_id"]) if cfg["user_id"] else None
    if user is None or not user.is_active:
        return {"status": "error", "message": "Turn auto-reply on again from Settings (the user who set it is gone)."}
    row = _row(db)
    handled: list[str] = list((row.data or {}).get("auto_reply_handled") or [])
    today = datetime.now(UTC).date().isoformat()
    if state.get("day") != today:
        state.update(day=today, sent_today=0)
    inbox = call_tool(db, agent="email", tool="gmail_read_inbox", args={"unread_only": True, "max_results": 25},
                      user=user)
    if inbox.status != "ok":
        state.update(last_run=datetime.now(UTC).isoformat(timespec="seconds"), last_result=f"Inbox: {inbox.error}")
        _save_state(db, state, handled)
        return {"status": "error", "message": inbox.error}
    me = user.email.lower()
    own = {me, str(inbox.result.get("address", "")).lower()}
    agent = EmailAgent()
    ctx = SimpleNamespace(llm=get_llm(), user=SimpleNamespace(name=user.full_name or user.email.split("@")[0]))
    sent = drafted = skipped = 0
    for msg in inbox.result.get("items", []):
        if sent + drafted >= cfg["max_per_run"]:
            break
        mid = str(msg.get("id") or "")
        if not mid or mid in handled:
            continue
        name, addr = parseaddr(msg.get("sender", ""))
        addr = (addr or "").lower()
        reason = ""
        if not _after(msg.get("date", ""), cfg["enabled_at"]):
            reason = "older than auto-reply"
        elif not addr or "@" not in addr or addr in own:
            reason = "own or no address"
        elif SKIP_SENDER.search(addr) or BULK.search(msg.get("body", "")[-3000:]):
            reason = "automatic or bulk mail"
        if reason:
            if reason != "older than auto-reply":
                handled.append(mid)
            skipped += 1
            continue
        draft, _sim = agent._draft(ctx, original=msg, instruction=cfg["instructions"], about="", to_name=name)
        args = {"to": [addr], "subject": draft.subject, "body": draft.body}
        if msg.get("thread_id"):
            args["thread_id"] = msg["thread_id"]
        summary = f"Auto-reply to {addr}: {draft.subject}"[:300]
        risky = bool(injection_signals(msg.get("body", "")))
        if mode == "send" and not risky and state["sent_today"] < cfg["max_per_day"]:
            o = call_tool(db, agent="email", tool="gmail_send_email", args=args, user=user, summary=summary,
                          direct=True, request_key=f"autoreply-{mid}")
            if o.status == "ok":
                sent += 1
                state["sent_today"] += 1
            else:
                log.warning("auto-reply send failed", extra={"error": o.error})
                state["last_result"] = f"Sending failed: {o.error}"
                continue  # try again next time
        else:
            o = call_tool(db, agent="email", tool="gmail_send_email", args=args, user=user, summary=summary)
            if o.status != "approval_required":
                continue
            drafted += 1
        handled.append(mid)
    result = (f"{sent} sent, {drafted} waiting for approval, {skipped} skipped"
              f" ({len(inbox.result.get('items', []))} unread checked)")
    state.update(last_run=datetime.now(UTC).isoformat(timespec="seconds"), last_result=result)
    _save_state(db, state, handled)
    log.info("auto-reply run", extra={"mode": mode, "sent": sent, "drafted": drafted, "skipped": skipped})
    return {"status": "ok", "sent": sent, "drafted": drafted, "skipped": skipped, "message": result}


_thread: threading.Thread | None = None
_stop = threading.Event()


def start_background() -> None:
    """Started by the core API. Checks every 30 s whether a run is due (the interval is a setting)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    def loop():
        from ..db.session import SessionLocal

        last = 0.0
        while not _stop.wait(30):
            try:
                with SessionLocal() as db:
                    cfg = get_config(db)
                    if cfg["mode"] == "off" or time.time() - last < cfg["interval_minutes"] * 60:
                        continue
                    last = time.time()
                    run_once(db)
            except Exception:  # noqa: BLE001 - logged; the loop keeps going
                log.exception("auto-reply check failed")

    _stop.clear()
    _thread = threading.Thread(target=loop, name="auto-reply", daemon=True)
    _thread.start()


def stop_background() -> None:
    _stop.set()
