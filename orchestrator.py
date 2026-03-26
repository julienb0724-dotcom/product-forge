#!/usr/bin/env python3
"""
Product Forge — Pipeline Orchestrator (v2)

Executes the full 5-phase product development pipeline:

  Phase 0: Research (Maya's AutoResearch loop)
  Phase 1: Independent Analysis (all 5 agents)
  Phase 2: Mailbox Deliberation (2-3 rounds)
  Phase 3: Revision (agents incorporate accepted feedback)
  Phase 4: Synthesis (Opus resolves conflicts, produces unified brief)

Usage:
  python orchestrator.py "Your product brief here"
  python orchestrator.py --brief research_agendas/emporia_energy_dashboard.md
  python orchestrator.py --phase 1 "brief"   # run only Phase 1
  python orchestrator.py --skip-research "brief"  # skip Phase 0

Requires: ANTHROPIC_API_KEY
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))

from agents import AGENTS, AGENT_META
from deliberation import (
    Mailbox, MessageType, MessagePriority, ResolutionStatus,
    DeliberationRound, Message,
    ResearchDimension, ResearchFinding, ResearchState,
    build_challenge_prompt, build_response_prompt, build_revision_prompt,
)
from knowledge import (
    KnowledgePack, KnowledgeSource, KnowledgeType,
    BrandSystem, CompetitorDossier, CommunityVoiceProfile,
    AGENT_KNOWLEDGE_ASSIGNMENTS,
    build_emporia_technical_spec, build_knowledge_enriched_prompt,
)

# Models
AGENT_MODEL = "claude-sonnet-4-6"
SYNTHESIS_MODEL = "claude-opus-4-6"

# Limits
MAX_RESEARCH_ROUNDS = 5
RESEARCH_COVERAGE_THRESHOLD = 60
MAX_DELIBERATION_ROUNDS = 3
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]


# ══════════════════════════════════════════════════════════════════
# Token / cost tracking
# ══════════════════════════════════════════════════════════════════

class TokenTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def record(self, resp):
        self.input_tokens += resp.usage.input_tokens
        self.output_tokens += resp.usage.output_tokens
        self.calls += 1

    def cost_estimate(self) -> float:
        # Sonnet: $3/1M input, $15/1M output; Opus: $15/1M input, $75/1M output
        # Use blended estimate (mostly Sonnet)
        return (self.input_tokens * 4 / 1_000_000) + (self.output_tokens * 18 / 1_000_000)

    def summary(self) -> str:
        return (
            f"API calls: {self.calls} | "
            f"Input: {self.input_tokens:,} tokens | "
            f"Output: {self.output_tokens:,} tokens | "
            f"Est. cost: ${self.cost_estimate():.2f}"
        )


# ══════════════════════════════════════════════════════════════════
# LLM call with retry
# ══════════════════════════════════════════════════════════════════

async def call_llm(
    client: anthropic.AsyncAnthropic,
    tracker: TokenTracker,
    model: str,
    system: str,
    user_content: str,
    max_tokens: int = 4096,
) -> str:
    """Call Claude with exponential backoff retry."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            tracker.record(resp)
            return resp.content[0].text
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                print(f"    Retry {attempt + 1}/{MAX_RETRIES} in {wait}s: {e}")
                await asyncio.sleep(wait)
            else:
                raise


# ══════════════════════════════════════════════════════════════════
# Knowledge pack loader
# ══════════════════════════════════════════════════════════════════

