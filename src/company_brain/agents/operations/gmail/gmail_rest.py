"""Thin Gmail REST client (history, labels, modify).

Uses ``GMAIL_OAUTH_ACCESS_TOKEN`` — same token as the official MCP path.
Requires ``gmail.modify`` in addition to readonly/compose for label changes.
"""

from __future__ import annotations

import base64
import os
from email.utils import parsedate_to_datetime
from typing import Any

import requests

API_BASE = "https://gmail.googleapis.com/gmail/v1/users"


class GmailAPIError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"Gmail API {status}: {detail[:400]}")
        self.status = status


def _token() -> str:
    tok = os.getenv("GMAIL_OAUTH_ACCESS_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("GMAIL_OAUTH_ACCESS_TOKEN not set — see project_install.md")
    return tok


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> Any:
    url = f"{API_BASE}/{path.lstrip('/')}"
    resp = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {_token()}"},
        params=params,
        json=json_body,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise GmailAPIError(resp.status_code, resp.text)
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def get_profile(mailbox: str = "me") -> dict[str, Any]:
    return _request("GET", f"{mailbox}/profile")


def list_labels(mailbox: str = "me") -> list[dict[str, Any]]:
    data = _request("GET", f"{mailbox}/labels")
    return data.get("labels") or []


def create_label(
    name: str,
    *,
    visible: bool = False,
    mailbox: str = "me",
) -> dict[str, Any]:
    body = {
        "name": name,
        "labelListVisibility": "labelShow" if visible else "labelHide",
        "messageListVisibility": "show" if visible else "hide",
    }
    return _request("POST", f"{mailbox}/labels", json_body=body)


def ensure_label(name: str, *, visible: bool = False, mailbox: str = "me") -> str:
    for lbl in list_labels(mailbox):
        if lbl.get("name") == name:
            return lbl["id"]
    return create_label(name, visible=visible, mailbox=mailbox)["id"]


def list_messages(
    query: str,
    *,
    max_results: int = 100,
    page_token: str | None = None,
    mailbox: str = "me",
) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query, "maxResults": max_results}
    if page_token:
        params["pageToken"] = page_token
    return _request("GET", f"{mailbox}/messages", params=params)


def iter_messages(query: str, *, max_total: int = 500, mailbox: str = "me"):
    token = None
    count = 0
    while count < max_total:
        page = list_messages(
            query,
            page_token=token,
            max_results=min(100, max_total - count),
            mailbox=mailbox,
        )
        for msg in page.get("messages") or []:
            yield msg["id"]
            count += 1
            if count >= max_total:
                break
        token = page.get("nextPageToken")
        if not token:
            break


def get_message(message_id: str, *, format: str = "full", mailbox: str = "me") -> dict[str, Any]:
    return _request("GET", f"{mailbox}/messages/{message_id}", params={"format": format})


def get_thread(thread_id: str, *, format: str = "full", mailbox: str = "me") -> dict[str, Any]:
    return _request("GET", f"{mailbox}/threads/{thread_id}", params={"format": format})


