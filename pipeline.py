"""
Product Forge — Multi-agent product development pipeline.

Three phases:
  1. Individual Analysis — each agent analyzes the input from their perspective
  2. Cross-Review — agents review each other's work (selective pairs)
  3. Synthesis — combine into a unified product brief

Supports text input, image input (screenshots), or both.
Optional knowledge packs loaded from configurable paths.
"""

import asyncio
import base64
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

from agents import AGENTS, REVIEW_PROMPT, SYNTHESIS_PROMPT

# Model selection
MODEL = "claude-sonnet-4-6"  # fast + capable for individual agents
SYNTHESIS_MODEL = "claude-opus-4-6"  # best reasoning for synthesis

OUTPUT_DIR = Path(__file__).parent / "output"


def _load_image(path: str) -> dict:
    """Load an image file and return a Claude-compatible content block."""
    ext = Path(path).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/png")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _build_user_content(prompt: str, image_path: Optional[str] = None) -> list:
    """Build the user message content blocks."""
    content = []
    if image_path and os.path.exists(image_path):
        content.append(_load_image(image_path))
    content.append({"type": "text", "text": prompt})
    return content


async def _call_agent(
    client: anthropic.AsyncAnthropic,
    agent_key: str,
    user_content: list,
    model: str = MODEL,
    knowledge_block: str = "",
) -> str:
    """Call a single agent and return its response text."""
    agent = AGENTS[agent_key]
    system = (
        f"{agent['persona']}\n\n"
    )
    if knowledge_block:
        system += f"{knowledge_block}\n\n"
    system += (
        f"Your deliverable: **{agent['deliverable']}**\n\n"
        f"{agent['output_format']}"
    )

    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return resp.content[0].text


async def _call_reviewer(
    client: anthropic.AsyncAnthropic,
    reviewer_key: str,
    reviewee_key: str,
    reviewee_output: str,
    original_prompt: str,
) -> str:
    """Have one agent review another's work."""
    reviewer = AGENTS[reviewer_key]
    reviewee = AGENTS[reviewee_key]

    system = (
        f"{reviewer['persona']}\n\n"
        f"You are reviewing {reviewee['name']}'s {reviewee['deliverable']}."
    )

    review_msg = REVIEW_PROMPT.format(
        name=reviewer["name"],
        title=reviewer["title"],
        other_name=reviewee["name"],
        other_title=reviewee["title"],
    )

    user_text = (
        f"{review_msg}\n\n"
        f"---\n\n"
        f"## Original Brief\n{original_prompt}\n\n"
        f"---\n\n"
        f"## {reviewee['name']}'s {reviewee['deliverable']}\n\n"
        f"{reviewee_output}"
    )

    resp = await client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    return resp.content[0].text