def load_knowledge_packs() -> dict[str, KnowledgePack]:
    """Load all available knowledge into per-agent packs."""
    knowledge_dir = Path(__file__).parent / "knowledge"
    packs: dict[str, KnowledgePack] = {}

    for agent_key in AGENTS:
        packs[agent_key] = KnowledgePack(agent_key=agent_key)

    # Brand system → designer, engineer
    brand_path = knowledge_dir / "brand" / "emporia_brand_system.json"
    if brand_path.exists():
        with open(brand_path) as f:
            data = json.load(f)
        brand = BrandSystem(
            brand_name=data.get("brand_name", ""),
            tagline=data.get("tagline", ""),
            brand_voice=data.get("brand_voice", ""),
            brand_personality=data.get("brand_personality", []),
            primary_colors=data.get("primary_colors", {}),
            secondary_colors=data.get("secondary_colors", {}),
            accent_colors=data.get("accent_colors", {}),
            semantic_color_mapping=data.get("semantic_color_mapping", {}),
            primary_typeface=data.get("primary_typeface", ""),
            secondary_typeface=data.get("secondary_typeface", ""),
            type_scale=data.get("type_scale", {}),
            grid_system=data.get("grid_system", ""),
            spacing_scale=data.get("spacing_scale", []),
            border_radius=data.get("border_radius", ""),
            shadow_system=data.get("shadow_system", ""),
            photography_style=data.get("photography_style", ""),
            icon_style=data.get("icon_style", ""),
            illustration_style=data.get("illustration_style", ""),
            writing_principles=data.get("writing_principles", []),
            terminology_preferences=data.get("terminology_preferences", {}),
            logo_usage=data.get("logo_usage", ""),
        )
        ks = brand.to_knowledge_source()
        for key in ["designer", "engineer"]:
            packs[key].add_source(ks)

    # Community voice → pm, strategist, designer
    community_path = knowledge_dir / "community" / "emporia_community_voice.json"
    if community_path.exists():
        with open(community_path) as f:
            data = json.load(f)
        from knowledge import CommunityTheme
        profile = CommunityVoiceProfile(
            sources=data.get("sources", []),
            collection_date=data.get("collection_date", ""),
            total_posts_analyzed=data.get("total_posts_analyzed", 0),
            themes=[CommunityTheme(**t) for t in data.get("themes", [])],
            top_feature_requests=data.get("top_feature_requests", []),
            top_complaints=data.get("top_complaints", []),
            language_patterns=data.get("language_patterns", {}),
        )
        ks = profile.to_knowledge_source()
        for key in ["pm", "strategist", "designer"]:
            packs[key].add_source(ks)

    # Competitor dossiers → pm, strategist, designer
    competitors_dir = knowledge_dir / "competitors"
    if competitors_dir.exists():
        for fp in sorted(competitors_dir.glob("*.json")):
            with open(fp) as f:
                data = json.load(f)
            if "error" in data:
                continue
            dossier = CompetitorDossier(
                company_name=data.get("company_name", fp.stem),
                website=data.get("website", ""),
                products=data.get("products", []),
                positioning=data.get("positioning", ""),
                target_customer=data.get("target_customer", ""),
                pricing_model=data.get("pricing_model", ""),
                strengths=data.get("strengths", []),
                weaknesses=data.get("weaknesses", []),
                recent_moves=data.get("recent_moves", []),
                ecosystem_integrations=data.get("ecosystem_integrations", []),
                data_moat=data.get("data_moat", ""),
                app_store_rating=data.get("app_store_rating"),
                estimated_user_base=data.get("estimated_user_base"),
                key_differentiator=data.get("key_differentiator", ""),
                threat_assessment=data.get("threat_assessment", ""),
            )
            ks = dossier.to_knowledge_source()
            for key in ["pm", "strategist", "designer"]:
                packs[key].add_source(ks)

    # Technical spec → architect, engineer
    tech_ks = build_emporia_technical_spec()
    for key in ["architect", "engineer"]:
        packs[key].add_source(tech_ks)

    return packs


# ══════════════════════════════════════════════════════════════════
# Phase 0: AutoResearch (Maya)
# ══════════════════════════════════════════════════════════════════

