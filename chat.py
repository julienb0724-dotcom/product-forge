#!/usr/bin/env python3
"""
Product Forge — Interactive Chat Mode

Chat with the 5 specialist agents in real-time.
Address a specific agent by name, or ask everyone.

Usage:
    python chat.py
    python chat.py --context "We're building an energy dashboard for homeowners"
    python chat.py --agent jony  # Start in 1-on-1 with Jony

Commands:
    @jony, @maya, @kai, @elena, @dev  — Direct message to one agent
    @all or just type                  — All agents respond
    /focus jony                        — Switch to 1-on-1 mode with an agent
    /all                               — Switch back to group mode
    /agents                            — List all agents
    /context <text>                    — Set/update project context
    /history                           — Show conversation so far
    /clear                             — Clear conversation history
    /export                            — Save conversation to file
    /quit                              — Exit
"""

import argparse
import asyncio
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# Load .env file if ANTHROPIC_API_KEY not set
if not os.environ.get("ANTHROPIC_API_KEY"):
    for env_path in [Path.home() / "cortana-api" / ".env", Path(".env")]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
            break

try:
    import anthropic
except ImportError:
    print("Error: pip install anthropic")
    sys.exit(1)

from agents import AGENTS, AGENT_META

# Colors for terminal output
COLORS = {
    "designer": "\033[92m",   # green
    "pm": "\033[94m",         # blue
    "architect": "\033[93m",  # yellow
    "strategist": "\033[95m", # magenta
    "engineer": "\033[96m",   # cyan
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

AGENT_ALIASES = {
    "jony": "designer",
    "maya": "pm",
    "kai": "architect",
    "elena": "strategist",
    "dev": "engineer",
}

MODEL = "claude-sonnet-4-6"


def agent_color(key: str) -> str:
    return COLORS.get(key, "")


def agent_name(key: str) -> str:
    return AGENTS[key]["name"]


def build_system_prompt(agent_key: str, context: str) -> str:
    agent = AGENTS[agent_key]
    parts = [
        f"You are {agent['name']}, {agent['title']} at Product Forge.",
        "",
        "## Your Role",
        agent.get("persona", ""),
        "",
        AGENT_META,
        "",
        "## Interaction Mode",
        "You are in a live conversation with the user and your fellow agents.",
        "Keep responses concise and conversational — this is a discussion, not a deliverable.",
        "Use 2-5 paragraphs max unless asked for detail.",
        "Be direct. Disagree when you should. Build on what others said.",
        "If another agent said something you agree with, don't repeat it — add to it.",
        "",
    ]
    if context:
        parts.extend([
            "## Project Context",
            context,
            "",
        ])
    return "\n".join(parts)


class ForgeChat:
    def __init__(self, context: str = "", focus_agent: Optional[str] = None):
        self.client = anthropic.Anthropic()
        self.context = context
        self.focus_agent = focus_agent  # None = group mode
        self.history: list = []  # {role, agent, content}
        self.agent_histories: dict = {k: [] for k in AGENTS}

    def _resolve_agent(self, name: str) -> Optional[str]:
        name = name.lower().strip().lstrip("@")
        if name in AGENTS:
            return name
        return AGENT_ALIASES.get(name)

    def _parse_message(self, text: str) -> tuple[list, str]:
        """Returns (target_agents, message)."""
        text = text.strip()

        # @agent prefix
        if text.startswith("@"):
            parts = text.split(None, 1)
            tag = parts[0]
            msg = parts[1] if len(parts) > 1 else ""
            if tag.lower() == "@all":
                return list(AGENTS.keys()), msg
            resolved = self._resolve_agent(tag[1:])
            if resolved:
                return [resolved], msg

        # Focus mode
        if self.focus_agent:
            return [self.focus_agent], text

        # Default: all agents
        return list(AGENTS.keys()), text

    async def ask_agent(self, agent_key: str, user_message: str) -> str:
        system = build_system_prompt(agent_key, self.context)

        # Build messages with conversation context
        messages = []

        # Include recent conversation history (last 10 exchanges)
        for entry in self.history[-20:]:
            if entry["role"] == "user":
                messages.append({"role": "user", "content": entry["content"]})
            else:
                # Other agents' responses as context
                prefix = f"[{entry['agent']}]: " if entry.get("agent") else ""
                messages.append({"role": "assistant", "content": prefix + entry["content"]})

        # The current question
        messages.append({"role": "user", "content": user_message})

        # Deduplicate: ensure alternating user/assistant
        deduped = []
        for m in messages:
            if deduped and deduped[-1]["role"] == m["role"]:
                deduped[-1]["content"] += "\n" + m["content"]
            else:
                deduped.append(m)

        # Ensure starts with user
        if deduped and deduped[0]["role"] != "user":
            deduped.insert(0, {"role": "user", "content": "(conversation context)"})

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=system,
            messages=deduped,
        )

        return response.content[0].text

    async def process(self, user_input: str) -> list:
        targets, message = self._parse_message(user_input)
        if not message:
            return []

        self.history.append({"role": "user", "content": user_input})

        # Query agents in parallel
        tasks = {key: self.ask_agent(key, message) for key in targets}
        results = []

        for key in targets:
            response = await tasks[key]
            self.history.append({"role": "assistant", "agent": agent_name(key), "content": response})
            results.append((key, response))

        return results

    def export(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(f"chat_{ts}.md")
        lines = [f"# Product Forge Chat — {ts}\n"]
        if self.context:
            lines.append(f"**Context:** {self.context}\n")
        lines.append("---\n")
        for entry in self.history:
            if entry["role"] == "user":
                lines.append(f"\n**You:** {entry['content']}\n")
            else:
                lines.append(f"\n**{entry.get('agent', '?')}:** {entry['content']}\n")
        path.write_text("\n".join(lines))
        return str(path)


async def main():
    parser = argparse.ArgumentParser(description="Product Forge — Interactive Chat")
    parser.add_argument("--context", "-c", help="Project context for all agents")
    parser.add_argument("--agent", "-a", help="Start focused on one agent (jony/maya/kai/elena/dev)")
    args = parser.parse_args()

    focus = None
    if args.agent:
        focus = AGENT_ALIASES.get(args.agent.lower()) or args.agent.lower()
        if focus not in AGENTS:
            print(f"Unknown agent: {args.agent}")
            sys.exit(1)

    chat = ForgeChat(context=args.context or "", focus_agent=focus)

    print(f"\n{BOLD}🔥 Product Forge — Interactive Chat{RESET}")
    print(f"{DIM}Type a message to talk to all agents, or @name for one.{RESET}")
    print(f"{DIM}Commands: /focus <name>, /all, /agents, /context, /export, /quit{RESET}")
    if focus:
        name = agent_name(focus)
        color = agent_color(focus)
        print(f"{DIM}Focused on {color}{BOLD}{name}{RESET}{DIM}. Use /all to talk to everyone.{RESET}")
    if args.context:
        print(f"{DIM}Context: {args.context[:100]}{'...' if len(args.context) > 100 else ''}{RESET}")
    print()

    while True:
        try:
            user_input = input(f"{BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Bye!")
            break

        if not user_input:
            continue

        # Commands
        if user_input.startswith("/"):
            cmd = user_input.split(None, 1)
            command = cmd[0].lower()

            if command == "/quit":
                print("👋 Bye!")
                break
            elif command == "/agents":
                for k, v in AGENTS.items():
                    color = agent_color(k)
                    print(f"  {color}{BOLD}{v['name']}{RESET} — {v['title']}")
                continue
            elif command == "/focus":
                if len(cmd) < 2:
                    print("Usage: /focus <agent name>")
                    continue
                resolved = AGENT_ALIASES.get(cmd[1].lower()) or cmd[1].lower()
                if resolved in AGENTS:
                    chat.focus_agent = resolved
                    print(f"  → Focused on {agent_color(resolved)}{BOLD}{agent_name(resolved)}{RESET}")
                else:
                    print(f"  Unknown agent: {cmd[1]}")
                continue
            elif command == "/all":
                chat.focus_agent = None
                print("  → Group mode (all agents)")
                continue
            elif command == "/context":
                if len(cmd) < 2:
                    print(f"  Current: {chat.context or '(none)'}")
                else:
                    chat.context = cmd[1]
                    print(f"  → Context updated")
                continue
            elif command == "/history":
                for entry in chat.history[-20:]:
                    if entry["role"] == "user":
                        print(f"  {BOLD}You:{RESET} {entry['content'][:80]}")
                    else:
                        print(f"  {DIM}{entry.get('agent', '?')}:{RESET} {entry['content'][:80]}...")
                continue
            elif command == "/clear":
                chat.history.clear()
                print("  → History cleared")
                continue
            elif command == "/export":
                path = chat.export()
                print(f"  → Saved to {path}")
                continue
            else:
                print(f"  Unknown command: {command}")
                continue

        # Send to agents
        print()
        results = await chat.process(user_input)

        for agent_key, response in results:
            color = agent_color(agent_key)
            name = agent_name(agent_key)
            print(f"{color}{BOLD}{name}:{RESET} {response}\n")


if __name__ == "__main__":
    asyncio.run(main())
