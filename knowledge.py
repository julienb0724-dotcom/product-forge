"""
Product Forge — Agent Knowledge System (v2)

Transforms generalist agents into domain experts through runtime knowledge injection.

Architecture:
  - Knowledge Packs: structured domain context loaded at runtime
  - Community Voice: Reddit/forum mining for real customer language
  - Brand System: design constraints from brand guidelines
  - Competitive Dossiers: deep-dive files on specific competitors
  - Regulatory Briefings: policy/regulatory context by jurisdiction
  - Technical Specs: hardware/API documentation for integration context

Each agent has a `knowledge_pack` attribute that determines which
knowledge sources are injected into their prompt at runtime. This is
analogous to the `field_guide_path` pattern in vIDT — structured
context loaded per-agent, not baked into the persona.

Design principle: personas define HOW agents think.
Knowledge packs define WHAT they know.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json


# ══════════════════════════════════════════════════════════════════
# PART 1: KNOWLEDGE PACK ARCHITECTURE
# ══════════════════════════════════════════════════════════════════


class KnowledgeType(Enum):
    """Categories of injectable knowledge."""
    COMMUNITY_VOICE = "community_voice"       # Reddit, forums, app reviews
    BRAND_SYSTEM = "brand_system"             # Brand guidelines, design system
    COMPETITIVE_DOSSIER = "competitive_dossier"  # Deep competitor profiles
    REGULATORY_BRIEFING = "regulatory_briefing"  # Policy/regulatory context
    TECHNICAL_SPEC = "technical_spec"          # Hardware/API documentation
    DOMAIN_TAXONOMY = "domain_taxonomy"        # SOPs, classification systems
    USER_RESEARCH = "user_research"            # Interview transcripts, survey data
    FINANCIAL_MODEL = "financial_model"        # Unit economics, pricing data


@dataclass
class KnowledgeSource:
    """
    A single knowledge source that can be injected into an agent's context.

    Analogous to vIDT's field guide files — structured context loaded at runtime.
    """
    id: str
    name: str
    knowledge_type: KnowledgeType
    description: str                    # What this source contains and why it matters
    content: str                        # The actual knowledge (markdown formatted)
    source_urls: list[str] = field(default_factory=list)  # Where this came from
    last_updated: str = ""              # ISO date — staleness tracking
    token_estimate: int = 0             # Rough token count for context budget management
    relevance_tags: list[str] = field(default_factory=list)  # For matching to agent queries

    def to_injection_block(self) -> str:
        """Format this source for injection into an agent prompt."""
        return (
            f"### {self.name}\n"
            f"*Type: {self.knowledge_type.value} | "
            f"Updated: {self.last_updated or 'unknown'}*\n\n"
            f"{self.content}\n"
        )


@dataclass
class KnowledgePack:
    """
    A curated bundle of knowledge sources assigned to an agent.

    Each agent gets a KnowledgePack that defines their domain expertise
    beyond what's in their persona. The pack is injected between the
    persona and the output format in the prompt.

    Token budget management: packs have a max_tokens limit to prevent
    context window overflow. Sources are prioritized by relevance.
    """
    agent_key: str
    sources: list[KnowledgeSource] = field(default_factory=list)
    max_tokens: int = 8000              # Budget for knowledge injection

    def add_source(self, source: KnowledgeSource) -> None:
        """Add a source, respecting token budget."""
        current_tokens = sum(s.token_estimate for s in self.sources)
        if current_tokens + source.token_estimate > self.max_tokens:
            print(
                f"Warning: adding '{source.name}' ({source.token_estimate} tokens) "
                f"would exceed budget ({current_tokens}/{self.max_tokens}). "
                f"Consider removing a lower-priority source."
            )
        self.sources.append(source)

    def to_injection_block(self) -> str:
        """Render the full knowledge pack for prompt injection."""
        if not self.sources:
            return ""
        blocks = [
            "---\n\n"
            "# Domain Knowledge (injected at runtime)\n\n"
            "The following is proprietary context that informs your analysis. "
            "Cite this knowledge where relevant. Flag when your recommendations "
            "conflict with or extend beyond this context.\n\n"
        ]
        for source in self.sources:
            blocks.append(source.to_injection_block())
        return "\n".join(blocks)


# ══════════════════════════════════════════════════════════════════
# PART 2: COMMUNITY VOICE MINING
# ══════════════════════════════════════════════════════════════════
#
# This is the system for mining Reddit, app reviews, forums, etc.
# for real customer language that Maya and Elena can use.
#
# The output is structured: not raw posts, but synthesized themes
# with representative quotes and sentiment signals.
# ══════════════════════════════════════════════════════════════════


@dataclass
class CommunityTheme:
    """A recurring theme extracted from community discussions."""
    theme: str                          # e.g., "Frustration with cost visibility"
    sentiment: str                      # positive / negative / mixed / neutral
    frequency: str                      # how often this appears: rare / common / dominant
    representative_quotes: list[str]    # 3-5 real quotes (anonymized)
    user_segments: list[str]            # who says this
    product_implications: str           # what this means for product decisions
    competing_solutions_mentioned: list[str]  # products users reference as alternatives


@dataclass
class CommunityVoiceProfile:
    """
    Structured synthesis of community discussions.
    This is what gets injected into Maya's and Elena's knowledge packs.
    """
    sources: list[str]                  # subreddits, forums, app stores
    collection_date: str                # when this was gathered
    total_posts_analyzed: int
    themes: list[CommunityTheme]
    top_feature_requests: list[str]     # ranked by frequency
    top_complaints: list[str]           # ranked by severity x frequency
    language_patterns: dict[str, list[str]]  # how users describe things in their own words

    def to_knowledge_source(self) -> KnowledgeSource:
        """Convert to a KnowledgeSource for injection."""
        lines = [
            f"**Sources:** {', '.join(self.sources)}\n"
            f"**Analyzed:** {self.total_posts_analyzed} posts "
            f"(collected {self.collection_date})\n\n"
        ]

        # Themes
        lines.append("#### Key Themes\n")
        for theme in self.themes:
            lines.append(
                f"**{theme.theme}** [{theme.sentiment}, {theme.frequency}]\n"
                f"- Who says this: {', '.join(theme.user_segments)}\n"
                f"- Product implication: {theme.product_implications}\n"
                f"- Alternatives mentioned: {', '.join(theme.competing_solutions_mentioned) or 'none'}\n"
                f"- Representative voices:\n"
            )
            for quote in theme.representative_quotes[:3]:
                lines.append(f'  > "{quote}"\n')
            lines.append("")

        # Feature requests
        lines.append("#### Top Feature Requests (by frequency)\n")
        for i, req in enumerate(self.top_feature_requests, 1):
            lines.append(f"{i}. {req}")
        lines.append("")

        # Complaints
        lines.append("#### Top Complaints (by severity x frequency)\n")
        for i, complaint in enumerate(self.top_complaints, 1):
            lines.append(f"{i}. {complaint}")
        lines.append("")

        # Language patterns
        lines.append("#### How Users Actually Talk About This\n")
        lines.append(
            "*Use these phrases in user stories and UI copy. "
            "Match the language your users actually use.*\n"
        )
        for concept, phrases in self.language_patterns.items():
            quoted = ['"' + p + '"' for p in phrases]
            lines.append(f"- **{concept}**: {', '.join(quoted)}")
        lines.append("")

        content = "\n".join(lines)
        token_est = len(content) // 4  # rough approximation

        return KnowledgeSource(
            id="community_voice",
            name="Community Voice Profile",
            knowledge_type=KnowledgeType.COMMUNITY_VOICE,
            description=(
                "Synthesized themes from user communities. "
                "Contains real customer language, feature requests, complaints, "
                "and competitive product mentions."
            ),
            content=content,
            source_urls=[f"https://reddit.com/r/{s}" for s in self.sources if "/" not in s],
            last_updated=self.collection_date,
            token_estimate=token_est,
            relevance_tags=[
                "user feedback", "feature requests",
                "complaints", "competitive intel", "user language",
            ],
        )


# ══════════════════════════════════════════════════════════════════
# PART 3: BRAND SYSTEM INTEGRATION
# ══════════════════════════════════════════════════════════════════
#
# Jony needs the brand guidelines to produce implementable designs.
# This structure defines what to extract from brand guidelines and
# how to inject it as design constraints.
# ══════════════════════════════════════════════════════════════════


@dataclass
class BrandSystem:
    """
    Structured brand guidelines for injection into Jony's knowledge pack.

    When you load brand guidelines, extract into this structure.
    This ensures Jony's design specs use the actual brand system, not generic tokens.
    """
    # Identity
    brand_name: str = ""
    tagline: str = ""
    brand_voice: str = ""
    brand_personality: list[str] = field(default_factory=list)

    # Visual Identity
    logo_usage: str = ""
    primary_colors: dict[str, str] = field(default_factory=dict)
    secondary_colors: dict[str, str] = field(default_factory=dict)
    accent_colors: dict[str, str] = field(default_factory=dict)
    semantic_color_mapping: dict[str, str] = field(default_factory=dict)

    # Typography
    primary_typeface: str = ""
    secondary_typeface: str = ""
    type_scale: dict[str, str] = field(default_factory=dict)

    # Spacing & Layout
    grid_system: str = ""
    spacing_scale: list[int] = field(default_factory=list)
    border_radius: str = ""
    shadow_system: str = ""

    # Imagery & Iconography
    photography_style: str = ""
    icon_style: str = ""
    illustration_style: str = ""

    # Tone of Voice
    writing_principles: list[str] = field(default_factory=list)
    terminology_preferences: dict[str, str] = field(default_factory=dict)

    def to_knowledge_source(self) -> KnowledgeSource:
        """Convert brand system to injectable knowledge for Jony."""
        lines = ["#### Brand Identity\n"]
        if self.brand_name:
            lines.append(f"**Brand:** {self.brand_name}")
        if self.tagline:
            lines.append(f"**Tagline:** {self.tagline}")
        if self.brand_voice:
            lines.append(f"**Voice:** {self.brand_voice}")
        if self.brand_personality:
            lines.append(f"**Personality:** {', '.join(self.brand_personality)}")
        lines.append("")

        # Colors
        lines.append("#### Color System\n")
        if self.primary_colors:
            lines.append("**Primary:**")
            for name, value in self.primary_colors.items():
                lines.append(f"  - `{name}`: {value}")
        if self.secondary_colors:
            lines.append("**Secondary:**")
            for name, value in self.secondary_colors.items():
                lines.append(f"  - `{name}`: {value}")
        if self.accent_colors:
            lines.append("**Accent:**")
            for name, value in self.accent_colors.items():
                lines.append(f"  - `{name}`: {value}")
        if self.semantic_color_mapping:
            lines.append("**Semantic Mapping:**")
            for semantic, color in self.semantic_color_mapping.items():
                lines.append(f"  - `{semantic}` → {color}")
        lines.append("")

        # Typography
        if self.primary_typeface or self.type_scale:
            lines.append("#### Typography\n")
            if self.primary_typeface:
                lines.append(f"**Primary typeface:** {self.primary_typeface}")
            if self.secondary_typeface:
                lines.append(f"**Secondary typeface:** {self.secondary_typeface}")
            if self.type_scale:
                lines.append("**Type scale:**")
                for level, spec in self.type_scale.items():
                    lines.append(f"  - `{level}`: {spec}")
            lines.append("")

        # Spacing
        if self.grid_system or self.spacing_scale:
            lines.append("#### Spacing & Layout\n")
            if self.grid_system:
                lines.append(f"**Grid:** {self.grid_system}")
            if self.spacing_scale:
                lines.append(f"**Scale:** {', '.join(str(s) for s in self.spacing_scale)}px")
            if self.border_radius:
                lines.append(f"**Radius:** {self.border_radius}")
            if self.shadow_system:
                lines.append(f"**Shadows:** {self.shadow_system}")
            lines.append("")

        # Imagery
        if self.photography_style or self.icon_style:
            lines.append("#### Imagery & Icons\n")
            if self.photography_style:
                lines.append(f"**Photography:** {self.photography_style}")
            if self.icon_style:
                lines.append(f"**Icons:** {self.icon_style}")
            if self.illustration_style:
                lines.append(f"**Illustrations:** {self.illustration_style}")
            lines.append("")

        # Tone of voice
        if self.writing_principles or self.terminology_preferences:
            lines.append("#### Tone of Voice\n")
            if self.writing_principles:
                for principle in self.writing_principles:
                    lines.append(f"- {principle}")
            if self.terminology_preferences:
                lines.append("\n**Terminology:**")
                for directive, term in self.terminology_preferences.items():
                    lines.append(f"  - {directive}: *{term}*")
            lines.append("")

        # Logo
        if self.logo_usage:
            lines.append("#### Logo Usage\n")
            lines.append(self.logo_usage)
            lines.append("")

        content = "\n".join(lines)
        return KnowledgeSource(
            id=f"brand_system_{self.brand_name.lower().replace(' ', '_') if self.brand_name else 'default'}",
            name=f"{self.brand_name or 'Brand'} System",
            knowledge_type=KnowledgeType.BRAND_SYSTEM,
            description=(
                f"Brand guidelines for {self.brand_name or 'the product'} including colors, typography, "
                "spacing, imagery rules, and tone of voice. All design "
                "specifications must conform to these constraints."
            ),
            content=content,
            last_updated="",
            token_estimate=len(content) // 4,
            relevance_tags=[
                "brand", "design system", "colors", "typography",
                "logo", "visual identity", "tone of voice",
            ],
        )


# ══════════════════════════════════════════════════════════════════
# PART 4: COMPETITIVE DOSSIERS
# ══════════════════════════════════════════════════════════════════


@dataclass
class CompetitorDossier:
    """
    Deep profile of a single competitor. Elena and Maya both use these.
    Much richer than what a single search round would produce.
    """
    company_name: str
    website: str
    products: list[dict]                # [{"name": "...", "price": "...", "category": "..."}]
    positioning: str                    # one paragraph on their strategy
    target_customer: str
    pricing_model: str                  # hardware margin, SaaS, freemium, etc.
    strengths: list[str]
    weaknesses: list[str]
    recent_moves: list[str]             # last 6 months: launches, partnerships, funding
    ecosystem_integrations: list[str]   # what they connect to
    data_moat: str                      # what proprietary data they have
    app_store_rating: Optional[float] = None
    estimated_user_base: Optional[str] = None
    key_differentiator: str = ""
    threat_assessment: str = ""         # how this competitor threatens the product

    def to_knowledge_source(self) -> KnowledgeSource:
        """Convert to injectable knowledge."""
        lines = [
            f"**Company:** [{self.company_name}]({self.website})\n"
            f"**Positioning:** {self.positioning}\n"
            f"**Target:** {self.target_customer}\n"
            f"**Pricing:** {self.pricing_model}\n"
        ]
        if self.estimated_user_base:
            lines.append(f"**Est. users:** {self.estimated_user_base}")
        if self.app_store_rating:
            lines.append(f"**App rating:** {self.app_store_rating}/5.0")
        if self.key_differentiator:
            lines.append(f"**Key differentiator:** {self.key_differentiator}")
        lines.append("")

        lines.append("**Products:**")
        for p in self.products:
            lines.append(f"  - {p.get('name', '?')} — {p.get('price', '?')} ({p.get('category', '')})")
        lines.append("")

        lines.append("**Strengths:**")
        for s in self.strengths:
            lines.append(f"  - {s}")
        lines.append("")

        lines.append("**Weaknesses:**")
        for w in self.weaknesses:
            lines.append(f"  - {w}")
        lines.append("")

        lines.append("**Recent moves (last 6mo):**")
        for m in self.recent_moves:
            lines.append(f"  - {m}")
        lines.append("")

        lines.append("**Integrations:**")
        lines.append(f"  {', '.join(self.ecosystem_integrations)}")
        lines.append("")

        lines.append(f"**Data moat:** {self.data_moat}")
        lines.append("")

        if self.threat_assessment:
            lines.append(f"**Threat assessment:** {self.threat_assessment}")
            lines.append("")

        content = "\n".join(lines)
        return KnowledgeSource(
            id=f"competitor_{self.company_name.lower().replace(' ', '_')}",
            name=f"Competitor Dossier: {self.company_name}",
            knowledge_type=KnowledgeType.COMPETITIVE_DOSSIER,
            description=f"Deep competitive profile of {self.company_name}.",
            content=content,
            source_urls=[self.website],
            token_estimate=len(content) // 4,
            relevance_tags=[
                self.company_name.lower(), "competitor", "competitive intel",
            ],
        )


# ══════════════════════════════════════════════════════════════════
# PART 5: KNOWLEDGE PACK TEMPLATES
# ══════════════════════════════════════════════════════════════════
#
# Default knowledge pack assignments per agent.
# These define which knowledge types each agent receives.
# ══════════════════════════════════════════════════════════════════

AGENT_KNOWLEDGE_ASSIGNMENTS = {
    "designer": {
        "receives": [
            KnowledgeType.BRAND_SYSTEM,
            KnowledgeType.COMMUNITY_VOICE,
            KnowledgeType.COMPETITIVE_DOSSIER,
            KnowledgeType.USER_RESEARCH,
        ],
        "injection_note": (
            "Jony receives brand guidelines as HARD CONSTRAINTS — his design specs "
            "must conform to these. Community voice informs UI copy and feature "
            "prioritization. Competitor dossiers show what UX patterns exist in "
            "the market (to borrow or differentiate from)."
        ),
    },
    "pm": {
        "receives": [
            KnowledgeType.COMMUNITY_VOICE,
            KnowledgeType.COMPETITIVE_DOSSIER,
            KnowledgeType.USER_RESEARCH,
            KnowledgeType.FINANCIAL_MODEL,
            KnowledgeType.DOMAIN_TAXONOMY,
        ],
        "injection_note": (
            "Maya receives community voice as her PRIMARY research input — real "
            "customer language shapes user stories, feature priority, and the "
            "problem statement. Competitor dossiers validate (or challenge) her "
            "market assumptions. Financial models ground her business case."
        ),
    },
    "architect": {
        "receives": [
            KnowledgeType.TECHNICAL_SPEC,
            KnowledgeType.DOMAIN_TAXONOMY,
        ],
        "injection_note": (
            "Kai receives technical specs for integration targets (APIs, data formats). "
            "Domain taxonomies inform his data model. "
            "He does NOT receive brand or community data — those are not his domain."
        ),
    },
    "strategist": {
        "receives": [
            KnowledgeType.COMPETITIVE_DOSSIER,
            KnowledgeType.REGULATORY_BRIEFING,
            KnowledgeType.COMMUNITY_VOICE,
            KnowledgeType.FINANCIAL_MODEL,
        ],
        "injection_note": (
            "Elena receives the richest knowledge pack because her analysis spans "
            "the widest territory. Competitor dossiers are her primary input. "
            "Regulatory briefings inform her moat and risk analysis. Community "
            "voice gives her ground-truth on consumer sentiment."
        ),
    },
    "engineer": {
        "receives": [
            KnowledgeType.TECHNICAL_SPEC,
            KnowledgeType.BRAND_SYSTEM,
        ],
        "injection_note": (
            "Dev receives technical specs for APIs he needs to integrate with "
            "and the brand system so he can translate design tokens directly "
            "into theme configuration."
        ),
    },
}


# ══════════════════════════════════════════════════════════════════
# PART 6: PROMPT INTEGRATION
# ══════════════════════════════════════════════════════════════════


def build_knowledge_enriched_prompt(
    agent_key: str,
    brief: str,
    knowledge_pack: Optional[KnowledgePack] = None,
) -> str:
    """
    Build a full agent prompt with knowledge pack injected.

    Prompt structure:
    1. Agent persona (from agents.py)
    2. Domain knowledge (from knowledge pack)
    3. Shared meta-instructions
    4. Output format
    5. Product brief

    The knowledge sits between persona and meta-instructions because
    it's contextual expertise — more specific than the persona's general
    principles, but broader than the specific brief.
    """
    from agents import AGENTS, AGENT_META
    agent = AGENTS[agent_key]

    knowledge_block = ""
    if knowledge_pack and knowledge_pack.sources:
        knowledge_block = knowledge_pack.to_injection_block()

    return (
        f"# {agent['name']} — {agent['title']}\n\n"
        f"{agent['persona']}\n\n"
        f"{knowledge_block}\n\n"
        f"---\n\n"
        f"{AGENT_META}\n\n"
        f"---\n\n"
        f"# Your Deliverable: {agent['deliverable']}\n\n"
        f"{agent['output_format']}\n\n"
        f"---\n\n"
        f"# Product Brief\n\n"
        f"{brief}\n\n"
        f"---\n\n"
        f"Now produce your {agent['deliverable']}. Follow your output format precisely. "
        f"Reference your domain knowledge where relevant — cite specific data points, "
        f"brand constraints, and competitive intelligence. "
        f"Flag your confidence level on key recommendations. Challenge the brief where needed. "
        f"Tag cross-agent dependencies."
    )


# ══════════════════════════════════════════════════════════════════
# PART 7: GENERIC KNOWLEDGE LOADING FROM DIRECTORIES
# ══════════════════════════════════════════════════════════════════
#
# Loads knowledge from the knowledge/ directory structure.
# Each subdirectory contains JSON files that are loaded generically.
# No hardcoded brand/product names.
# ══════════════════════════════════════════════════════════════════

KNOWLEDGE_BASE = Path(__file__).parent / "knowledge"


def _load_json_files(directory: Path) -> list[dict]:
    """Load all JSON files from a directory. Returns empty list if dir doesn't exist."""
    if not directory.exists() or not directory.is_dir():
        return []
    results = []
    for f in sorted(directory.glob("*.json")):
        try:
            with open(f) as fh:
                results.append(json.load(fh))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not load {f}: {e}")
    return results


