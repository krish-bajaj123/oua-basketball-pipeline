"""Scraper + Kafka producer entrypoint.

Iterates OUA teams x {MBB, WBB} for the configured season, scrapes each
team-season page (record, roster, schedule, stats), each linked player
profile, and the league-wide seasongames page. Publishes JSON messages
to three Kafka topics.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

from config import (
    BASE_URL, GENDERS, OUA_TEAMS, SEASON,
    TOPIC_GAME, TOPIC_PLAYER_PROFILE, TOPIC_TEAM_SEASON,
)
from http_client import ThrottledClient
from parsers import parse_player_profile, parse_seasongames, parse_team_season

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scraper")


def make_producer() -> KafkaProducer:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
    for attempt in range(1, 31):
        try:
            return KafkaProducer(
                bootstrap_servers=bootstrap,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                linger_ms=200,
            )
        except NoBrokersAvailable:
            log.info("kafka not ready, retry %d", attempt)
            time.sleep(2)
    raise RuntimeError("kafka unreachable")


def envelope(payload: dict) -> dict:
    payload.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())
    return payload


def run() -> int:
    client = ThrottledClient(min_delay=float(os.environ.get("SCRAPE_DELAY", "1.0")))
    producer = make_producer()
    seen_persons: set[tuple[str, str]] = set()
    n_team = n_player = n_game = 0

    for gender in GENDERS:
        # League-wide schedule (all OUA + non-conf games involving OUA teams)
        sg_url = f"{BASE_URL}/seasongames.php"
        sg_params = {"Gender": gender, "Season": SEASON, "League": "OUA"}
        try:
            html = client.get(sg_url, params=sg_params)
            for game in parse_seasongames(html, gender=gender, season=SEASON,
                                          source_url=f"{sg_url}?Gender={gender}&Season={SEASON}&League=OUA"):
                key = game.get("game_id") or f"{game['date_raw']}:{game['winner_display']}:{game['loser_display']}"
                producer.send(TOPIC_GAME, key=key, value=envelope(game))
                n_game += 1
        except Exception as e:
            log.error("seasongames %s failed: %s", gender, e)

        for team_key, division, display_name in OUA_TEAMS:
            ts_url = f"{BASE_URL}/teamseason.php"
            ts_params = {"Gender": gender, "Season": SEASON, "Team": team_key}
            full_ts_url = f"{ts_url}?Gender={gender}&Season={SEASON}&Team={team_key}"
            try:
                html = client.get(ts_url, params=ts_params)
                if not html:
                    log.warning("no team page %s/%s", gender, team_key)
                    continue
                ts = parse_team_season(html, team_key=team_key, gender=gender,
                                       season=SEASON, source_url=full_ts_url)
                ts.setdefault("division", division)
                producer.send(TOPIC_TEAM_SEASON, key=f"{gender}:{team_key}:{SEASON}",
                              value=envelope(ts))
                n_team += 1
                log.info("team %s %s — %d players", gender, team_key, len(ts.get("roster", [])))

                for p in ts.get("roster", []):
                    pkey = p.get("person_key")
                    if not pkey or (pkey, gender) in seen_persons:
                        continue
                    seen_persons.add((pkey, gender))
                    pp_url = f"{BASE_URL}/person.php"
                    pp_params = {"Gender": gender, "Person": pkey}
                    full_pp_url = f"{pp_url}?Gender={gender}&Person={pkey}"
                    try:
                        php = client.get(pp_url, params=pp_params)
                        if not php:
                            continue
                        pp = parse_player_profile(php, person_key=pkey, gender=gender,
                                                  source_url=full_pp_url)
                        producer.send(TOPIC_PLAYER_PROFILE, key=f"{gender}:{pkey}",
                                      value=envelope(pp))
                        n_player += 1
                    except Exception as e:
                        log.error("player %s/%s failed: %s", gender, pkey, e)
            except Exception as e:
                log.error("team %s/%s failed: %s", gender, team_key, e)

    producer.flush(timeout=60)
    producer.close()
    log.info("DONE — team_season=%d player_profile=%d game=%d", n_team, n_player, n_game)
    return 0


if __name__ == "__main__":
    sys.exit(run())
