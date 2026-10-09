# -*- coding: utf-8 -*-
"""Which files the framework owns inside a hub, and how templates are rendered."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from cc_hub import __version__
from cc_hub.encoding import read_text

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Overwritten by `cc-hub update` (after backup).
FRAMEWORK_OWNED: tuple[str, ...] = (
    "AGENTS.md",
    "BOOTSTRAP.md",
    ".gitignore",
    "cron/README.md",
    "cron/memory-consolidate.md",
    "skills/hub-adapt/SKILL.md",
    "skills/hub-apps/SKILL.md",
    "skills/hub-apps/authoring.md",
    "skills/hub-memory/SKILL.md",
)
# Seeded once by `cc-hub init`, never touched afterwards.
USER_OWNED: tuple[str, ...] = (
    "AGENTS.local.md",
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "MEMORY.md",
)
# Framework-owned files that `update` must not recreate once the agent removed them.
ONE_TIME: tuple[str, ...] = ("BOOTSTRAP.md",)
# Framework-owned files whose content below TAIL_MARKER belongs to the user and
# cc-connect; `update` replaces only what is above it.
KEEPS_TAIL: tuple[str, ...] = ("AGENTS.md",)
TAIL_MARKER = (
    "<!-- cc-hub: framework content ends here; everything below is kept by cc-hub update -->"
)
# Files a hub may hold that this package no longer ships; `update` backs them up
# and removes them.
RETIRED: tuple[str, ...] = (
    "skills/hub-jobs/SKILL.md",
    "skills/hub-hosts/SKILL.md",
    "skills/hub-projects/SKILL.md",
    "skills/hub-cc-connect/SKILL.md",
    "ENV.md",
    "env.json",
)
# Structure owned by the framework, values owned by the user: merged, never overwritten.
HUB_TOML = "hub.toml"
USER_DIRS: tuple[str, ...] = ("memory", "scripts")

_SOURCE_NAMES = {".gitignore": "_gitignore"}


def template_source(rel: str) -> Path:
    return TEMPLATES_DIR / _SOURCE_NAMES.get(rel, rel)


def all_templates() -> tuple[str, ...]:
    return FRAMEWORK_OWNED + USER_OWNED + (HUB_TOML,)


def render(
    rel: str,
    *,
    name: str = "hub",
    version: str = __version__,
    created: date | None = None,
) -> str:
    text = read_text(template_source(rel))
    created = created or date.today()
    return (
        text.replace("{{name}}", name)
        .replace("{{version}}", version)
        .replace("{{created}}", created.isoformat())
    )
