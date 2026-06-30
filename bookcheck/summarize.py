"""Comprehension layer: per-chapter summaries (with self-flagged uncertainties),
prose character descriptions, and an overall beta-reader impression.

This is the "show what I understood" half of the tool. Unlike hole-detection,
being approximately right is fine here -- the author reads the summary and
instantly sees whether the model (or the prose) went wrong. The model's
*uncertainties* are themselves useful: a spot the model couldn't follow is often
a spot a reader can't either.
"""

from __future__ import annotations

import json

from . import store
from .ollama_client import OllamaClient

# Comprehension benefits from the stronger model; these are low-volume passes.
SUMMARY_MODEL = "qwen3:8b"

# --- per-chapter summary -------------------------------------------------

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "uncertainties"],
}

SUMMARY_SYSTEM = """\
You are a developmental editor's assistant doing a first read of a novel. You are
given ONE chapter (a single point-of-view section). Produce:
- summary: 2-4 sentences, plain language, describing what actually happens in
  this chapter in reading order. Faithful to the text; do not invent or
  speculate about meaning.
- uncertainties: a short list of things that were genuinely unclear in the
  writing -- places where you could not tell who "he/she/they" referred to, what
  physically happened, or what something meant. These flag possibly-confusing
  prose for the author. List ONLY real ambiguities, not style preferences. If
  the chapter was clear, return an empty list.

Return valid JSON.\
"""


def _chapter_text(conn, chapter_seq) -> tuple[str, str, str]:
    rows = conn.execute(
        "SELECT pov_character, date_label, text FROM chunks WHERE chapter_seq=? "
        "ORDER BY scene_index", (chapter_seq,)).fetchall()
    pov = rows[0]["pov_character"] if rows else None
    date = rows[0]["date_label"] if rows else None
    text = "\n\n".join(r["text"] for r in rows)
    # Keep within context; chapters are short, but guard the rare long one.
    words = text.split()
    if len(words) > 2500:
        text = " ".join(words[:2500])
    return pov, date, text


def run_summaries(conn, client: OllamaClient, model=SUMMARY_MODEL,
                  verbose=True) -> int:
    conn.execute("DELETE FROM chapter_summaries")
    conn.commit()
    seqs = [r["chapter_seq"] for r in conn.execute(
        "SELECT DISTINCT chapter_seq FROM chunks ORDER BY chapter_seq").fetchall()]
    done = 0
    for seq in seqs:
        pov, date, text = _chapter_text(conn, seq)
        label = "Prologue" if not pov else f"Ch.{seq} ({pov}, {date})"
        header = f"[{label}]"
        user = f"{header}\n\nCHAPTER:\n\"\"\"\n{text}\n\"\"\"\n\nSummarize now."
        try:
            data = client.chat_json(model, SUMMARY_SYSTEM, user,
                                    schema=SUMMARY_SCHEMA, think=False,
                                    num_ctx=8192, num_predict=600)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [summary] {label}: FAILED ({e})")
            continue
        store.save_chapter_summary(
            conn, chapter_seq=seq, pov_character=pov, date_label=date,
            summary=(data.get("summary") if isinstance(data, dict) else "") or "",
            uncertainties=(data.get("uncertainties") if isinstance(data, dict)
                           else []) or [])
        conn.commit()
        done += 1
        if verbose:
            n = len(data.get("uncertainties", [])) if isinstance(data, dict) else 0
            print(f"  [summary] {label}: ok ({n} uncertainty flag(s))")
    return done


# --- character descriptions + arc analysis ------------------------------

def _classify_role(pov_chapters, chapters_in) -> str:
    if pov_chapters >= 2:
        return "main"
    if pov_chapters == 1 or chapters_in >= 3:
        return "supporting"
    return "minor"


MINOR_SYSTEM = """\
Write a 1-2 sentence story-bible description of this minor character based only
on the provided facts and relationships: who they are and their role. Natural
prose, no bullet points, no invention.\
"""

ARC_SYSTEM = """\
You are a developmental editor analyzing one character in a novel draft. Using
ONLY the provided facts, relationships, and the summaries of chapters where they
appear, return JSON with:
- description: 2-3 sentences on who they are and their key relationships.
- strengths: what is working about this character as written (what's vivid,
  distinct, or compelling).
- weaknesses: what feels thin, underdeveloped, or unclear about them.
- arc: their emotional/story arc across the draft so far, in 1-2 sentences.
- development: concrete, specific suggestions to deepen their arc (readers want
  fuller arcs). 1-3 sentences.
Be honest and specific; base everything on the provided material, do not invent
plot. If the character genuinely has little material, keep fields short.\
"""

ARC_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "strengths": {"type": "string"},
        "weaknesses": {"type": "string"},
        "arc": {"type": "string"},
        "development": {"type": "string"},
    },
    "required": ["description", "strengths", "weaknesses", "arc", "development"],
}


