from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from context_stat.domain.content import ContentItem, ContentKind, TextPayload


def make_environment() -> SandboxedEnvironment:
    environment = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
    environment.filters["quote"] = shlex.quote
    return environment


def render_template(path: Path, params: dict[str, Any]) -> ContentItem:
    text = make_environment().from_string(path.read_text(encoding="utf-8")).render(params)
    return ContentItem(
        item_id=f"jinja:{path}",
        origin="jinja",
        label=str(path),
        kind=ContentKind.TEXT,
        payload=TextPayload(raw=text.encode("utf-8"), text=text, encoding="utf-8"),
        metadata={"template": str(path)},
    )


def render_command(template: str, path: Path) -> list[str]:
    rendered = make_environment().from_string(template).render(path=str(path))
    argv = shlex.split(rendered, posix=True)
    if not argv:
        raise ValueError("command template rendered to an empty command")
    shell_tokens = {"|", ";", "&&", "||", ">", ">>", "<", "<<"}
    if shell_tokens.intersection(argv):
        raise ValueError("shell operators are not supported; commands run with shell=False")
    return argv
