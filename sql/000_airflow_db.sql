-- Companion DB for Airflow metadata so it can share the Postgres instance.
SELECT 'CREATE DATABASE airflow' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
