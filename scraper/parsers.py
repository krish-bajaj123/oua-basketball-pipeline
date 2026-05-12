"""HTML parsers for usportshoops.ca pages.

Each public function takes raw HTML and returns a dict shaped like the
JSON we publish to Kafka.

Parsers are tolerant: missing sections return None / empty list rather
than raising. The site uses <table> for layout in places, so we always
pass `recursive=False` when reading row cells to avoid nested-table bleed.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cells(row: Tag) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"], recursive=False)]


def _to_int(s: str | None) -> int | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s == "-":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace("%", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _height_to_inches(s: str) -> int | None:
    """'6-1' -> 73."""
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", s or "")
    if not m:
        return None
    return int(m.group(1)) * 12 + int(m.group(2))


def _split_made_att(s: str) -> tuple[int | None, int | None]:
    """'95-269' -> (95, 269)."""
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", s or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _find_tables(soup: BeautifulSoup) -> list[Tag]:
    return soup.find_all("table")


def _table_with_header(soup: BeautifulSoup, *required_cells: str) -> Tag | None:
    """Find the first table whose first row's direct cells contain all required cells."""
    for t in _find_tables(soup):
        rows = t.find_all("tr")
        if not rows:
            continue
        head = [c.lower() for c in _cells(rows[0])]
        if all(any(req.lower() in h for h in head) for req in required_cells):
            return t
    return None


# ---------------------------------------------------------------------------
# Team season page
# ---------------------------------------------------------------------------

def parse_team_season(html: str, *, team_key: str, gender: str, season: str, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    head_coach = _extract_head_coach(soup)
    league, division = _extract_league_division(soup)
    record = _extract_record(soup)
    roster = _extract_roster(soup)
    schedule = _extract_schedule(soup, season=season)
    season_stats = _extract_team_season_stats(soup)

    return {
        "schema": "team_season",
        "schema_version": 1,
        "source_url": source_url,
        "team_key": team_key,
        "gender": gender,
        "season": season,
        "league": league,
        "division": division,
        "head_coach": head_coach,
        "record": record,
        "roster": roster,
        "schedule": schedule,
        "season_stats_overall": season_stats.get("overall", []),
        "season_stats_league": season_stats.get("league", []),
    }


def _extract_head_coach(soup: BeautifulSoup) -> str | None:
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"Head\s*Coach:\s*([^\n]+?)(?:Other\s*staff|Assistant Coach|League:|Website:|$)", txt)
    if m:
        return m.group(1).strip().rstrip(",")
    return None


def _extract_league_division(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"League:\s*(OUA)\s*(East|West|Central)?", txt)
    if not m:
        return None, None
    return m.group(1), (m.group(2) or None)


def _extract_record(soup: BeautifulSoup) -> dict[str, Any]:
    """Parse the 'Conference Record / U Sports Record / Overall Record' table."""
    t = _table_with_header(soup, "Conference Record", "Overall Record")
    out: dict[str, Any] = {"conference": {}, "usports": {}, "overall": {}}
    if not t:
        return out
    rows = t.find_all("tr")
    if len(rows) < 3:
        return out

    # Row 1: column groups (already in headers); row 2: subheaders W-L Pct Points PPG x3
    # Row 3: actual values, 12 cells in order.
    values = _cells(rows[2])
    # Some seasons have only 11 cells if Points missing; pad.
    values += [""] * (12 - len(values))

    def block(slc: slice) -> dict[str, Any]:
        wl, pct, pts, ppg = values[slc]
        wins, losses = (None, None)
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", wl or "")
        if m:
            wins, losses = int(m.group(1)), int(m.group(2))
        pf, pa = (None, None)
        m2 = re.match(r"^(\d+)\s*-\s*(\d+)$", pts or "")
        if m2:
            pf, pa = int(m2.group(1)), int(m2.group(2))
        return {
            "wins": wins, "losses": losses,
            "pct": _to_float(pct),
            "points_for": pf, "points_against": pa,
            "ppg_raw": ppg or None,
        }

    out["conference"] = block(slice(0, 4))
    out["usports"]    = block(slice(4, 8))
    out["overall"]    = block(slice(8, 12))
    return out


