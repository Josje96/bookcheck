"""Read-only views over the story-bible (book.db) for the HTTP API.

Two consumers:
  * `story_bible(conn)` -> a JSON-serializable dict the front end renders.
  * `chat_context(conn)` -> a compact text digest injected as the system
    prompt so the user can chat *about their own manuscript* (the DB is the
    grounding context — no vector RAG, the bible is already small + structured).
"""

from __future__ import annotations

import json

from . import report, store
from .textfmt import dedash_deep

_ROLE_ORDER = {"main": 0, "supporting": 1, "minor": 2}

# Already surfaced as the species badge, so we don't repeat them as traits.
_TRAIT_SKIP = {"species", "race"}


def _traits_for(conn, name: str, limit: int = 14) -> list[dict]:
    """Distinct asserted facts about a character (eye color, hair, build,
    personality, ...) for the Characters-tab 'Appearance & traits' section.
    Pulled straight from the facts table the extractor already fills, so this
    works on existing DBs with no re-analyze."""
    rows = conn.execute(
        "SELECT attribute, value FROM facts "
        "WHERE entity_type='character' AND entity_name = ? COLLATE NOCASE "
        "AND polarity >= 0 ORDER BY id", (name,)).fetchall()
    out, seen = [], set()
    for r in rows:
        attr = (r["attribute"] or "").strip()
        val = (r["value"] or "").strip()
        if not attr or not val or attr.lower() in _TRAIT_SKIP:
            continue
        key = (attr.lower(), val.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"attribute": attr, "value": val})
        if len(out) >= limit:
            break
    return out


def _characters(conn) -> list[dict]:
    out = []
    for c in store.real_characters(conn):
        name = c["canonical_name"]
        prof = conn.execute(
            "SELECT * FROM character_profiles WHERE character_name=? COLLATE NOCASE",
            (name,)).fetchone()
        species = report._species_for(conn, name)
        if not (prof and prof["description"]):
            continue
        try:
            aliases = json.loads(c["aliases"] or "[]")
        except Exception:  # noqa: BLE001
            aliases = []
        out.append({
            "name": name,
            "aliases": aliases,
            "species": species or None,
            "role": (prof["role"] if prof else None) or None,
            "description": (prof["description"] if prof else None) or None,
            "strengths": (prof["strengths"] if prof else None) or None,
            "weaknesses": (prof["weaknesses"] if prof else None) or None,
            "arc": (prof["arc"] if prof else None) or None,
            "development": (prof["development"] if prof else None) or None,
            "traits": _traits_for(conn, name),
        })
    out.sort(key=lambda d: (_ROLE_ORDER.get(d["role"] or "minor", 2), d["name"]))
    return out


def _chapters(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM chapter_summaries ORDER BY chapter_seq").fetchall()
    out = []
    for s in rows:
        out.append({
            "chapter_seq": s["chapter_seq"],
            "pov_character": s["pov_character"],
            "date_label": s["date_label"],
            "summary": s["summary"],
            "uncertainties": json.loads(s["uncertainties"] or "[]"),
        })
    return out


def _contradictions(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM conflicts WHERE status='open' AND detected_by='entity_pass' "
        "AND kind != 'draft_note'").fetchall()
    out = []
    for c in rows:
        out.append({
            "description": c["description"],
            "severity": c["severity"],
            "source_a": {"quote": c["source_a_quote"],
                         "ref": store.chunk_ref(conn, c["source_a_chunk"])},
            "source_b": {"quote": c["source_b_quote"],
                         "ref": store.chunk_ref(conn, c["source_b_chunk"])},
        })
    return out


def _relationships(conn) -> list[dict]:
    """Deduped relationships between two real, known characters."""
    real = {c["canonical_name"].strip().lower() for c in store.real_characters(conn)}
    rows = conn.execute(
        "SELECT char_a, char_b, relation_type FROM relationships").fetchall()
    seen, out = set(), []
    for r in rows:
        a = (r["char_a"] or "").strip()
        b = (r["char_b"] or "").strip()
        rel = (r["relation_type"] or "").strip()
        if not a or not b or not rel:
            continue
        if a.lower() not in real or b.lower() not in real:
            continue
        key = (a.lower(), b.lower(), rel.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"a": a, "b": b, "relation": rel})
    return out