async def phase0_research(
    client: anthropic.AsyncAnthropic,
    tracker: TokenTracker,
    brief: str,
    out_dir: Path,
) -> ResearchState:
    """Run Maya's autonomous research loop."""
    print("\n Phase 0: AutoResearch (Maya)")
    print("=" * 60)

    state = ResearchState(max_rounds=MAX_RESEARCH_ROUNDS, coverage_threshold=RESEARCH_COVERAGE_THRESHOLD)
    (out_dir / "phase0_research").mkdir(parents=True, exist_ok=True)

    while state.should_continue():
        state.rounds_completed += 1
        gaps = state.get_gaps()
        target = gaps[0] if gaps else list(ResearchDimension)[0]

        print(f"\n  Round {state.rounds_completed}/{state.max_rounds} — targeting: {target.value}")
        print(f"  Coverage: {state.coverage_scores[target.value]}/100")

        # Web search is a server-managed tool — Claude handles it in a single call
        research_system = (
            "You are Maya, a product manager conducting autonomous market research. "
            "You are building a PRD for an Emporia Energy product.\n\n"
            "Use web search to find real, current data. Search 2-3 queries.\n\n"
            "After searching, synthesize your findings as a JSON array:\n"
            "```json\n[\n"
            '  {"dimension": "...", "query": "search query used", "source": "url",\n'
            '   "summary": "2-3 sentence synthesis", "confidence": "HIGH|MEDIUM|LOW",\n'
            '   "key_data_points": ["specific fact 1", "fact 2"],\n'
            '   "implications_for_prd": "how this changes the PRD"}\n'
            "]\n```"
        )
        research_user = (
            f"## Product Brief\n{brief[:4000]}\n\n"
            f"## Research Target\n"
            f"Dimension: **{target.value}**\n"
            f"Current coverage: {state.coverage_scores[target.value]}%\n\n"
            f"## Previous Findings\n{state.get_findings_summary()[:2000]}\n\n"
            f"Search the web for current information about {target.value} "
            f"related to this product concept. Focus on the biggest gap in our knowledge."
        )

        web_search_tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
        try:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.messages.create(
                        model=AGENT_MODEL,
                        max_tokens=4096,
                        system=research_system,
                        messages=[{"role": "user", "content": research_user}],
                        tools=[web_search_tool],
                    )
                    tracker.record(resp)
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        wait = RETRY_BACKOFF[attempt]
                        print(f"    Retry {attempt+1}/{MAX_RETRIES} in {wait}s: {e}")
                        await asyncio.sleep(wait)
                    else:
                        raise

            # Extract text from response (web search results are inline)
            raw = "\n".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception as e:
            print(f"    Research round failed: {e}")
            raw = ""

        # Parse findings
        json_match = re.search(r'\[[\s\S]*?\]', raw)
        if json_match:
            try:
                findings_data = json.loads(json_match.group())
                for fd in findings_data:
                    state._finding_counter += 1
                    finding = ResearchFinding(
                        id=f"RF-{state._finding_counter:04d}",
                        round_number=state.rounds_completed,
                        dimension=ResearchDimension(fd.get("dimension", target.value)),
                        query=fd.get("query", ""),
                        source=fd.get("source", ""),
                        summary=fd.get("summary", ""),
                        confidence=fd.get("confidence", "MEDIUM"),
                        key_data_points=fd.get("key_data_points", []),
                        implications_for_prd=fd.get("implications_for_prd", ""),
                    )
                    state.add_finding(finding)
                    print(f"    [{finding.confidence}] {finding.summary[:80]}...")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"    Warning: could not parse findings: {e}")

    # Save research state
    report = state.get_coverage_report()
    summary = state.get_findings_summary()
    (out_dir / "phase0_research" / "coverage_report.md").write_text(report)
    (out_dir / "phase0_research" / "findings_summary.md").write_text(summary)

    print(f"\n{report}")
    return state


# ══════════════════════════════════════════════════════════════════
# Phase 1: Independent Analysis
# ══════════════════════════════════════════════════════════════════

