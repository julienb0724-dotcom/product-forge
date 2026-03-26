"""
Product Forge — Deliberation & Research Systems (v2)

Two systems that transform Product Forge from a one-pass pipeline into
something closer to a real product team:

1. MAILBOX DELIBERATION SYSTEM
   Typed inter-agent messages with challenge/response rounds.
   Modeled after the vIDT mailbox pattern: agents post challenges,
   recipients respond, deliberation continues until convergence.

2. AUTORESEARCH LOOP (Maya & Elena)
   Adapted from Karpathy's autoresearch pattern:
   - Instead of train.py → val_bpb, it's web_search → research_completeness
   - Maya runs autonomous research rounds before producing her PRD
   - Elena can piggyback on Maya's research or run her own rounds
   - The "program.md" equivalent is a research_agenda that the human
     (or the PM agent) defines: what questions need answers, what
     competitive intel is needed, what market data to validate.

Architecture:
  Agents produce deliverables → Mailbox deliberation (2-3 rounds) →
  Agents revise → Synthesis from revised outputs + deliberation transcript
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
import json


# ══════════════════════════════════════════════════════════════════
# PART 1: MAILBOX DELIBERATION SYSTEM
# ══════════════════════════════════════════════════════════════════


class MessageType(Enum):
    """Types of inter-agent messages. Each type implies an expected response."""
    CHALLENGE = "challenge"             # "I disagree with X because Y. Respond."
    QUESTION = "question"               # "I need to understand X before I can proceed."
    DEPENDENCY_FLAG = "dependency_flag"  # "My recommendation depends on your answer to X."
    SCOPE_CONCERN = "scope_concern"     # "This is too big / too small / wrong priority."
    RISK_ESCALATION = "risk_escalation" # "I see a failure mode that affects multiple agents."
    ENDORSEMENT = "endorsement"         # "This is solid. I'm building on it." (stops the loop)
    REVISION_NOTICE = "revision_notice" # "I've updated my deliverable based on your feedback."


class MessagePriority(Enum):
    """Priority determines routing order. BLOCKING must be resolved before synthesis."""
    BLOCKING = "blocking"       # Cannot proceed without resolution
    HIGH = "high"               # Should be resolved, but synthesis can proceed with caveat
    INFORMATIONAL = "info"      # FYI — no response required


class ResolutionStatus(Enum):
    """Track whether a message has been addressed."""
    PENDING = "pending"
    RESPONDED = "responded"
    ACCEPTED = "accepted"       # Sender accepted the response
    REJECTED = "rejected"       # Sender rejected — escalate to synthesis
    WITHDRAWN = "withdrawn"     # Sender withdrew the message


@dataclass
class Message:
    """A single message in the mailbox system."""
    id: str
    sender: str                         # agent key: "designer", "pm", etc.
    recipient: str                      # agent key
    message_type: MessageType
    priority: MessagePriority
    subject: str                        # one-line summary
    body: str                           # full message
    references_deliverable: Optional[str] = None  # which deliverable section this refers to
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    resolution_status: ResolutionStatus = ResolutionStatus.PENDING
    response: Optional[str] = None
    response_timestamp: Optional[str] = None


@dataclass
class DeliberationRound:
    """One round of deliberation. Tracks all messages sent and received."""
    round_number: int
    messages: list[Message] = field(default_factory=list)
    unresolved_blocking: list[str] = field(default_factory=list)  # message IDs

    @property
    def is_converged(self) -> bool:
        """Round is converged when no BLOCKING messages are PENDING."""
        return not any(
            m.priority == MessagePriority.BLOCKING
            and m.resolution_status == ResolutionStatus.PENDING
            for m in self.messages
        )


@dataclass
class Mailbox:
    """
    Central message router for inter-agent deliberation.

    Flow:
    1. After Phase 1 (independent analysis), each agent reads others' deliverables
    2. Agents post messages to the mailbox (challenges, questions, flags)
    3. Router delivers messages to recipients
    4. Recipients respond
    5. Senders evaluate responses (accept/reject)
    6. Repeat for up to MAX_ROUNDS
    7. Unresolved items escalate to synthesis with full transcript
    """
    rounds: list[DeliberationRound] = field(default_factory=list)
    max_rounds: int = 3
    _message_counter: int = 0

    def create_message(
        self,
        sender: str,
        recipient: str,
        message_type: MessageType,
        priority: MessagePriority,
        subject: str,
        body: str,
        references_deliverable: Optional[str] = None,
    ) -> Message:
        """Create a new message with auto-incrementing ID."""
        self._message_counter += 1
        return Message(
            id=f"MSG-{self._message_counter:04d}",
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            priority=priority,
            subject=subject,
            body=body,
            references_deliverable=references_deliverable,
        )

    def get_inbox(self, agent_key: str, round_number: Optional[int] = None) -> list[Message]:
        """Get all pending messages for an agent, optionally filtered by round."""
        messages = []
        rounds = self.rounds if round_number is None else [
            r for r in self.rounds if r.round_number == round_number
        ]
        for round_ in rounds:
            for msg in round_.messages:
                if msg.recipient == agent_key and msg.resolution_status == ResolutionStatus.PENDING:
                    messages.append(msg)
        return messages

    def get_outbox(self, agent_key: str) -> list[Message]:
        """Get all messages sent by an agent across all rounds."""
        messages = []
        for round_ in self.rounds:
            for msg in round_.messages:
                if msg.sender == agent_key:
                    messages.append(msg)
        return messages

    def get_blocking_unresolved(self) -> list[Message]:
        """Get all BLOCKING messages that haven't been resolved."""
        unresolved = []
        for round_ in self.rounds:
            for msg in round_.messages:
                if (
                    msg.priority == MessagePriority.BLOCKING
                    and msg.resolution_status in (
                        ResolutionStatus.PENDING, ResolutionStatus.REJECTED
                    )
                ):
                    unresolved.append(msg)
        return unresolved

    def get_full_transcript(self) -> str:
        """
        Generate the full deliberation transcript for the synthesis prompt.
        Organized by round, then by conversation thread.
        """
        lines = ["# Deliberation Transcript\n"]
        for round_ in self.rounds:
            lines.append(f"## Round {round_.round_number}\n")
            for msg in round_.messages:
                status_icon = {
                    ResolutionStatus.PENDING: "⏳",
                    ResolutionStatus.RESPONDED: "💬",
                    ResolutionStatus.ACCEPTED: "✅",
                    ResolutionStatus.REJECTED: "❌",
                    ResolutionStatus.WITHDRAWN: "🔙",
                }[msg.resolution_status]

                lines.append(
                    f"### {status_icon} {msg.id}: {msg.sender} → {msg.recipient} "
                    f"[{msg.message_type.value}] [{msg.priority.value}]\n"
                    f"**Subject:** {msg.subject}\n\n"
                    f"{msg.body}\n"
                )
                if msg.response:
                    lines.append(
                        f"**Response from {msg.recipient}:**\n\n"
                        f"{msg.response}\n"
                    )
                    lines.append(
                        f"**Resolution:** {msg.resolution_status.value}\n"
                    )
                lines.append("---\n")
        return "\n".join(lines)

    def should_continue(self) -> bool:
        """Determine if another deliberation round is needed."""
        if len(self.rounds) >= self.max_rounds:
            return False
        if not self.rounds:
            return True
        latest = self.rounds[-1]
        return not latest.is_converged


