"""FastAPI read API over the curated Postgres tables.

Endpoints:
  GET /health
  GET /seasons
  GET /standings?gender=MBB&season=2025-26
  GET /teams?gender=MBB
  GET /teams/{gender}/{team_key}
  GET /teams/{gender}/{team_key}/roster?season=2025-26
  GET /players/{gender}/{person_key}
  GET /leaders?stat=points_pg&gender=MBB&season=2025-26&limit=20
  GET /games?gender=MBB&season=2025-26
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DB_URL = (f"postgresql+psycopg2://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
          f"@{os.environ.get('PG_HOST','postgres')}:{os.environ.get('PG_PORT','5432')}"
          f"/{os.environ['PG_DB']}")

engine: Engine = create_engine(DB_URL, pool_pre_ping=True, future=True)

app = FastAPI(title="usports OUA basketball API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


def query(sql: str, **params) -> list[dict[str, Any]]:
    with engine.connect() as c:
        c.execute(text("SET search_path TO usports, public"))
        rows = c.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(503, str(e))


@app.get("/seasons")
def seasons() -> list[dict]:
    return query("SELECT season, start_year, end_year FROM dim_season ORDER BY start_year DESC")


@app.get("/teams")
def teams(gender: str = Query(..., regex="^(MBB|WBB)$"), league: str = "OUA") -> list[dict]:
    return query(
        "SELECT team_key, gender, league, division, display_name "
        "FROM dim_team WHERE gender=:g AND league=:l ORDER BY division, display_name",
        g=gender, l=league,
    )


@app.get("/standings")
def standings(gender: str = Query(...), season: str = Query(...), league: str = "OUA") -> list[dict]:
    return query("""
        SELECT t.display_name, t.team_key, t.division,
               fts.conf_wins, fts.conf_losses, fts.conf_pct,
               fts.overall_wins, fts.overall_losses, fts.overall_pct,
               fts.conf_points_for, fts.conf_points_against
        FROM fact_team_season fts
        JOIN dim_team t USING (team_key, gender)
        WHERE fts.gender=:g AND fts.season=:s AND fts.league=:l
        ORDER BY t.division, COALESCE(fts.conf_pct,0) DESC
    """, g=gender, s=season, l=league)


@app.get("/teams/{gender}/{team_key}")
def team_detail(gender: str, team_key: str, season: str = "2025-26") -> dict:
    base = query("""SELECT t.*, fts.head_coach,
                           fts.conf_wins, fts.conf_losses, fts.conf_pct,
                           fts.overall_wins, fts.overall_losses, fts.overall_pct
                    FROM dim_team t
                    LEFT JOIN fact_team_season fts USING (team_key, gender)
                    WHERE t.gender=:g AND t.team_key=:k
                      AND (fts.season=:s OR fts.season IS NULL)""",
                 g=gender, k=team_key, s=season)
    if not base:
        raise HTTPException(404, "team not found")
    return base[0]


@app.get("/teams/{gender}/{team_key}/roster")
def roster(gender: str, team_key: str, season: str = "2025-26") -> list[dict]:
    return query("""
        SELECT r.person_key, p.full_name, r.jersey_number, r.position,
               r.height_inches, r.eligibility, r.hometown, r.high_school
        FROM fact_roster r
        LEFT JOIN dim_player p USING (person_key, gender)
        WHERE r.gender=:g AND r.team_key=:k AND r.season=:s
        ORDER BY r.jersey_number
    """, g=gender, k=team_key, s=season)


@app.get("/players/{gender}/{person_key}")
def player_detail(gender: str, person_key: str) -> dict:
    pl = query("SELECT * FROM dim_player WHERE gender=:g AND person_key=:k",
               g=gender, k=person_key)
    if not pl:
        raise HTTPException(404, "player not found")
    stats = query("""
        SELECT * FROM fact_player_season_stats
        WHERE gender=:g AND person_key=:k
        ORDER BY season DESC, stat_type
    """, g=gender, k=person_key)
    return {**pl[0], "stats": stats}


@app.get("/leaders")
def leaders(
    gender: str, season: str,
    stat: str = Query("points_pg", regex="^(points_pg|rebounds_pg|assists|fg_pct|three_pct|ft_pct|points|total_rebounds|steals|blocks)$"),
    league: str = "OUA",
    limit: int = 20,
) -> list[dict]:
    return query(f"""
        SELECT p.full_name, s.person_key, s.team_key, s.{stat} AS value,
               s.games_played, s.points_pg, s.rebounds_pg
        FROM fact_player_season_stats s
        JOIN dim_player p USING (person_key, gender)
        JOIN fact_roster r USING (person_key, gender, season, team_key)
        JOIN dim_team t USING (team_key, gender)
        WHERE s.gender=:g AND s.season=:s AND s.stat_type='regular' AND t.league=:l
          AND s.{stat} IS NOT NULL
        ORDER BY s.{stat} DESC NULLS LAST
        LIMIT :n
    """, g=gender, s=season, l=league, n=limit)


@app.get("/games")
def games(gender: str, season: str, limit: int = 200) -> list[dict]:
    return query("""
        SELECT game_id, game_date, location,
               winner_team_key, winner_score, loser_team_key, loser_score, comment
        FROM fact_game
        WHERE gender=:g AND season=:s
        ORDER BY game_date DESC NULLS LAST
        LIMIT :n
    """, g=gender, s=season, n=limit)
