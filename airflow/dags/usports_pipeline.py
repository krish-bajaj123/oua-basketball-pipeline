"""Daily Airflow DAG: scrape -> wait -> spark curate -> postgres.

Each step is a DockerOperator that runs the existing service image.
The Postgres load happens inside the Spark job (via JDBC), so the DAG
reduces to: scrape, drain, curate, quality_check.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from docker.types import Mount

DEFAULT_ARGS = {
    "owner": "usports",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

NETWORK = "usports_default"

with DAG(
    dag_id="usports_pipeline",
    description="Scrape OUA basketball, land in S3, curate via Spark, load Postgres.",
    start_date=datetime(2025, 9, 1),
    schedule="0 6 * * *",
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["usports", "etl"],
) as dag:

    scrape = DockerOperator(
        task_id="scrape",
        image="usports-scraper:latest",
        auto_remove="success",
        network_mode=NETWORK,
        environment={"KAFKA_BOOTSTRAP": "kafka:9092",
                     "LOG_LEVEL": "INFO",
                     "SCRAPE_DELAY": "1.0"},
    )

    # Allow consumer to drain in-flight messages to S3
    from airflow.operators.bash import BashOperator
    drain = BashOperator(task_id="wait_for_drain", bash_command="sleep 90")

    spark_curate = DockerOperator(
        task_id="spark_curate",
        image="usports-spark:latest",
        auto_remove="success",
        network_mode=NETWORK,
        environment={
            "AWS_ACCESS_KEY_ID":     "{{ var.value.AWS_ACCESS_KEY_ID }}",
            "AWS_SECRET_ACCESS_KEY": "{{ var.value.AWS_SECRET_ACCESS_KEY }}",
            "AWS_REGION":            "{{ var.value.get('AWS_REGION', 'us-east-1') }}",
            "RAW_BUCKET":            "{{ var.value.RAW_BUCKET }}",
            "CURATED_BUCKET":        "{{ var.value.get('CURATED_BUCKET', '') }}",
            "PG_HOST": "postgres", "PG_PORT": "5432",
            "PG_DB":   "{{ var.value.PG_DB }}",
            "PG_USER": "{{ var.value.PG_USER }}",
            "PG_PASSWORD": "{{ var.value.PG_PASSWORD }}",
        },
    )

    quality_check = PostgresOperator(
        task_id="quality_check",
        postgres_conn_id="usports_pg",
        sql="""
            SET search_path TO usports, public;
            -- Fail if no team_season rows for current season
            DO $$
            DECLARE n INT;
            BEGIN
              SELECT COUNT(*) INTO n FROM fact_team_season WHERE season = '2025-26';
              IF n = 0 THEN
                RAISE EXCEPTION 'fact_team_season is empty for 2025-26';
              END IF;
            END $$;
        """,
    )

    scrape >> drain >> spark_curate >> quality_check