# ──────────────────────────────────────────────────────────────────
# Prompt builders for the deliberation system
# ──────────────────────────────────────────────────────────────────

def build_challenge_prompt(agent_key: str, all_deliverables: dict[str, str]) -> str:
    """
    Build the prompt for an agent to generate challenges after reading
    all other agents' deliverables.

    This replaces the old REVIEW_PROMPT with something that produces
    structured, routable messages instead of freeform reviews.
    """
    from agents import AGENTS  # late import to avoid circular dependency
    agent = AGENTS[agent_key]

    other_deliverables = "\n\n---\n\n".join(
        f"## {AGENTS[k]['name']} ({AGENTS[k]['title']}) — {AGENTS[k]['deliverable']}\n\n{v}"
        for k, v in all_deliverables.items()
        if k != agent_key
    )

    return (
        f"# You are {agent['name']} ({agent['title']})\n\n"
        f"You've read your teammates' deliverables below. Now post messages "
        f"to the team mailbox.\n\n"
        f"## Instructions\n"
        f"For each issue you want to raise, produce a JSON message object:\n"
        f"```json\n"
        f'{{\n'
        f'  "recipient": "<agent_key>",\n'
        f'  "message_type": "challenge|question|dependency_flag|scope_concern|risk_escalation|endorsement",\n'
        f'  "priority": "blocking|high|info",\n'
        f'  "subject": "<one-line summary>",\n'
        f'  "body": "<your full message — specific, actionable, referencing their deliverable>",\n'
        f'  "references_deliverable": "<section name or null>"\n'
        f'}}\n'
        f"```\n\n"
        f"## Rules\n"
        f"- Post 3-6 messages total. Prioritize impact.\n"
        f"- At most 1 BLOCKING message (reserve for genuine showstoppers).\n"
        f"- Use ENDORSEMENT when something is solid — it helps the team know what's settled.\n"
        f"- Be specific. 'The cost estimate is wrong' is not helpful. "
        f"'The cost estimate assumes on-demand DynamoDB at 10K writes/day but Maya's "
        f"activation metric implies 50K writes/day during onboarding spikes' is helpful.\n"
        f"- Reference the specific section of their deliverable you're responding to.\n\n"
        f"## Your Teammates' Deliverables\n\n"
        f"{other_deliverables}\n"
    )