def _character_context(conn, name) -> str:
    facts = conn.execute(
        "SELECT DISTINCT attribute, value FROM facts WHERE entity_name=? "
        "COLLATE NOCASE AND polarity>=0 LIMIT 25", (name,)).fetchall()
    rels = conn.execute(
        "SELECT DISTINCT char_a, char_b, relation_type FROM relationships "
        "WHERE char_a=? OR char_b=? COLLATE NOCASE LIMIT 15", (name, name)
    ).fetchall()
    fact_s = "; ".join(f"{f['attribute']}={f['value']}" for f in facts) or "none"
    rel_s = "; ".join(
        f"{r['char_a']} & {r['char_b']}: {r['relation_type']}" for r in rels
    ) or "none recorded"
    # Chapter summaries where this character is POV or is mentioned.
    sums = conn.execute(
        "SELECT chapter_seq, pov_character, summary FROM chapter_summaries "
        "ORDER BY chapter_seq").fetchall()
    rel_sums = []
    for s in sums:
        if (s["pov_character"] and s["pov_character"].lower() == name.lower()) \
                or (name.lower() in (s["summary"] or "").lower()):
            tag = "POV" if (s["pov_character"] and
                            s["pov_character"].lower() == name.lower()) else "appears"
            rel_sums.append(f"Ch.{s['chapter_seq']} ({tag}): {s['summary']}")
    sum_s = "\n".join(rel_sums[:8]) or "none"
    return f"FACTS: {fact_s}\nRELATIONSHIPS: {rel_s}\n\nCHAPTERS:\n{sum_s}"


def run_profiles(conn, client: OllamaClient, model=SUMMARY_MODEL,
                 verbose=True) -> int:
    # Rebuild the table so schema changes always take effect.
    conn.execute("DROP TABLE IF EXISTS character_profiles")
    conn.executescript(store.SCHEMA)
    conn.commit()
    done = 0
    for c in store.real_characters(conn):
        name = c["canonical_name"]
        nfacts = conn.execute(
            "SELECT COUNT(*) n FROM facts WHERE entity_name=? COLLATE NOCASE",
            (name,)).fetchone()["n"]
        pov, chaps = store.character_appearances(conn, name)
        role = _classify_role(pov, chaps)
        # Too little to say anything real (no facts, never POV, not tied to a
        # chapter -- e.g. a name known only from a relationship). Surface them
        # anyway with an honest placeholder rather than dropping them silently;
        # an author wants to see "Mila is here but thin", not have her vanish.
        # Costs no model call.
        if nfacts < 2 and pov == 0 and chaps == 0:
            store.save_character_profile(
                conn, name, role="minor",
                description="Not enough information recorded for this character "
                            "yet -- they appear in the draft but the read didn't "
                            "pick up enough detail to describe them.")
            done += 1
            conn.commit()
            if verbose:
                print(f"  [profile] {name}: thin (placeholder)")
            continue
        ctx = _character_context(conn, name)
        try:
            if role == "minor":
                desc = client.strip_think(client.chat(
                    model, MINOR_SYSTEM, f"CHARACTER: {name}\n\n{ctx}",
                    think=False, num_ctx=4096, num_predict=200)).strip()
                store.save_character_profile(conn, name, role=role,
                                             description=desc)
            else:
                d = client.chat_json(
                    model, ARC_SYSTEM, f"CHARACTER: {name} (role: {role})\n\n{ctx}",
                    schema=ARC_SCHEMA, think=False, num_ctx=8192, num_predict=700)
                store.save_character_profile(
                    conn, name, role=role,
                    description=(d.get("description") or "").strip(),
                    strengths=(d.get("strengths") or "").strip(),
                    weaknesses=(d.get("weaknesses") or "").strip(),
                    arc=(d.get("arc") or "").strip(),
                    development=(d.get("development") or "").strip())
            done += 1
            if verbose:
                print(f"  [profile] {name} ({role}): ok")
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [profile] {name}: FAILED ({e})")
        conn.commit()
    return done


# --- overall beta-reader impression -------------------------------------

FEEDBACK_SYSTEM = """\
You are an experienced beta reader giving a first-pass impression of a novel
draft. You are given short summaries of each chapter (labelled Ch.N). Write a
warm but honest impression for the author:
- 2-3 short paragraphs on what is working and what might need attention
  (pacing, clarity, character, structure, momentum).
- Then three one-line notes labelled Clarity, Pacing, and Consistency.
CRUCIAL: whenever you raise an issue (e.g. repetition, slow pacing, confusion),
NAME the specific chapters by their Ch.N label and say briefly WHY (e.g. "Ch.10
and Ch.16 both re-establish Ester's wish to leave without advancing it"). Never
say "some chapters" without naming them. Be specific and constructive; you are
helping a writer, not grading. Do NOT give a numeric score. Plain prose / light
markdown.\
"""


