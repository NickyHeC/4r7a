"""Draft Reply Agent — compose draft replies for simple 2. Reply threads.

Dispatched by gmail_manager at 8/12/4 workdays. Handles unhandled routing
records with attention ``2. Reply`` where complexity heuristics mark the thread
as simple. Uses Gmail MCP (create_draft only, never send) via Claude Agent SDK.

SDK: Anthropic Claude Agent SDK — MCP-native read + draft compose.
"""

from __future__ import annotations

import asyncio
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_client
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.complexity import is_simple_reply
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig

SPECIALIST_KEY = "draft_reply"
_RESULT_MARKER = "DRAFT_CREATED"


class DraftReplyAgent(BaseAgent):
    """Create Gmail drafts for low-complexity Reply threads."""

    name = "gmail_draft_reply"
    WRITE_MODE = "update"

    def __init__(
        self,
        config: AppConfig,
        mailbox: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self.model = model
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        pending = self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, attention="2. Reply",
        )
        return bool(pending)

    def run(self, **kwargs: Any) -> dict[str, Any]:
        pending = self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, attention="2. Reply",
        )
        drafted = 0
        skipped = 0
        for record in pending:
            try:
                thread = rest.get_thread(record.thread_id, mailbox=self.mailbox)
                if not is_simple_reply(thread, mailbox=self.mailbox):
                    skipped += 1
                    continue
                asyncio.run(self._create_draft(record.thread_id, record.message_id))
                self._store.mark_handled(record, SPECIALIST_KEY)
                drafted += 1
            except Exception:
                self.logger.exception("Draft failed for message %s", record.message_id)
        return {"drafted": drafted, "skipped_complex": skipped}

    async def _create_draft(self, thread_id: str, message_id: str) -> None:
        from claude_agent_sdk import ClaudeAgentOptions, query

        from company_brain.llm import claude as llm_claude

        prompt = f"""You are drafting a reply for the CEO's Gmail inbox.

Read thread id {thread_id} (latest inbound message id {message_id}) using Gmail MCP tools.
Compose a concise, professional reply in the CEO's voice: direct, warm, no fluff.

Rules:
- Use create_draft ONLY. Never send email.
- Reply in-thread on the same thread.
- Keep it short unless the inbound mail clearly needs detail.
- If you cannot draft confidently, output exactly: SKIP

When the draft is created, output exactly: {_RESULT_MARKER}"""

        options = ClaudeAgentOptions(
            allowed_tools=gmail_client.gmail_allowed_tools(),
            mcp_servers=gmail_client.gmail_mcp_servers(),
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(self.model),
        )
        collected: list[str] = []
        async for message in query(prompt=prompt, options=options):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                collected.append(result)
            content = getattr(message, "content", None)
            if isinstance(content, str):
                collected.append(content)
        output = "\n".join(collected)
        if _RESULT_MARKER not in output and "SKIP" not in output:
            self.logger.warning(
                "Draft agent did not confirm draft creation for thread %s", thread_id,
            )
