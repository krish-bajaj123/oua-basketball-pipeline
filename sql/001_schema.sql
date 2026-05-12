-- usports OUA basketball pipeline schema
-- Star-ish model: fact tables keyed by natural keys from usportshoops.ca
-- Upserts use ON CONFLICT on the natural key columns.

CREATE SCHEMA IF NOT EXISTS usports;
SET search_path TO usports, public;

-- ---------------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_season (
    season         TEXT PRIMARY KEY,        -- e.g. '2025-26'
    start_year     INTEGER NOT NULL,
    end_year       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_team (
    team_key       TEXT NOT NULL,           -- usportshoops Team= param, e.g. 'Carleton'
    gender         TEXT NOT NULL CHECK (gender IN ('MBB','WBB')),
    league         TEXT NOT NULL,           -- 'OUA'
    division       TEXT,                    -- 'East','West','Central'
    display_name   TEXT NOT NULL,
    PRIMARY KEY (team_key, gender)
);

CREATE TABLE IF NOT EXISTS dim_player (
    person_key     TEXT NOT NULL,           -- usportshoops Person= param, e.g. 'okado-marjok'
    gender         TEXT NOT NULL CHECK (gender IN ('MBB','WBB')),
    full_name      TEXT NOT NULL,
    hometown       TEXT,
    position       TEXT,
    height_inches  INTEGER,
    high_school    TEXT,
    PRIMARY KEY (person_key, gender)
);

-- ---------------------------------------------------------------------------
-- Facts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_team_season (
    team_key            TEXT NOT NULL,
    gender              TEXT NOT NULL,
    season              TEXT NOT NULL REFERENCES dim_season(season),
    league              TEXT,
    division            TEXT,
    head_coach          TEXT,
    conf_wins           INTEGER,
    conf_losses         INTEGER,
    conf_pct            NUMERIC(5,3),
    conf_points_for     INTEGER,
    conf_points_against INTEGER,
    overall_wins        INTEGER,
    overall_losses      INTEGER,
    overall_pct         NUMERIC(5,3),
    overall_points_for  INTEGER,
    overall_points_against INTEGER,
    scraped_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_key, gender, season),
    FOREIGN KEY (team_key, gender) REFERENCES dim_team(team_key, gender)
);

-- Roster bridge (one row per player-team-season)
CREATE TABLE IF NOT EXISTS fact_roster (
    person_key      TEXT NOT NULL,
    gender          TEXT NOT NULL,
    team_key        TEXT NOT NULL,
    season          TEXT NOT NULL,
    jersey_number   TEXT,
    position        TEXT,
    height_inches   INTEGER,
    eligibility     TEXT,
    hometown        TEXT,
    high_school     TEXT,
    prior_team      TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (person_key, gender, team_key, season)
);

-- Player season stats — one row per (player, season, stat_type)
-- stat_type ∈ {regular, playoff, national, overall}
CREATE TABLE IF NOT EXISTS fact_player_season_stats (
    person_key      TEXT NOT NULL,
    gender          TEXT NOT NULL,
    season          TEXT NOT NULL,
    team_key        TEXT,
    stat_type       TEXT NOT NULL CHECK (stat_type IN ('regular','playoff','national','overall')),
    games_played    INTEGER,
    games_started   INTEGER,
    minutes         INTEGER,
    minutes_per_game NUMERIC(5,2),
    fg_made         INTEGER,
    fg_attempted    INTEGER,
    fg_pct          NUMERIC(5,3),
    three_made      INTEGER,
    three_attempted INTEGER,
    three_pct       NUMERIC(5,3),
    ft_made         INTEGER,
    ft_attempted    INTEGER,
    ft_pct          NUMERIC(5,3),
    offensive_reb   INTEGER,
    defensive_reb   INTEGER,
    total_rebounds  INTEGER,
    rebounds_pg     NUMERIC(5,2),
    personal_fouls  INTEGER,
    assists         INTEGER,
    assists_pg      NUMERIC(5,2),
    turnovers       INTEGER,
    blocks          INTEGER,
    steals          INTEGER,
    points          INTEGER,
    points_pg       NUMERIC(5,2),
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (person_key, gender, season, stat_type)
);

-- Game results — one row per game
CREATE TABLE IF NOT EXISTS fact_game (
    game_id         TEXT PRIMARY KEY,        -- usportshoops Gameid, fallback to date+teams hash
    gender          TEXT NOT NULL,
    season          TEXT NOT NULL,
    game_date       DATE,
    location        TEXT,
    winner_team_key TEXT,
    loser_team_key  TEXT,
    winner_score    INTEGER,
    loser_score     INTEGER,
    comment         TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Indexes for common dashboard queries
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_roster_team_season ON fact_roster(team_key, gender, season);
CREATE INDEX IF NOT EXISTS idx_player_stats_team  ON fact_player_season_stats(team_key, gender, season);
CREATE INDEX IF NOT EXISTS idx_player_stats_pts   ON fact_player_season_stats(season, gender, stat_type, points_pg DESC);
CREATE INDEX IF NOT EXISTS idx_game_season        ON fact_game(season, gender, game_date);
CREATE INDEX IF NOT EXISTS idx_team_season_league ON fact_team_season(league, gender, season);

-- ---------------------------------------------------------------------------
-- Convenience views
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_oua_standings AS
SELECT
    t.display_name,
    fts.team_key,
    fts.gender,
    fts.season,
    fts.division,
    fts.conf_wins,
    fts.conf_losses,
    fts.conf_pct,
    fts.overall_wins,
    fts.overall_losses
FROM fact_team_season fts
JOIN dim_team t USING (team_key, gender)
WHERE fts.league = 'OUA';

CREATE OR REPLACE VIEW v_player_leaders AS
SELECT
    p.full_name,
    s.person_key,
    s.gender,
    s.season,
    s.team_key,
    s.points_pg,
    s.rebounds_pg,
    s.assists_pg,
    s.games_played
FROM fact_player_season_stats s
JOIN dim_player p USING (person_key, gender)
WHERE s.stat_type = 'regular';

-- Seed current season
INSERT INTO dim_season (season, start_year, end_year)
VALUES ('2025-26', 2025, 2026)
ON CONFLICT (season) DO NOTHING;
