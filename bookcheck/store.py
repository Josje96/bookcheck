"""SQLite story-state store: schema + typed read/write helpers.

This is the source of truth. Markdown reports are a generated, read-only view.
Every extracted fact carries provenance (chunk_id + quote) so the report can
always point back to where in the book something was stated.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY,
    part          TEXT,
    chapter_seq   INTEGER,   -- 0-based chapter index in reading order
    scene_index   INTEGER,   -- 0-based scene within the chapter
    pov_character TEXT,       -- whose point of view (header), may be NULL
    date_label    TEXT,       -- raw header date, e.g. "November 24th - Evening"
    date_norm     TEXT,       -- normalized, e.g. "11-24 evening"
    ordering_hint INTEGER,    -- sortable timeline position derived from the date
    text          TEXT
);

CREATE TABLE IF NOT EXISTS characters (
    id             INTEGER PRIMARY KEY,
    canonical_name TEXT UNIQUE,
    aliases        TEXT,      -- JSON array
    species        TEXT       -- witch/vampire/werewolf/human/...
);

CREATE TABLE IF NOT EXISTS locations (
    id    INTEGER PRIMARY KEY,
    name  TEXT UNIQUE,
    notes TEXT
);

-- The heart of plot-hole detection: entity-attribute-value with polarity and
-- a source quote. Conflict checks are cheap key lookups on
-- (entity_type, entity_id, attribute) -- no embeddings, no similarity search.
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY,
    entity_type TEXT,         -- character | location | object | world
    entity_id   INTEGER,      -- FK into characters/locations when applicable
    entity_name TEXT,         -- denormalized for object/world facts & reporting
    attribute   TEXT,         -- e.g. "eye_color", "is_alive", "owns:cottage"
    value       TEXT,
    polarity    INTEGER,      -- +1 asserted, -1 negated
    chunk_id    INTEGER,
    quote       TEXT,
    confidence  REAL,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id            INTEGER PRIMARY KEY,
    char_a        TEXT,
    char_b        TEXT,
    relation_type TEXT,
    polarity      INTEGER,
    chunk_id      INTEGER,
    quote         TEXT,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id            INTEGER PRIMARY KEY,
    when_norm     TEXT,
    when_raw      TEXT,
    ordering_hint INTEGER,
    description   TEXT,
    characters    TEXT,       -- JSON array of names
    location_id   INTEGER,
    chunk_id      INTEGER,
    quote         TEXT,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
);

-- Who-knows-what-when: the cross-POV knowledge-leak detector.
CREATE TABLE IF NOT EXISTS knowledge (
    id               INTEGER PRIMARY KEY,
    character_name   TEXT,
    proposition      TEXT,
    learned_chunk_id INTEGER,
    quote            TEXT,
    FOREIGN KEY (learned_chunk_id) REFERENCES chunks(id)
);

-- Chekhov's guns / foreshadowing.
CREATE TABLE IF NOT EXISTS plot_threads (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    description     TEXT,
    status          TEXT,     -- open | resolved
    setup_chunk_id  INTEGER,
    payoff_chunk_id INTEGER
);

CREATE TABLE IF NOT EXISTS conflicts (
    id             INTEGER PRIMARY KEY,
    kind           TEXT,      -- trait_contradiction | timeline | knowledge_leak
                              -- | object_state | unresolved_thread | relationship
    description    TEXT,
    severity       TEXT,      -- high | medium | low
    source_a_chunk INTEGER,
    source_a_quote TEXT,
    source_b_chunk INTEGER,
    source_b_quote TEXT,
    detected_by    TEXT,      -- entity_pass | final_pass
    status         TEXT       -- open | dismissed
);

-- Per-chapter comprehension: a plain summary + things the model couldn't follow.
CREATE TABLE IF NOT EXISTS chapter_summaries (
    id            INTEGER PRIMARY KEY,
    chapter_seq   INTEGER,
    pov_character TEXT,
    date_label    TEXT,
    summary       TEXT,
    uncertainties TEXT       -- JSON array of strings
);

-- Prose character descriptions + arc analysis for the human-readable bible.
CREATE TABLE IF NOT EXISTS character_profiles (
    character_name TEXT PRIMARY KEY,
    role           TEXT,   -- main | supporting | minor
    description    TEXT,
    strengths      TEXT,
    weaknesses     TEXT,
    arc            TEXT,
    development    TEXT
);

-- For unfinished drafts: suggested ways to resolve open threads.
CREATE TABLE IF NOT EXISTS closing_suggestions (
    id         INTEGER PRIMARY KEY,
    thread     TEXT,
    suggestion TEXT
);

-- Single-row overall beta-reader impression of the whole draft.
CREATE TABLE IF NOT EXISTS book_feedback (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    impression TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_entity
    ON facts(entity_type, entity_name, attribute);
CREATE INDEX IF NOT EXISTS idx_knowledge_char ON knowledge(character_name);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, reset: bool = False) -> None:
    if reset:
        for tbl in (
            "conflicts", "plot_threads", "knowledge", "timeline_events",
            "relationships", "facts", "locations", "characters", "chunks",
            "chapter_summaries", "character_profiles", "book_feedback",
            "closing_suggestions",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.executescript(SCHEMA)
    conn.commit()


# --- writers -------------------------------------------------------------

def insert_chunk(conn: sqlite3.Connection, chunk: dict) -> int:
    cur = conn.execute(
        """INSERT INTO chunks
           (part, chapter_seq, scene_index, pov_character, date_label,
            date_norm, ordering_hint, text)
           VALUES (?,?,?,?,?,?,?,?)""",
        (chunk.get("part"), chunk.get("chapter_seq"), chunk.get("scene_index"),
         chunk.get("pov"), chunk.get("date_label"), chunk.get("date_norm"),
         chunk.get("ordering_hint"), chunk.get("text")),
    )
    return cur.lastrowid


def upsert_character(conn: sqlite3.Connection, name: str,
                     species: Optional[str] = None) -> int:
    name = name.strip()
    row = conn.execute(
        "SELECT id, species FROM characters WHERE canonical_name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    if row:
        if species and not row["species"]:
            conn.execute("UPDATE characters SET species = ? WHERE id = ?",
                         (species, row["id"]))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO characters (canonical_name, aliases, species) VALUES (?,?,?)",
        (name, json.dumps([]), species),
    )
    return cur.lastrowid


def upsert_location(conn: sqlite3.Connection, name: str,
                    notes: Optional[str] = None) -> int:
    name = name.strip()
    row = conn.execute(
        "SELECT id, notes FROM locations WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        # Fill in a description the first time one is offered.
        if notes and not row["notes"]:
            conn.execute("UPDATE locations SET notes = ? WHERE id = ?",
                         (notes, row["id"]))
        return row["id"]
    cur = conn.execute("INSERT INTO locations (name, notes) VALUES (?, ?)",
                       (name, notes))
    return cur.lastrowid


def insert_fact(conn: sqlite3.Connection, *, entity_type: str, entity_id,
                entity_name: str, attribute: str, value: str, polarity: int,
                chunk_id: int, quote: str, confidence: float = 0.8) -> int:
    cur = conn.execute(
        """INSERT INTO facts
           (entity_type, entity_id, entity_name, attribute, value, polarity,
            chunk_id, quote, confidence)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (entity_type, entity_id, entity_name, attribute, value, polarity,
         chunk_id, quote, confidence),
    )
    return cur.lastrowid