def build_response_prompt(
    agent_key: str,
    inbox: list[Message],
    own_deliverable: str,
) -> str:
    """
    Build the prompt for an agent to respond to their inbox messages.
    """
    from agents import AGENTS
    agent = AGENTS[agent_key]

    inbox_text = "\n\n---\n\n".join(
        f"### {msg.id} from {AGENTS[msg.sender]['name']} "
        f"[{msg.message_type.value}] [{msg.priority.value}]\n"
        f"**Subject:** {msg.subject}\n\n"
        f"{msg.body}"
        for msg in inbox
    )

    return (
        f"# You are {agent['name']} ({agent['title']})\n\n"
        f"You've received the following messages from your teammates. "
        f"Respond to each one.\n\n"
        f"## Your Current Deliverable (for reference)\n\n"
        f"{own_deliverable}\n\n"
        f"---\n\n"
        f"## Messages to Respond To\n\n"
        f"{inbox_text}\n\n"
        f"---\n\n"
        f"## Instructions\n"
        f"For each message, produce a JSON response:\n"
        f"```json\n"
        f'{{\n'
        f'  "message_id": "<MSG-XXXX>",\n'
        f'  "response": "<your detailed response>",\n'
        f'  "action_taken": "accepted|rejected_with_reasoning|needs_discussion|will_revise",\n'
        f'  "revision_note": "<if you will revise your deliverable, describe what changes>"\n'
        f'}}\n'
        f"```\n\n"
        f"## Rules\n"
        f"- BLOCKING messages require substantive responses. Don't hand-wave.\n"
        f"- If they're right, say so and describe your revision.\n"
        f"- If they're wrong, explain why with specifics from your domain expertise.\n"
        f"- If you need more info to respond, say what you need.\n"
        f"- Respond to ALL messages, even ENDORSEMENTS (a brief acknowledgment is fine).\n"
    )


def build_revision_prompt(
    agent_key: str,
    original_deliverable: str,
    accepted_feedback: list[tuple[Message, str]],  # (message, response_text)
) -> str:
    """
    Build the prompt for an agent to revise their deliverable based on
    accepted feedback from deliberation.
    """
    from agents import AGENTS
    agent = AGENTS[agent_key]

    feedback_text = "\n\n---\n\n".join(
        f"### Feedback from {AGENTS[msg.sender]['name']} ({msg.subject})\n\n"
        f"**Their point:** {msg.body}\n\n"
        f"**Your agreed response:** {response}"
        for msg, response in accepted_feedback
    )

    return (
        f"# {agent['name']} — Revision Pass\n\n"
        f"You're revising your {agent['deliverable']} based on feedback "
        f"you accepted during team deliberation.\n\n"
        f"## Original Deliverable\n\n"
        f"{original_deliverable}\n\n"
        f"---\n\n"
        f"## Accepted Feedback to Incorporate\n\n"
        f"{feedback_text}\n\n"
        f"---\n\n"
        f"## Instructions\n"
        f"1. Produce your REVISED deliverable incorporating all accepted feedback.\n"
        f"2. At the top, include a '### Revision Log' section listing each change made "
        f"and which feedback item it addresses.\n"
        f"3. Mark changed sections with [REVISED] so the synthesis can track what moved.\n"
        f"4. Do NOT change sections that weren't challenged — stability matters.\n"
        f"5. If incorporating one change conflicts with another, flag the conflict explicitly.\n"
    )


