"""Render the author-facing markdown report.

Structure (the new "show understanding" format):
  1. Overall impression  -- a beta-reader's first-pass reaction.
  2. How the read went    -- per-chapter summaries + spots the model (or prose)
                             got murky.
  3. Characters           -- prose descriptions, not stat blocks.
  4. Things to fix        -- reliable mechanical/continuity catches: verified
                             contradictions, duplicated passages, draft notes.
  5. Reference            -- compact timeline & locations.
"""

from __future__ import annotations

import datetime as _dt
import json
import re

from . import store
from .textfmt import dedash

_SEV_BADGE = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟡 Low"}
_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
_KIND_LABEL = {
    "trait_contradiction": "Contradicted detail",
    "object_state": "Object/state mismatch",
    "relationship": "Relationship mismatch",
    "timeline": "Timeline problem",
    "unresolved_thread": "Unresolved setup",
    "other": "Continuity issue",
}


def _ref(conn, chunk_id):
    return store.chunk_ref(conn, chunk_id) if chunk_id is not None else None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# --- deterministic duplicate-passage detection ---------------------------

def _duplicate_passages(conn):
    """Find sentences (>=5 words) that appear verbatim more than once -- a common
    copy-paste slip. Returns list of (sentence, [chunk_ids])."""
    seen: dict[str, list] = {}
    originals: dict[str, str] = {}
    for row in conn.execute("SELECT id, text FROM chunks ORDER BY chapter_seq, "
                            "scene_index").fetchall():
        for sent in re.split(r"(?<=[.!?])\s+", row["text"] or ""):
            s = sent.strip()
            if len(s.split()) < 5:
                continue
            key = _norm(s)
            if len(key) < 15:
                continue
            seen.setdefault(key, []).append(row["id"])
            originals.setdefault(key, s)
    out = []
    for key, chunk_ids in seen.items():
        if len(chunk_ids) >= 2:
            out.append((originals[key], chunk_ids))
    return out


# --- contradiction dedupe (verified flags) -------------------------------

