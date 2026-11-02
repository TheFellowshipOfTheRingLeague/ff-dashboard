// Seasons that still have data on record but shouldn't clutter the season
// pickers (too few games tracked / not worth surfacing as a browsable year).
const EXCLUDED_HISTORY_YEARS = [2021, 2022];

const SERIES_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];

function colorFor(index) {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

function fmtNum(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtPct(n) {
  if (n === null || n === undefined) return "-";
  return (n * 100).toFixed(1) + "%";
}

function fmtDate(iso) {
  if (!iso) return "Unknown date";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown date";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function barChart(rows, { valueKey, maxValue, labelKey = "label", digits = 1 }) {
  const max = maxValue || Math.max(1, ...rows.map((r) => r[valueKey] || 0));
  const container = el("div", { class: "bar-chart" });
  rows.forEach((row, i) => {
    const pct = Math.max(2, Math.round(((row[valueKey] || 0) / max) * 100));
    const track = el("div", { class: "bar-track" }, [
      el("div", { class: "bar-fill", style: `width:${pct}%; background:${colorFor(i)};` }),
    ]);
    container.appendChild(
      el("div", { class: "bar-row" }, [
        el("div", { class: "name", title: row[labelKey] }, row[labelKey]),
        track,
        el("div", { class: "val" }, fmtNum(row[valueKey], digits)),
      ])
    );
  });
  return container;
}

function sortableTable(columns, rows, initialSortIdx = 0, initialDir = -1) {
  let sortIdx = initialSortIdx;
  let dir = initialDir;

  const wrap = el("div", { class: "table-scroll" });
  const table = el("table");
  wrap.appendChild(table);

  function render() {
    const sorted = [...rows].sort((a, b) => {
      const col = columns[sortIdx];
      const av = col.value(a);
      const bv = col.value(b);
      if (typeof av === "string" || typeof bv === "string") {
        return String(av).localeCompare(String(bv)) * dir;
      }
      return ((av ?? -Infinity) - (bv ?? -Infinity)) * dir;
    });

    table.innerHTML = "";
    const thead = el("thead");
    const headRow = el("tr");
    columns.forEach((col, idx) => {
      const th = el("th", { class: idx === sortIdx ? "sorted" : "" }, col.label);
      th.addEventListener("click", () => {
        if (sortIdx === idx) dir *= -1;
        else {
          sortIdx = idx;
          dir = col.defaultDir || -1;
        }
        render();
      });
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = el("tbody");
    sorted.forEach((row) => {
      const tr = el("tr");
      columns.forEach((col) => {
        tr.appendChild(el("td", {}, col.render ? col.render(row) : String(col.value(row) ?? "-")));
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }

  render();
  return wrap;
}

function setTab(name) {
  document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
}

function renderOverview(data) {
  const root = document.getElementById("panel-overview");
  root.innerHTML = "";

  const allTime = data.all_time || [];
  const totalChamps = allTime.reduce((s, r) => s + r.championships, 0);
  const seasonsCount = data.seasons.length;

  root.appendChild(
    el("div", { class: "stat-row" }, [
      statTile(seasonsCount, "Seasons tracked"),
      statTile(totalChamps, "Championships awarded"),
      statTile(allTime.length, "Managers"),
      statTile(data.current_season_year, "Current season"),
    ])
  );

  const leaderCard = el("div", { class: "card" }, [
    el("h2", {}, "All-time standings"),
    el("p", { class: "sub" }, "Every manager's full league history, by owner identity (so a renamed team still counts toward the same manager). Click a column to sort."),
  ]);

  const columns = [
    { label: "Manager", value: (r) => r.owner, render: (r) => managerCell(r) },
    { label: "Titles", value: (r) => r.championships, defaultDir: -1, render: (r) => (r.championships ? `${"🏆".repeat(Math.min(r.championships, 3))} ${r.championships}` : "0") },
    { label: "2nd place", value: (r) => r.runner_up_finishes, defaultDir: -1 },
    { label: "Record", value: (r) => r.wins, defaultDir: -1, render: (r) => `${r.wins}-${r.losses}${r.ties ? "-" + r.ties : ""}` },
    { label: "Win %", value: (r) => r.win_pct, defaultDir: -1, render: (r) => fmtPct(r.win_pct) },
    { label: "Points for", value: (r) => r.points_for, defaultDir: -1, render: (r) => fmtNum(r.points_for) },
    { label: "Points against", value: (r) => r.points_against, defaultDir: -1, render: (r) => fmtNum(r.points_against) },
    { label: "Seasons", value: (r) => r.seasons_played, defaultDir: -1 },
  ];
  leaderCard.appendChild(sortableTable(columns, allTime, 1, -1));
  root.appendChild(leaderCard);

  const champCard = el("div", { class: "card" }, [
    el("h2", {}, "Championships by manager"),
    el("p", { class: "sub" }, "Total league titles won."),
  ]);
  const champRows = [...allTime].sort((a, b) => b.championships - a.championships).filter((r) => r.championships > 0);
  if (champRows.length) {
    champCard.appendChild(barChart(champRows, { valueKey: "championships", labelKey: "owner", digits: 0 }));
  } else {
    champCard.appendChild(el("div", { class: "empty-state" }, "No completed seasons with a recorded champion yet."));
  }
  root.appendChild(champCard);

  const pfCard = el("div", { class: "card" }, [
    el("h2", {}, "All-time points for"),
    el("p", { class: "sub" }, "Total regular-season points scored across all tracked seasons."),
  ]);
  const pfRows = [...allTime].sort((a, b) => b.points_for - a.points_for);
  pfCard.appendChild(barChart(pfRows, { valueKey: "points_for", labelKey: "owner" }));
  root.appendChild(pfCard);
}

function statTile(value, label) {
  return el("div", { class: "stat-tile" }, [el("div", { class: "value" }, String(value ?? "-")), el("div", { class: "label" }, label)]);
}

function managerCell(r) {
  return el("span", {}, r.owner);
}

function renderSeasons(data) {
  const root = document.getElementById("panel-seasons");
  root.innerHTML = "";

  const seasons = [...data.seasons]
    .filter((s) => !EXCLUDED_HISTORY_YEARS.includes(Number(s.year)))
    .sort((a, b) => b.year - a.year);
  const controls = el("div", { class: "controls" });
  const select = el("select", { id: "season-select" });
  seasons.forEach((s) => select.appendChild(el("option", { value: s.year }, String(s.year))));
  controls.appendChild(el("label", {}, "Season"));
  controls.appendChild(select);
  root.appendChild(controls);

  const body = el("div", { id: "season-body" });
  root.appendChild(body);

  function renderSeason(year) {
    const season = data.seasons.find((s) => String(s.year) === String(year));
    body.innerHTML = "";
    if (!season) {
      body.appendChild(el("div", { class: "empty-state" }, "No data for this season."));
      return;
    }

    const summary = el("div", { class: "season-summary" });
    summary.appendChild(
      el("div", { class: "champ-card" }, [
        el("div", { class: "title" }, "🏆 Champion"),
        el("div", { class: "name" }, season.champion ? season.champion.owner : "Season in progress"),
      ])
    );
    if (season.runner_up) {
      summary.appendChild(
        el("div", { class: "champ-card" }, [
          el("div", { class: "title" }, "Runner-up"),
          el("div", { class: "name" }, season.runner_up.owner),
        ])
      );
    }
    body.appendChild(summary);

    if (season.errors && season.errors.length) {
      body.appendChild(el("div", { class: "banner" }, `Some data for ${season.year} could not be fetched (${season.errors.length} issue${season.errors.length > 1 ? "s" : ""}). The rest of the season's data below is still accurate.`));
    }

    const standingsCard = el("div", { class: "card" }, [el("h2", {}, `${season.year} standings`)]);
    const standingsCols = [
      { label: "Rank", value: (t) => t.final_rank ?? 99, render: (t) => (t.final_rank ? String(t.final_rank) : "-") },
      { label: "Manager", value: (t) => t.owner },
      { label: "Record", value: (t) => t.wins, render: (t) => `${t.wins}-${t.losses}${t.ties ? "-" + t.ties : ""}` },
      { label: "Points for", value: (t) => t.points_for, render: (t) => fmtNum(t.points_for) },
      { label: "Points against", value: (t) => t.points_against, render: (t) => fmtNum(t.points_against) },
    ];
    standingsCard.appendChild(sortableTable(standingsCols, season.teams, 0, 1));
    body.appendChild(standingsCard);

    const draftCard = el("div", { class: "card" }, [
      el("h2", {}, `${season.year} draft board`),
      el("p", { class: "sub" }, season.draft.length ? `${season.draft.length} picks` : "No draft data available for this season."),
    ]);
    if (season.draft.length) {
      const byRound = {};
      season.draft.forEach((p) => {
        const r = p.round ?? "?";
        (byRound[r] = byRound[r] || []).push(p);
      });
      Object.keys(byRound)
        .sort((a, b) => Number(a) - Number(b))
        .forEach((r) => {
          draftCard.appendChild(el("div", { class: "round-heading" }, `Round ${r}`));
          const board = el("div", { class: "draft-board" });
          byRound[r]
            .sort((a, b) => (a.round_pick ?? 0) - (b.round_pick ?? 0))
            .forEach((p) => {
              board.appendChild(
                el("div", { class: "pick-card" }, [
                  el("div", { class: "pick-no" }, `Pick ${p.overall_pick ?? "?"}${p.keeper ? " · keeper" : ""}`),
                  el("div", { class: "player" }, p.player_name || "Unknown player"),
                  el("div", { class: "team" }, p.owner),
                ])
              );
            });
          draftCard.appendChild(board);
        });
    }
    body.appendChild(draftCard);

    const tradeCard = el("div", { class: "card" }, [
      el("h2", {}, `${season.year} trades`),
      el("p", { class: "sub" }, season.trades.length ? `${season.trades.length} trade${season.trades.length > 1 ? "s" : ""}` : "No trades recorded for this season."),
    ]);
    season.trades
      .slice()
      .sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0))
      .forEach((t) => tradeCard.appendChild(renderTradeCard(t, false)));
    body.appendChild(tradeCard);
  }

  select.addEventListener("change", (e) => renderSeason(e.target.value));
  if (seasons.length) renderSeason(seasons[0].year);
  else body.appendChild(el("div", { class: "empty-state" }, "No seasons available yet."));
}

function perfLabel(item) {
  // Post-trade performance for one player, same idea as the standalone
  // trade tracker: points-per-game and total points scored since the deal,
  // or an honest "nothing to show yet" when there's no post-trade data.
  if (item.ppg_since_trade == null) {
    return item.games_since_trade === 0 ? "no games since trade" : "no stat history";
  }
  return `${fmtNum(item.ppg_since_trade)} ppg · ${fmtNum(item.points_since_trade)} pts (${item.games_since_trade} gm)`;
}

function ownerFor(t, teamName) {
  // Managers only, never team names - a trade's "team_owners" map translates
  // the internal team_name grouping key to the owner it belongs to.
  return (t.team_owners && t.team_owners[teamName]) || teamName;
}

function fmtRecord(rec) {
  if (!rec) return null;
  return `${rec.wins}-${rec.losses}${rec.ties ? "-" + rec.ties : ""}`;
}

function renderTradeCard(t, showYear) {
  // Group this trade's players by the team that RECEIVED them, so each
  // "side" of the trade lists what that team walked away with - mirroring
  // the standalone trade tracker's two-sides-plus-verdict layout, but
  // computed live from this season's actual data instead of a static
  // snapshot.
  const sides = {};
  const order = [];
  (t.items || []).forEach((item) => {
    const side = item.to_team || item.from_team || "Unknown team";
    if (!sides[side]) {
      sides[side] = [];
      order.push(side);
    }
    sides[side].push(item);
  });

  const sideEls = [];
  order.forEach((team, i) => {
    if (i > 0) sideEls.push(el("div", { class: "trade-vs" }, "↔"));
    const rec = t.records_since_trade ? t.records_since_trade[team] : null;
    const recordStr = fmtRecord(rec);
    sideEls.push(
      el("div", { class: "trade-side" }, [
        el("p", { class: "team-name" }, ownerFor(t, team)),
        recordStr ? el("p", { class: "team-record" }, `${recordStr} since the trade`) : null,
        el(
          "ul",
          {},
          sides[team].map((item) =>
            el("li", { class: "player-row" }, [
              el("span", { class: "name" }, item.player || "Unknown player"),
              el("span", { class: "stats" }, perfLabel(item)),
            ])
          )
        ),
      ])
    );
  });

  const children = [
    el("div", { class: "trade-date" }, showYear ? `${t.year} · ${fmtDate(t.date)}` : fmtDate(t.date)),
    el("div", { class: "trade-sides" }, sideEls),
  ];

  if (t.verdict) {
    const totalsStr = Object.entries(t.verdict.side_totals || {})
      .map(([team, pts]) => `${ownerFor(t, team)}: ${fmtNum(pts)} pts`)
      .join(" · ");
    children.push(
      el("div", { class: "trade-verdict" }, [
        el(
          "span",
          {},
          t.verdict.leader_team
            ? [el("b", {}, ownerFor(t, t.verdict.leader_team)), ` leads by ${fmtNum(t.verdict.margin)} pts since the trade`]
            : "Even so far since the trade"
        ),
        el("span", {}, totalsStr),
      ])
    );
  }

  return el("div", { class: "trade-card" }, children);
}

const WAIVER_TRADE_YEAR = 2026;

function renderTrades(data) {
  const root = document.getElementById("panel-trades");
  root.innerHTML = "";

  const all = [];
  data.seasons.forEach((s) => {
    if (Number(s.year) !== WAIVER_TRADE_YEAR) return;
    s.trades.forEach((t) => all.push({ ...t, year: s.year }));
  });
  all.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

  const card = el("div", { class: "card" }, [
    el("h2", {}, `${WAIVER_TRADE_YEAR} trades`),
    el("p", { class: "sub" }, `${all.length} trade${all.length === 1 ? "" : "s"} in ${WAIVER_TRADE_YEAR}.`),
  ]);

  if (!all.length) {
    card.appendChild(el("div", { class: "empty-state" }, "No trades recorded yet."));
  } else {
    all.forEach((t) => card.appendChild(renderTradeCard(t, true)));
  }
  root.appendChild(card);
}

function renderWaivers(data) {
  const root = document.getElementById("panel-waivers");
  root.innerHTML = "";

  const body = el("div", { id: "waiver-body" });
  root.appendChild(body);

  function allAdds() {
    const out = [];
    data.seasons.forEach((s) => {
      if (Number(s.year) !== WAIVER_TRADE_YEAR) return;
      (s.waiver_adds || []).forEach((a) => out.push({ ...a, year: s.year }));
    });
    return out;
  }

  function render() {
    body.innerHTML = "";
    const adds = allAdds();
    adds.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

    const card = el("div", { class: "card" }, [
      el("h2", {}, `${WAIVER_TRADE_YEAR} waiver wire & free agent moves`),
      el("p", { class: "sub" }, `${adds.length} move${adds.length === 1 ? "" : "s"} in ${WAIVER_TRADE_YEAR}.`),
    ]);

    if (!adds.length) {
      card.appendChild(el("div", { class: "empty-state" }, "No waiver wire or free agent moves recorded yet."));
    } else {
      const columns = [
        { label: "Date", value: (a) => new Date(a.date || 0).getTime(), defaultDir: -1, render: (a) => fmtDate(a.date) },
        { label: "Season", value: (a) => a.year, defaultDir: -1 },
        { label: "Added", value: (a) => a.player_added || "", render: (a) => a.player_added || "—" },
        { label: "Dropped", value: (a) => a.player_dropped || "", render: (a) => a.player_dropped || "—" },
        { label: "Manager", value: (a) => a.owner || a.team },
        { label: "Type", value: (a) => a.type },
      ];
      card.appendChild(sortableTable(columns, adds, 0, -1));
    }
    body.appendChild(card);
  }

  render();
}

const SLOT_ORDER = ["QB", "RB", "RB/WR", "WR", "WR/TE", "TE", "OP", "RB/WR/TE", "D/ST", "K", "BE", "IR"];

function slotRank(slot) {
  const idx = SLOT_ORDER.indexOf(slot);
  // Unknown/rare slots (DT, DE, LB, etc. in IDP leagues) sort with the
  // starters, just before bench/IR, rather than falling off the end.
  return idx === -1 ? SLOT_ORDER.length - 2 : idx;
}

function lineupTable(players) {
  const wrap = el("div", { class: "table-scroll" });
  const table = el("table", { class: "lineup-table" });
  table.appendChild(
    el("thead", {}, el("tr", {}, [el("th", {}, "Slot"), el("th", {}, "Player"), el("th", {}, "Pos"), el("th", {}, "Pts")]))
  );
  const tbody = el("tbody");
  players.forEach((p) => {
    tbody.appendChild(
      el("tr", {}, [
        el("td", {}, p.slot || "-"),
        el("td", {}, p.name || "Unknown player"),
        el("td", {}, p.position || "-"),
        el("td", { class: "pts" }, fmtNum(p.points)),
      ])
    );
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function lineupSection(team) {
  if (!team) return el("div", { class: "lineup-col" }, el("div", { class: "empty-state" }, "Bye week"));

  const lineup = [...(team.lineup || [])];
  const starters = lineup.filter((p) => p.slot !== "BE" && p.slot !== "IR").sort((a, b) => slotRank(a.slot) - slotRank(b.slot));
  const bench = lineup.filter((p) => p.slot === "BE" || p.slot === "IR").sort((a, b) => slotRank(a.slot) - slotRank(b.slot));

  const col = el("div", { class: "lineup-col" }, lineupTable(starters));
  if (bench.length) {
    const details = el("details", { class: "bench-details" }, [el("summary", {}, `Bench (${bench.length})`), lineupTable(bench)]);
    col.appendChild(details);
  }
  return col;
}

function matchupCard(m) {
  const header = el("div", { class: "matchup-header" }, [
    el("div", { class: "matchup-team" }, [
      el("div", { class: "team-name" }, m.home ? m.home.owner : "BYE"),
      el("div", { class: "team-score" }, m.home ? fmtNum(m.home.score) : "-"),
    ]),
    el("div", { class: "matchup-vs" }, "vs"),
    el("div", { class: "matchup-team" }, [
      el("div", { class: "team-name" }, m.away ? m.away.owner : "BYE"),
      el("div", { class: "team-score" }, m.away ? fmtNum(m.away.score) : "-"),
    ]),
  ]);
  const children = [header, el("div", { class: "matchup-lineups" }, [lineupSection(m.home), lineupSection(m.away)])];
  if (m.is_playoff) children.unshift(el("div", { class: "trade-date" }, "Playoffs"));
  return el("div", { class: "matchup-card" }, children);
}

const matchupDataCache = {};

function renderMatchups(data) {
  const root = document.getElementById("panel-matchups");
  root.innerHTML = "";

  const seasons = [...data.seasons].filter((s) => (s.weeks_available || []).length).sort((a, b) => b.year - a.year);

  if (!seasons.length) {
    root.appendChild(el("div", { class: "empty-state" }, "No weekly matchup data available yet. Run the data refresh workflow to generate it."));
    return;
  }

  const controls = el("div", { class: "controls" });
  const yearSelect = el("select", { id: "matchup-year-select" });
  seasons.forEach((s) => yearSelect.appendChild(el("option", { value: s.year }, String(s.year))));
  const weekSelect = el("select", { id: "matchup-week-select" });
  controls.appendChild(el("label", {}, "Season"));
  controls.appendChild(yearSelect);
  controls.appendChild(el("label", {}, "Week"));
  controls.appendChild(weekSelect);
  root.appendChild(controls);

  const body = el("div", { id: "matchup-body" });
  root.appendChild(body);

  function populateWeeks(year) {
    const season = seasons.find((s) => String(s.year) === String(year));
    weekSelect.innerHTML = "";
    (season ? season.weeks_available : []).forEach((w) => weekSelect.appendChild(el("option", { value: w }, `Week ${w}`)));
  }

  async function loadYear(year) {
    if (year in matchupDataCache) return matchupDataCache[year];
    try {
      const res = await fetch(`data/boxscores/${year}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      matchupDataCache[year] = await res.json();
    } catch (e) {
      matchupDataCache[year] = null;
    }
    return matchupDataCache[year];
  }

  async function renderWeek(year, week) {
    body.innerHTML = "";
    body.appendChild(el("div", { class: "empty-state" }, "Loading matchups…"));
    const boxData = await loadYear(year);
    body.innerHTML = "";

    const matchups = boxData && boxData.weeks ? boxData.weeks[String(week)] : null;
    const card = el("div", { class: "card" }, [el("h2", {}, `${year} · Week ${week}`)]);
    if (!matchups || !matchups.length) {
      card.appendChild(
        el(
          "div",
          { class: "empty-state" },
          boxData === null ? "Could not load matchup data for this season." : "No matchup data for this week."
        )
      );
    } else {
      matchups.forEach((m) => card.appendChild(matchupCard(m)));
    }
    body.appendChild(card);
  }

  yearSelect.addEventListener("change", (e) => {
    populateWeeks(e.target.value);
    if (weekSelect.options.length) renderWeek(e.target.value, weekSelect.value);
  });
  weekSelect.addEventListener("change", (e) => renderWeek(yearSelect.value, e.target.value));

  populateWeeks(seasons[0].year);
  if (weekSelect.options.length) {
    // Default to the most recent week with data for that season.
    weekSelect.value = weekSelect.options[weekSelect.options.length - 1].value;
    renderWeek(seasons[0].year, weekSelect.value);
  }
}

function initTheme() {
  const saved = (() => {
    try {
      return localStorage.getItem("ff-dashboard-theme");
    } catch (e) {
      return null;
    }
  })();
  if (saved) document.documentElement.setAttribute("data-theme", saved);

  const btn = document.getElementById("theme-toggle");
  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("ff-dashboard-theme", next);
    } catch (e) {
      /* ignore - private browsing etc. */
    }
  });
}

async function main() {
  initTheme();

  document.querySelectorAll("nav.tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

  let data;
  try {
    const res = await fetch("data/league_history.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
    // 2021 and 2022 are excluded from season-by-season browsing (too little
    // tracked data to be worth a season page) but still count toward the
    // all-time career totals above, which come pre-aggregated as data.all_time.
    data.seasons = (data.seasons || []).filter((s) => !EXCLUDED_HISTORY_YEARS.includes(Number(s.year)));
  } catch (e) {
    document.getElementById("app").innerHTML = "";
    document.querySelector(".banner").textContent =
      "No league data yet. Run the \"Update Fantasy Football Dashboard\" workflow from the Actions tab (or wait for the first scheduled run) to generate data/league_history.json.";
    return;
  }

  if (!data.seasons || !data.seasons.length) {
    document.querySelector(".banner").textContent = "The data file loaded, but no seasons were found. Check the Action's run log for warnings.";
  } else {
    const trackedYears = data.seasons.map((s) => Number(s.year));
    const trackedStart = Math.min(...trackedYears);
    const trackedEnd = Math.max(...trackedYears, Number(data.current_season_year) || 0);
    document.querySelector(".banner").innerHTML = `Tracking <strong>${data.seasons.length}</strong> season${data.seasons.length > 1 ? "s" : ""} (${trackedStart}–${trackedEnd}) · League ID <strong>${data.league_id}</strong> · Last refreshed ${fmtDate(data.generated_at)}`;
  }

  renderOverview(data);
  renderSeasons(data);
  renderTrades(data);
  renderWaivers(data);
  renderMatchups(data);
}

main();