def _extract_roster(soup: BeautifulSoup) -> list[dict[str, Any]]:
    t = _table_with_header(soup, "Player", "Pos", "Ht", "Elig", "Hometown")
    if not t:
        return []
    out: list[dict[str, Any]] = []
    rows = t.find_all("tr")
    for r in rows[1:]:
        cells = _cells(r)
        if len(cells) < 7:
            continue
        # Player cell may contain link to person.php
        player_cell = r.find_all(["th", "td"], recursive=False)[1]
        person_key = _person_key_from_cell(player_cell)
        out.append({
            "jersey_number": cells[0] or None,
            "full_name": cells[1] or None,
            "person_key": person_key,
            "position": cells[2] or None,
            "height_raw": cells[3] or None,
            "height_inches": _height_to_inches(cells[3]),
            "eligibility": cells[4] or None,
            "hometown": cells[5] or None,
            "high_school": cells[6] or None,
        })
    return out


def _person_key_from_cell(cell: Tag) -> str | None:
    a = cell.find("a", href=True)
    if not a:
        return None
    href = a["href"]
    qs = parse_qs(urlparse(href).query)
    persons = qs.get("Person") or qs.get("person")
    if persons:
        return persons[0]
    return None


def _extract_schedule(soup: BeautifulSoup, *, season: str) -> list[dict[str, Any]]:
    """Team-page schedule table contains multiple sub-headers
    ('--- Non-Conference Games ---', '--- Conference Games ---', '--- Playoff Games ---')
    and rows like: Date | Location | Opponent | Win/Loss | score | Stats | Comment.
    A separate header row repeats per section. We classify each game by the
    most recent section header seen.
    """
    out: list[dict[str, Any]] = []
    target = None
    for t in _find_tables(soup):
        rows = t.find_all("tr")
        # Identify schedule table by presence of any row with 'Date' + 'Opponent' + 'Result'
        for r in rows:
            cells = _cells(r)
            head_text = " ".join(cells).lower()
            if "date" in head_text and "opponent" in head_text and "result" in head_text:
                target = t
                break
        if target:
            break
    if not target:
        return out

    section = "regular"
    for r in target.find_all("tr"):
        cells = _cells(r)
        if not cells:
            continue
        joined = " ".join(cells)
        # Section header rows are a single cell wrapped in dashes
        if len(cells) == 1 and "---" in joined:
            low = joined.lower()
            if "non-conference" in low:
                section = "non_conference"
            elif "playoff" in low:
                section = "playoff"
            elif "conference" in low:
                section = "conference"
            else:
                section = "other"
            continue
        # Header row repeats per section
        head_text = joined.lower()
        if "date" in head_text and "opponent" in head_text and "result" in head_text:
            continue
        if len(cells) < 5:
            continue
        date, location, opponent, result, score, *rest = cells + [""] * 6
        comment = rest[1] if len(rest) > 1 else (rest[0] if rest else "")
        team_score, opp_score = _split_made_att(score)
        out.append({
            "section": section,
            "date_raw": date,
            "location": location,
            "opponent_raw": opponent,
            "result": result,
            "team_score": team_score,
            "opponent_score": opp_score,
            "score_raw": score,
            "comment": comment,
        })
    return out


def _extract_team_season_stats(soup: BeautifulSoup) -> dict[str, list[dict[str, Any]]]:
    """The team page has two stat tables: overall and league-only.
    Both have header beginning with 'Player GP Mins Mpg ...'."""
    out: dict[str, list[dict[str, Any]]] = {"overall": [], "league": []}
    found = []
    for t in _find_tables(soup):
        rows = t.find_all("tr")
        if not rows:
            continue
        head = _cells(rows[0])
        if head and head[0].lower() == "player" and len(head) > 5 and head[1].upper() == "GP":
            parsed_rows = []
            for r in rows[1:]:
                pr = _parse_stat_row(_cells(r))
                if pr:
                    parsed_rows.append(pr)
            found.append(parsed_rows)
    if found:
        out["overall"] = found[0]
    if len(found) > 1:
        out["league"] = found[1]
    return out