def load_brand_knowledge(brand_path: Optional[str] = None) -> Optional[KnowledgeSource]:
    """
    Load brand knowledge from a specific JSON file or the knowledge/brand/ directory.

    Args:
        brand_path: Optional path to a specific brand JSON file.
                    If None, loads from knowledge/brand/ (first file found).

    Returns:
        KnowledgeSource or None if no brand data found.
    """
    if brand_path:
        try:
            with open(brand_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not load brand file {brand_path}: {e}")
            return None
    else:
        files = _load_json_files(KNOWLEDGE_BASE / "brand")
        if not files:
            return None
        data = files[0]

    brand = BrandSystem(
        brand_name=data.get("brand_name", ""),
        tagline=data.get("tagline", ""),
        brand_voice=data.get("brand_voice", ""),
        brand_personality=data.get("brand_personality", []),
        logo_usage=data.get("logo_usage", ""),
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
    )
    return brand.to_knowledge_source()


def load_community_knowledge(community_path: Optional[str] = None) -> Optional[KnowledgeSource]:
    """
    Load community voice from a specific JSON file or the knowledge/community/ directory.

    Returns KnowledgeSource or None if no community data found.
    """
    if community_path:
        try:
            with open(community_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not load community file {community_path}: {e}")
            return None
    else:
        files = _load_json_files(KNOWLEDGE_BASE / "community")
        if not files:
            return None
        data = files[0]

    themes = []
    for t in data.get("themes", []):
        themes.append(CommunityTheme(
            theme=t.get("theme", ""),
            sentiment=t.get("sentiment", "neutral"),
            frequency=t.get("frequency", "common"),
            representative_quotes=t.get("representative_quotes", []),
            user_segments=t.get("user_segments", []),
            product_implications=t.get("product_implications", ""),
            competing_solutions_mentioned=t.get("competing_solutions_mentioned", []),
        ))

    profile = CommunityVoiceProfile(
        sources=data.get("sources", []),
        collection_date=data.get("collection_date", ""),
        total_posts_analyzed=data.get("total_posts_analyzed", 0),
        themes=themes,
        top_feature_requests=data.get("top_feature_requests", []),
        top_complaints=data.get("top_complaints", []),
        language_patterns=data.get("language_patterns", {}),
    )
    return profile.to_knowledge_source()


def load_competitor_knowledge(competitors_dir: Optional[str] = None) -> list[KnowledgeSource]:
    """
    Load competitor dossiers from a directory of JSON files.

    Args:
        competitors_dir: Optional path to directory of competitor JSON files.
                         If None, loads from knowledge/competitors/.

    Returns:
        List of KnowledgeSource objects (one per competitor). Empty list if none found.
    """
    directory = Path(competitors_dir) if competitors_dir else KNOWLEDGE_BASE / "competitors"
    files = _load_json_files(directory)
    sources = []
    for data in files:
        dossier = CompetitorDossier(
            company_name=data.get("company_name", "Unknown"),
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
        sources.append(dossier.to_knowledge_source())
    return sources


def load_regulatory_knowledge() -> list[KnowledgeSource]:
    """Load regulatory briefings from knowledge/regulatory/ directory."""
    files = _load_json_files(KNOWLEDGE_BASE / "regulatory")
    sources = []
    for data in files:
        content = data.get("content", json.dumps(data, indent=2))
        name = data.get("name", "Regulatory Briefing")
        ks = KnowledgeSource(
            id=f"regulatory_{name.lower().replace(' ', '_')}",
            name=name,
            knowledge_type=KnowledgeType.REGULATORY_BRIEFING,
            description=data.get("description", "Regulatory context"),
            content=content if isinstance(content, str) else json.dumps(content, indent=2),
            last_updated=data.get("last_updated", ""),
            token_estimate=len(str(content)) // 4,
            relevance_tags=data.get("tags", ["regulatory"]),
        )
        sources.append(ks)
    return sources


def load_technical_knowledge() -> list[KnowledgeSource]:
    """Load technical specs from knowledge/technical/ directory."""
    files = _load_json_files(KNOWLEDGE_BASE / "technical")
    sources = []
    for data in files:
        content = data.get("content", json.dumps(data, indent=2))
        name = data.get("name", "Technical Specification")
        ks = KnowledgeSource(
            id=f"technical_{name.lower().replace(' ', '_')}",
            name=name,
            knowledge_type=KnowledgeType.TECHNICAL_SPEC,
            description=data.get("description", "Technical specification"),
            content=content if isinstance(content, str) else json.dumps(content, indent=2),
            last_updated=data.get("last_updated", ""),
            token_estimate=len(str(content)) // 4,
            relevance_tags=data.get("tags", ["technical"]),
        )
        sources.append(ks)
    return sources


def build_knowledge_packs(
    brand_path: Optional[str] = None,
    competitors_dir: Optional[str] = None,
    community_path: Optional[str] = None,
) -> dict[str, KnowledgePack]:
    """
    Build knowledge packs for all agents from available knowledge sources.

    Loads from the knowledge/ directory structure by default.
    Override paths for brand, competitors, or community data as needed.

    Returns:
        dict mapping agent_key -> KnowledgePack
    """
    # Load all available knowledge
    brand_source = load_brand_knowledge(brand_path)
    community_source = load_community_knowledge(community_path)
    competitor_sources = load_competitor_knowledge(competitors_dir)
    regulatory_sources = load_regulatory_knowledge()
    technical_sources = load_technical_knowledge()

    # Build a lookup by type
    sources_by_type: dict[KnowledgeType, list[KnowledgeSource]] = {
        KnowledgeType.BRAND_SYSTEM: [brand_source] if brand_source else [],
        KnowledgeType.COMMUNITY_VOICE: [community_source] if community_source else [],
        KnowledgeType.COMPETITIVE_DOSSIER: competitor_sources,
        KnowledgeType.REGULATORY_BRIEFING: regulatory_sources,
        KnowledgeType.TECHNICAL_SPEC: technical_sources,
        KnowledgeType.DOMAIN_TAXONOMY: [],
        KnowledgeType.USER_RESEARCH: [],
        KnowledgeType.FINANCIAL_MODEL: [],
    }

    # Build packs per agent
    packs = {}
    for agent_key, assignment in AGENT_KNOWLEDGE_ASSIGNMENTS.items():
        pack = KnowledgePack(agent_key=agent_key)
        for ktype in assignment["receives"]:
            for source in sources_by_type.get(ktype, []):
                pack.add_source(source)
        packs[agent_key] = pack

    return packs
