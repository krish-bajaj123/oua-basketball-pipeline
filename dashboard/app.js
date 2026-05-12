const API = window.API_BASE || "/api";

const $ = (s) => document.querySelector(s);
const view = $("#view");
const genderSel = $("#gender");
const seasonSel = $("#season");

const fmt = (v, d=1) => (v == null || v === "") ? "—" : (typeof v === "number" ? v.toFixed(d) : v);
const intFmt = (v) => (v == null || v === "") ? "—" : v;

async function api(path) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

const params = () => ({ gender: genderSel.value, season: seasonSel.value });

const routes = {
  "": () => render("#standings"),
  "#standings": renderStandings,
  "#leaders":   renderLeaders,
  "#teams":     renderTeams,
  "#games":     renderGames,
};

function render(hash) {
  // Match exact route or team/* / player/*
  const route = hash || "#standings";
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === route));
  if (route.startsWith("#team/")) return renderTeam(route.slice("#team/".length));
  if (route.startsWith("#player/")) return renderPlayer(route.slice("#player/".length));
  (routes[route] || routes[""])();
}

window.addEventListener("hashchange", () => render(location.hash));
[genderSel, seasonSel].forEach(el => el.addEventListener("change", () => render(location.hash)));

(async function init() {
  try {
    const seasons = await api("/seasons");
    if (seasons.length) {
      seasonSel.innerHTML = seasons.map(s => `<option value="${s.season}">${s.season}</option>`).join("");
    }
  } catch {}
  render(location.hash);
})();

// ----- views -----

async function renderStandings() {
  const { gender, season } = params();
  view.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const rows = await api(`/standings?gender=${gender}&season=${season}`);
    if (!rows.length) return view.innerHTML = `<div class="empty">No standings yet for ${gender} ${season}.</div>`;
    const groups = {};
    for (const r of rows) (groups[r.division || "—"] ||= []).push(r);
    view.innerHTML = Object.entries(groups).map(([div, list]) => `
      <h2 class="h2">OUA ${div}</h2>
      <table>
        <thead><tr><th>Team</th><th class="num">Conf W-L</th><th class="num">Pct</th><th class="num">Overall</th><th class="num">PF</th><th class="num">PA</th></tr></thead>
        <tbody>
          ${list.map(t => `
            <tr>
              <td><a class="team" href="#team/${gender}/${encodeURIComponent(t.team_key)}">${t.display_name}</a></td>
              <td class="num">${intFmt(t.conf_wins)}-${intFmt(t.conf_losses)}</td>
              <td class="num">${fmt(t.conf_pct, 3)}</td>
              <td class="num">${intFmt(t.overall_wins)}-${intFmt(t.overall_losses)}</td>
              <td class="num">${intFmt(t.conf_points_for)}</td>
              <td class="num">${intFmt(t.conf_points_against)}</td>
            </tr>`).join("")}
        </tbody>
      </table>`).join("");
  } catch (e) { view.innerHTML = `<div class="empty">error: ${e.message}</div>`; }
}

async function renderLeaders() {
  const { gender, season } = params();
  const stats = ["points_pg", "rebounds_pg", "assists", "fg_pct", "three_pct", "steals", "blocks"];
  view.innerHTML = `
    <div style="margin-bottom:.6rem">
      Sort by:
      <select id="statSel">${stats.map(s => `<option value="${s}">${s}</option>`).join("")}</select>
    </div>
    <div id="leaderTable" class="empty">loading…</div>`;
  const sel = $("#statSel");
  const load = async () => {
    try {
      const rows = await api(`/leaders?gender=${gender}&season=${season}&stat=${sel.value}&limit=25`);
      $("#leaderTable").innerHTML = rows.length ? `
        <table><thead>
          <tr><th>#</th><th>Player</th><th>Team</th><th class="num">${sel.value}</th><th class="num">GP</th><th class="num">PPG</th><th class="num">RPG</th></tr>
        </thead><tbody>
          ${rows.map((r,i) => `
            <tr>
              <td>${i+1}</td>
              <td><a class="player" href="#player/${gender}/${encodeURIComponent(r.person_key)}">${r.full_name || r.person_key}</a></td>
              <td><a class="team" href="#team/${gender}/${encodeURIComponent(r.team_key)}">${r.team_key}</a></td>
              <td class="num">${fmt(r.value, 2)}</td>
              <td class="num">${intFmt(r.games_played)}</td>
              <td class="num">${fmt(r.points_pg, 1)}</td>
              <td class="num">${fmt(r.rebounds_pg, 1)}</td>
            </tr>`).join("")}
        </tbody></table>` : `<div class="empty">No leaders for ${gender} ${season}.</div>`;
    } catch (e) { $("#leaderTable").innerHTML = `<div class="empty">error: ${e.message}</div>`; }
  };
  sel.addEventListener("change", load);
  load();
}