# ══════════════════════════════════════════════════════════════════
# PART 2: AUTORESEARCH LOOP (Maya & Elena)
# ══════════════════════════════════════════════════════════════════
#
# Adapted from Karpathy's autoresearch pattern:
#
#   Karpathy                    Product Forge
#   ─────────                   ──────────────
#   program.md                  research_agenda (defines what to research)
#   train.py                    research_state (accumulates findings)
#   val_bpb (single metric)    coverage_score (multi-dimensional)
#   5-min GPU run              web_search + synthesis round
#   keep/revert commit         keep/discard finding
#   agent loop                 Maya/Elena research loop
#
# The key insight from Karpathy: the human writes the STRATEGY
# (program.md / research_agenda), the agent executes the TACTICS
# (experiments / searches). The human's leverage is in the quality
# of the research agenda, not in doing the research.
# ══════════════════════════════════════════════════════════════════


class ResearchDimension(Enum):
    """
    Dimensions of research completeness.
    Each dimension has a coverage score (0-100).
    Maya's research loop runs until all dimensions reach threshold OR max rounds hit.
    """
    MARKET_VALIDATION = "market_validation"          # Is the market real? How big?
    COMPETITIVE_INTEL = "competitive_intel"           # Who else is doing this? How?
    USER_PAIN_CONFIRMATION = "user_pain_confirmation" # Real evidence of the problem
    PRICING_SIGNALS = "pricing_signals"               # What are people paying for alternatives?
    REGULATORY_LANDSCAPE = "regulatory_landscape"     # What rules apply? What's changing?
    TECHNOLOGY_LANDSCAPE = "technology_landscape"      # What's technically possible now?
    DISTRIBUTION_CHANNELS = "distribution_channels"   # How do you reach the user?
    BUSINESS_MODEL_EVIDENCE = "business_model_evidence"  # What models work in this space?


@dataclass
class ResearchFinding:
    """A single finding from a research round. Analogous to one experiment in autoresearch."""
    id: str
    round_number: int
    dimension: ResearchDimension
    query: str                          # The search query or research question
    source: str                         # Where this came from (URL, search result, etc.)
    summary: str                        # 2-3 sentence synthesis of the finding
    confidence: str                     # HIGH / MEDIUM / LOW
    key_data_points: list[str]          # Specific numbers, quotes, facts extracted
    implications_for_prd: str           # How this changes the PRD
    kept: bool = True                   # Analogous to keep/revert in autoresearch
    discard_reason: Optional[str] = None