def insert_relationship(conn, *, char_a, char_b, relation_type, polarity,
                        chunk_id, quote) -> int:
    cur = conn.execute(
        """INSERT INTO relationships
           (char_a, char_b, relation_type, polarity, chunk_id, quote)
           VALUES (?,?,?,?,?,?)""",
        (char_a, char_b, relation_type, polarity, chunk_id, quote),
    )
    return cur.lastrowid


def insert_timeline_event(conn, *, when_norm, when_raw, ordering_hint,
                          description, characters, location_id, chunk_id,
                          quote) -> int:
    cur = conn.execute(
        """INSERT INTO timeline_events
           (when_norm, when_raw, ordering_hint, description, characters,
            location_id, chunk_id, quote)
           VALUES (?,?,?,?,?,?,?,?)""",
        (when_norm, when_raw, ordering_hint, description,
         json.dumps(characters), location_id, chunk_id, quote),
    )
    return cur.lastrowid


def insert_knowledge(conn, *, character_name, proposition, learned_chunk_id,
                     quote) -> int:
    cur = conn.execute(
        """INSERT INTO knowledge
           (character_name, proposition, learned_chunk_id, quote)
           VALUES (?,?,?,?)""",
        (character_name, proposition, learned_chunk_id, quote),
    )
    return cur.lastrowid


def insert_plot_thread(conn, *, name, description, status, setup_chunk_id,
                       payoff_chunk_id=None) -> int:
    cur = conn.execute(
        """INSERT INTO plot_threads
           (name, description, status, setup_chunk_id, payoff_chunk_id)
           VALUES (?,?,?,?,?)""",
        (name, description, status, setup_chunk_id, payoff_chunk_id),
    )
    return cur.lastrowid


