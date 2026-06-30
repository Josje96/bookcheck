"""Extraction pass: per-scene structured extraction (qwen3:4b) -> store."""

from __future__ import annotations

import re

from . import prompts, store
from .ollama_client import OllamaClient

# qwen3:4b is the extraction workhorse: ~2x the tokens/sec of 8b on a Vulkan
# AMD GPU, and plenty accurate for structured fact-pulling. Override with the
# --model flag (e.g. qwen3:8b) for higher quality at lower speed.
EXTRACT_MODEL = "qwen3:4b"
NUM_PREDICT = 2400   # generous cap: avoids mid-JSON truncation, still bounded
# Large scenes are split into windows so each model call stays small and the
# model stays accurate (and outputs fit comfortably under NUM_PREDICT).
WINDOW_WORDS = 1000

# Author draft notes left inline, e.g. *add him getting there* or [TODO: fix].
DRAFT_NOTE_RE = re.compile(r"(\*[^*\n]{3,}\*|\[[^\]\n]{3,}\])")
_POLARITY = {"positive": 1, "negative": -1, "+": 1, "-": -1}

# First-person/POV narration makes small models extract pronouns as "characters".
JUNK_NAMES = {
    "i", "me", "my", "myself", "we", "us", "you", "he", "him", "his", "she",
    "her", "they", "them", "it", "the", "a", "an", "someone", "everyone",
    "no one", "narrator", "unknown", "man", "woman", "girl", "boy", "child",
    "kid", "vendor", "shop owner", "shopkeeper", "stranger", "figure", "voice",
    "werewolf", "vampire", "witch", "fairy", "fae", "person", "guard", "king",
    "queen", "young woman", "young man", "old man", "old woman",
}


def _valid_name(name: str) -> bool:
    n = (name or "").strip().lower()
    # Strip leading articles ("the man", "a vendor") before checking.
    for art in ("the ", "a ", "an "):
        if n.startswith(art):
            n = n[len(art):]
    return len(n) >= 2 and n not in JUNK_NAMES and any(c.isalpha() for c in n)


def _valid_location(name: str) -> bool:
    """Keep only places that read as a specific, named location. Generic,
    un-named places ("kitchen", "town", "city street", "the cottage") are noise;
    the model writes those in lowercase, while proper places carry a capital
    (Stillwater, The Lair) or a possessive owner (Mila's cottage), so an
    uppercase letter is a reliable, simple signal."""
    n = (name or "").strip()
    if len(n) < 2:
        return False
    return any(c.isupper() for c in n)


def _windows(text: str, max_words: int = WINDOW_WORDS) -> list[str]:
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    windows, cur, cur_n = [], [], 0
    for p in paras:
        n = len(p.split())
        if cur and cur_n + n > max_words:
            windows.append("\n\n".join(cur))
            cur, cur_n = [], 0
        cur.append(p)
        cur_n += n
    if cur:
        windows.append("\n\n".join(cur))
    return windows or [text]


def _capture_draft_notes(conn, chunk_id, text, cref):
    for m in DRAFT_NOTE_RE.finditer(text):
        note = m.group(1).strip()
        # Skip pure scene-break asterisks already handled by the splitter.
        if set(note) <= {"*", " "}:
            continue
        store.insert_conflict(
            conn, kind="draft_note",
            description=f"Author draft note / unfinished spot left in the text at {cref}.",
            severity="low", source_a_chunk=chunk_id, source_a_quote=note,
            source_b_chunk=None, source_b_quote=None, detected_by="ingest")


def extract_chunk(conn, client: OllamaClient, chunk_id: int, chunk: dict) -> dict:
    cref = store.chunk_ref(conn, chunk_id)
    text = chunk["text"]
    _capture_draft_notes(conn, chunk_id, text, cref)

    counts = {"characters": 0, "facts": 0, "relationships": 0, "timeline": 0,
              "knowledge": 0, "plot_setups": 0, "plot_payoffs": 0, "locations": 0}

    for window in _windows(text):
        user = prompts.extraction_user(window, chunk.get("pov_character"),
                                       chunk.get("date_label"), cref)
        data = client.chat_json(
            EXTRACT_MODEL, prompts.EXTRACTION_SYSTEM, user,
            schema=prompts.EXTRACTION_SCHEMA, think=False, num_ctx=6144,
            num_predict=NUM_PREDICT)
        _write(conn, chunk_id, data, counts)
        conn.commit()
    return counts


