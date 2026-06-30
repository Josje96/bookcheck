"""Entity-resolution pass: consolidate the extracted character list.

Small models pull the same person under several surface forms — full name vs
title ("King Alaric" / "Alaric Valerius"), an epithet ("the grumpy old werewolf"),
or a relational reference ("Brax's father") — and also mis-extract generic roles
("the bartender"), crowds/species ("the fairies"), and animals as characters.

`merge_subset_characters` (in store.py) handles the easy token-subset case
deterministically. This pass uses the LLM for the harder cases: it sees the whole
name list (with species + appearance counts) and returns alias groups + a list of
entries that aren't real named characters. We then reassign every fact, knowledge
row and relationship to the canonical name and drop the rest. Provider-agnostic:
takes any client exposing `chat_json` (see providers.py).
"""

from __future__ import annotations

import json
import re

from . import store

# Relationship nouns used to detect "X's father" style references.
_RELATIVE_WORDS = {
    "father", "dad", "mother", "mom", "mum", "parent", "parents", "aunt",
    "uncle", "grandmother", "grandfather", "grandma", "grandpa", "granny",
    "sister", "brother", "son", "daughter", "cousin", "wife", "husband",
    "niece", "nephew", "kid", "child", "boyfriend", "girlfriend",
}
_POSSESSIVE_RE = re.compile(r"^(.+?)['’]s\s+(\w+)")


def _is_relative_of(alias: str, canon: str) -> bool:
    """True if `alias` is a relational reference to `canon` itself (e.g. alias
    "Brax's father", canon "Brax"). Such a person is NOT canon, so the LLM must
    never merge them together -- this is the deterministic backstop for that."""
    m = _POSSESSIVE_RE.match(alias.strip().lower())
    if not m:
        return False
    possessor, rel = m.group(1).strip(), m.group(2).strip()
    if rel not in _RELATIVE_WORDS:
        return False
    canon_l = canon.strip().lower()
    canon_first = canon_l.split()[0] if canon_l else canon_l
    return possessor in (canon_l, canon_first)

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["canonical", "aliases"],
            },
        },
        "not_characters": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["groups", "not_characters"],
}

RESOLVE_SYSTEM = """\
You are consolidating a character list extracted from a SINGLE novel. Some
entries refer to the SAME person in different ways: a full name vs a title
("King Alaric" and "Alaric Valerius"), a nickname, or an epithet ("the grumpy
old werewolf"). Other entries are NOT a specific named person: generic roles
("the bartender", "a realtor"), crowds or species ("vampires", "the fairies"),
or animals.

Return JSON with two keys:
- groups: each {canonical, aliases}. Put together entries you are CONFIDENT are
  the same individual. canonical = the entry that is the most complete PROPER
  NAME (prefer a real given/family name over a title-only name, and either of
  those over an epithet). aliases = the OTHER entries for that same person. Only
  include a group when there is at least one alias.
- not_characters: entries that are not one specific named person (generic roles,
  species/crowds, animals).

CRITICAL rules about RELATIONAL references like "Brax's father", "Dani's aunt",
"Mila's grandmother":
- Such a phrase denotes a DIFFERENT person from the named anchor. "Brax's
  father" is NOT Brax. NEVER put "X's father/mother/aunt/son/..." as an alias of
  "X".
- Only group a relational phrase with a NAMED entry when the story clearly makes
  them the same individual. Example: if the list has both "Alaric Valerius" and
  "Brax's father" and Alaric is Brax's father, then canonical "Alaric Valerius"
  with alias "Brax's father" (NOT alias of "Brax"). If no named entry matches,
  leave the relational phrase ungrouped (do not force it).

Other rules: use the provided names EXACTLY as written (verbatim). Do not invent
names. Entries with DIFFERENT given names are different people unless one is
clearly a nickname/spelling variant of the other. Each name appears at most once
across all groups and not_characters. When unsure, do NOT group. Be conservative.\
"""


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _resolve_name(raw: str, present: dict[str, str]) -> str | None:
    """Map a model-returned name back to an actual DB name (case-insensitive)."""
    return present.get(_norm(raw))