# Stat row layout on team page (16 cells):
# Player | GP | Mins | Mpg | 3Pt(m-a) | 3Pt% | FG(m-a) | FG% | FT(m-a) | FT% |
#   Reb(o-d) | Reb tot | RPG | PF | A | TO | Bl | St | Pts | PPG
# Some columns are merged in the display so total may vary; we parse defensively.
_STAT_KEYS = [
    "player", "games_played", "minutes", "minutes_per_game",
    "three_pt_made_att", "three_pct",
    "fg_made_att", "fg_pct",
    "ft_made_att", "ft_pct",
    "reb_off_def", "total_rebounds", "rebounds_pg",
    "personal_fouls", "assists", "turnovers",
    "blocks", "steals", "points", "points_pg",
]


def _parse_stat_row(cells: list[str]) -> dict[str, Any] | None:
    if not cells or not cells[0]:
        return None
    # Pad / truncate to known length
    cells = cells + [""] * (len(_STAT_KEYS) - len(cells))
    raw = dict(zip(_STAT_KEYS, cells[:len(_STAT_KEYS)]))
    fg_made, fg_att = _split_made_att(raw["fg_made_att"])
    three_made, three_att = _split_made_att(raw["three_pt_made_att"])
    ft_made, ft_att = _split_made_att(raw["ft_made_att"])
    oreb, dreb = _split_made_att(raw["reb_off_def"])
    return {
        "player_name": raw["player"],
        "games_played":   _to_int(raw["games_played"]),
        "minutes":        _to_int(raw["minutes"]),
        "minutes_per_game": _to_float(raw["minutes_per_game"]),
        "three_made":     three_made, "three_attempted": three_att,
        "three_pct":      _to_float(raw["three_pct"]),
        "fg_made":        fg_made, "fg_attempted": fg_att,
        "fg_pct":         _to_float(raw["fg_pct"]),
        "ft_made":        ft_made, "ft_attempted": ft_att,
        "ft_pct":         _to_float(raw["ft_pct"]),
        "offensive_reb":  oreb, "defensive_reb": dreb,
        "total_rebounds": _to_int(raw["total_rebounds"]),
        "rebounds_pg":    _to_float(raw["rebounds_pg"]),
        "personal_fouls": _to_int(raw["personal_fouls"]),
        "assists":        _to_int(raw["assists"]),
        "turnovers":      _to_int(raw["turnovers"]),
        "blocks":         _to_int(raw["blocks"]),
        "steals":         _to_int(raw["steals"]),
        "points":         _to_int(raw["points"]),
        "points_pg":      _to_float(raw["points_pg"]),
    }


# ---------------------------------------------------------------------------
# Player profile page
# ---------------------------------------------------------------------------

