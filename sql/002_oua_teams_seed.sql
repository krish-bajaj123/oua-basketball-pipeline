-- Seed OUA team dimension. team_key matches usportshoops Team= URL parameter.
-- Same key list works for both MBB and WBB on usportshoops.ca.

SET search_path TO usports, public;

INSERT INTO dim_team (team_key, gender, league, division, display_name) VALUES
    ('TMUnow',       'MBB', 'OUA', 'Central', 'Toronto Metropolitan'),
    ('Brock',        'MBB', 'OUA', 'Central', 'Brock'),
    ('Lakehead',     'MBB', 'OUA', 'Central', 'Lakehead'),
    ('Toronto',      'MBB', 'OUA', 'Central', 'Toronto'),
    ('York',         'MBB', 'OUA', 'Central', 'York'),
    ('McMaster',     'MBB', 'OUA', 'Central', 'McMaster'),
    ('Carleton',     'MBB', 'OUA', 'East',    'Carleton'),
    ('Ottawa',       'MBB', 'OUA', 'East',    'Ottawa'),
    ('Queens',       'MBB', 'OUA', 'East',    'Queen''s'),
    ('Laurentian',   'MBB', 'OUA', 'East',    'Laurentian'),
    ('Ontario Tech', 'MBB', 'OUA', 'East',    'Ontario Tech'),
    ('Nipissing',    'MBB', 'OUA', 'East',    'Nipissing'),
    ('Western',      'MBB', 'OUA', 'West',    'Western'),
    ('Guelph',       'MBB', 'OUA', 'West',    'Guelph'),
    ('Windsor',      'MBB', 'OUA', 'West',    'Windsor'),
    ('WLUteam',      'MBB', 'OUA', 'West',    'Laurier'),
    ('Waterloo',     'MBB', 'OUA', 'West',    'Waterloo'),
    ('Algoma',       'MBB', 'OUA', 'West',    'Algoma'),
    ('TMUnow',       'WBB', 'OUA', 'Central', 'Toronto Metropolitan'),
    ('Brock',        'WBB', 'OUA', 'Central', 'Brock'),
    ('Lakehead',     'WBB', 'OUA', 'Central', 'Lakehead'),
    ('Toronto',      'WBB', 'OUA', 'Central', 'Toronto'),
    ('York',         'WBB', 'OUA', 'Central', 'York'),
    ('McMaster',     'WBB', 'OUA', 'Central', 'McMaster'),
    ('Carleton',     'WBB', 'OUA', 'East',    'Carleton'),
    ('Ottawa',       'WBB', 'OUA', 'East',    'Ottawa'),
    ('Queens',       'WBB', 'OUA', 'East',    'Queen''s'),
    ('Laurentian',   'WBB', 'OUA', 'East',    'Laurentian'),
    ('Ontario Tech', 'WBB', 'OUA', 'East',    'Ontario Tech'),
    ('Nipissing',    'WBB', 'OUA', 'East',    'Nipissing'),
    ('Western',      'WBB', 'OUA', 'West',    'Western'),
    ('Guelph',       'WBB', 'OUA', 'West',    'Guelph'),
    ('Windsor',      'WBB', 'OUA', 'West',    'Windsor'),
    ('WLUteam',      'WBB', 'OUA', 'West',    'Laurier'),
    ('Waterloo',     'WBB', 'OUA', 'West',    'Waterloo'),
    ('Algoma',       'WBB', 'OUA', 'West',    'Algoma')
ON CONFLICT (team_key, gender) DO UPDATE SET
    league       = EXCLUDED.league,
    division     = EXCLUDED.division,
    display_name = EXCLUDED.display_name;