def _dedupe_conflicts(conflicts):
    seen, out = set(), []
    for c in conflicts:
        qa, qb = _norm(c["source_a_quote"]), _norm(c["source_b_quote"])
        if qa and qa == qb:
            continue
        key = _norm(c["description"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def generate(conn, out_path: str) -> str:
    L: list[str] = []
    add = L.append

    add("# Manuscript Read-Through")
    add("")
    add(f"*Generated {_dt.date.today().isoformat()} by bookcheck — a local, "
        "private first-pass read. Nothing left this machine.*")
    add("")

    # Gather data
    feedback = conn.execute("SELECT impression FROM book_feedback WHERE id=1"
                            ).fetchone()
    summaries = conn.execute(
        "SELECT * FROM chapter_summaries ORDER BY chapter_seq").fetchall()
    contradictions = _dedupe_conflicts(conn.execute(
        "SELECT * FROM conflicts WHERE status='open' AND detected_by='entity_pass' "
        "AND kind != 'draft_note'").fetchall())
    observations = conn.execute(
        "SELECT * FROM conflicts WHERE status='open' AND detected_by='final_pass'"
    ).fetchall()
    draft_notes = conn.execute(
        "SELECT * FROM conflicts WHERE status='open' AND kind='draft_note'"
    ).fetchall()
    dupes = _duplicate_passages(conn)
    n_chapters = conn.execute(
        "SELECT COUNT(DISTINCT chapter_seq) n FROM chunks").fetchone()["n"]
    # Characters we have something to show for, with their profile rows.
    _ROLE_ORDER = {"main": 0, "supporting": 1, "minor": 2}
    chars = []
    for c in store.real_characters(conn):
        prof = conn.execute(
            "SELECT * FROM character_profiles WHERE character_name=? "
            "COLLATE NOCASE", (c["canonical_name"],)).fetchone()
        species = _species_for(conn, c["canonical_name"])
        if prof and prof["description"]:
            chars.append((c["canonical_name"], species, prof))
    chars.sort(key=lambda t: (_ROLE_ORDER.get(t[2]["role"] if t[2] else "minor", 2),
                              t[0]))

    n_uncertain = sum(len(json.loads(s["uncertainties"] or "[]")) for s in summaries)

    # --- At a glance ---
    add("## At a glance")
    add("")
    add(f"- **{n_chapters}** chapters read · **{len(chars)}** characters")
    add(f"- **{len(contradictions)}** likely continuity contradictions")
    add(f"- **{len(dupes)}** duplicated passages · **{len(draft_notes)}** draft "
        f"notes/TODOs left in the text")
    add(f"- **{n_uncertain}** spots the read got murky (possible unclear writing)")
    add("")
    add("> ⚠️ An automated first reader — helpful, not infallible. The chapter "
        "summaries show how the story came across; the *things to fix* are "
        "mechanical catches that are usually reliable. Trust your own judgment.")
    add("")

    # --- 1. Overall impression ---
    if feedback and feedback["impression"]:
        add("---")
        add("")
        add("## Overall impression")
        add("")
        add(feedback["impression"].strip())
        add("")

    # --- 2. How the read went (per-chapter) ---
    if summaries:
        add("---")
        add("")
        add("## Chapter-by-chapter")
        add("")
        add("*How the story came across on a first read. If a summary is off, "
            "that sentence or scene may be unclear — the “murky spots” flag where "
            "the read stumbled.*")
        add("")
        for s in summaries:
            if not s["pov_character"]:
                label = "Prologue"
            else:
                label = f"Ch.{s['chapter_seq']} — {s['pov_character']}"
                if s["date_label"]:
                    label += f" ({s['date_label']})"
            add(f"### {label}")
            add("")
            add(s["summary"] or "*No summary.*")
            add("")
            unc = json.loads(s["uncertainties"] or "[]")
            if unc:
                add("**Murky spots:**")
                for u in unc:
                    add(f"- {u}")
                add("")

    # --- 3. Characters (prose) ---
    add("---")
    add("")
    add("## Characters")
    add("")
    _ROLE_BADGE = {"main": "main character", "supporting": "supporting",
                   "minor": "minor"}
    for name, species, prof in chars:
        role = (prof["role"] if prof else "") or ""
        bits = [b for b in (species, _ROLE_BADGE.get(role)) if b]
        suffix = f" — {' · '.join(bits)}" if bits else ""
        desc = (prof["description"].strip() if prof and prof["description"] else "")
        add(f"#### {name}{suffix}")
        add("")
        if desc:
            add(desc)
            add("")
        # Arc analysis (main/supporting only).
        if prof and (prof["strengths"] or prof["weaknesses"] or prof["arc"]
                     or prof["development"]):
            if prof["arc"]:
                add(f"- **Arc so far:** {prof['arc'].strip()}")
            if prof["strengths"]:
                add(f"- **Strengths:** {prof['strengths'].strip()}")
            if prof["weaknesses"]:
                add(f"- **Weaknesses:** {prof['weaknesses'].strip()}")
            if prof["development"]:
                add(f"- **To develop the arc:** {prof['development'].strip()}")
            add("")
    if not chars:
        add("*No characters with recorded detail.*")
        add("")

    # --- 4. Things to fix ---
    add("---")
    add("")
    add("## Things to fix")
    add("")

    add("### Likely continuity contradictions")
    add("")
    if not contradictions:
        add("*None found in tracked attributes (species, eye/hair color, …).*")
        add("")
    else:
        ordered = sorted(contradictions,
                         key=lambda c: _SEV_ORDER.get(c["severity"] or "medium", 1))
        for i, c in enumerate(ordered, 1):
            badge = _SEV_BADGE.get((c["severity"] or "medium").lower(), "🟠 Medium")
            add(f"**{i}. {badge}** — {c['description']}")
            for q, ch in ((c["source_a_quote"], c["source_a_chunk"]),
                          (c["source_b_quote"], c["source_b_chunk"])):
                if q:
                    r = _ref(conn, ch)
                    add(f"  > {q.strip()}" + (f" — *{r}*" if r else ""))
            add("")

    add("### Duplicated passages")
    add("")
    if not dupes:
        add("*No verbatim repeats found.*")
        add("")
    else:
        add("*The same sentence appears more than once — usually a copy-paste "
            "slip.*")
        add("")
        for sent, chunk_ids in dupes:
            refs = ", ".join(sorted({_ref(conn, cid) for cid in chunk_ids}))
            add(f"- “{sent}” — *{refs}*")
        add("")

    if draft_notes:
        add("### Draft notes & TODOs")
        add("")
        add("*Notes left in the manuscript itself (bracketed or starred).*")
        add("")
        for c in draft_notes:
            r = _ref(conn, c["source_a_chunk"])
            add(f"- `{c['source_a_quote'].strip()}` — *{r}*")
        add("")

    if observations:
        add("### Things to double-check (lower confidence)")
        add("")
        add("*From an AI reasoning pass — can misread sequence; treat as prompts.*")
        add("")
        for c in observations:
            add(f"- {c['description']}")
        add("")

    # --- Finishing the draft (WIP only) ---
    closings = conn.execute(
        "SELECT thread, suggestion FROM closing_suggestions").fetchall()
    if closings:
        add("---")
        add("")
        add("## Finishing the draft")
        add("")
        add("*This looks like a work in progress, so here are the major open "
            "threads with possible ways to land each — brainstorming to help you "
            "finish, not prescriptions.*")
        add("")
        for c in closings:
            add(f"**{c['thread'].strip()}**")
            add("")
            add(c["suggestion"].strip())
            add("")

    # --- 5. Reference ---
    add("---")
    add("")
    add("## Reference")
    add("")
    _timeline_section(conn, add)
    _locations_section(conn, add)
    _relationships_section(conn, add)

    # No em/en dashes in the output -- catches our own separators above and any
    # the model wrote into summaries/impressions/arcs. See textfmt.dedash.
    text = dedash("\n".join(L)).rstrip() + "\n"
    import os
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


_SPECIES_WORDS = ("vampire", "werewolf", "witch", "wizard", "fae", "fairy",
                  "ghost", "demon", "shifter", "human")


def _normalize_species(value: str) -> str:
    """Tidy a stored species value for display (e.g. 'fae/fairy' -> 'fae')."""
    v = (value or "").strip().lower()
    if "/" in v:
        v = v.split("/")[0].strip()
    return v


def _species_for(conn, name):
    """A character's species. Prefer the populated `characters.species` column
    (the extractor fills it readily); fall back to species/race facts for older
    DBs where only facts were recorded."""
    row = conn.execute(
        "SELECT species FROM characters WHERE canonical_name = ? COLLATE NOCASE",
        (name,)).fetchone()
    if row and (row["species"] or "").strip():
        return _normalize_species(row["species"])

    rows = conn.execute(
        "SELECT value FROM facts WHERE entity_name = ? COLLATE NOCASE AND "
        "attribute IN ('species','race') AND polarity >= 0", (name,)).fetchall()
    found = []
    for r in rows:
        v = (r["value"] or "").lower()
        for sp in _SPECIES_WORDS:
            if sp in v and sp not in found:
                found.append(sp)
    supernatural = [s for s in found if s != "human"]
    if len(supernatural) == 1:
        return supernatural[0]
    if len(supernatural) > 1:
        return " / ".join(supernatural) + " (?)"
    if found == ["human"]:
        return "human"
    return ""


def _timeline_section(conn, add):
    rows = conn.execute(
        "SELECT * FROM timeline_events ORDER BY ordering_hint, chunk_id"
    ).fetchall()
    if not rows:
        return
    add("### Timeline")
    add("")
    last = object()
    seen = set()
    for t in rows:
        desc = (t["description"] or "").strip()
        if not desc or _norm(desc) in seen:
            continue
        seen.add(_norm(desc))
        when = t["when_norm"] or "?"
        if when != last:
            add(f"**{when}**")
            last = when
        add(f"- {desc}  <sub>{store.chunk_ref(conn, t['chunk_id'])}</sub>")
    add("")


def _locations_section(conn, add):
    locs = store.merged_locations(conn)
    if not locs:
        return
    add("### Locations")
    add("")
    for loc in locs:
        desc = (loc["description"] or "").strip()
        add(f"- **{loc['name']}**" + (f" — {desc}" if desc else ""))
    add("")


def _relationships_section(conn, add):
    real = {c["canonical_name"].strip().lower() for c in store.real_characters(conn)}
    rows = conn.execute(
        "SELECT char_a, char_b, relation_type FROM relationships").fetchall()
    seen, pairs = set(), []
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
        pairs.append(f"- **{a}** & **{b}**: {rel}")
    if not pairs:
        return
    add("### Relationships")
    add("")
    for p in pairs:
        add(p)
    add("")