def _timeline(conn) -> list[dict]:
    """In-story events in sequence (dedup'd by description). `when` is the
    normalized day/phase label, or None for unsequenced events."""
    rows = conn.execute(
        "SELECT * FROM timeline_events ORDER BY ordering_hint, chunk_id"
    ).fetchall()
    out, seen = [], set()
    for t in rows:
        desc = (t["description"] or "").strip()
        if not desc:
            continue
        key = report._norm(desc)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "when": t["when_norm"] or None,
            "event": desc,
            "ref": store.chunk_ref(conn, t["chunk_id"]),
        })
    return out


def story_bible(conn) -> dict:
    """Structured story bible for the front end."""
    feedback = conn.execute(
        "SELECT impression FROM book_feedback WHERE id=1").fetchone()
    n_chapters = conn.execute(
        "SELECT COUNT(DISTINCT chapter_seq) n FROM chunks").fetchone()["n"]
    characters = _characters(conn)
    locations = store.merged_locations(conn)
    # dedash_deep strips em/en dashes from all served strings (existing DB data
    # included, so no re-analyze is needed). See textfmt.dedash.
    return dedash_deep({
        "meta": {
            "chapters": n_chapters,
            "characters": len(characters),
        },
        "impression": feedback["impression"] if feedback else None,
        "chapters": _chapters(conn),
        "characters": characters,
        "contradictions": _contradictions(conn),
        "locations": locations,
        "relationships": _relationships(conn),
        "timeline": _timeline(conn),
    })


def has_data(conn) -> bool:
    """True once a manuscript has been ingested (so chat/bible have grounding)."""
    try:
        return conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None
    except Exception:  # noqa: BLE001 - table may not exist yet
        return False


def chat_context(conn, max_chars: int = 9000) -> str:
    """A compact text digest of the manuscript for grounding the chat model."""
    b = story_bible(conn)
    parts: list[str] = []
    if b["impression"]:
        parts.append("OVERALL IMPRESSION:\n" + b["impression"].strip())

    if b["characters"]:
        lines = ["CHARACTERS:"]
        for c in b["characters"]:
            tag = " / ".join(x for x in (c["role"], c["species"]) if x)
            head = f"- {c['name']}" + (f" ({tag})" if tag else "")
            if c["description"]:
                head += f": {c['description'].strip()}"
            lines.append(head)
            if c["arc"]:
                lines.append(f"    arc: {c['arc'].strip()}")
        parts.append("\n".join(lines))

    if b["chapters"]:
        lines = ["CHAPTER SUMMARIES:"]
        for ch in b["chapters"]:
            if ch["pov_character"]:
                label = f"Ch.{ch['chapter_seq']} ({ch['pov_character']}"
                label += f", {ch['date_label']})" if ch["date_label"] else ")"
            else:
                label = "Prologue"
            lines.append(f"- {label}: {(ch['summary'] or '').strip()}")
        parts.append("\n".join(lines))

    if b["relationships"]:
        lines = ["RELATIONSHIPS:"]
        for r in b["relationships"]:
            lines.append(f"- {r['a']} & {r['b']}: {r['relation']}")
        parts.append("\n".join(lines))

    if b["contradictions"]:
        lines = ["FLAGGED CONTRADICTIONS:"]
        for c in b["contradictions"]:
            lines.append(f"- {c['description']}")
        parts.append("\n".join(lines))

    if b["locations"]:
        loc_lines = ["LOCATIONS:"]
        for loc in b["locations"]:
            loc_lines.append(
                f"- {loc['name']}" + (f": {loc['description']}"
                                      if loc["description"] else ""))
        parts.append("\n".join(loc_lines))

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[...digest truncated...]"
    return text
