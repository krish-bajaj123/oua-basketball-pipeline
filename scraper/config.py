"""Static configuration for the usportshoops.ca OUA basketball scraper."""
from __future__ import annotations

BASE_URL = "https://usportshoops.ca/history"

# OUA team_key values match the Team= URL parameter on usportshoops.ca.
# Same key list works for MBB and WBB.
OUA_TEAMS: list[tuple[str, str, str]] = [
    # (team_key, division, display_name)
    ("TMUnow",       "Central", "Toronto Metropolitan"),
    ("Brock",        "Central", "Brock"),
    ("Lakehead",     "Central", "Lakehead"),
    ("Toronto",      "Central", "Toronto"),
    ("York",         "Central", "York"),
    ("McMaster",     "Central", "McMaster"),
    ("Carleton",     "East",    "Carleton"),
    ("Ottawa",       "East",    "Ottawa"),
    ("Queens",       "East",    "Queen's"),
    ("Laurentian",   "East",    "Laurentian"),
    ("Ontario Tech", "East",    "Ontario Tech"),
    ("Nipissing",    "East",    "Nipissing"),
    ("Western",      "West",    "Western"),
    ("Guelph",       "West",    "Guelph"),
    ("Windsor",      "West",    "Windsor"),
    ("WLUteam",      "West",    "Laurier"),
    ("Waterloo",     "West",    "Waterloo"),
    ("Algoma",       "West",    "Algoma"),
]

GENDERS = ("MBB", "WBB")
SEASON = "2025-26"

# Kafka topics
TOPIC_TEAM_SEASON    = "usports.team_season.raw"
TOPIC_PLAYER_PROFILE = "usports.player_profile.raw"
TOPIC_GAME           = "usports.game.raw"

SCHEMA_VERSION = 1