def _context(conn) -> tuple[str, dict[str, str]]:
    rows = conn.execute(
        "SELECT canonical_name, species FROM characters ORDER BY canonical_name"
    ).fetchall()
    present = {_norm(r["canonical_name"]): r["canonical_name"] for r in rows}
    lines = []
    for r in rows:
        name = r["canonical_name"]
        _, chaps = store.character_appearances(conn, name)
        sp = (r["species"] or "").strip() or "unknown"
        f = conn.execute(
            "SELECT attribute, value FROM facts WHERE entity_name = ? "
            "COLLATE NOCASE LIMIT 1", (name,)).fetchone()
        extra = f"; {f['attribute']}={f['value']}" if f else ""
        lines.append(f"- {name} (species: {sp}; in {chaps} chapter(s){extra})")
    return "\n".join(lines), present


def _merge(conn, canon: str, aliases: list[str]) -> None:
    crow = conn.execute(
        "SELECT id, aliases, species FROM characters WHERE canonical_name = ? "
        "COLLATE NOCASE", (canon,)).fetchone()
    if not crow:
        return
    existing = json.loads(crow["aliases"] or "[]")
    canon_species = crow["species"]
    for a in aliases:
        arow = conn.execute(
            "SELECT species FROM characters WHERE canonical_name = ? COLLATE NOCASE",
            (a,)).fetchone()
        if arow and arow["species"] and not canon_species:
            canon_species = arow["species"]
            conn.execute("UPDATE characters SET species = ? WHERE id = ?",
                         (canon_species, crow["id"]))
        for tbl, col in (("facts", "entity_name"),
                         ("knowledge", "character_name"),
                         ("relationships", "char_a"),
                         ("relationships", "char_b")):
            conn.execute(
                f"UPDATE {tbl} SET {col} = ? WHERE {col} = ? COLLATE NOCASE",
                (canon, a))
        if a not in existing:
            existing.append(a)
        conn.execute("DELETE FROM characters WHERE canonical_name = ? COLLATE NOCASE",
                     (a,))
    conn.execute("UPDATE characters SET aliases = ? WHERE id = ?",
                 (json.dumps(existing), crow["id"]))


def run_entity_resolution(conn, client, model=None, verbose: bool = True) -> int:
    """Merge alias characters and drop non-characters. Returns merge count."""
    ctx, present = _context(conn)
    if len(present) < 2:
        return 0
    user = (f"CHARACTERS:\n{ctx}\n\nConsolidate them now. Group only "
            "same-person entries; list non-people under not_characters.")
    try:
        data = client.chat_json(model, RESOLVE_SYSTEM, user,
                                schema=RESOLVE_SCHEMA, think=False,
                                num_ctx=8192, num_predict=1500)
    except Exception as e:  # noqa: BLE001 - resolution is best-effort
        if verbose:
            print(f"  [resolve] FAILED ({e})")
        return 0

    groups = data.get("groups", []) if isinstance(data, dict) else []
    drops = data.get("not_characters", []) if isinstance(data, dict) else []

    merged = 0
    for g in groups:
        if not isinstance(g, dict):
            continue
        canon = _resolve_name(g.get("canonical", ""), present)
        if not canon:
            continue
        aliases = []
        for a in g.get("aliases", []) or []:
            am = _resolve_name(a, present)
            if not am or _norm(am) == _norm(canon):
                continue
            # Deterministic backstop: "X's father" is not X. Models merge these
            # into the anchor anyway, so reject it regardless of what they say.
            if _is_relative_of(am, canon):
                if verbose:
                    print(f"  [resolve] kept '{am}' separate (relative of '{canon}')")
                continue
            aliases.append(am)
        if not aliases:
            continue
        _merge(conn, canon, aliases)
        for am in aliases:
            present.pop(_norm(am), None)
        merged += len(aliases)
        if verbose:
            print(f"  [resolve] merged {aliases} -> '{canon}'")

    dropped = 0
    for d in drops:
        dm = _resolve_name(d, present)
        if not dm:
            continue
        conn.execute("DELETE FROM characters WHERE canonical_name = ? COLLATE NOCASE",
                     (dm,))
        present.pop(_norm(dm), None)
        dropped += 1
    conn.commit()
    if verbose:
        print(f"  [resolve] {merged} alias(es) merged, {dropped} non-character(s) "
              "dropped")
    return merged
