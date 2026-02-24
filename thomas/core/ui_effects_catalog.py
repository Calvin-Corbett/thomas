"""Curated UI effects catalog for Thomas UI workflows."""

from __future__ import annotations

from typing import Any, Dict, List

EFFECTS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "view-transitions-native",
        "name": "Native View Transitions",
        "category": "transitions",
        "summary": "Browser-native cross-state/page transitions with minimal JS.",
        "reference_url": "https://developer.mozilla.org/en-US/docs/Web/API/View_Transitions_API",
        "cost": "low",
        "accessibility": "respect reduced-motion preferences",
        "notes": "Use for route swaps and card-to-detail transitions.",
    },
    {
        "id": "scroll-driven-animations",
        "name": "Scroll Timeline Effects",
        "category": "motion",
        "summary": "Declarative scroll-linked animations using CSS timelines.",
        "reference_url": "https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_scroll-driven_animations",
        "cost": "medium",
        "accessibility": "add reduced-motion fallback",
        "notes": "Best for progressive reveals and timeline storytelling.",
    },
    {
        "id": "container-query-layouts",
        "name": "Container Query Layouts",
        "category": "responsive",
        "summary": "Component-level responsive behavior independent of viewport.",
        "reference_url": "https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries",
        "cost": "low",
        "accessibility": "n/a",
        "notes": "Use to keep card/composer components consistent across tabs.",
    },
    {
        "id": "gsap-timeline-choreo",
        "name": "GSAP Timeline Choreography",
        "category": "motion",
        "summary": "Fine-grained staggered choreography for premium interactions.",
        "reference_url": "https://gsap.com/docs/v3/",
        "cost": "medium",
        "accessibility": "gate with reduced-motion checks",
        "notes": "Use for hero intros and guided attention movement.",
    },
    {
        "id": "motion-one-springs",
        "name": "Motion One Springs",
        "category": "motion",
        "summary": "Tiny animation runtime for spring interactions.",
        "reference_url": "https://motion.dev/docs",
        "cost": "low",
        "accessibility": "support reduced-motion shortcuts",
        "notes": "Good for subtle card, button, and panel micro-feel.",
    },
    {
        "id": "backdrop-filter-depth",
        "name": "Backdrop Filter Depth",
        "category": "visual",
        "summary": "Glass-like layered depth with blur and translucency.",
        "reference_url": "https://developer.mozilla.org/en-US/docs/Web/CSS/backdrop-filter",
        "cost": "medium",
        "accessibility": "ensure contrast passes",
        "notes": "Use sparingly on overlays and fixed toolbars.",
    },
    {
        "id": "web-rendering-performance",
        "name": "Rendering Performance Guardrails",
        "category": "quality",
        "summary": "Reduce jank with transform/opacity and avoid layout thrash.",
        "reference_url": "https://web.dev/articles/rendering-performance",
        "cost": "low",
        "accessibility": "n/a",
        "notes": "Required for smooth 60fps transitions on weaker devices.",
    },
]
