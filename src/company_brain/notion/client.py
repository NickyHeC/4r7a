"""Thin wrapper around the Notion CLI (ntn) for page and API operations."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class NtnError(Exception):
    """Raised when a ntn CLI command fails."""

    def __init__(self, command: list[str], returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"ntn exited {returncode}: {stderr.strip()}")


@dataclass
class NtnResult:
    stdout: str
    stderr: str
    returncode: int
    json_data: dict[str, Any] | list[Any] | None = field(default=None)


class NotionClient:
    """Executes Notion operations through the ntn CLI binary."""

    def __init__(self, ntn_path: str | None = None, notion_version: str | None = None):
        self._ntn = ntn_path or shutil.which("ntn") or "ntn"
        self._notion_version = notion_version

    def _run(
        self,
        args: list[str],
        *,
        input_data: str | None = None,
        check: bool = True,
        parse_json: bool = False,
    ) -> NtnResult:
        cmd = [self._ntn] + args
        logger.debug("Running: %s", " ".join(cmd))

        proc = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=120,
        )

        result = NtnResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )

        if parse_json and proc.stdout.strip():
            try:
                result.json_data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                logger.warning("Failed to parse ntn JSON output")

        if check and proc.returncode != 0:
            raise NtnError(cmd, proc.returncode, proc.stderr)

        return result

    # -- Auth & health --------------------------------------------------------

    def check_auth(self) -> bool:
        """Return True if ntn is authenticated and can reach the workspace."""
        try:
            result = self._run(["api", "v1/users/me", "--json"], check=False, parse_json=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def is_installed(self) -> bool:
        """Return True if the ntn binary is on PATH."""
        return shutil.which(self._ntn) is not None

    # -- Pages ----------------------------------------------------------------

    def create_page(
        self,
        parent_id: str,
        markdown: str,
        *,
        title: str | None = None,
    ) -> NtnResult:
        """Create a Notion page under parent_id with markdown content.

        If title is omitted, the first # heading in the markdown is used.
        """
        args = ["pages", "create", "--parent", f"page:{parent_id}"]
        if self._notion_version:
            args += ["--notion-version", self._notion_version]
        args += ["--content", "-"]
        content = markdown if title is None else f"# {title}\n\n{markdown}"
        return self._run(args, input_data=content, parse_json=True)

    def get_page(self, page_id: str, *, as_json: bool = False) -> NtnResult:
        """Retrieve a page's content as markdown (or JSON)."""
        args = ["pages", "get", page_id]
        if as_json:
            args.append("--json")
        if self._notion_version:
            args += ["--notion-version", self._notion_version]
        return self._run(args, parse_json=as_json)

    def update_page(self, page_id: str, markdown: str) -> NtnResult:
        """Replace a page's content with new markdown."""
        args = ["pages", "update", page_id, "--content", "-"]
        if self._notion_version:
            args += ["--notion-version", self._notion_version]
        return self._run(args, input_data=markdown)

    def trash_page(self, page_id: str) -> NtnResult:
        """Move a page to the trash."""
        args = ["pages", "trash", page_id, "--yes"]
        if self._notion_version:
            args += ["--notion-version", self._notion_version]
        return self._run(args)

    # -- Search & API ---------------------------------------------------------

    def search(
        self,
        query: str = "",
        *,
        filter_object: str | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> NtnResult:
        """Search the workspace. Returns JSON."""
        args = ["api", "v1/search", "--json"]
        body_parts = []
        if query:
            body_parts.append(f"query={query}")
        if filter_object:
            body_parts.append(f'filter:={{"property":"object","value":"{filter_object}"}}')
        body_parts.append(f"page_size:={page_size}")
        if start_cursor:
            body_parts.append(f"start_cursor={start_cursor}")
        args += body_parts
        return self._run(args, parse_json=True)

    def api(
        self,
        path: str,
        *,
        method: str | None = None,
        data: str | None = None,
        inline_args: list[str] | None = None,
    ) -> NtnResult:
        """Make a raw API call through ntn."""
        args = ["api", path, "--json"]
        if method:
            args += ["-X", method]
        if inline_args:
            args += inline_args
        return self._run(args, input_data=data, parse_json=True)

    # -- Helpers --------------------------------------------------------------

    def search_all_pages(self, page_size: int = 100) -> list[dict[str, Any]]:
        """Paginate through all pages in the workspace."""
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            result = self.search(filter_object="page", page_size=page_size, start_cursor=cursor)
            if result.json_data and isinstance(result.json_data, dict):
                pages.extend(result.json_data.get("results", []))
                if not result.json_data.get("has_more"):
                    break
                cursor = result.json_data.get("next_cursor")
            else:
                break
        return pages

    def search_all_databases(self, page_size: int = 100) -> list[dict[str, Any]]:
        """Paginate through all databases in the workspace."""
        databases: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            result = self.search(filter_object="database", page_size=page_size, start_cursor=cursor)
            if result.json_data and isinstance(result.json_data, dict):
                databases.extend(result.json_data.get("results", []))
                if not result.json_data.get("has_more"):
                    break
                cursor = result.json_data.get("next_cursor")
            else:
                break
        return databases

    def get_block_children(self, block_id: str) -> list[dict[str, Any]]:
        """Return child blocks of a page or block."""
        result = self.api(f"v1/blocks/{block_id}/children")
        if result.json_data and isinstance(result.json_data, dict):
            return result.json_data.get("results", [])
        return []
