#!/usr/bin/env python3
"""
Resume Generator using Claude Agent SDK

This example uses web search to research a person and generates
a professional 1-page resume as a .docx file.

Usage: python resume_generator.py "Person Name"
"""

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolUseBlock,
    query,
)

SYSTEM_PROMPT = """You are a professional resume writer. Research a person and create a 1-page .docx resume.

WORKFLOW:
1. WebSearch for the person's background (LinkedIn, GitHub, company pages)
2. Create a .docx file using the docx library

OUTPUT:
- Script: agent/custom_scripts/generate_resume.js
- Resume: agent/custom_scripts/resume.docx

PAGE FIT (must be exactly 1 page):
- 0.5 inch margins, Name 24pt, Headers 12pt, Body 10pt
- 2-3 bullet points per job, ~80-100 chars each
- Max 3 job roles, 2-line summary, 2-line skills"""


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

    options = ClaudeAgentOptions(
        max_turns=30,
        cwd=Path.cwd(),
        model="sonnet",
        allowed_tools=["Skill", "WebSearch", "WebFetch", "Bash", "Write", "Read", "Glob"],
        setting_sources=["project"],  # Load skills from .claude/skills/
        system_prompt=SYSTEM_PROMPT,
    )

    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    if block.name == "WebSearch" and "query" in block.input:
                        print(f'\n🔍 Searching: "{block.input["query"]}"')
                    else:
                        print(f"\n🔧 Using tool: {block.name}")

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