async def phase1_analysis(
    client: anthropic.AsyncAnthropic,
    tracker: TokenTracker,
    brief: str,
    knowledge_packs: dict[str, KnowledgePack],
    research_state: Optional[ResearchState],
    out_dir: Path,
) -> dict[str, str]:
    """Run all 5 agents in parallel."""
    print("\n Phase 1: Independent Analysis")
    print("=" * 60)

    (out_dir / "phase1_deliverables").mkdir(parents=True, exist_ok=True)

    # Enrich Maya's brief with research findings
    enriched_briefs = {}
    for key in AGENTS:
        enriched = brief
        if research_state and key in ("pm", "strategist"):
            enriched += f"\n\n## Research Findings\n{research_state.get_findings_summary()}"
        enriched_briefs[key] = enriched

    async def run_agent(key: str) -> tuple[str, str]:
        agent = AGENTS[key]
        prompt = build_knowledge_enriched_prompt(key, enriched_briefs[key], knowledge_packs.get(key))
        text = await call_llm(client, tracker, AGENT_MODEL, prompt, "Produce your deliverable now.", max_tokens=6000)
        print(f"  {agent['name']} ({agent['title']}): {len(text)} chars")
        return key, text

    tasks = [run_agent(key) for key in AGENTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    deliverables = {}
    for result in results:
        if isinstance(result, Exception):
            print(f"  FAILED: {result}")
            continue
        key, text = result
        deliverables[key] = text
        (out_dir / "phase1_deliverables" / f"{key}.md").write_text(
            f"# {AGENTS[key]['name']} — {AGENTS[key]['deliverable']}\n\n{text}"
        )

    return deliverables


# ══════════════════════════════════════════════════════════════════
# Phase 2: Mailbox Deliberation
# ══════════════════════════════════════════════════════════════════

async def phase2_deliberation(
    client: anthropic.AsyncAnthropic,
    tracker: TokenTracker,
    deliverables: dict[str, str],
    out_dir: Path,
) -> Mailbox:
    """Run 2-3 rounds of inter-agent deliberation."""
    print("\n Phase 2: Mailbox Deliberation")
    print("=" * 60)

    (out_dir / "phase2_deliberation").mkdir(parents=True, exist_ok=True)
    mailbox = Mailbox()

    for round_num in range(1, MAX_DELIBERATION_ROUNDS + 1):
        if round_num > 1 and not mailbox.should_continue():
            print(f"  Round {round_num}: converged, skipping")
            break

        print(f"\n  Round {round_num}: Challenge Phase")
        round_ = DeliberationRound(round_number=round_num)

        # Each agent posts challenges
        async def post_challenges(agent_key: str):
            prompt = build_challenge_prompt(agent_key, deliverables)
            raw = await call_llm(client, tracker, AGENT_MODEL, prompt,
                                 "Post your messages to the mailbox now.", max_tokens=3000)

            # Parse JSON messages from response
            messages = []
            for match in re.finditer(r'\{[^{}]*\}', raw, re.DOTALL):
                try:
                    data = json.loads(match.group())
                    if "recipient" in data and "body" in data:
                        msg = mailbox.create_message(
                            sender=agent_key,
                            recipient=data.get("recipient", ""),
                            message_type=MessageType(data.get("message_type", "question")),
                            priority=MessagePriority(data.get("priority", "high")),
                            subject=data.get("subject", ""),
                            body=data.get("body", ""),
                            references_deliverable=data.get("references_deliverable"),
                        )
                        messages.append(msg)
                except (json.JSONDecodeError, ValueError):
                    continue

            name = AGENTS[agent_key]["name"]
            print(f"    {name}: {len(messages)} messages")
            return messages

        # Run all agents' challenges in parallel
        challenge_tasks = [post_challenges(key) for key in deliverables]
        all_messages = await asyncio.gather(*challenge_tasks, return_exceptions=True)

        for result in all_messages:
            if isinstance(result, Exception):
                continue
            for msg in result:
                round_.messages.append(msg)

        mailbox.rounds.append(round_)

        # Response phase
        if round_num <= 2:  # only respond in first 2 rounds
            print(f"\n  Round {round_num}: Response Phase")

            async def respond(agent_key: str):
                inbox = mailbox.get_inbox(agent_key, round_num)
                if not inbox:
                    return []

                prompt = build_response_prompt(agent_key, inbox, deliverables.get(agent_key, ""))
                raw = await call_llm(client, tracker, AGENT_MODEL, prompt,
                                     "Respond to all messages in your inbox.", max_tokens=3000)

                responses = []
                for match in re.finditer(r'\{[^{}]*\}', raw, re.DOTALL):
                    try:
                        data = json.loads(match.group())
                        if "message_id" in data:
                            responses.append(data)
                    except json.JSONDecodeError:
                        continue

                # Apply responses to messages
                for resp_data in responses:
                    msg_id = resp_data.get("message_id", "")
                    for msg in inbox:
                        if msg.id == msg_id:
                            msg.response = resp_data.get("response", "")
                            msg.response_timestamp = datetime.now().isoformat()
                            action = resp_data.get("action_taken", "accepted")
                            if "accept" in action or "revise" in action:
                                msg.resolution_status = ResolutionStatus.ACCEPTED
                            elif "reject" in action:
                                msg.resolution_status = ResolutionStatus.REJECTED
                            else:
                                msg.resolution_status = ResolutionStatus.RESPONDED

                name = AGENTS[agent_key]["name"]
                print(f"    {name}: responded to {len(responses)} messages")
                return responses

            response_tasks = [respond(key) for key in deliverables]
            await asyncio.gather(*response_tasks, return_exceptions=True)

    # Save transcript
    transcript = mailbox.get_full_transcript()
    (out_dir / "phase2_deliberation" / "transcript.md").write_text(transcript)

    blocking = mailbox.get_blocking_unresolved()
    print(f"\n  Deliberation complete: {sum(len(r.messages) for r in mailbox.rounds)} messages, "
          f"{len(blocking)} unresolved blocking")

    return mailbox


# ══════════════════════════════════════════════════════════════════
# Phase 3: Revision
# ══════════════════════════════════════════════════════════════════

async def phase3_revision(
    client: anthropic.AsyncAnthropic,
    tracker: TokenTracker,
    deliverables: dict[str, str],
    mailbox: Mailbox,
    out_dir: Path,
) -> dict[str, str]:
    """Agents revise their deliverables based on accepted feedback."""
    print("\n Phase 3: Revision")
    print("=" * 60)

    (out_dir / "phase3_revisions").mkdir(parents=True, exist_ok=True)
    revised = dict(deliverables)  # start with originals

    for agent_key in deliverables:
        # Collect accepted feedback for this agent
        accepted = []
        for round_ in mailbox.rounds:
            for msg in round_.messages:
                if msg.recipient == agent_key and msg.resolution_status == ResolutionStatus.ACCEPTED:
                    accepted.append((msg, msg.response or ""))

        if not accepted:
            print(f"  {AGENTS[agent_key]['name']}: no accepted feedback, skipping")
            continue

        prompt = build_revision_prompt(agent_key, deliverables[agent_key], accepted)
        text = await call_llm(client, tracker, AGENT_MODEL, prompt,
                              "Produce your revised deliverable now.", max_tokens=6000)

        revised[agent_key] = text
        (out_dir / "phase3_revisions" / f"{agent_key}_revised.md").write_text(
            f"# {AGENTS[agent_key]['name']} — Revised {AGENTS[agent_key]['deliverable']}\n\n{text}"
        )
        print(f"  {AGENTS[agent_key]['name']}: revised ({len(accepted)} feedback items incorporated)")

    return revised


# ══════════════════════════════════════════════════════════════════
# Phase 4: Synthesis
# ══════════════════════════════════════════════════════════════════

async def phase4_synthesis(
    client: anthropic.AsyncAnthropic,
    tracker: TokenTracker,
    deliverables: dict[str, str],
    mailbox: Optional[Mailbox],
    research_state: Optional[ResearchState],
    out_dir: Path,
) -> str:
    """Opus synthesizes everything into a unified product brief."""
    print("\n Phase 4: Synthesis")
    print("=" * 60)

    (out_dir / "phase4_synthesis").mkdir(parents=True, exist_ok=True)

    # Build synthesis input
    sections = ["# Individual Deliverables\n"]
    for key, text in deliverables.items():
        agent = AGENTS[key]
        sections.append(f"## {agent['name']} — {agent['deliverable']}\n\n{text}\n\n---\n")

    if mailbox:
        sections.append(f"\n{mailbox.get_full_transcript()}")
        blocking = mailbox.get_blocking_unresolved()
        if blocking:
            sections.append("\n# UNRESOLVED BLOCKING ITEMS (you must decide)\n")
            for msg in blocking:
                sections.append(f"- **{msg.id}**: {msg.sender} → {msg.recipient}: {msg.subject}\n  {msg.body}\n")

    if research_state:
        sections.append(f"\n# Research Findings\n{research_state.get_findings_summary()}")

    synth_input = "\n".join(sections)

    synthesis_system = (
        "You are the product team lead synthesizing the work of five specialists: "
        "Jony (Design), Maya (Product), Kai (Architecture), Elena (Strategy), Dev (Engineering).\n\n"
        "Below are their deliverables, cross-reviews, and any unresolved debates.\n\n"
        "Produce a unified product brief that:\n"
        "1. Resolves all conflicts between deliverables\n"
        "2. Highlights the 3 most critical decisions the team needs to align on\n"
        "3. Defines a clear V1 scope that all perspectives agree on\n"
        "4. Identifies the single biggest risk and mitigation\n"
        "5. Outlines the first 30 days of execution\n"
        "6. For any UNRESOLVED BLOCKING items, make a final decision with reasoning\n\n"
        "Be concise. This document should be readable in 5 minutes."
    )

    text = await call_llm(client, tracker, SYNTHESIS_MODEL, synthesis_system, synth_input, max_tokens=8000)

    (out_dir / "phase4_synthesis" / "product_brief.md").write_text(
        f"# Synthesized Product Brief\n\n{text}"
    )
    print(f"  Synthesis: {len(text)} chars")
    return text


# ══════════════════════════════════════════════════════════════════
# Main orchestrator
# ══════════════════════════════════════════════════════════════════

async def run_pipeline(
    brief: str,
    phases: Optional[list[int]] = None,
    skip_research: bool = False,
    output_dir: Optional[str] = None,
) -> dict:
    """Run the full pipeline."""
    client = anthropic.AsyncAnthropic()
    tracker = TokenTracker()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir) if output_dir else Path(__file__).parent / "outputs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save brief
    (out_dir / "brief.md").write_text(brief)

    run_phases = phases or [0, 1, 2, 3, 4]

    print(f"\n{'=' * 60}")
    print(f" Product Forge v2 — Run {run_id}")
    print(f"{'=' * 60}")
    print(f"Phases: {run_phases}")
    print(f"Output: {out_dir}")

    # Load knowledge
    print("\nLoading knowledge packs...")
    knowledge_packs = load_knowledge_packs()
    for key, pack in knowledge_packs.items():
        tokens = sum(s.token_estimate for s in pack.sources)
        if tokens > 0:
            print(f"  {AGENTS[key]['name']}: {len(pack.sources)} sources, {tokens} tokens")

    results = {}

    # Phase 0
    research_state = None
    if 0 in run_phases and not skip_research:
        t0 = time.time()
        research_state = await phase0_research(client, tracker, brief, out_dir)
        results["phase0_time"] = round(time.time() - t0, 1)

    # Phase 1
    deliverables = {}
    if 1 in run_phases:
        t0 = time.time()
        deliverables = await phase1_analysis(client, tracker, brief, knowledge_packs, research_state, out_dir)
        results["phase1_time"] = round(time.time() - t0, 1)

    # Phase 2
    mailbox = None
    if 2 in run_phases and deliverables:
        t0 = time.time()
        mailbox = await phase2_deliberation(client, tracker, deliverables, out_dir)
        results["phase2_time"] = round(time.time() - t0, 1)

    # Phase 3
    revised = deliverables
    if 3 in run_phases and deliverables and mailbox:
        t0 = time.time()
        revised = await phase3_revision(client, tracker, deliverables, mailbox, out_dir)
        results["phase3_time"] = round(time.time() - t0, 1)

    # Phase 4
    if 4 in run_phases and revised:
        t0 = time.time()
        synthesis = await phase4_synthesis(client, tracker, revised, mailbox, research_state, out_dir)
        results["phase4_time"] = round(time.time() - t0, 1)
        results["synthesis"] = synthesis

    # Write combined output
    combined = f"# Product Forge v2 — Complete Output\n\nRun: {run_id}\n\n"
    for key, text in revised.items():
        agent = AGENTS[key]
        combined += f"---\n\n## {agent['name']} — {agent['deliverable']}\n\n{text}\n\n"
    if "synthesis" in results:
        combined += f"---\n\n## Synthesized Product Brief\n\n{results['synthesis']}\n"
    (out_dir / "COMPLETE.md").write_text(combined)

    # Final summary
    print(f"\n{'=' * 60}")
    print(f" Pipeline Complete")
    print(f"{'=' * 60}")
    print(f"Output: {out_dir}/COMPLETE.md")
    print(f"{tracker.summary()}")
    for phase, key in [(0, "phase0_time"), (1, "phase1_time"), (2, "phase2_time"),
                       (3, "phase3_time"), (4, "phase4_time")]:
        if key in results:
            print(f"  Phase {phase}: {results[key]}s")

    results["output_dir"] = str(out_dir)
    results["token_summary"] = tracker.summary()
    return results


def main():
    parser = argparse.ArgumentParser(description="Product Forge v2 — Pipeline Orchestrator")
    parser.add_argument("brief", nargs="?", help="Product brief text (or use --brief-file)")
    parser.add_argument("--brief-file", "-f", help="Path to brief file (markdown)")
    parser.add_argument("--phase", "-p", type=int, action="append", help="Run specific phase(s) only")
    parser.add_argument("--skip-research", action="store_true", help="Skip Phase 0 (research)")
    parser.add_argument("--output", "-o", help="Output directory")

    args = parser.parse_args()

    # Load brief
    brief = args.brief
    if args.brief_file:
        brief = Path(args.brief_file).read_text()
    elif not brief and not sys.stdin.isatty():
        brief = sys.stdin.read().strip()

    if not brief:
        parser.print_help()
        print("\nError: provide a brief as argument, --brief-file, or via stdin")
        sys.exit(1)

    asyncio.run(run_pipeline(
        brief=brief,
        phases=args.phase,
        skip_research=args.skip_research,
        output_dir=args.output,
    ))


if __name__ == "__main__":
    main()