async function renderTeams() {
  const { gender } = params();
  view.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const teams = await api(`/teams?gender=${gender}`);
    if (!teams.length) return view.innerHTML = `<div class="empty">No teams.</div>`;
    view.innerHTML = `<div class="cards">${teams.map(t => `
      <a class="card" href="#team/${gender}/${encodeURIComponent(t.team_key)}" style="text-decoration:none;color:inherit">
        <h3>${t.display_name}</h3>
        <div class="meta">${t.league} ${t.division || ""}</div>
      </a>`).join("")}</div>`;
  } catch (e) { view.innerHTML = `<div class="empty">error: ${e.message}</div>`; }
}

async function renderTeam(path) {
  const [gender, key] = path.split("/").map(decodeURIComponent);
  const season = seasonSel.value;
  view.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const [team, roster] = await Promise.all([
      api(`/teams/${gender}/${encodeURIComponent(key)}?season=${season}`),
      api(`/teams/${gender}/${encodeURIComponent(key)}/roster?season=${season}`),
    ]);
    view.innerHTML = `
      <h2 class="h2">${team.display_name} <span class="tag">${team.league} ${team.division || ""}</span></h2>
      <div class="meta" style="color:var(--muted);margin-bottom:.5rem">
        Coach: ${team.head_coach || "—"} · Conf ${intFmt(team.conf_wins)}-${intFmt(team.conf_losses)}
        · Overall ${intFmt(team.overall_wins)}-${intFmt(team.overall_losses)}
      </div>
      <h3 class="h2">Roster (${season})</h3>
      ${roster.length ? `<table><thead>
        <tr><th>#</th><th>Player</th><th>Pos</th><th>Ht</th><th>Elig</th><th>Hometown</th></tr></thead>
        <tbody>${roster.map(p => `
          <tr><td>${intFmt(p.jersey_number)}</td>
              <td><a class="player" href="#player/${gender}/${encodeURIComponent(p.person_key)}">${p.full_name || p.person_key}</a></td>
              <td>${p.position || "—"}</td>
              <td>${p.height_inches ? `${Math.floor(p.height_inches/12)}-${p.height_inches%12}` : "—"}</td>
              <td>${p.eligibility || "—"}</td>
              <td>${p.hometown || "—"}</td></tr>`).join("")}
        </tbody></table>` : `<div class="empty">No roster yet.</div>`}`;
  } catch (e) { view.innerHTML = `<div class="empty">error: ${e.message}</div>`; }
}

async function renderPlayer(path) {
  const [gender, key] = path.split("/").map(decodeURIComponent);
  view.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const p = await api(`/players/${gender}/${encodeURIComponent(key)}`);
    const ht = p.height_inches ? `${Math.floor(p.height_inches/12)}-${p.height_inches%12}` : "—";
    const reg = p.stats.filter(s => s.stat_type === "regular");
    view.innerHTML = `
      <h2 class="h2">${p.full_name || p.person_key} <span class="tag">${gender}</span></h2>
      <div class="meta" style="color:var(--muted);margin-bottom:.7rem">
        ${p.position || "—"} · ${ht} · ${p.hometown || "—"} · HS: ${p.high_school || "—"}
      </div>
      <h3 class="h2">Regular Season</h3>
      ${reg.length ? `<table><thead>
        <tr><th>Season</th><th>Team</th><th class="num">GP</th><th class="num">MPG</th>
            <th class="num">PPG</th><th class="num">RPG</th><th class="num">AST</th>
            <th class="num">FG%</th><th class="num">3P%</th><th class="num">FT%</th></tr></thead>
        <tbody>${reg.map(s => `
          <tr><td>${s.season}</td><td>${s.team_key || "—"}</td>
              <td class="num">${intFmt(s.games_played)}</td>
              <td class="num">${fmt(s.minutes_per_game,1)}</td>
              <td class="num">${fmt(s.points_pg,1)}</td>
              <td class="num">${fmt(s.rebounds_pg,1)}</td>
              <td class="num">${intFmt(s.assists)}</td>
              <td class="num">${fmt(s.fg_pct,1)}</td>
              <td class="num">${fmt(s.three_pct,1)}</td>
              <td class="num">${fmt(s.ft_pct,1)}</td></tr>`).join("")}
        </tbody></table>` : `<div class="empty">No stats found.</div>`}`;
  } catch (e) { view.innerHTML = `<div class="empty">error: ${e.message}</div>`; }
}

async function renderGames() {
  const { gender, season } = params();
  view.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const rows = await api(`/games?gender=${gender}&season=${season}&limit=200`);
    view.innerHTML = rows.length ? `<table><thead>
      <tr><th>Date</th><th>Winner</th><th class="num">Score</th><th>Loser</th><th>Location</th></tr></thead>
      <tbody>${rows.map(g => `
        <tr><td>${g.game_date || "—"}</td>
            <td>${g.winner_team_key || "—"}</td>
            <td class="num">${intFmt(g.winner_score)}-${intFmt(g.loser_score)}</td>
            <td>${g.loser_team_key || "—"}</td>
            <td>${g.location || ""}</td></tr>`).join("")}
      </tbody></table>` : `<div class="empty">No games yet for ${gender} ${season}.</div>`;
  } catch (e) { view.innerHTML = `<div class="empty">error: ${e.message}</div>`; }
}