def modify_message(
    message_id: str,
    *,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
    mailbox: str = "me",
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if add_label_ids:
        body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        body["removeLabelIds"] = remove_label_ids
    return _request("POST", f"{mailbox}/messages/{message_id}/modify", json_body=body)


def list_history(
    start_history_id: str,
    *,
    label_id: str | None = None,
    mailbox: str = "me",
) -> dict[str, Any]:
    params: dict[str, Any] = {"startHistoryId": start_history_id}
    if label_id:
        params["labelId"] = label_id
    return _request("GET", f"{mailbox}/history", params=params)


def history_message_ids(
    start_history_id: str, *, mailbox: str = "me"
) -> tuple[list[str], str | None]:
    """Return new message ids from history delta and the latest historyId."""
    ids: list[str] = []
    page_token = None
    latest = None
    while True:
        params: dict[str, Any] = {"startHistoryId": start_history_id}
        if page_token:
            params["pageToken"] = page_token
        data = _request("GET", f"{mailbox}/history", params=params)
        latest = data.get("historyId") or latest
        for record in data.get("history") or []:
            for added in record.get("messagesAdded") or []:
                msg = added.get("message") or {}
                if msg.get("id"):
                    ids.append(msg["id"])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return list(dict.fromkeys(ids)), latest


def history_sent_message_ids(
    start_history_id: str, *, mailbox: str = "me"
) -> tuple[list[str], str | None]:
    """Return message ids where the user sent mail (SENT label added)."""
    ids: list[str] = []
    page_token = None
    latest = None
    while True:
        params: dict[str, Any] = {"startHistoryId": start_history_id}
        if page_token:
            params["pageToken"] = page_token
        data = _request("GET", f"{mailbox}/history", params=params)
        latest = data.get("historyId") or latest
        for record in data.get("history") or []:
            for added in record.get("messagesAdded") or []:
                msg = added.get("message") or {}
                labels = msg.get("labelIds") or []
                if msg.get("id") and "SENT" in labels:
                    ids.append(msg["id"])
            for labels_added in record.get("labelsAdded") or []:
                msg = labels_added.get("message") or {}
                labels = labels_added.get("labelIds") or []
                if msg.get("id") and "SENT" in labels:
                    ids.append(msg["id"])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return list(dict.fromkeys(ids)), latest


def header_map(message: dict[str, Any]) -> dict[str, str]:
    headers = (message.get("payload") or {}).get("headers") or []
    out: dict[str, str] = {}
    for h in headers:
        name = h.get("name", "").lower()
        if name:
            out[name] = h.get("value", "")
    return out


def message_subject_from(message: dict[str, Any]) -> str:
    return header_map(message).get("subject", "")


def message_from(message: dict[str, Any]) -> str:
    return header_map(message).get("from", "")


def message_date(message: dict[str, Any]) -> str | None:
    internal = message.get("internalDate")
    if internal:
        try:
            from datetime import datetime, timezone
            return datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass
    raw = header_map(message).get("date")
    if raw:
        try:
            return parsedate_to_datetime(raw).isoformat()
        except (ValueError, TypeError):
            pass
    return None


def snippet(message: dict[str, Any]) -> str:
    return message.get("snippet") or ""


def label_names(message: dict[str, Any], *, mailbox: str = "me") -> list[str]:
    id_to_name = {lbl["id"]: lbl["name"] for lbl in list_labels(mailbox)}
    return [id_to_name[lid] for lid in message.get("labelIds") or [] if lid in id_to_name]


def thread_has_sent_reply(thread: dict[str, Any], *, mailbox: str = "me") -> bool:
    profile = get_profile(mailbox)
    me = profile.get("emailAddress", "").lower()
    for msg in thread.get("messages") or []:
        labels = msg.get("labelIds") or []
        if "SENT" in labels:
            return True
        from_hdr = message_from(msg).lower()
        if me and me in from_hdr:
            return True
    return False


def is_unread(message: dict[str, Any]) -> bool:
    return "UNREAD" in (message.get("labelIds") or [])


def is_in_inbox(message: dict[str, Any]) -> bool:
    return "INBOX" in (message.get("labelIds") or [])


def latest_sent_message(thread: dict[str, Any], *, mailbox: str = "me") -> dict[str, Any] | None:
    profile = get_profile(mailbox)
    me = profile.get("emailAddress", "").lower()
    sent: list[dict[str, Any]] = []
    for msg in thread.get("messages") or []:
        labels = msg.get("labelIds") or []
        from_hdr = message_from(msg).lower()
        if "SENT" in labels or (me and me in from_hdr):
            sent.append(msg)
    return sent[-1] if sent else None


def list_attachments(message: dict[str, Any]) -> list[dict[str, str]]:
    """Return attachment metadata (filename, mimeType, attachmentId) from a message."""
    out: list[dict[str, str]] = []

    def walk(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        if body.get("attachmentId"):
            out.append({
                "filename": part.get("filename") or "attachment",
                "mimeType": part.get("mimeType") or "application/octet-stream",
                "attachmentId": body["attachmentId"],
            })
        for child in part.get("parts") or []:
            walk(child)

    payload = message.get("payload") or {}
    walk(payload)
    return out


def get_attachment(message_id: str, attachment_id: str, *, mailbox: str = "me") -> bytes:
    data = _request("GET", f"{mailbox}/messages/{message_id}/attachments/{attachment_id}")
    raw = data.get("data") or ""
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