def _write(conn, chunk_id, data, counts):
    if not isinstance(data, dict):
        return

    for ch in data.get("characters", []) or []:
        if isinstance(ch, str):
            name, species, traits = ch.strip(), None, []
        elif isinstance(ch, dict):
            name = (ch.get("name") or "").strip()
            species = (ch.get("species") or "").strip() or None
            traits = ch.get("traits", []) or []
        else:
            continue
        if not _valid_name(name):
            continue
        cid = store.upsert_character(conn, name, species)
        counts["characters"] += 1
        for tr in traits:
            # Tolerate traits as dicts (schema) or bare strings (json fallback).
            if isinstance(tr, str):
                attr, val, quote = "trait", tr.strip(), ""
            elif isinstance(tr, dict):
                attr = (tr.get("attribute") or "").strip()
                val = (tr.get("value") or "").strip()
                quote = (tr.get("quote") or "").strip()
            else:
                continue
            if not attr or not val:
                continue
            store.insert_fact(conn, entity_type="character", entity_id=cid,
                              entity_name=name, attribute=attr, value=val,
                              polarity=1, chunk_id=chunk_id, quote=quote)
            counts["facts"] += 1

    for loc in data.get("locations", []) or []:
        # Schema returns {name, description}; tolerate bare strings too.
        if isinstance(loc, str):
            name, desc = loc.strip(), None
        elif isinstance(loc, dict):
            name = (loc.get("name") or "").strip()
            desc = (loc.get("description") or "").strip() or None
        else:
            continue
        if name and _valid_location(name):
            store.upsert_location(conn, name, notes=desc)
            counts["locations"] += 1

    for f in data.get("facts", []) or []:
        if not isinstance(f, dict):
            continue
        ent = (f.get("entity") or "").strip()
        attr = (f.get("attribute") or "").strip()
        val = (f.get("value") or "").strip()
        if not ent or not attr:
            continue
        etype = (f.get("entity_type") or "world").strip()
        if etype == "character" and not _valid_name(ent):
            continue
        eid = store.upsert_character(conn, ent) if etype == "character" else None
        pol = _POLARITY.get((f.get("polarity") or "positive").strip().lower(), 1)
        store.insert_fact(conn, entity_type=etype, entity_id=eid,
                          entity_name=ent, attribute=attr, value=val,
                          polarity=pol, chunk_id=chunk_id,
                          quote=(f.get("quote") or "").strip())
        counts["facts"] += 1

    for r in data.get("relationships", []) or []:
        if not isinstance(r, dict):
            continue
        a, b = (r.get("char_a") or "").strip(), (r.get("char_b") or "").strip()
        if not a or not b:
            continue
        store.insert_relationship(conn, char_a=a, char_b=b,
                                  relation_type=(r.get("relation") or "").strip(),
                                  polarity=1, chunk_id=chunk_id,
                                  quote=(r.get("quote") or "").strip())
        counts["relationships"] += 1

    for t in data.get("timeline", []) or []:
        if not isinstance(t, dict):
            continue
        ev = (t.get("event") or "").strip()
        if not ev:
            continue
        row = conn.execute("SELECT ordering_hint, date_norm FROM chunks WHERE id=?",
                           (chunk_id,)).fetchone()
        store.insert_timeline_event(
            conn, when_norm=(row["date_norm"] if row else None),
            when_raw=(t.get("when") or "").strip(),
            ordering_hint=(row["ordering_hint"] if row else None),
            description=ev, characters=[], location_id=None,
            chunk_id=chunk_id, quote=(t.get("quote") or "").strip())
        counts["timeline"] += 1

    for k in data.get("knowledge", []) or []:
        if not isinstance(k, dict):
            continue
        who = (k.get("character") or "").strip()
        prop = (k.get("learns") or "").strip()
        if not who or not prop:
            continue
        store.insert_knowledge(conn, character_name=who, proposition=prop,
                               learned_chunk_id=chunk_id,
                               quote=(k.get("quote") or "").strip())
        counts["knowledge"] += 1

    for s in data.get("plot_setups", []) or []:
        if not isinstance(s, dict):
            continue
        nm = (s.get("name") or s.get("description") or "").strip()
        if not nm:
            continue
        store.insert_plot_thread(conn, name=nm[:80],
                                 description=(s.get("description") or "").strip(),
                                 status="open", setup_chunk_id=chunk_id)
        counts["plot_setups"] += 1

    for p in data.get("plot_payoffs", []) or []:
        if not isinstance(p, dict):
            continue
        nm = (p.get("name") or p.get("description") or "").strip()
        if not nm:
            continue
        store.insert_plot_thread(conn, name=nm[:80],
                                 description=(p.get("description") or "").strip(),
                                 status="resolved", setup_chunk_id=None,
                                 payoff_chunk_id=chunk_id)
        counts["plot_payoffs"] += 1


def run_extraction(conn, client: OllamaClient, verbose: bool = True) -> None:
    chunks = conn.execute(
        "SELECT * FROM chunks ORDER BY chapter_seq, scene_index").fetchall()
    for row in chunks:
        chunk = dict(row)
        cref = store.chunk_ref(conn, row["id"])
        try:
            counts = extract_chunk(conn, client, row["id"], chunk)
            if verbose:
                summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
                print(f"  [extract] {cref}: {summary or 'nothing'}")
        except Exception as e:  # noqa: BLE001 - keep going on a bad scene
            print(f"  [extract] {cref}: FAILED ({e})")
