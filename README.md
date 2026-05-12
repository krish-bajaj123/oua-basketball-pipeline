# OUA Basketball Data Pipeline + Dashboard

End-to-end data engineering pipeline for an OUA (Ontario University Athletics)
men's & women's basketball player dashboard. Source: `usportshoops.ca`.

```
scraper ──► Kafka ──► consumer ──► S3 (raw NDJSON)
                                       │
                                       ▼
                                     Spark (curate + JDBC upsert)
                                       │
                                       ▼
                                   PostgreSQL ──► FastAPI ──► Dashboard
                                       ▲
                                       │
                                    Airflow (daily DAG orchestrating the above)
```

## Components

| Path          | Purpose                                                                 |
|---------------|-------------------------------------------------------------------------|
| `scraper/`    | Polite HTML scraper, publishes JSON to 3 Kafka topics                   |
| `consumer/`   | Kafka → S3 raw landing (NDJSON, partitioned by topic + date)            |
| `spark/`      | Batch job: read raw S3 NDJSON → curated Parquet → upsert to Postgres    |
| `sql/`        | DDL (auto-applied to Postgres on first start via `initdb.d`)            |
| `api/`        | FastAPI read API over curated tables                                    |
| `dashboard/`  | Static HTML/JS dashboard, served by nginx, proxies `/api/` to FastAPI   |
| `airflow/`    | Daily DAG: scrape → drain → spark curate → quality check                |

## Kafka topics

- `usports.team_season.raw` — one message per (gender, team, season)
- `usports.player_profile.raw` — one message per (gender, person)
- `usports.game.raw` — one message per game (from league-wide schedule page)

All messages are JSON, include `schema`, `schema_version`, `source_url`, `scraped_at`.

## Running it

1. Provide AWS credentials and Postgres password:

   ```bash
   cp .env.example .env
   # edit .env — fill AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, RAW_BUCKET, CURATED_BUCKET
   ```

   Buckets must already exist in your AWS account. The IAM key needs
   `s3:PutObject` / `s3:GetObject` / `s3:ListBucket` on them.

2. Bring up the long-running services (postgres, kafka, consumer, api, dashboard):

   ```bash
   docker compose up -d --build postgres zookeeper kafka consumer api dashboard
   ```

3. Run the scraper once (publishes ~600 player profiles + 36 team-seasons + ~1500 games):

   ```bash
   docker compose run --rm scraper
   ```

4. Once the consumer drains to S3 (watch `docker compose logs -f consumer`),
   run the Spark curate job to populate Postgres:

   ```bash
   docker compose run --rm spark
   ```

5. Open the dashboard at <http://localhost:8080>.

## Optional: Airflow orchestration

```bash
docker compose --profile airflow up -d airflow
```

Then in the UI at <http://localhost:8081> (admin / admin), set the following
Airflow Variables before unpausing `usports_pipeline`:

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
- `RAW_BUCKET`, `CURATED_BUCKET`
- `PG_DB`, `PG_USER`, `PG_PASSWORD`

And add a Postgres connection `usports_pg` pointing to `postgres:5432`.

## Database schema

See `sql/001_schema.sql`. Star-ish schema:

- `dim_season`, `dim_team`, `dim_player` — dimensions
- `fact_team_season` — team record per season
- `fact_roster` — player ↔ team ↔ season bridge
- `fact_player_season_stats` — one row per (player, season, stat_type ∈ regular/playoff/national/overall)
- `fact_game` — one row per game
- Convenience views `v_oua_standings`, `v_player_leaders`

Natural keys come from usportshoops.ca URL parameters (`Team=`, `Person=`),
so re-runs upsert deterministically.

## Re-running

The whole pipeline is idempotent. Re-running the scraper republishes messages
with fresh `scraped_at`; Spark dedupes to the latest per natural key before
writing to Postgres. Old raw NDJSON in S3 is kept indefinitely (cheap audit log).
