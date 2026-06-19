"""Gmail label taxonomy: create with visibility, resolve ids, apply to messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.gmail_config import label_defs

logger = logging.getLogger(__name__)

CB_TRIAGED = "cb/triaged"


@dataclass
class LabelSpec:
    name: str
    visible: bool
    parent: str | None = None


def all_label_specs() -> list[LabelSpec]:
    defs = label_defs()
    specs: list[LabelSpec] = []

    for entry in defs.get("attention") or []:
        specs.append(LabelSpec(name=entry["name"], visible=bool(entry.get("visible", True))))

    for entry in defs.get("domain") or []:
        specs.append(LabelSpec(name=entry["name"], visible=bool(entry.get("visible", False))))

    parent = defs.get("cold_inbound_parent", "Cold Inbound")
    for entry in defs.get("cold_inbound") or []:
        specs.append(LabelSpec(
            name=entry["name"],
            visible=False,
            parent=parent,
        ))

    specs.append(LabelSpec(name=CB_TRIAGED, visible=False))
    return specs


def ensure_taxonomy(mailbox: str = "me") -> dict[str, str]:
    """Create missing labels; return map name → label id."""
    defs = label_defs()
    name_to_id: dict[str, str] = {}
    existing = {lbl["name"]: lbl["id"] for lbl in rest.list_labels(mailbox)}

    for parent_name in (
        defs.get("cold_inbound_parent", "Cold Inbound"),
        defs.get("newsletters_parent", "Newsletters"),
    ):
        if parent_name in existing:
            name_to_id[parent_name] = existing[parent_name]
        else:
            name_to_id[parent_name] = rest.ensure_label(parent_name, visible=False, mailbox=mailbox)

    for spec in all_label_specs():
        full_name = f"{spec.parent}/{spec.name}" if spec.parent else spec.name
        if full_name in existing:
            name_to_id[full_name] = existing[full_name]
            continue
        if spec.parent and spec.parent not in name_to_id:
            name_to_id[spec.parent] = rest.ensure_label(spec.parent, visible=False, mailbox=mailbox)
        created = rest.create_label(
            full_name,
            visible=spec.visible,
            mailbox=mailbox,
        )
        name_to_id[full_name] = created["id"]
        logger.info("Created Gmail label %s (visible=%s)", full_name, spec.visible)

    return name_to_id


def resolve_label_id(name: str, *, parent: str | None = None, mailbox: str = "me") -> str | None:
    full = f"{parent}/{name}" if parent else name
    for lbl in rest.list_labels(mailbox):
        if lbl.get("name") == full:
            return lbl["id"]
    return None


def apply_labels(
    message_id: str,
    *,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    mailbox: str = "me",
) -> None:
    add_ids = [lid for n in (add or []) if (lid := _name_to_id(n, mailbox=mailbox))]
    remove_ids = [lid for n in (remove or []) if (lid := _name_to_id(n, mailbox=mailbox))]
    if add_ids or remove_ids:
        rest.modify_message(message_id, add_label_ids=add_ids, remove_label_ids=remove_ids, mailbox=mailbox)


def _name_to_id(name: str, *, mailbox: str) -> str | None:
    for lbl in rest.list_labels(mailbox):
        if lbl.get("name") == name:
            return lbl["id"]
    created = rest.ensure_label(name, visible=name.startswith(("1.", "2.", "3.", "4.")), mailbox=mailbox)
    return created


def attention_label_names() -> list[str]:
    return [e["name"] for e in label_defs().get("attention") or []]


def apply_attention(message_id: str, attention: str | None, *, mailbox: str = "me") -> None:
    """Set exactly one visible attention label (or clear all attention labels)."""
    remove = attention_label_names()
    add = [attention] if attention else []
    apply_labels(message_id, add=add, remove=remove, mailbox=mailbox)


def mark_triaged(message_id: str, *, mailbox: str = "me") -> None:
    apply_labels(message_id, add=[CB_TRIAGED], mailbox=mailbox)


def mark_read(message_id: str, *, mailbox: str = "me") -> None:
    rest.modify_message(message_id, remove_label_ids=["UNREAD"], mailbox=mailbox)


def archive(message_id: str, *, mailbox: str = "me") -> None:
    rest.modify_message(message_id, remove_label_ids=["INBOX"], mailbox=mailbox)