def _overlap_hint(rows) -> str:
    """Deterministically flag chapter pairs whose summaries share a lot of
    content words -- gives the model concrete candidates for 'repetitive'."""
    import re as _re
    stop = set("the a an and or but of to in on at for with her his their she "
               "he they it him them as is was were be been into out from that "
               "this who which when then than over under up down off about back "
               "after before while during".split())
    def words(s):
        return {w for w in _re.findall(r"[a-z]+", (s or "").lower())
                if len(w) > 3 and w not in stop}
    wsets = [(r["chapter_seq"], r["pov_character"], words(r["summary"]))
             for r in rows]
    pairs = []
    for i in range(len(wsets)):
        for j in range(i + 1, len(wsets)):
            a, b = wsets[i][2], wsets[j][2]
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac >= 0.28:
                pairs.append((wsets[i][0], wsets[j][0], round(jac, 2)))
    pairs.sort(key=lambda p: -p[2])
    if not pairs:
        return ""
    return ("\n\nPOSSIBLE OVERLAPS (chapters sharing similar content — verify "
            "before citing): " +
            "; ".join(f"Ch.{a}~Ch.{b}" for a, b, _ in pairs[:6]))


def run_feedback(conn, client: OllamaClient, model=SUMMARY_MODEL,
                 verbose=True) -> int:
    rows = conn.execute(
        "SELECT chapter_seq, pov_character, date_label, summary "
        "FROM chapter_summaries ORDER BY chapter_seq").fetchall()
    if not rows:
        return 0
    lines = []
    for r in rows:
        label = "Prologue" if not r["pov_character"] else \
            f"Ch.{r['chapter_seq']} ({r['pov_character']}, {r['date_label']})"
        lines.append(f"{label}: {r['summary']}")
    user = ("Here are the chapter summaries of the draft:\n\n" +
            "\n".join(lines) + _overlap_hint(rows) +
            "\n\nWrite your first-pass impression now, citing specific chapters.")
    try:
        text = client.chat(model, FEEDBACK_SYSTEM, user, think=False,
                           num_ctx=8192, num_predict=900)
        text = client.strip_think(text).strip()
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  [feedback] FAILED ({e})")
        return 0
    if text:
        store.save_book_feedback(conn, text)
        if verbose:
            print("  [feedback] ok")
        conn.commit()
    return 1 if text else 0


# --- WIP: how to close open threads -------------------------------------

CLOSING_SYSTEM = """\
You are a story consultant helping with an UNFINISHED novel draft. You are given
chapter summaries and a list of open threads/setups. Identify the major
unresolved threads and, for each, suggest 1-2 plausible ways the author could
resolve it that stay consistent with what's already established. Be concrete and
generative -- this is brainstorming to help finish the story, not criticism.
Return JSON: {"threads": [{"thread": "...", "suggestion": "..."}]}. Focus on the
handful of biggest threads, not every minor detail.\
"""

CLOSING_SCHEMA = {
    "type": "object",
    "properties": {
        "threads": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "thread": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["thread", "suggestion"],
            },
        }
    },
    "required": ["threads"],
}


def run_closing(conn, client: OllamaClient, model=SUMMARY_MODEL,
                verbose=True) -> int:
    conn.execute("DELETE FROM closing_suggestions")
    conn.commit()
    sums = conn.execute(
        "SELECT chapter_seq, pov_character, summary FROM chapter_summaries "
        "ORDER BY chapter_seq").fetchall()
    if not sums:
        return 0
    setups = conn.execute(
        "SELECT DISTINCT name, description FROM plot_threads WHERE status='open' "
        "LIMIT 30").fetchall()
    sum_s = "\n".join(
        f"Ch.{s['chapter_seq']} ({s['pov_character'] or 'Prologue'}): {s['summary']}"
        for s in sums)
    setup_s = "\n".join(f"- {s['name']}: {s['description']}" for s in setups) \
        or "(none extracted)"
    user = (f"CHAPTER SUMMARIES:\n{sum_s}\n\nOPEN THREADS:\n{setup_s}\n\n"
            "Suggest how to close the major threads.")
    try:
        data = client.chat_json(model, CLOSING_SYSTEM, user,
                                schema=CLOSING_SCHEMA, think=False,
                                num_ctx=8192, num_predict=1200)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  [closing] FAILED ({e})")
        return 0
    threads = data.get("threads", []) if isinstance(data, dict) else []
    for t in threads:
        if isinstance(t, dict) and t.get("thread"):
            store.save_closing_suggestion(conn, t["thread"].strip(),
                                          (t.get("suggestion") or "").strip())
    conn.commit()
    if verbose:
        print(f"  [closing] {len(threads)} thread suggestion(s)")
    return len(threads)


def run_all_comprehension(conn, client: OllamaClient, model=SUMMARY_MODEL,
                          wip=None):
    if wip is None:
        wip = store.detect_wip(conn)
    print(f"Chapter summaries ({model})...")
    run_summaries(conn, client, model)
    print(f"Character descriptions + arcs ({model})...")
    run_profiles(conn, client, model)
    print(f"Overall impression ({model})...")
    run_feedback(conn, client, model)
    if wip:
        print(f"Closing suggestions — work-in-progress ({model})...")
        run_closing(conn, client, model)
    else:
        print("Skipping closing suggestions (manuscript looks finished).")
