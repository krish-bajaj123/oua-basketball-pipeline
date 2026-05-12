"""Spark batch job: read raw NDJSON from S3, normalize into curated tables,
write Parquet to s3://.../curated/, then JDBC-upsert into Postgres.

Inputs (NDJSON written by the consumer):
  s3://$RAW_BUCKET/raw/usports.team_season.raw/dt=*/...jsonl
  s3://$RAW_BUCKET/raw/usports.player_profile.raw/dt=*/...jsonl
  s3://$RAW_BUCKET/raw/usports.game.raw/dt=*/...jsonl

Run with spark-submit. Required packages:
  org.apache.hadoop:hadoop-aws:3.3.4
  org.postgresql:postgresql:42.7.3
"""
from __future__ import annotations

import os
import sys

from pyspark.sql import DataFrame, SparkSession, functions as F, types as T


def build_spark() -> SparkSession:
    return (
        SparkSession.builder.appName("usports-curate")
        .config("spark.hadoop.fs.s3a.aws.credentials.provider",
                "com.amazonaws.auth.EnvironmentVariableCredentialsProvider")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def raw_path(bucket: str, topic: str) -> str:
    return f"s3a://{bucket}/raw/{topic}/dt=*/*.jsonl"


def latest_per_key(df: DataFrame, keys: list[str]) -> DataFrame:
    """Keep the most recent record per natural key (by scraped_at)."""
    from pyspark.sql.window import Window
    w = Window.partitionBy(*keys).orderBy(F.col("scraped_at").desc())
    return (df.withColumn("_rn", F.row_number().over(w))
              .where("_rn = 1").drop("_rn"))


def parse_date(col: str):
    return F.to_date(F.regexp_replace(F.col(col), r"^[A-Za-z]{3}\s+", ""), "MMM d, yyyy")


def write_jdbc(df: DataFrame, table: str, jdbc_url: str, props: dict, mode: str = "append") -> None:
    df.write.mode(mode).format("jdbc") \
        .option("url", jdbc_url) \
        .option("dbtable", table) \
        .options(**props) \
        .save()


def upsert_via_staging(spark, df, target: str, key_cols: list[str], jdbc_url: str, props: dict):
    """Spark JDBC has no native upsert. Strategy: write to a staging table,
    then run an INSERT...ON CONFLICT from a JDBC executeUpdate."""
    staging = f"{target}_stage"
    write_jdbc(df, staging, jdbc_url, props, mode="overwrite")

    cols = df.columns
    update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in key_cols)
    key_list = ", ".join(key_cols)
    col_list = ", ".join(cols)
    sql = (f"INSERT INTO {target} ({col_list}) "
           f"SELECT {col_list} FROM {staging} "
           f"ON CONFLICT ({key_list}) DO UPDATE SET {update_set};")

    import psycopg2
    pg = psycopg2.connect(
        host=os.environ["PG_HOST"], port=os.environ.get("PG_PORT", "5432"),
        dbname=os.environ["PG_DB"], user=os.environ["PG_USER"], password=os.environ["PG_PASSWORD"],
    )
    with pg, pg.cursor() as cur:
        cur.execute("SET search_path TO usports, public;")
        cur.execute(sql)
        cur.execute(f"DROP TABLE IF EXISTS {staging};")
    pg.close()