def parse_player_profile(html: str, *, person_key: str, gender: str, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    name = _extract_player_name(soup)
    bio = _extract_player_bio(soup)
    career = _extract_playing_career(soup)
    season_lines = _extract_career_stats_blocks(soup)

    return {
        "schema": "player_profile",
        "schema_version": 1,
        "source_url": source_url,
        "person_key": person_key,
        "gender": gender,
        "full_name": name,
        "bio": bio,
        "career": career,
        "season_stats": season_lines,
    }


def _extract_player_name(soup: BeautifulSoup) -> str | None:
    """Player name lives inside a <font><b>...</b></font> near the top.
    The text "from <city>, <prov>" follows it. We use that anchor."""
    txt = soup.get_text("\n", strip=True)
    m = re.search(r"^([A-Z][^\n]+?)\nfrom\s+", txt, re.MULTILINE)
    if m:
        return m.group(1).strip()
    # Fallback: first <b> whose text is multiword and not navigation
    for b in soup.find_all("b"):
        s = b.get_text(" ", strip=True)
        if s and " " in s and "U Sports" not in s and "Search" not in s:
            return s
    return None


def _extract_player_bio(soup: BeautifulSoup) -> dict[str, Any]:
    """Bio line format: 'from <City, PROV>, <Position> <H-IN> Highschool: <school>'."""
    txt = soup.get_text(" ", strip=True)
    out: dict[str, Any] = {}
    m = re.search(r"from\s+([A-Za-z .'\-]+,\s*[A-Z]{2})", txt)
    if m:
        out["hometown"] = m.group(1).strip()
    m = re.search(r"from\s+[A-Za-z .'\-]+,\s*[A-Z]{2}\s*,?\s*([A-Za-z/ ]+?)\s+(\d+\s*-\s*\d+)", txt)
    if m:
        out["position"] = m.group(1).strip().rstrip(",")
        out["height_raw"] = m.group(2).strip()
        out["height_inches"] = _height_to_inches(out["height_raw"])
    m = re.search(r"Highschool:\s*([^|]+?)(?:\s+Awards received:|\s+Playing career:|$)", txt)
    if m:
        out["high_school"] = m.group(1).strip(" ,;")
    return out


def _extract_playing_career(soup: BeautifulSoup) -> list[dict[str, Any]]:
    t = _table_with_header(soup, "Season", "Team", "Num", "Elig")
    if not t:
        return []
    out = []
    for r in t.find_all("tr")[1:]:
        cells = _cells(r)
        if len(cells) < 4:
            continue
        team_cell = r.find_all(["th", "td"], recursive=False)[1]
        team_link_team = None
        team_link_gender = None
        a = team_cell.find("a", href=True)
        if a:
            qs = parse_qs(urlparse(a["href"]).query)
            team_link_team = (qs.get("Team") or [None])[0]
            team_link_gender = (qs.get("Gender") or [None])[0]
        out.append({
            "season": cells[0] or None,
            "team_display": cells[1] or None,
            "team_key": team_link_team,
            "gender": team_link_gender,
            "jersey_number": cells[2] if len(cells) > 2 else None,
            "eligibility": cells[3] if len(cells) > 3 else None,
            "team_finish": cells[4] if len(cells) > 4 else None,
            "league_record": cells[5] if len(cells) > 5 else None,
            "overall_record": cells[6] if len(cells) > 6 else None,
        })
    return out


def _extract_career_stats_blocks(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Player profile has up to 4 stats tables: regular / playoff / national / overall.
    They share the header 'Season GP-GS Mins MPG 3 Pt Field Goals Free Throws Rebounds PF AS ...'.
    We classify by order (table appearance) since the text headers above each table
    are in non-table tags and are not robust.
    """
    stats_tables: list[Tag] = []
    for t in _find_tables(soup):
        rows = t.find_all("tr")
        if not rows:
            continue
        head = _cells(rows[0])
        if head and head[0].lower() == "season" and any("gp" in h.lower() for h in head):
            stats_tables.append(t)

    types_by_index = ["regular", "playoff", "national", "overall"]
    out: list[dict[str, Any]] = []
    for idx, t in enumerate(stats_tables[:4]):
        stat_type = types_by_index[idx] if idx < len(types_by_index) else f"extra_{idx}"
        for r in t.find_all("tr")[1:]:
            row = _parse_player_stat_row(_cells(r))
            if row:
                row["stat_type"] = stat_type
                out.append(row)
    return out


# Player profile stats: 19 cells, no off/def rebound split.
# Season | GP-GS | Mins | MPG | 3Pt(m-a) | 3% | FG(m-a) | FG% | FT(m-a) | FT% |
#   Reb total | RPG | PF | AS | TO | Bl | ST | Pts | PPG
_PLAYER_STAT_KEYS = [
    "season", "gp_gs", "minutes", "minutes_per_game",
    "three_pt_made_att", "three_pct",
    "fg_made_att", "fg_pct",
    "ft_made_att", "ft_pct",
    "total_rebounds", "rebounds_pg",
    "personal_fouls", "assists", "turnovers",
    "blocks", "steals", "points", "points_pg",
]


def _parse_player_stat_row(cells: list[str]) -> dict[str, Any] | None:
    if not cells or not cells[0]:
        return None
    if cells[0].lower().startswith("total"):
        return None
    cells = cells + [""] * (len(_PLAYER_STAT_KEYS) - len(cells))
    raw = dict(zip(_PLAYER_STAT_KEYS, cells[:len(_PLAYER_STAT_KEYS)]))
    gp, gs = _split_made_att(raw["gp_gs"])
    fg_made, fg_att = _split_made_att(raw["fg_made_att"])
    three_made, three_att = _split_made_att(raw["three_pt_made_att"])
    ft_made, ft_att = _split_made_att(raw["ft_made_att"])
    return {
        "season":         raw["season"],
        "games_played":   gp, "games_started": gs,
        "minutes":        _to_int(raw["minutes"]),
        "minutes_per_game": _to_float(raw["minutes_per_game"]),
        "three_made":     three_made, "three_attempted": three_att,
        "three_pct":      _to_float(raw["three_pct"]),
        "fg_made":        fg_made, "fg_attempted": fg_att,
        "fg_pct":         _to_float(raw["fg_pct"]),
        "ft_made":        ft_made, "ft_attempted": ft_att,
        "ft_pct":         _to_float(raw["ft_pct"]),
        "offensive_reb":  None, "defensive_reb": None,
        "total_rebounds": _to_int(raw["total_rebounds"]),
        "rebounds_pg":    _to_float(raw["rebounds_pg"]),
        "personal_fouls": _to_int(raw["personal_fouls"]),
        "assists":        _to_int(raw["assists"]),
        "turnovers":      _to_int(raw["turnovers"]),
        "blocks":         _to_int(raw["blocks"]),
        "steals":         _to_int(raw["steals"]),
        "points":         _to_int(raw["points"]),
        "points_pg":      _to_float(raw["points_pg"]),
    }


# ---------------------------------------------------------------------------
# Schedule (seasongames.php) — game-level rows
# ---------------------------------------------------------------------------

def parse_seasongames(html: str, *, gender: str, season: str, source_url: str) -> list[dict[str, Any]]:
    """Parse league-wide schedule. One dict per game.
    Row layout (9 cells): Date | Location | _ | WinnerTeam | WinnerScore |
                         OpponentTeam | OpponentScore | Stats | Comment.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for t in _find_tables(soup):
        rows = t.find_all("tr")
        if not rows:
            continue
        head = [c.lower() for c in _cells(rows[0])]
        if "date" in head and "winner" in head and "opponent" in head:
            for r in rows[1:]:
                cells = _cells(r)
                if len(cells) < 7:
                    continue
                date, location = cells[0], cells[1]
                w_team, w_score_raw = cells[3], cells[4]
                l_team, l_score_raw = cells[5], cells[6]
                comment = cells[8] if len(cells) > 8 else (cells[7] if len(cells) > 7 else "")

                # Try to extract Gameid from any link
                game_id = None
                for a in r.find_all("a", href=True):
                    qs = parse_qs(urlparse(a["href"]).query)
                    if "Gameid" in qs:
                        game_id = qs["Gameid"][0]
                        break

                out.append({
                    "schema": "game",
                    "schema_version": 1,
                    "source_url": source_url,
                    "gender": gender,
                    "season": season,
                    "game_id": game_id,
                    "date_raw": date,
                    "location": location,
                    "winner_display": w_team or None,
                    "winner_score": _to_int(w_score_raw),
                    "loser_display": l_team or None,
                    "loser_score": _to_int(l_score_raw),
                    "comment": comment,
                })
            break
    return out
