# -*- coding: utf-8 -*-
import json
from datetime import date, datetime
from pathlib import Path

from typer.testing import CliRunner

from cc_hub.cli import app
from cc_hub.commands.memory import log_entry, recent, search, stats
from cc_hub.encoding import read_text


def write_day(hub: Path, day: str, body: str) -> None:
    (hub / "memory" / f"{day}.md").write_text(f"# {day}\n\n{body}", encoding="utf-8")


def test_log_entry_creates_file_with_heading_and_timestamp(hub: Path) -> None:
    path = log_entry(hub, "did a thing\nsecond line", now=datetime(2026, 9, 22, 14, 30))
    assert path == hub / "memory" / "2026-09-22.md"
    assert read_text(path) == "# 2026-09-22\n\n- [14:30] did a thing\n  second line\n"
    log_entry(hub, "另一条 记录", now=datetime(2026, 9, 22, 15, 0))
    assert read_text(path).endswith("- [15:00] 另一条 记录\n")


def test_recent_returns_only_last_n_days_newest_first(hub: Path) -> None:
    for day in ("2026-09-20", "2026-09-21", "2026-09-22"):
        write_day(hub, day, "")
    (hub / "memory" / "notes.md").write_text("x", encoding="utf-8")
    files = recent(hub, days=2, today=date(2026, 9, 22))
    assert [p.name for p in files] == ["2026-09-22.md", "2026-09-21.md"]


def test_search_is_case_insensitive_newest_first_with_context(hub: Path) -> None:
    write_day(hub, "2026-09-20", "- [10:00] Deployed UnifX to staging\n- [11:00] lunch\n")
    write_day(hub, "2026-09-22", "- [09:00] unifx tests green\n")
    hits = search(hub, "unifx", today=date(2026, 9, 22))
    assert [h.file for h in hits] == ["memory/2026-09-22.md", "memory/2026-09-20.md"]
    assert hits[1].line_no == 3
    assert hits[1].context == "- [11:00] lunch"


def test_search_days_limit_and_regex(hub: Path) -> None:
    write_day(hub, "2026-09-20", "- [10:00] tests green\n")
    write_day(hub, "2026-09-22", "- [09:00] test green\n- [09:30] test green again\n")
    assert len(search(hub, "green", days=1, today=date(2026, 9, 22))) == 2
    assert len(search(hub, "green", limit=1, today=date(2026, 9, 22))) == 1
    assert len(search(hub, r"tests? green", regex=True, today=date(2026, 9, 22))) == 3


def test_search_includes_memory_md_first(hub: Path) -> None:
    content = "# Memory\n\n## Facts\n\n- 2026-09-22: hub lives in ~/.cc-hub\n"
    (hub / "MEMORY.md").write_text(content, encoding="utf-8")
    write_day(hub, "2026-09-22", "- [09:00] moved hub to ~/.cc-hub\n")
    hits = search(hub, "cc-hub", today=date(2026, 9, 22))
    assert hits[0].file == "MEMORY.md"
    assert hits[0].line_no == 5


def test_stats_reports_budgets(hub: Path) -> None:
    write_day(hub, "2026-09-22", "- a\n- b\n")
    s = stats(hub, max_lines=200)
    assert s["MEMORY.md"]["max"] == 200
    assert s["USER.md"]["max"] == 100
    assert s["memory/"] == {"files": 1, "lines": 4}


def test_memory_cli_log_recent_search(hub: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["--hub", str(hub), "memory", "log", "hello 世界"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["--hub", str(hub), "memory", "recent"])
    assert "hello 世界" in r.output
    r = runner.invoke(app, ["--hub", str(hub), "memory", "search", "世界", "--json"])
    assert json.loads(r.output)[0]["line"].endswith("hello 世界")
    r = runner.invoke(app, ["--hub", str(hub), "memory", "search", "nothing-here"])
    assert "no matches" in r.output


def test_search_cli_reports_invalid_regex(hub: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["--hub", str(hub), "memory", "search",
                            "(unclosed", "--regex"])
    assert r.exit_code == 1
    assert "invalid regex" in r.output