@dataclass
class ResearchState:
    """
    Accumulating research state. Analogous to the evolving train.py.

    After each round, the coverage scores update and the research agenda
    can be refined (analogous to how autoresearch commits improvements
    to the codebase).
    """
    findings: list[ResearchFinding] = field(default_factory=list)
    coverage_scores: dict[str, int] = field(default_factory=lambda: {
        d.value: 0 for d in ResearchDimension
    })
    rounds_completed: int = 0
    max_rounds: int = 5                 # Cap to prevent infinite research loops
    coverage_threshold: int = 60        # Minimum score to consider a dimension "covered"
    _finding_counter: int = 0

    def add_finding(self, finding: ResearchFinding) -> None:
        """Add a finding and update coverage scores."""
        self.findings.append(finding)
        if finding.kept:
            # Increment coverage for this dimension
            current = self.coverage_scores[finding.dimension.value]
            # Diminishing returns: each finding adds less as coverage increases
            increment = max(5, 25 - current // 4)
            self.coverage_scores[finding.dimension.value] = min(100, current + increment)

    def get_gaps(self) -> list[ResearchDimension]:
        """Return dimensions below the coverage threshold."""
        return [
            ResearchDimension(dim)
            for dim, score in self.coverage_scores.items()
            if score < self.coverage_threshold
        ]

    def should_continue(self) -> bool:
        """
        Should we run another research round?
        Analogous to autoresearch's loop condition.
        """
        if self.rounds_completed >= self.max_rounds:
            return False
        gaps = self.get_gaps()
        return len(gaps) > 0

    def get_coverage_report(self) -> str:
        """Human-readable coverage report."""
        lines = ["## Research Coverage Report\n"]
        for dim in ResearchDimension:
            score = self.coverage_scores[dim.value]
            bar = "█" * (score // 5) + "░" * (20 - score // 5)
            status = "✅" if score >= self.coverage_threshold else "🔍"
            lines.append(f"{status} **{dim.value}**: [{bar}] {score}/100")
        lines.append(f"\nRounds completed: {self.rounds_completed}/{self.max_rounds}")
        gaps = self.get_gaps()
        if gaps:
            lines.append(f"Gaps remaining: {', '.join(g.value for g in gaps)}")
        else:
            lines.append("All dimensions meet threshold. Research complete.")
        return "\n".join(lines)

    def get_findings_summary(self) -> str:
        """
        Summarize all kept findings for injection into Maya's PRD prompt.
        This is the research equivalent of the optimized train.py.
        """
        if not self.findings:
            return "No research findings yet."

        kept = [f for f in self.findings if f.kept]
        by_dimension: dict[str, list[ResearchFinding]] = {}
        for f in kept:
            by_dimension.setdefault(f.dimension.value, []).append(f)

        lines = ["## Research Findings Summary\n"]
        for dim in ResearchDimension:
            findings = by_dimension.get(dim.value, [])
            if not findings:
                lines.append(f"### {dim.value}\nNo findings yet.\n")
                continue
            lines.append(f"### {dim.value} ({len(findings)} findings)\n")
            for f in findings:
                lines.append(
                    f"- **[{f.confidence}]** {f.summary}\n"
                    f"  - Source: {f.source}\n"
                    f"  - Key data: {'; '.join(f.key_data_points)}\n"
                    f"  - PRD implication: {f.implications_for_prd}\n"
                )
        return "\n".join(lines)


@dataclass
class ResearchAgenda:
    """
    The human-authored research strategy. Analogous to program.md.

    This is where the PM's (or human's) judgment lives:
    - What questions need answers
    - What dimensions to prioritize
    - What sources to prefer
    - What constraints to respect

    Like program.md, this is the artifact the human iterates on.
    The quality of the research agenda determines the quality of
    the autonomous research output.
    """
    product_concept: str                # one paragraph describing the product idea
    target_market: str                  # who is this for
    priority_dimensions: list[ResearchDimension]  # which dimensions to research first
    specific_questions: list[str]       # explicit questions the research must answer
    known_competitors: list[str]        # seed list of competitors to investigate
    geographic_focus: str               # e.g., "US residential", "EU commercial"
    constraints: list[str]              # e.g., "Must work with existing Emporia hardware"
    search_preferences: list[str]       # preferred source types: "SEC filings", "utility PUC filings"

    def to_prompt(self) -> str:
        """Render the research agenda as a prompt section."""
        priority_str = ", ".join(d.value for d in self.priority_dimensions)
        questions_str = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(self.specific_questions))
        competitors_str = ", ".join(self.known_competitors)
        constraints_str = "\n".join(f"  - {c}" for c in self.constraints)
        preferences_str = ", ".join(self.search_preferences)

        return (
            f"## Research Agenda\n\n"
            f"### Product Concept\n{self.product_concept}\n\n"
            f"### Target Market\n{self.target_market}\n\n"
            f"### Priority Research Dimensions\n{priority_str}\n\n"
            f"### Questions That Must Be Answered\n{questions_str}\n\n"
            f"### Known Competitors to Investigate\n{competitors_str}\n\n"
            f"### Geographic Focus\n{self.geographic_focus}\n\n"
            f"### Constraints\n{constraints_str}\n\n"
            f"### Preferred Sources\n{preferences_str}\n"
        )


# ──────────────────────────────────────────────────────────────────
# Research loop prompt builders
# ──────────────────────────────────────────────────────────────────

def build_research_round_prompt(
    agenda: ResearchAgenda,
    state: ResearchState,
    round_number: int,
) -> str:
    """
    Build the prompt for one research round.
    Analogous to autoresearch's experiment loop iteration.

    The agent will:
    1. Read the agenda and current coverage
    2. Identify the biggest gap
    3. Formulate 3-5 search queries
    4. Execute searches (via tool use)
    5. Synthesize findings
    6. Score each finding (keep/discard)
    7. Update the coverage report
    """
    gaps = state.get_gaps()
    gap_str = ", ".join(g.value for g in gaps) if gaps else "None — all covered"

    return (
        f"# Product Research — Round {round_number}\n\n"
        f"You are Maya, conducting autonomous product research.\n\n"
        f"{agenda.to_prompt()}\n\n"
        f"---\n\n"
        f"## Current Research State\n\n"
        f"{state.get_coverage_report()}\n\n"
        f"## Previous Findings (for context, do not repeat)\n\n"
        f"{state.get_findings_summary()}\n\n"
        f"---\n\n"
        f"## This Round's Objective\n\n"
        f"**Gaps to fill:** {gap_str}\n\n"
        f"Focus this round on the dimension with the LOWEST coverage score. "
        f"If multiple dimensions are tied, prioritize based on the research agenda's "
        f"priority order.\n\n"
        f"## Instructions\n\n"
        f"1. **Identify target dimension**: pick the biggest gap.\n"
        f"2. **Formulate 3-5 search queries**: specific, varied, targeting different "
        f"aspects of the dimension. Good queries are 2-6 words, specific to the domain.\n"
        f"3. **Execute searches**: use web_search for each query.\n"
        f"4. **Synthesize findings**: for each useful result, produce a finding:\n"
        f"```json\n"
        f'{{\n'
        f'  "dimension": "<dimension_value>",\n'
        f'  "query": "<the search query used>",\n'
        f'  "source": "<url or description>",\n'
        f'  "summary": "<2-3 sentence synthesis>",\n'
        f'  "confidence": "HIGH|MEDIUM|LOW",\n'
        f'  "key_data_points": ["<specific numbers, facts, quotes>"],\n'
        f'  "implications_for_prd": "<how this changes what we should build>",\n'
        f'  "kept": true,\n'
        f'  "discard_reason": null\n'
        f'}}\n'
        f"```\n"
        f"5. **Discard low-value findings**: if a search returns nothing useful, "
        f"produce the finding with `kept: false` and explain why in `discard_reason`.\n"
        f"6. **Update coverage assessment**: estimate new coverage score for the dimension.\n\n"
        f"## Quality Bar\n"
        f"- **Keep** findings with: specific data points, named sources, actionable implications.\n"
        f"- **Discard** findings with: vague claims, no numbers, restatements of common knowledge.\n"
        f"- Like autoresearch: if the finding doesn't improve the research state, revert it.\n"
    )


def build_research_informed_prd_prompt(
    agent_key: str,
    brief: str,
    research_state: ResearchState,
) -> str:
    """
    Build Maya's PRD prompt enriched with research findings.
    This is the payoff — Maya doesn't guess about markets, she KNOWS.
    """
    from agents import AGENTS, AGENT_META
    agent = AGENTS[agent_key]

    return (
        f"# {agent['name']} — {agent['title']}\n\n"
        f"{agent['persona']}\n\n"
        f"---\n\n"
        f"{AGENT_META}\n\n"
        f"---\n\n"
        f"# Research-Informed PRD\n\n"
        f"You have completed {research_state.rounds_completed} rounds of autonomous "
        f"product research. Below are your validated findings. Your PRD must be "
        f"grounded in this research — cite specific findings, not general knowledge.\n\n"
        f"{research_state.get_findings_summary()}\n\n"
        f"{research_state.get_coverage_report()}\n\n"
        f"---\n\n"
        f"# Your Deliverable: {agent['deliverable']}\n\n"
        f"{agent['output_format']}\n\n"
        f"---\n\n"
        f"# Product Brief\n\n"
        f"{brief}\n\n"
        f"---\n\n"
        f"## Additional PRD Requirements (research-informed)\n\n"
        f"Because you have real research data, your PRD must:\n"
        f"1. **Cite findings**: reference specific research findings by dimension when "
        f"making market claims, competitive assertions, or pricing assumptions.\n"
        f"2. **Flag low-confidence areas**: where research coverage is below threshold, "
        f"explicitly mark those sections as 'needs validation' with specific research "
        f"questions that remain unanswered.\n"
        f"3. **Quantify with real data**: use actual numbers from your research, not "
        f"estimates. If you didn't find a number, say so.\n"
        f"4. **Name real competitors**: reference specific companies and products from "
        f"your competitive intel, not generic 'competitors in the space'.\n"
        f"5. **Connect regulatory findings**: if your research uncovered regulatory "
        f"tailwinds or headwinds, they must appear in both the opportunity section "
        f"AND the risks section.\n\n"
        f"Now produce your {agent['deliverable']}. Follow your output format precisely."
    )


# ══════════════════════════════════════════════════════════════════
# PART 3: ORCHESTRATION — Full Pipeline
# ══════════════════════════════════════════════════════════════════

def build_enhanced_synthesis_prompt(
    agent_outputs: dict[str, str],
    revised_outputs: dict[str, str],
    mailbox: Mailbox,
    research_state: Optional[ResearchState] = None,
) -> str:
    """
    Build the synthesis prompt that includes:
    - Original deliverables
    - Revised deliverables (post-deliberation)
    - Full deliberation transcript
    - Research findings (if research loop was used)
    - Unresolved blocking items (must be decided by synthesis)
    """
    from agents import AGENTS, SYNTHESIS_PROMPT

    sections = []

    # Research context (if available)
    if research_state and research_state.findings:
        sections.append(
            "# Research Foundation\n\n"
            "Maya conducted autonomous product research before producing her PRD. "
            "The findings below informed her analysis and should be treated as "
            "validated market intelligence.\n\n"
            f"{research_state.get_coverage_report()}\n\n"
            f"{research_state.get_findings_summary()}\n\n"
        )

    # Original deliverables
    sections.append("# Original Analyses (Pre-Deliberation)\n")
    for key in ["designer", "pm", "architect", "strategist", "engineer"]:
        agent = AGENTS[key]
        sections.append(
            f"## {agent['name']} ({agent['title']}) — {agent['deliverable']}\n\n"
            f"{agent_outputs.get(key, '[Not yet submitted]')}\n\n"
        )

    # Deliberation transcript
    sections.append(mailbox.get_full_transcript())

    # Revised deliverables
    if revised_outputs:
        sections.append("\n# Revised Analyses (Post-Deliberation)\n")
        for key, output in revised_outputs.items():
            agent = AGENTS[key]
            sections.append(
                f"## {agent['name']} ({agent['title']}) — REVISED {agent['deliverable']}\n\n"
                f"{output}\n\n"
            )

    # Unresolved items that synthesis MUST decide
    blocking = mailbox.get_blocking_unresolved()
    if blocking:
        sections.append(
            "\n# ⚠️ UNRESOLVED BLOCKING ITEMS\n\n"
            "The following issues were not resolved during deliberation. "
            "You MUST make a decision on each one in your synthesis.\n\n"
        )
        for msg in blocking:
            from agents import AGENTS as A
            sections.append(
                f"- **{msg.id}**: {A[msg.sender]['name']} → {A[msg.recipient]['name']}: "
                f"{msg.subject}\n"
                f"  {msg.body}\n"
                f"  Response: {msg.response or 'No response'}\n\n"
            )

    return SYNTHESIS_PROMPT + "\n\n---\n\n" + "\n".join(sections)


# ══════════════════════════════════════════════════════════════════
# PART 4: PIPELINE DEFINITION
# ══════════════════════════════════════════════════════════════════

PIPELINE_PHASES = """
# Product Forge Pipeline (v2)

## Phase 0: Research (Maya + Elena) — "The Karpathy Loop"
- Human writes research_agenda (analogous to program.md)
- Maya runs autonomous research rounds (web search → synthesize → score → keep/discard)
- Continues until coverage thresholds met or max rounds hit
- Elena reviews research findings and adds strategic context
- Output: ResearchState with validated findings

## Phase 1: Independent Analysis
- All 5 agents produce deliverables from the brief
- Maya's deliverable is research-informed (cites actual findings)
- Elena can reference Maya's research state for market data
- Other agents work from brief + their domain expertise

## Phase 2: Mailbox Deliberation (2-3 rounds)
- Round 1: All agents read all deliverables, post messages to mailbox
  - Challenges, questions, dependency flags, scope concerns, risk escalations
  - Each agent posts 3-6 messages
- Round 2: Recipients respond to inbox, senders evaluate responses
  - Accept → agent will revise deliverable
  - Reject → escalate to synthesis
  - Needs discussion → another round
- Round 3 (if needed): resolve remaining blocking items

## Phase 3: Revision
- Each agent with accepted feedback revises their deliverable
- Revisions are tracked with a revision log
- Original + revised deliverables both go to synthesis

## Phase 4: Synthesis
- Team lead synthesizes revised deliverables + deliberation transcript
- Must resolve all unresolved blocking items
- Produces the final product brief with:
  - Conflict resolutions
  - V1 scope (consensus)
  - Risk register
  - 30-day execution plan
  - Go/no-go criteria
"""
