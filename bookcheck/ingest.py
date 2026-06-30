"""Ingest: split a manuscript into Part / Chapter (POV + date) / Scene chunks.

The target manuscript uses a recurring header shape:

    Part One
    <POV name on its own short line>
    <date line, e.g. "November 24th - Evening">
    ...prose...
    * * *           <- scene break
    ...prose...

The first chapter is irregular (a blank line sits between the POV name and the
date), so we anchor on date lines and look *backwards* for the POV name rather
than requiring them to be adjacent. Any prose before the first header becomes a
"Prologue" chunk with no POV.
"""

from __future__ import annotations

import re

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")

# A date line: starts with a month, contains a day number. The trailing \d
# requirement stops "Maybe..." (which begins with "May") from matching.
DATE_RE = re.compile(rf"^\s*(?:{MONTHS})\b.*?\d", re.IGNORECASE)
# A POV header: a single capitalized word on an otherwise-empty line.
NAME_RE = re.compile(r"^\s*([A-Z][a-z]+)\s*$")
PART_RE = re.compile(r"^\s*Part\s+\w+\s*$", re.IGNORECASE)
SCENE_BREAK_RE = re.compile(r"^\s*\*\s*\*\s*\*\s*$")

_QUALIFIERS = {
    "morning": 1, "dawn": 0, "afternoon": 2, "midday": 2, "noon": 2,
    "evening": 3, "dusk": 3, "night": 4, "midnight": 5,
}
_MONTH_NUM = {m.lower(): i + 1 for i, m in enumerate(
    "January February March April May June July August September October "
    "November December".split())}


def _normalize_date(label: str) -> tuple[str | None, int | None]:
    """Return (date_norm, ordering_hint) from a raw date label."""
    if not label:
        return None, None
    low = label.lower()
    month = None
    for name, num in _MONTH_NUM.items():
        if name in low:
            month = num
            break
    day_m = re.search(r"(\d{1,2})", low)
    day = int(day_m.group(1)) if day_m else None
    qual = 2  # default to midday so unspecified scenes sort sensibly
    qual_name = ""
    for word, rank in _QUALIFIERS.items():
        if word in low:
            qual, qual_name = rank, word
            break
    if month is None or day is None:
        return label.strip(), None
    norm = f"{month:02d}-{day:02d}" + (f" {qual_name}" if qual_name else "")
    ordering = month * 1000 + day * 10 + qual
    return norm, ordering


def _date_after(lines: list[str], name_idx: int) -> int | None:
    """If a date line follows the POV name (skipping blanks, before any prose),
    return its line index; else None."""
    for k in range(name_idx + 1, min(len(lines), name_idx + 4)):
        if not lines[k].strip():
            continue
        return k if DATE_RE.match(lines[k]) else None
    return None


def _find_headers(lines: list[str]) -> list[dict]:
    """Locate POV-name section headers.

    The manuscript anchors on POV-name headers; a date line follows only when
    the day changes. We first learn the POV cast from name headers that *do*
    carry a date, then treat every standalone occurrence of a cast name as a
    section start, inheriting the most recent date forward.
    """
    # Pass A: discover the cast from dated headers.
    cast: set[str] = set()
    for i, line in enumerate(lines):
        m = NAME_RE.match(line)
        if m and _date_after(lines, i) is not None:
            cast.add(m.group(1))

    # Pass B: every standalone cast-name line is a section header.
    headers = []
    for i, line in enumerate(lines):
        m = NAME_RE.match(line)
        if not m or m.group(1) not in cast:
            continue
        date_idx = _date_after(lines, i)
        headers.append({
            "start": i,
            "date_line": date_idx,                       # may be None
            "body_start": (date_idx + 1) if date_idx is not None else i + 1,
            "pov": m.group(1),
            "date_label": lines[date_idx].strip() if date_idx is not None else None,
        })

    # Inherit dates forward for date-less (same-day) headers.
    last_label = None
    for h in headers:
        if h["date_label"]:
            last_label = h["date_label"]
        else:
            h["date_label"] = last_label
    return headers


def _current_part(lines: list[str], upto: int) -> str | None:
    part = None
    for k in range(upto):
        if PART_RE.match(lines[k]):
            part = lines[k].strip()
    return part


def split_manuscript(text: str) -> list[dict]:
    """Split raw manuscript text into a list of scene chunks (dicts)."""
    lines = text.splitlines()
    headers = _find_headers(lines)
    chunks: list[dict] = []

    # Prologue: prose before the first header (excluding Part markers).
    first = headers[0]["start"] if headers else len(lines)
    prologue = "\n".join(lines[:first]).strip()
    # Strip a leading "Part One" line from the prologue body if present.
    prologue_lines = [ln for ln in prologue.splitlines() if not PART_RE.match(ln)]
    prologue = "\n".join(prologue_lines).strip()
    if prologue:
        chunks.extend(_scenes_to_chunks(
            prologue, part=_current_part(lines, first) or "Part One",
            chapter_seq=0, pov=None, date_label=None))

    chapter_seq = 1 if prologue else 0
    for idx, h in enumerate(headers):
        body_start = h["body_start"]
        body_end = headers[idx + 1]["start"] if idx + 1 < len(headers) else len(lines)
        body = "\n".join(lines[body_start:body_end]).strip()
        part = _current_part(lines, h["start"] + 1)
        chunks.extend(_scenes_to_chunks(
            body, part=part, chapter_seq=chapter_seq, pov=h["pov"],
            date_label=h["date_label"]))
        chapter_seq += 1

    return chunks


def _scenes_to_chunks(body: str, *, part, chapter_seq, pov, date_label):
    date_norm, ordering = _normalize_date(date_label) if date_label else (None, None)
    scenes, current = [], []
    for line in body.splitlines():
        if SCENE_BREAK_RE.match(line):
            scenes.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    scenes.append("\n".join(current).strip())
    # Drop empty scenes and dangling header-only fragments (e.g. a lone POV
    # name at EOF).
    scenes = [s for s in scenes if len(s.split()) >= 3]

    out = []
    for si, scene in enumerate(scenes):
        out.append({
            "part": part, "chapter_seq": chapter_seq, "scene_index": si,
            "pov": pov, "date_label": date_label, "date_norm": date_norm,
            "ordering_hint": ordering, "text": scene,
        })
    return out


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], encoding="utf-8") as f:
        cs = split_manuscript(f.read())
    print(f"{len(cs)} chunks")
    for c in cs:
        words = len(c["text"].split())
        print(f"  Ch.{c['chapter_seq']} sc.{c['scene_index']} "
              f"pov={c['pov']} date={c['date_label']!r} "
              f"norm={c['date_norm']!r} words={words}")