async def run_pipeline(
    prompt: str,
    image_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    skip_review: bool = False,
    skip_synthesis: bool = False,
    brand_path: Optional[str] = None,
    competitors_dir: Optional[str] = None,
    community_path: Optional[str] = None,
) -> dict:
    """
    Run the full product development pipeline.

    Args:
        prompt: Text description or brief for the product
        image_path: Optional path to a UI screenshot or reference image
        output_dir: Where to write output files (default: output/<timestamp>/)
        skip_review: Skip Phase 2 (cross-review)
        skip_synthesis: Skip Phase 3 (synthesis)
        brand_path: Optional path to brand JSON file
        competitors_dir: Optional path to competitors directory
        community_path: Optional path to community voice JSON file

    Returns:
        dict with all phase outputs
    """
    client = anthropic.AsyncAnthropic()

    # Setup output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load knowledge packs if any knowledge sources are available
    knowledge_blocks = {}
    try:
        from knowledge import build_knowledge_packs
        packs = build_knowledge_packs(
            brand_path=brand_path,
            competitors_dir=competitors_dir,
            community_path=community_path,
        )
        for agent_key, pack in packs.items():
            block = pack.to_injection_block()
            if block:
                knowledge_blocks[agent_key] = block
                print(f"  Loaded knowledge pack for {agent_key}: {len(pack.sources)} sources")
    except Exception as e:
        print(f"  Warning: could not load knowledge packs: {e}")

    # Save input
    (out_dir / "input.md").write_text(
        f"# Product Forge Input\n\n"
        f"**Prompt:** {prompt}\n\n"
        f"**Image:** {image_path or 'none'}\n\n"
        f"**Timestamp:** {timestamp}\n"
    )

    user_content = _build_user_content(
        f"Analyze the following product concept and create your deliverable.\n\n"
        f"## Brief\n\n{prompt}",
        image_path,
    )

    results = {"phases": {}, "output_dir": str(out_dir)}

    # =========================================================================
    # Phase 1: Individual Analysis (parallel)
    # =========================================================================
    print("\n Phase 1: Individual Analysis")
    print("=" * 60)

    phase1_start = time.time()
    agent_keys = list(AGENTS.keys())

    tasks = [
        _call_agent(
            client, key, user_content,
            knowledge_block=knowledge_blocks.get(key, ""),
        )
        for key in agent_keys
    ]
    outputs = await asyncio.gather(*tasks, return_exceptions=True)

    phase1 = {}
    for key, output in zip(agent_keys, outputs):
        agent = AGENTS[key]
        if isinstance(output, Exception):
            print(f"  {agent['name']} ({agent['title']}): FAILED — {output}")
            phase1[key] = f"[Error: {output}]"
        else:
            print(f"  {agent['name']} ({agent['title']}): {len(output)} chars")
            phase1[key] = output
            # Write individual output
            (out_dir / f"phase1_{key}.md").write_text(
                f"# {agent['name']} — {agent['deliverable']}\n\n{output}"
            )

    results["phases"]["analysis"] = phase1
    print(f"\n  Phase 1 complete in {time.time() - phase1_start:.1f}s")

    if skip_review and skip_synthesis:
        _write_combined(out_dir, results)
        return results

    # =========================================================================
    # Phase 2: Cross-Review (selective pairs)
    # =========================================================================
    if not skip_review:
        print("\n Phase 2: Cross-Review")
        print("=" * 60)

        phase2_start = time.time()

        # Strategic review pairs (each agent reviews the most relevant other)
        review_pairs = [
            ("designer", "pm"),       # Jony reviews Maya's PRD (is it designable?)
            ("pm", "designer"),       # Maya reviews Jony's design (does it match the PRD?)
            ("architect", "engineer"), # Kai reviews Dev's blueprint (is it architecturally sound?)
            ("engineer", "architect"), # Dev reviews Kai's architecture (is it buildable?)
            ("strategist", "pm"),     # Elena reviews Maya's PRD (market fit?)
            ("pm", "strategist"),     # Maya reviews Elena's analysis (actionable?)
        ]

        review_tasks = [
            _call_reviewer(client, reviewer, reviewee, phase1[reviewee], prompt)
            for reviewer, reviewee in review_pairs
        ]
        review_outputs = await asyncio.gather(*review_tasks, return_exceptions=True)

        phase2 = {}
        for (reviewer, reviewee), output in zip(review_pairs, review_outputs):
            pair_key = f"{reviewer}_reviews_{reviewee}"
            reviewer_agent = AGENTS[reviewer]
            reviewee_agent = AGENTS[reviewee]

            if isinstance(output, Exception):
                print(f"  {reviewer_agent['name']} -> {reviewee_agent['name']}: FAILED")
                phase2[pair_key] = f"[Error: {output}]"
            else:
                print(f"  {reviewer_agent['name']} reviews {reviewee_agent['name']}: {len(output)} chars")
                phase2[pair_key] = output

        results["phases"]["reviews"] = phase2

        # Write reviews
        review_md = "# Phase 2: Cross-Reviews\n\n"
        for pair_key, review in phase2.items():
            parts = pair_key.split("_reviews_")
            reviewer_name = AGENTS[parts[0]]["name"]
            reviewee_name = AGENTS[parts[1]]["name"]
            review_md += f"## {reviewer_name} reviews {reviewee_name}\n\n{review}\n\n---\n\n"
        (out_dir / "phase2_reviews.md").write_text(review_md)

        print(f"\n  Phase 2 complete in {time.time() - phase2_start:.1f}s")

    # =========================================================================
    # Phase 3: Synthesis
    # =========================================================================
    if not skip_synthesis:
        print("\n Phase 3: Synthesis")
        print("=" * 60)

        phase3_start = time.time()

        # Build synthesis input
        synth_input = "# Individual Analyses\n\n"
        for key in agent_keys:
            agent = AGENTS[key]
            synth_input += f"## {agent['name']} — {agent['deliverable']}\n\n{phase1[key]}\n\n---\n\n"

        if not skip_review and "reviews" in results["phases"]:
            synth_input += "\n# Cross-Reviews\n\n"
            for pair_key, review in results["phases"]["reviews"].items():
                parts = pair_key.split("_reviews_")
                reviewer_name = AGENTS[parts[0]]["name"]
                reviewee_name = AGENTS[parts[1]]["name"]
                synth_input += f"## {reviewer_name} -> {reviewee_name}\n\n{review}\n\n---\n\n"

        synthesis = await client.messages.create(
            model=SYNTHESIS_MODEL,
            max_tokens=4096,
            system=SYNTHESIS_PROMPT,
            messages=[{"role": "user", "content": synth_input}],
        )
        synthesis_text = synthesis.content[0].text

        results["phases"]["synthesis"] = synthesis_text
        (out_dir / "phase3_synthesis.md").write_text(
            f"# Product Brief — Synthesized\n\n{synthesis_text}"
        )

        print(f"  Synthesis: {len(synthesis_text)} chars")
        print(f"\n  Phase 3 complete in {time.time() - phase3_start:.1f}s")

    # Write combined output
    _write_combined(out_dir, results)

    print(f"\n Output written to {out_dir}/")
    return results


def _write_combined(out_dir: Path, results: dict):
    """Write a single combined markdown file with all phases."""
    combined = "# Product Forge — Complete Output\n\n"
    combined += f"Generated: {datetime.now().isoformat()}\n\n"

    # Phase 1
    combined += "---\n\n# Phase 1: Individual Analysis\n\n"
    for key, output in results["phases"].get("analysis", {}).items():
        agent = AGENTS[key]
        combined += f"## {agent['name']} — {agent['deliverable']}\n\n{output}\n\n---\n\n"

    # Phase 2
    if "reviews" in results["phases"]:
        combined += "# Phase 2: Cross-Reviews\n\n"
        for pair_key, review in results["phases"]["reviews"].items():
            parts = pair_key.split("_reviews_")
            reviewer_name = AGENTS[parts[0]]["name"]
            reviewee_name = AGENTS[parts[1]]["name"]
            combined += f"## {reviewer_name} reviews {reviewee_name}\n\n{review}\n\n---\n\n"

    # Phase 3
    if "synthesis" in results["phases"]:
        combined += "# Phase 3: Synthesized Product Brief\n\n"
        combined += results["phases"]["synthesis"]

    (out_dir / "COMPLETE.md").write_text(combined)