def main() -> int:
    raw_bucket = os.environ["RAW_BUCKET"]
    curated_bucket = os.environ.get("CURATED_BUCKET", raw_bucket)
    jdbc_url = (f"jdbc:postgresql://{os.environ['PG_HOST']}:{os.environ.get('PG_PORT','5432')}/"
                f"{os.environ['PG_DB']}?currentSchema=usports")
    jdbc_props = {
        "user": os.environ["PG_USER"],
        "password": os.environ["PG_PASSWORD"],
        "driver": "org.postgresql.Driver",
    }

    spark = build_spark()

    # ----- team_season -----
    ts_raw = spark.read.json(raw_path(raw_bucket, "usports.team_season.raw"))
    ts = latest_per_key(ts_raw, ["team_key", "gender", "season"])

    fact_team_season = (ts.select(
        F.col("team_key"), F.col("gender"), F.col("season"),
        F.col("league"), F.col("division"), F.col("head_coach"),
        F.col("record.conference.wins").alias("conf_wins"),
        F.col("record.conference.losses").alias("conf_losses"),
        F.col("record.conference.pct").alias("conf_pct"),
        F.col("record.conference.points_for").alias("conf_points_for"),
        F.col("record.conference.points_against").alias("conf_points_against"),
        F.col("record.overall.wins").alias("overall_wins"),
        F.col("record.overall.losses").alias("overall_losses"),
        F.col("record.overall.pct").alias("overall_pct"),
        F.col("record.overall.points_for").alias("overall_points_for"),
        F.col("record.overall.points_against").alias("overall_points_against"),
    ))
    fact_team_season.write.mode("overwrite").parquet(
        f"s3a://{curated_bucket}/curated/fact_team_season")
    upsert_via_staging(spark, fact_team_season, "fact_team_season",
                       ["team_key", "gender", "season"], jdbc_url, jdbc_props)

    # ----- roster -----
    fact_roster = (ts.select(
        F.col("team_key"), F.col("gender"), F.col("season"),
        F.explode_outer("roster").alias("p"),
    ).select(
        F.col("p.person_key").alias("person_key"),
        F.col("gender"),
        F.col("team_key"),
        F.col("season"),
        F.col("p.jersey_number").alias("jersey_number"),
        F.col("p.position").alias("position"),
        F.col("p.height_inches").alias("height_inches"),
        F.col("p.eligibility").alias("eligibility"),
        F.col("p.hometown").alias("hometown"),
        F.col("p.high_school").alias("high_school"),
        F.lit(None).cast("string").alias("prior_team"),
    ).filter("person_key IS NOT NULL"))
    fact_roster.write.mode("overwrite").parquet(f"s3a://{curated_bucket}/curated/fact_roster")
    upsert_via_staging(spark, fact_roster, "fact_roster",
                       ["person_key", "gender", "team_key", "season"], jdbc_url, jdbc_props)

    # ----- player profiles + season stats -----
    pp_raw = spark.read.json(raw_path(raw_bucket, "usports.player_profile.raw"))
    pp = latest_per_key(pp_raw, ["person_key", "gender"])

    dim_player = pp.select(
        F.col("person_key"), F.col("gender"), F.col("full_name"),
        F.col("bio.hometown").alias("hometown"),
        F.col("bio.position").alias("position"),
        F.col("bio.height_inches").alias("height_inches"),
        F.col("bio.high_school").alias("high_school"),
    )
    dim_player.write.mode("overwrite").parquet(f"s3a://{curated_bucket}/curated/dim_player")
    upsert_via_staging(spark, dim_player, "dim_player",
                       ["person_key", "gender"], jdbc_url, jdbc_props)

    # season stats (latest per person + season + stat_type)
    stats = (pp.select(F.col("person_key"), F.col("gender"),
                       F.explode_outer("season_stats").alias("s"))
              .select(F.col("person_key"), F.col("gender"),
                      F.col("s.season").alias("season"),
                      F.col("s.stat_type").alias("stat_type"),
                      F.col("s.games_played").alias("games_played"),
                      F.col("s.games_started").alias("games_started"),
                      F.col("s.minutes").alias("minutes"),
                      F.col("s.minutes_per_game").alias("minutes_per_game"),
                      F.col("s.fg_made").alias("fg_made"),
                      F.col("s.fg_attempted").alias("fg_attempted"),
                      F.col("s.fg_pct").alias("fg_pct"),
                      F.col("s.three_made").alias("three_made"),
                      F.col("s.three_attempted").alias("three_attempted"),
                      F.col("s.three_pct").alias("three_pct"),
                      F.col("s.ft_made").alias("ft_made"),
                      F.col("s.ft_attempted").alias("ft_attempted"),
                      F.col("s.ft_pct").alias("ft_pct"),
                      F.col("s.offensive_reb").alias("offensive_reb"),
                      F.col("s.defensive_reb").alias("defensive_reb"),
                      F.col("s.total_rebounds").alias("total_rebounds"),
                      F.col("s.rebounds_pg").alias("rebounds_pg"),
                      F.col("s.personal_fouls").alias("personal_fouls"),
                      F.col("s.assists").alias("assists"),
                      F.lit(None).cast("double").alias("assists_pg"),
                      F.col("s.turnovers").alias("turnovers"),
                      F.col("s.blocks").alias("blocks"),
                      F.col("s.steals").alias("steals"),
                      F.col("s.points").alias("points"),
                      F.col("s.points_pg").alias("points_pg"))
              .filter("season IS NOT NULL AND stat_type IS NOT NULL"))

    # team_key for current season (from roster); may be NULL for historical
    roster_team = fact_roster.select("person_key", "gender", "season", "team_key")
    stats = stats.join(roster_team, on=["person_key", "gender", "season"], how="left")

    cols_in_order = [
        "person_key", "gender", "season", "team_key", "stat_type",
        "games_played", "games_started", "minutes", "minutes_per_game",
        "fg_made", "fg_attempted", "fg_pct",
        "three_made", "three_attempted", "three_pct",
        "ft_made", "ft_attempted", "ft_pct",
        "offensive_reb", "defensive_reb", "total_rebounds", "rebounds_pg",
        "personal_fouls", "assists", "assists_pg",
        "turnovers", "blocks", "steals", "points", "points_pg",
    ]
    stats = stats.select(*cols_in_order)
    int_cols = ["games_played", "games_started", "minutes",
                "fg_made", "fg_attempted", "three_made", "three_attempted",
                "ft_made", "ft_attempted", "offensive_reb", "defensive_reb",
                "total_rebounds", "personal_fouls", "assists", "turnovers",
                "blocks", "steals", "points"]
    dec_cols = ["minutes_per_game", "fg_pct", "three_pct", "ft_pct",
                "rebounds_pg", "assists_pg", "points_pg"]
    for c in int_cols:
        stats = stats.withColumn(c, F.col(c).cast("int"))
    for c in dec_cols:
        stats = stats.withColumn(c, F.col(c).cast("double"))
    stats.write.mode("overwrite").parquet(f"s3a://{curated_bucket}/curated/fact_player_season_stats")
    upsert_via_staging(spark, stats, "fact_player_season_stats",
                       ["person_key", "gender", "season", "stat_type"], jdbc_url, jdbc_props)

    # ----- games -----
    g_raw = spark.read.json(raw_path(raw_bucket, "usports.game.raw"))
    g = latest_per_key(g_raw.filter("game_id IS NOT NULL"), ["game_id"])
    games = g.select(
        F.col("game_id"), F.col("gender"), F.col("season"),
        parse_date("date_raw").alias("game_date"),
        F.col("location"),
        F.col("winner_display").alias("winner_team_key"),
        F.col("loser_display").alias("loser_team_key"),
        F.col("winner_score"), F.col("loser_score"),
        F.col("comment"),
    )
    games.write.mode("overwrite").parquet(f"s3a://{curated_bucket}/curated/fact_game")
    upsert_via_staging(spark, games, "fact_game", ["game_id"], jdbc_url, jdbc_props)

    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
