"""Security scan for employee wiki zip imports (deterministic, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}", re.I), "OpenAI-style API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub personal access token"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S{8,}"), "credential assignment"),
]

INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all )?(previous|prior) instructions"),
    re.compile(r"(?i)you are now (?:a|an) "),
    re.compile(r"(?i)system:\s*"),
]

HTML_PATTERNS = [
    re.compile(r"<\s*script\b", re.I),
    re.compile(r"<\s*iframe\b", re.I),
    re.compile(r"javascript:", re.I),
]

SUSPICIOUS_URL = re.compile(
    r"https?://(?:pastebin|requestbin|webhook\.site|ngrok|burpcollaborator)[^\s)>\]]*",
    re.I,
)


@dataclass
class ImportLimits:
    max_zip_bytes: int = 52_428_800
    max_file_bytes: int = 1_048_576
    max_files: int = 500


@dataclass
class ScanFinding:
    path: str
    severity: str  # block | warn
    reason: str


@dataclass
class ScanReport:
    ok: bool
    findings: list[ScanFinding] = field(default_factory=list)

    def blocked(self) -> list[ScanFinding]:
        return [f for f in self.findings if f.severity == "block"]


def scan_import_files(
    files: dict[str, str],
    *,
    limits: ImportLimits | None = None,
    zip_bytes: int = 0,
) -> ScanReport:
    """Scan extracted import files. ``files`` maps quarantine-relative path -> content."""
    limits = limits or ImportLimits()
    findings: list[ScanFinding] = []

    if zip_bytes and zip_bytes > limits.max_zip_bytes:
        findings.append(ScanFinding("", "block", f"zip exceeds {limits.max_zip_bytes} bytes"))
    if len(files) > limits.max_files:
        findings.append(
            ScanFinding("", "block", f"too many files ({len(files)} > {limits.max_files})"),
        )

    for path, content in files.items():
        if not path.lower().endswith(".md"):
            findings.append(ScanFinding(path, "block", "non-.md file in import"))
            continue
        encoded = content.encode("utf-8")
        if len(encoded) > limits.max_file_bytes:
            findings.append(
                ScanFinding(path, "block", f"file exceeds {limits.max_file_bytes} bytes"),
            )
        findings.extend(_scan_content(path, content))

    blocked = any(f.severity == "block" for f in findings)
    return ScanReport(ok=not blocked, findings=findings)


def _scan_content(path: str, content: str) -> list[ScanFinding]:
    out: list[ScanFinding] = []
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(content):
            out.append(ScanFinding(path, "block", label))
    for pattern in INJECTION_PATTERNS:
        if pattern.search(content):
            out.append(ScanFinding(path, "warn", "possible prompt-injection marker"))
    for pattern in HTML_PATTERNS:
        if pattern.search(content):
            out.append(ScanFinding(path, "block", "embedded HTML/script"))
    if SUSPICIOUS_URL.search(content):
        out.append(ScanFinding(path, "warn", "suspicious exfiltration URL"))
    return out