def insert_conflict(conn, *, kind, description, severity, source_a_chunk,
                    source_a_quote, source_b_chunk, source_b_quote,
                    detected_by, status="open") -> int:
    cur = conn.execute(
        """INSERT INTO conflicts
           (kind, description, severity, source_a_chunk, source_a_quote,
            source_b_chunk, source_b_quote, detected_by, status)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (kind, description, severity, source_a_chunk, source_a_quote,
         source_b_chunk, source_b_quote, detected_by, status),
    )
    return cur.lastrowid


_GENERIC_NOUNS = {
    "man", "woman", "girl", "boy", "child", "kid", "vendor", "shop owner",
    "shopkeeper", "stranger", "figure", "voice", "werewolf", "vampire", "witch",
    "fairy", "fae", "person", "guard", "king", "queen", "young woman",
    "young man", "old man", "old woman", "the raven", "human", "humans",
    "fairies", "vampires", "werewolves", "witches", "people",
}


def is_real_character(name: str) -> bool:
    n = (name or "").strip().lower()
    for art in ("the ", "a "):
        if n.startswith(art):
            n = n[len(art):]
    return n not in _GENERIC_NOUNS and len(n) >= 2


def real_characters(conn) -> list:
    """Characters that are actual named people (not generic descriptors or
    place-names that got mis-extracted as characters)."""
    locs = {r["name"].strip().lower()
            for r in conn.execute("SELECT name FROM locations").fetchall()}
    return [c for c in conn.execute(
        "SELECT * FROM characters ORDER BY canonical_name").fetchall()
        if is_real_character(c["canonical_name"])
        and c["canonical_name"].strip().lower() not in locs]


# A possessive place name -> (owner, part), e.g. "Mila's kitchen" -> ("Mila's",
# "kitchen"). Matches straight and curly apostrophes.
_OWNER_RE = __import__("re").compile(r"^(.+?['’]s)\s+(.+)$")
# When several "<owner>'s <part>" places collapse into one, prefer a
# whole-dwelling tail as the canonical name over a mere room/feature. Ranked by
# any dwelling word *contained* in the tail (so "boarding house" counts as a
# house, beating "bedroom"/"kitchen").
_DWELLING_RANK = {
    "home": 0, "house": 0, "cottage": 0, "cabin": 1, "apartment": 1,
    "flat": 1, "manor": 1, "estate": 1, "mansion": 1, "place": 2,
}


def _dwelling_rank(tail: str) -> int:
    best = 9
    for word in tail.split():
        best = min(best, _DWELLING_RANK.get(word, 9))
    return best


def merged_locations(conn) -> list[dict]:
    """Locations for display, with same-owner duplicates collapsed.

    The extractor often records the parts of one dwelling as separate places
    ("Mila's house", "Mila's kitchen", "Mila's door"). Group anything of the
    form "<owner>'s <part>" by owner, keep one canonical name (preferring a
    whole-dwelling word like 'cottage' over a room), and merge the notes. This
    is a non-destructive view, so it cleans up existing DBs with no re-analyze.
    Returns dicts shaped like {"name", "description"}."""
    rows = conn.execute("SELECT name, notes FROM locations ORDER BY name").fetchall()
    groups: dict[str, list[tuple[str, str, str]]] = {}
    out: list[dict] = []
    for r in rows:
        name = (r["name"] or "").strip()
        notes = (r["notes"] or "").strip()
        if not name:
            continue
        m = _OWNER_RE.match(name)
        if m:
            groups.setdefault(m.group(1).lower(), []).append(
                (name, notes, m.group(2).strip().lower()))
        else:
            out.append({"name": name, "description": notes or None})

    for members in groups.values():
        # Canonical name: best-ranked dwelling tail, else the shortest name.
        canon = min(
            members, key=lambda m: (_dwelling_rank(m[2]), len(m[0])))[0]
        seen, descs = set(), []
        for _, notes, _ in members:
            if notes and notes.lower() not in seen:
                seen.add(notes.lower())
                descs.append(notes)
        out.append({"name": canon, "description": " ".join(descs) or None})

    out.sort(key=lambda d: d["name"].lower())
    return out


def save_chapter_summary(conn, *, chapter_seq, pov_character, date_label,
                         summary, uncertainties) -> None:
    conn.execute(
        """INSERT INTO chapter_summaries
           (chapter_seq, pov_character, date_label, summary, uncertainties)
           VALUES (?,?,?,?,?)""",
        (chapter_seq, pov_character, date_label, summary,
         json.dumps(uncertainties or [])),
    )


def save_character_profile(conn, name, *, role="", description="", strengths="",
                           weaknesses="", arc="", development="") -> None:
    conn.execute(
        """INSERT OR REPLACE INTO character_profiles
           (character_name, role, description, strengths, weaknesses, arc,
            development) VALUES (?,?,?,?,?,?,?)""",
        (name, role, description, strengths, weaknesses, arc, development))


def save_closing_suggestion(conn, thread, suggestion) -> None:
    conn.execute(
        "INSERT INTO closing_suggestions (thread, suggestion) VALUES (?, ?)",
        (thread, suggestion))


def character_appearances(conn, name) -> tuple[int, int]:
    """(distinct POV chapters, distinct chapters appeared in) for a character --
    a deterministic signal of how central they are."""
    pov = conn.execute(
        "SELECT COUNT(DISTINCT chapter_seq) n FROM chunks WHERE "
        "pov_character = ? COLLATE NOCASE", (name,)).fetchone()["n"]
    chaps = conn.execute(
        """SELECT COUNT(DISTINCT c.chapter_seq) n FROM facts f
           JOIN chunks c ON f.chunk_id = c.id
           WHERE f.entity_name = ? COLLATE NOCASE""", (name,)).fetchone()["n"]
    return pov, chaps


def detect_wip(conn) -> bool:
    """Heuristic: a manuscript with author draft notes/TODOs left in the text is
    almost certainly a work in progress."""
    n = conn.execute(
        "SELECT COUNT(*) n FROM conflicts WHERE kind='draft_note'").fetchone()["n"]
    return n > 0


def save_book_feedback(conn, impression) -> None:
    conn.execute("INSERT OR REPLACE INTO book_feedback (id, impression) "
                 "VALUES (1, ?)", (impression,))


# --- readers -------------------------------------------------------------

def chunk_ref(conn: sqlite3.Connection, chunk_id) -> str:
    """Human-readable chapter reference for a chunk id, e.g.
    'Ch.3 (Willow, November 24th) sc.1'."""
    if chunk_id is None:
        return "?"
    row = conn.execute(
        "SELECT chapter_seq, scene_index, pov_character, date_label "
        "FROM chunks WHERE id = ?", (chunk_id,),
    ).fetchone()
    if not row:
        return f"chunk#{chunk_id}"
    scene = (row["scene_index"] or 0) + 1
    # The prologue (chapter_seq 0) has no POV; real chapters start at seq 1.
    if not row["pov_character"]:
        return "Prologue" + (f" sc.{scene}" if scene > 1 else "")
    pov = row["pov_character"]
    date = row["date_label"] or "?"
    return f"Ch.{row['chapter_seq']} ({pov}, {date}) sc.{scene}"


def all_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT * FROM {table}").fetchall()


def _name_tokens(name: str) -> list[str]:
    import re
    return [t for t in re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).split() if t]


def merge_subset_characters(conn: sqlite3.Connection, verbose: bool = True) -> int:
    """Merge characters whose name is a token-subset of a longer character's
    name (e.g. 'King Alaric' -> 'King Alaric Valerius'), reassigning their facts,
    knowledge and relationships to the fuller name. Returns the merge count."""
    chars = conn.execute("SELECT canonical_name FROM characters").fetchall()
    names = [c["canonical_name"] for c in chars]
    toks = {n: set(_name_tokens(n)) for n in names}
    merged = 0
    for short in sorted(names, key=lambda n: len(toks[n])):
        if short not in toks or not toks[short]:
            continue
        # Find a strictly-longer name whose tokens are a superset and that
        # shares the first token (avoids merging unrelated people).
        best = None
        for long in names:
            if long == short or long not in toks:
                continue
            if (toks[short] < toks[long]
                    and _name_tokens(short)[0] == _name_tokens(long)[0]):
                if best is None or len(toks[long]) < len(toks[best]):
                    best = long
        if not best:
            continue
        for tbl, col in (("facts", "entity_name"),
                         ("knowledge", "character_name"),
                         ("relationships", "char_a"),
                         ("relationships", "char_b")):
            conn.execute(
                f"UPDATE {tbl} SET {col} = ? WHERE {col} = ? COLLATE NOCASE",
                (best, short))
        conn.execute("DELETE FROM characters WHERE canonical_name = ? "
                     "COLLATE NOCASE", (short,))
        toks.pop(short, None)
        merged += 1
        if verbose:
            print(f"  [merge] '{short}' -> '{best}'")
    conn.commit()
    return merged
