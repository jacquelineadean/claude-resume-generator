#!/usr/bin/env python3
"""
Resume Generator using Claude Agent SDK

This example uses web search to research a person and generates
a professional 1-page resume as a .docx file.

If the agent needs a tool that isn't pre-approved, you are prompted
in the terminal to allow or deny it.

Usage: python resume_generator.py "Person Name"
"""

import asyncio
import sys
import warnings
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

SYSTEM_PROMPT = """You are a professional resume writer. Research a person and create a 1-page .docx resume.

WORKFLOW:
1. WebSearch for the person's background (LinkedIn, GitHub, company pages)
2. Create a .docx file using the docx library

OUTPUT:
- Script: agent/custom_scripts/generate_resume.js
- Resume: agent/custom_scripts/resume.docx

IMPORTANT: package.json declares "type": "module", so generate_resume.js must
use ESM syntax (import { Document } from "docx") — never require(). ESM has no
__dirname; derive paths from import.meta.url or use a path relative to cwd.

PAGE FIT (must be exactly 1 page):
- 0.5 inch margins, Name 24pt, Headers 12pt, Body 10pt
- 2-3 bullet points per job, ~80-100 chars each
- Max 3 job roles, 2-line summary, 2-line skills"""

# Tools the agent may use without asking. Anything else goes through the
# interactive permission prompt below.
ALLOWED_TOOLS = [
    "Skill",
    "WebSearch",
    "WebFetch",
    "Bash",
    "Write",
    "Read",
    "Edit",
    "Glob",
]


def _tool_detail(tool_name: str, input_data: dict[str, Any]) -> str:
    """One-line summary of a tool call for display."""
    if tool_name == "Bash":
        detail = input_data.get("command", "")
    elif tool_name in ("WebSearch", "WebFetch"):
        detail = input_data.get("query") or input_data.get("url") or ""
    else:
        detail = input_data.get("file_path") or input_data.get("path") or ""
    detail = str(detail).replace("\n", " ")
    return detail if len(detail) <= 120 else detail[:117] + "..."


def _block_text(content: str | list[dict[str, Any]] | None) -> str:
    """Flatten tool-result content (string or content-block list) to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(
        block.get("text", "") for block in content if block.get("type") == "text"
    )


class PermissionPrompter:
    """Terminal prompt invoked when the agent requests a non-pre-approved tool."""

    def __init__(self) -> None:
        self.always_allowed: set[str] = set()

    async def __call__(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        if tool_name in self.always_allowed:
            return PermissionResultAllow()

        print(f"\n🔐 Permission needed: {tool_name}")
        detail = _tool_detail(tool_name, input_data)
        if detail:
            print(f"   {detail}")
        if context.decision_reason:
            print(f"   Reason: {context.decision_reason}")

        while True:
            try:
                # input() blocks, so run it in a thread to keep the agent's
                # message stream alive.
                answer = await asyncio.to_thread(
                    input, "   Allow? [y]es / [a]lways for this tool / [n]o: "
                )
            except (EOFError, KeyboardInterrupt):
                return PermissionResultDeny(
                    message="No interactive user available to approve this tool. "
                    "Continue with the pre-approved tools instead."
                )
            answer = answer.strip().lower()
            if answer in ("y", "yes"):
                return PermissionResultAllow()
            if answer in ("a", "always"):
                self.always_allowed.add(tool_name)
                return PermissionResultAllow()
            if answer in ("n", "no"):
                try:
                    reason = await asyncio.to_thread(
                        input, "   Tell the agent why / what to do instead (optional): "
                    )
                except (EOFError, KeyboardInterrupt):
                    reason = ""
                return PermissionResultDeny(
                    message=reason.strip() or "User denied permission for this tool."
                )
            print("   Please answer y, a, or n.")


async def _prompt_stream(text: str) -> AsyncIterator[dict[str, Any]]:
    """Wrap the prompt for streaming mode, which can_use_tool requires."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
        "session_id": "default",
    }


async def generate_resume(person_name: str) -> None:
    print(f"\n📝 Generating resume for: {person_name}\n")
    print("=" * 50)

    # Ensure the output directory exists
    output_dir = Path.cwd() / "agent" / "custom_scripts"
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        f'Research "{person_name}" and create a professional 1-page resume as a '
        ".docx file. Search for their professional background, experience, "
        "education, and skills."
    )

    print("\n🔍 Researching and creating resume...\n")

    # Intentional shadowing: allowed_tools auto-approves the routine tools and
    # the callback only fires for everything else, so silence the SDK warning.
    warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

    options = ClaudeAgentOptions(
        max_turns=40,
        cwd=Path.cwd(),
        model="sonnet",
        allowed_tools=ALLOWED_TOOLS,
        can_use_tool=PermissionPrompter(),
        setting_sources=["project"],  # Load skills from .claude/skills/
        system_prompt=SYSTEM_PROMPT,
    )

    async for msg in query(prompt=_prompt_stream(prompt), options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    if block.name == "WebSearch" and "query" in block.input:
                        print(f'\n🔍 Searching: "{block.input["query"]}"')
                    else:
                        detail = _tool_detail(block.name, block.input)
                        suffix = f": {detail}" if detail else ""
                        print(f"\n🔧 Using tool: {block.name}{suffix}")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            # Surface tool failures (command errors, denied permissions, ...)
            for block in msg.content:
                if isinstance(block, ToolResultBlock) and block.is_error:
                    text = _block_text(block.content).strip()
                    if len(text) > 600:
                        text = text[:600] + "\n   [... truncated]"
                    print(f"\n⚠️  Tool error:\n   {text.replace(chr(10), chr(10) + '   ')}")
        elif isinstance(msg, ResultMessage) and msg.is_error:
            print(f"\n❌ Agent run failed ({msg.subtype})")
            for err in msg.errors or []:
                print(f"   {err}")
            if msg.result:
                print(f"   {msg.result[:600]}")
            if msg.subtype == "error_max_turns":
                print("   Hit the max_turns limit — consider raising it.")

    # Check if resume was created
    expected_path = Path.cwd() / "agent" / "custom_scripts" / "resume.docx"
    if expected_path.exists():
        print("\n" + "=" * 50)
        print(f"📄 Resume saved to: {expected_path}")
        print("=" * 50 + "\n")
    else:
        print("\n❌ Resume file was not created. Check the output above for errors.")


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python resume_generator.py "Person Name"')
        print('Example: python resume_generator.py "Jane Doe"')
        sys.exit(1)

    asyncio.run(generate_resume(sys.argv[1]))


if __name__ == "__main__":
    main()
