(() => {
  const DATA_DIR = "./data/";
  const COLORS = ["#0b74d1", "#ff4f4f", "#14b8a6", "#78e89a", "#7cc7ff", "#ff9fa3", "#8b5cf6", "#f59e0b"];
  const FILES = {
    manifest: "manifest.json",
    longitudinalMeta: "longitudinal_metadata.json",
    runMeta: "run_metadata.json",
    projectionMeta: "user_wants_projection_metadata.json",
    trends: "longitudinal_want_monthly_trends.csv",
    emerging: "longitudinal_emerging_wants.csv",
    assignments: "user_wants_all_assignments.csv",
    summary: "user_wants_full_corpus_summary.csv",
    journeys: "longitudinal_user_journeys.csv",
    events: "longitudinal_user_journey_events.csv",
    archetypes: "longitudinal_journey_archetypes.csv"
  };

  const PERSON_ATTRIBUTION_COLUMNS = new Set([
    "manager",
    "managers_touched",
    "top_managers",
    "managers_seen",
    "benchmark_manager"
  ]);

  const state = {
    data: {},
    noBanRows: [],
    uidIndex: new Map(),
    selectedTimeline: new Set(),
    currentLookupRows: [],
    currentAuditRows: [],
    currentNoBanRows: [],
    currentJourneyRows: [],
    charts: {}
  };

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    document.body.dataset.view = "lookup";
    bindNavigation();
    bindStaticControls();
    try {
      // Runs as plain static HTML (data is baked into data/bundle.js) — file:// works.
      await loadData();
      prepareData();
      setHealth("CSV package loaded. No AI is running in this page.", "ok");
      renderAll();
      window.addEventListener("resize", debounce(resizeCharts, 120));
    } catch (error) {
      console.error(error);
      setHealth(`Could not load CSV package: ${error.message}`, "bad");
      document.querySelectorAll(".view").forEach((view) => {
        view.insertAdjacentHTML("afterbegin", `<div class="panel"><div class="empty">${escapeHtml(error.message)}</div></div>`);
      });
    }
  }

  function bindNavigation() {
    const showSection = (target) => {
      document.body.dataset.view = target;
      document.body.classList.toggle("has-uid-result", target === "lookup" && state.currentLookupRows.length > 0);
      document.querySelectorAll(".nav__item").forEach((item) => {
        const active = item.dataset.section === target;
        item.classList.toggle("is-active", active);
        if (active) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      });
      document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-active", view.id === target));
      byId("mainContent").focus({ preventScroll: true });
      requestAnimationFrame(() => {
        if (target === "timeline") renderTimeline();
        resizeCharts();
      });
    };
    document.querySelectorAll(".nav__item").forEach((button) => {
      button.addEventListener("click", () => {
        showSection(button.dataset.section);
      });
    });
    document.querySelectorAll("[data-open-section]").forEach((button) => {
      button.addEventListener("click", () => showSection(button.dataset.openSection));
    });
  }

  function bindStaticControls() {
    byId("combineTitles").addEventListener("change", () => {
      seedTimelineSelection();
      renderTimeline();
      renderAudit();
    });
    byId("includePartial").addEventListener("change", () => {
      seedTimelineSelection();
      renderTimeline();
      renderAudit();
    });
    byId("auditWant").addEventListener("change", renderAudit);
    byId("auditMonth").addEventListener("change", renderAudit);
    byId("auditKeyword").addEventListener("input", debounce(renderAudit, 150));
    byId("downloadAudit").addEventListener("click", () => downloadRows("timeline_audit_rows.csv", rowsForExport(state.currentAuditRows)));
    document.querySelectorAll("[data-audit-view]").forEach((btn) => {
      btn.addEventListener("click", () => renderAuditView(btn.dataset.auditView));
    });
    byId("timelineTop6").addEventListener("click", () => {
      seedTimelineSelection();
      renderTimeline();
    });
    byId("timelineClear").addEventListener("click", () => {
      state.selectedTimeline = new Set();
      renderTimeline();
    });
    byId("downloadNoBan").addEventListener("click", () => downloadRows("no_ban_mentions.csv", rowsForExport(state.currentNoBanRows)));
    byId("downloadJourneys").addEventListener("click", () => downloadRows("repeat_user_journeys.csv", rowsForExport(state.currentJourneyRows)));
    byId("uidSearch").addEventListener("keydown", (event) => {
      if (event.key === "Enter") runUidSearch({ force: true });
    });
    byId("uidSearch").addEventListener("input", debounce(runUidSearch, 180));
    byId("uidMatchSelect").addEventListener("change", () => renderUidResult(byId("uidMatchSelect").value));
    ["noBanCategory", "noBanStatus", "noBanWant", "noBanSearch"].forEach((id) => {
      byId(id).addEventListener(id.endsWith("Search") ? "input" : "change", debounce(renderNoBanTable, 120));
    });
    byId("journeyUid").addEventListener("change", renderJourneyDetail);
  }

  async function loadData() {
    // Data is baked into data/bundle.js (window.WUW_DATA) and loaded via a <script> tag,
    // so the readout runs as plain static HTML — no fetch(), works from file:// and any
    // CDN with no server. Rebuild the bundle with scripts/export_static_readout.py.
    if (!window.WUW_DATA) {
      throw new Error("data/bundle.js is missing — rebuild the package with export_static_readout.py");
    }
    state.data = window.WUW_DATA;
  }

  async function fetchText(name) {
    const response = await fetch(DATA_DIR + name, { cache: "no-store" });
    if (!response.ok) throw new Error(`${name} is missing or not readable`);
    return response.text();
  }

  async function fetchJsonOptional(name) {
    try {
      const response = await fetch(DATA_DIR + name, { cache: "no-store" });
      if (!response.ok) return null;
      return response.json();
    } catch {
      return null;
    }
  }

  function prepareData() {
    const titleIds = new Map();
    for (const row of state.data.summary) {
      const title = row.want_title || "Untitled want";
      if (!titleIds.has(title)) titleIds.set(title, new Set());
      titleIds.get(title).add(row.assigned_want_id || row.want_label || title);
    }
    const duplicateTitles = new Set([...titleIds.entries()].filter(([, ids]) => ids.size > 1).map(([title]) => title));
    const decorate = (row) => {
      const title = row.want_title || "Untitled want";
      const id = row.assigned_want_id || row.want_label || "";
      row.display_want = duplicateTitles.has(title) ? `${title} · cluster ${id}` : title;
      row.month_from_date = monthFromDate(row.date_raw || row.date || "");
      return row;
    };
    state.data.assignments.forEach(decorate);
    state.data.trends.forEach((row) => {
      row.display_want = duplicateTitles.has(row.want_title) ? `${row.want_title} · cluster ${row.assigned_want_id}` : row.want_title;
    });
    state.data.events.forEach((row) => {
      row.month_from_date = monthFromDate(row.date || "");
    });
    state.noBanRows = state.data.assignments.filter((row) => noBanPattern().test(row.question_flat || ""));
    state.uidIndex = buildUidIndex();
    seedTimelineSelection();
  }

  function renderAll() {
    renderMeta();
    renderLookup();
    renderKpis();
    renderTimeline();
    setupNoBanFilters();
    renderNoBanTable();
    renderJourneys();
    bindReveals();
    bindKpiActions();
    hydrateLookupFromUrl();
  }

  function navTo(section) {
    const btn = document.querySelector(`.nav__item[data-section="${section}"]`);
    if (btn) btn.click();
  }
  function ensureRevealOpen(id) {
    const target = byId(id);
    if (!target || !target.hidden) return;
    const opener = document.querySelector(`[data-reveals="${id}"]`);
    if (opener) opener.click();
  }
  function renderJourneyQueueFilter(filter) {
    const rows = filter === "longrunning"
      ? (state.currentJourneyRows || []).filter((row) => num(row.active_days) >= 90)
      : (state.currentJourneyRows || []);
    const queueTable = byId("journeyTable");
    if (!queueTable) return;
    const note = filter === "longrunning"
      ? `<div class="queue-filter-note">Showing ${formatInt(rows.length)} long-running cases (90+ days). <button type="button" data-action="openJourneysQueue">See all</button></div>`
      : "";
    queueTable.innerHTML = note + tableHtml(rows.slice(0, 120), [
      ["uid", "UID"],
      ["records", "Records"],
      ["active_days", "Active days"],
      ["unique_wants", "Wants"],
      ["failed_or_open_share", "Open/failed share"],
      ["latest_want", "Latest want"],
      ["top_wants", "Top wants", "text-cell"],
      ["recommended_action", "Pattern note", "text-cell"]
    ]);
  }
  const kpiActions = {
    openTimeline: () => navTo("timeline"),
    openMethod: () => navTo("method"),
    openJourneysQueue: () => {
      navTo("journeys");
      requestAnimationFrame(() => {
        renderJourneyQueueFilter("all");
        ensureRevealOpen("queueBlock");
      });
    },
    openJourneysLongRunning: () => {
      navTo("journeys");
      requestAnimationFrame(() => {
        renderJourneyQueueFilter("longrunning");
        ensureRevealOpen("queueBlock");
      });
    },
    scrollToAudit: () => {
      const el = byId("auditTable");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    scrollToNoBan: () => {
      const el = byId("noBanTable");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
  let kpiActionsBound = false;
  function bindKpiActions() {
    if (kpiActionsBound) return;
    kpiActionsBound = true;
    document.addEventListener("click", (event) => {
      const el = event.target.closest("[data-action]");
      if (!el) return;
      const fn = kpiActions[el.dataset.action];
      if (!fn) return;
      event.preventDefault();
      fn();
    });
  }

  const deferredRenderers = { trend: () => { renderWarnings(); resizeCharts(); } };
  const renderedDeferred = new Set();
  function bindReveals() {
    document.querySelectorAll("[data-reveals]").forEach((button) => {
      if (button.dataset.revealBound === "1") return;
      button.dataset.revealBound = "1";
      button.addEventListener("click", () => {
        const id = button.dataset.reveals;
        const target = byId(id);
        if (!target) return;
        const icon = button.querySelector(".reveal-button__icon");
        const willOpen = target.hidden;
        target.hidden = !willOpen;
        target.setAttribute("aria-hidden", String(!willOpen));
        button.classList.toggle("is-shown", willOpen);
        button.setAttribute("aria-expanded", String(willOpen));
        if (icon) icon.textContent = willOpen ? "✓" : "+";
        if (!willOpen) return;
        const renderKey = button.dataset.render;
        if (renderKey && !renderedDeferred.has(renderKey) && deferredRenderers[renderKey]) {
          renderedDeferred.add(renderKey);
          requestAnimationFrame(deferredRenderers[renderKey]);
        }
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    document.querySelectorAll("[data-hides]").forEach((button) => {
      if (button.dataset.revealBound === "1") return;
      button.dataset.revealBound = "1";
      button.addEventListener("click", () => {
        const id = button.dataset.hides;
        const target = byId(id);
        if (!target) return;
        target.hidden = true;
        target.setAttribute("aria-hidden", "true");
        const opener = document.querySelector(`[data-reveals="${id}"]`);
        if (opener) {
          opener.classList.remove("is-shown");
          const icon = opener.querySelector(".reveal-button__icon");
          if (icon) icon.textContent = "+";
          opener.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
    });
  }

  function renderMeta() {
    const manifest = state.data.manifest || {};
    const longitudinal = state.data.longitudinalMeta || {};
    const run = state.data.runMeta || {};
    byId("runName").textContent = manifest.run_name || basename(run.output_dir || longitudinal.run_dir || "static CSV package");
    byId("generatedAt").textContent = `Data generated: ${formatDateTime(longitudinal.generated_at || run.generated_at || manifest.packaged_at || "")}`;
  }

  function renderKpis() {
    const longitudinal = state.data.longitudinalMeta || {};
    const projection = state.data.projectionMeta || {};
    const months = longitudinal.complete_months || completeMonths();
    const summarizedWants = summarizeWantsByTitle(state.data.summary);
    const topWant = topBy(summarizedWants, (row) => row.estimated);
    const topMomentum = topBy(state.data.emerging, (row) => num(row.momentum_score));
    const sameTopAsMomentum = topMomentum?.want_title && topWant?.title && topMomentum.want_title === topWant.title;
    const forecastNext = Math.round(num(topMomentum?.forecast_next_month || 0));
    const recentRecords = formatInt(topMomentum?.recent_records || 0);
    const momentumValue = sameTopAsMomentum
      ? `${recentRecords} this month → ${formatInt(forecastNext)} next`
      : (topMomentum?.want_title || "-");
    const momentumDetail = sameTopAsMomentum
      ? `Same need, picking up speed — projected ${formatInt(forecastNext)} records next month.`
      : `${recentRecords} recent records; projected ${formatInt(forecastNext)} next month.`;

    const rows = [
      {
        label: "What users keep asking for",
        value: topWant?.title || "-",
        detail: `${formatInt(topWant?.estimated || 0)} mapped records across ${formatInt(topWant?.clusters || 0)} discovered cluster${topWant?.clusters === 1 ? "" : "s"}.`,
        action: "openTimeline",
        openLabel: "See the trend"
      },
      {
        label: "Where demand is growing",
        value: momentumValue,
        detail: momentumDetail,
        action: "openTimeline",
        openLabel: "See the trend"
      },
      {
        label: "Users coming back",
        value: formatInt(longitudinal.repeat_users || state.data.journeys.length),
        detail: "UIDs with more than one support record. Open one to read the full trail.",
        action: "openJourneysQueue",
        openLabel: "Open priority queue"
      },
      {
        label: "Records analyzed",
        value: `${formatInt(longitudinal.records || state.data.assignments.length)} rows`,
        detail: `${formatInt(projection.llm_confirmed_rows || confirmedRows())} read by AI · ${formatInt(projection.projected_rows || 0)} mapped by embeddings.`,
        action: "openMethod",
        openLabel: "How counted"
      }
    ];
    const evidenceTarget = byId("executiveEvidence") || byId("kpiGrid");
    if (evidenceTarget) {
      evidenceTarget.innerHTML = rows.map(proofCardHtml).join("");
    }
    const headlineStat = byId("headlineStatValue");
    if (headlineStat) {
      headlineStat.textContent = formatInt(longitudinal.repeat_users || state.data.journeys.length);
    }

    const noBanByWant = groupCount(state.noBanRows, (row) => row.want_title || "Unknown");
    const topNoBan = topBy([...noBanByWant.entries()].map(([key, value]) => ({ key, value })), (row) => row.value);
    const noBanKpis = byId("noBanKpis");
    if (noBanKpis) {
      noBanKpis.innerHTML = [
        ["No-ban records", formatInt(state.noBanRows.length), "Matches no-ban / no ban / no_ban", "scrollToNoBan", "See rows"],
        ["Top no-ban want", escapeHtml(topNoBan?.key || "None"), `${formatInt(topNoBan?.value || 0)} records`, "scrollToNoBan", "See rows"],
        ["Complete months", formatInt(months.length), `${months[0] || "-"} to ${months.at(-1) || "-"}`],
        ["Largest want", escapeHtml(topWant?.want_title || "-"), `${formatInt(topWant?.estimated_tickets || 0)} mapped records`, "scrollToNoBan", "See rows"]
      ].map(kpiHtml).join("");
    }
  }

  function renderWarnings() {
    disposeChart("warnings");
    const rows = [...state.data.emerging]
      .sort((a, b) => num(b.momentum_score) - num(a.momentum_score))
      .slice(0, 5);
    const el = byId("warningBars");
    el.innerHTML = `
      <div class="forecast-copy">
        <span>Solid lines are observed monthly records.</span>
        <span>Dashed segments are the simple next-month projection from the run.</span>
      </div>
      <div id="warningForecastChart" class="echart echart--forecast" role="img" aria-label="Observed support records and next-month forecast"></div>
      <div class="forecast-list">${rows.map((row) => `
        <div>
          <span>${escapeHtml(forecastLabel(row, rows))}</span>
          <strong>${formatInt(row.recent_records)} recent · forecast ${formatFloat(row.forecast_next_month, 1)}</strong>
        </div>`).join("")}</div>`;
    if (!chartLibraryReady()) {
      byId("warningForecastChart").innerHTML = `<div class="empty">Chart library did not load. Upload vendor/echarts.min.js with this static package.</div>`;
      return;
    }
    drawForecastChart(rows);
  }

  function drawForecastChart(rows) {
    const chartEl = byId("warningForecastChart");
    if (!visibleBox(chartEl)) return;
    const complete = completeMonths();
    const forecastMonth = rows.find((row) => row.forecast_month)?.forecast_month || nextMonth(complete.at(-1));
    const months = unique([...complete, forecastMonth]).sort();
    const duplicateNames = duplicateValues(rows.map((row) => row.want_title));
    const series = rows.flatMap((row, idx) => {
      const color = COLORS[idx % COLORS.length];
      const key = row.assigned_want_id;
      const label = duplicateNames.has(row.want_title) ? `${row.want_title} · ${key}` : row.want_title;
      const monthValues = new Map(state.data.trends
        .filter((trend) => String(trend.assigned_want_id) === String(key))
        .map((trend) => [trend.month, num(trend.records)]));
      const lastMonth = [...complete].reverse().find((month) => monthValues.has(month));
      const lastValue = monthValues.get(lastMonth) ?? null;
      return [
        {
          name: label,
          type: "line",
          smooth: true,
          symbolSize: 6,
          lineStyle: { width: 3, color },
          itemStyle: { color },
          emphasis: { focus: "series" },
          data: months.map((month) => (month === forecastMonth ? null : monthValues.get(month) ?? null))
        },
        {
          name: label,
          type: "line",
          symbolSize: 6,
          lineStyle: { width: 3, type: "dashed", color },
          itemStyle: { color },
          emphasis: { focus: "series" },
          data: months.map((month) => {
            if (month === lastMonth) return { value: lastValue, forecastStart: true };
            if (month === forecastMonth) return { value: num(row.forecast_next_month), forecast: true };
            return null;
          })
        }
      ];
    });
    const chart = echarts.init(chartEl, null, { renderer: "svg" });
    state.charts.warnings = chart;
    chart.setOption({
      color: COLORS,
      animationDuration: 450,
      tooltip: {
        trigger: "axis",
        formatter: chartTooltipFormatter
      },
      legend: {
        type: "scroll",
        data: rows.map((row) => forecastLabel(row, rows)),
        bottom: 0,
        icon: "roundRect",
        itemWidth: 18,
        itemHeight: 4,
        textStyle: { color: "#4b5563" }
      },
      grid: { left: 54, right: 26, top: 28, bottom: 78, containLabel: true },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: months,
        axisLabel: { formatter: shortMonth, color: "#667085" },
        axisLine: { lineStyle: { color: "#dce4ef" } },
        axisTick: { show: false }
      },
      yAxis: {
        type: "value",
        name: "Mapped records",
        nameTextStyle: { color: "#667085", align: "left" },
        axisLabel: { color: "#667085" },
        splitLine: { lineStyle: { color: "#e8eef6" } }
      },
      series
    }, true);
  }

  function buildUidIndex() {
    const map = new Map();
    const seen = new Map();
    const add = (uid, row, source) => {
      if (!validUid(uid)) return;
      row.uid = uid;
      const rowKey = row.source_row ? `row:${row.source_row}` : `${source}:${row.event_index || ""}:${row.date_raw || ""}:${row.question_flat || ""}`;
      if (!seen.has(uid)) seen.set(uid, new Set());
      if (seen.get(uid).has(rowKey)) return;
      seen.get(uid).add(rowKey);
      if (!map.has(uid)) map.set(uid, []);
      map.get(uid).push(row);
    };
    for (const row of state.data.assignments) {
      const uid = normalizeUid(row.uid);
      add(uid, row, "assignment");
    }
    for (const row of state.data.events) {
      const uid = normalizeUid(row.uid);
      add(uid, eventRowForLookup(row, uid), "journey_event");
    }
    for (const rows of map.values()) {
      rows.sort((a, b) => dateSortValue(a.date_raw) - dateSortValue(b.date_raw) || num(a.source_row) - num(b.source_row));
    }
    return map;
  }

  function eventRowForLookup(row, uid) {
    return {
      ...row,
      uid,
      date_raw: row.date || row.date_raw || "",
      status_en: row.status || row.status_en || "",
      display_want: row.want_title || row.display_want || "",
      assignment_confidence: row.assignment_confidence || row.confidence_band || "",
      question_flat: row.question || row.question_flat || ""
    };
  }

  function renderLookup() {
    document.body.classList.remove("has-uid-result");
    byId("uidLookupResult").innerHTML = "";
    const summaryEl = byId("uidLookupSummary");
    if (summaryEl) summaryEl.innerHTML = "";
  }

  function runUidSearch({ force = false } = {}) {
    const query = uidQueryFromInput(byId("uidSearch").value);
    const wrap = byId("uidMatchWrap");
    if (!query) {
      wrap.hidden = true;
      state.currentLookupRows = [];
      clearUidUrl();
      renderLookup();
      return;
    }
    if (query.length < 4) {
      wrap.hidden = true;
      state.currentLookupRows = [];
      clearUidUrl();
      document.body.classList.remove("has-uid-result");
      byId("uidLookupResult").innerHTML = `<div class="lookup-empty"><h2>Keep typing the UID.</h2><p>Use at least four digits for partial matching.</p></div>`;
      const summaryEl = byId("uidLookupSummary");
      if (summaryEl) summaryEl.innerHTML = "";
      return;
    }
    const exact = state.uidIndex.has(query);
    const matches = exact
      ? [query]
      : uidPartialMatches(query);
    if (!matches.length) {
      wrap.hidden = true;
      state.currentLookupRows = [];
      clearUidUrl();
      document.body.classList.remove("has-uid-result");
      byId("uidLookupResult").innerHTML = `<div class="lookup-empty"><h2>No UID match found.</h2><p>Check the digits, or search a longer fragment from the screenshot/export.</p></div>`;
      const summaryEl = byId("uidLookupSummary");
      if (summaryEl) summaryEl.innerHTML = "";
      return;
    }
    wrap.hidden = exact || matches.length <= 1;
    setOptions(byId("uidMatchSelect"), matches, (uid) => `${uid} · ${formatInt(state.uidIndex.get(uid).length)} records`, matches[0]);
    if (exact || matches.length === 1) {
      renderUidResult(matches[0]);
      return;
    }
    state.currentLookupRows = [];
    clearUidUrl();
    document.body.classList.remove("has-uid-result");
    byId("uidLookupResult").innerHTML = `
      <div class="lookup-empty">
        <h2>${formatInt(matches.length)} UID match${matches.length === 1 ? "" : "es"} found.</h2>
        <p>${force ? "Several users match those digits." : "Keep typing, or"} select the right UID from the list above.</p>
      </div>`;
  }

  function uidQueryFromInput(value) {
    const raw = String(value || "").trim();
    const urlUid = raw.match(/[?&]uid=([^&#\s]+)/i);
    if (urlUid) return normalizeUid(decodeURIComponent(urlUid[1]));
    return normalizeUid(raw);
  }

  function uidPartialMatches(query) {
    return [...state.uidIndex.keys()]
      .filter((uid) => uid.includes(query))
      .sort((a, b) => uidMatchScore(query, b) - uidMatchScore(query, a) || a.localeCompare(b))
      .slice(0, 50);
  }

  function uidMatchScore(query, uid) {
    const count = state.uidIndex.get(uid)?.length || 0;
    return (uid.startsWith(query) ? 1_000_000 : 0)
      + (uid.endsWith(query) ? 500_000 : 0)
      + Math.min(count, 999) * 100
      - uid.length;
  }

  function renderUidResult(uid) {
    const rows = state.uidIndex.get(uid) || [];
    state.currentLookupRows = rows;
    byId("uidSearch").value = uid;
    const journey = state.data.journeys.find((row) => normalizeUid(row.uid) === uid);
    const wants = unique(rows.map((row) => row.want_title || row.display_want).filter(Boolean));
    const categories = unique(rows.map((row) => row.category).filter(Boolean));
    const noBanRows = rows.filter((row) => noBanPattern().test(row.question_flat || ""));
    const openFailedRows = rows.filter((row) => /open|fail|pending|progress/i.test(row.status_en || ""));
    const noBanCount = noBanRows.length;
    const openFailed = openFailedRows.length;
    const firstDate = rows[0]?.date_raw || "-";
    const latestDate = rows.at(-1)?.date_raw || "-";
    const latestStatus = rows.at(-1)?.status_en || "-";
    const latestWant = rows.at(-1)?.want_title || rows.at(-1)?.display_want || "-";
    const dateRange = firstDate === latestDate ? latestDate : `${firstDate} to ${latestDate}`;
    const noBanLine = noBanCount
      ? `${formatInt(noBanCount)} no-ban mention${noBanCount === 1 ? "" : "s"} found in this UID trail.`
      : "No no-ban mention found in this UID trail.";
    document.body.classList.add("has-uid-result");
    updateUidUrl(uid);
    const summaryEl = byId("uidLookupSummary");
    if (summaryEl) {
      summaryEl.innerHTML = `
        <span class="lookup-strip__uid">${escapeHtml(uid)}</span>
        <span class="lookup-strip__sep" aria-hidden="true">·</span>
        <span class="lookup-strip__meta">${formatInt(rows.length)} record${rows.length === 1 ? "" : "s"}</span>
        <span class="lookup-strip__sep" aria-hidden="true">·</span>
        <span class="lookup-strip__meta">${escapeHtml(dateRange)}</span>
        <span class="lookup-strip__sep" aria-hidden="true">·</span>
        <span class="lookup-strip__meta">${escapeHtml(latestWant)}</span>
        <span class="lookup-strip__sep" aria-hidden="true">·</span>
        <span class="lookup-strip__status">${escapeHtml(latestStatus)}</span>
        <button class="button button--subtle lookup-strip__download" id="downloadUidRows" type="button">Download</button>`;
    }
    byId("uidLookupResult").innerHTML = `
      <section class="panel panel--uid-timeline">
        <div class="uid-timeline-bar">
          <span class="uid-timeline-bar__label">Trail · ${formatInt(rows.length)} records, oldest to newest</span>
          <div class="uid-timeline-toolbar" role="tablist" aria-label="Timeline orientation">
            <button class="uid-mode-button is-active" type="button" data-uid-mode="vertical" aria-pressed="true">
              <span class="uid-mode-button__icon" aria-hidden="true">↕</span>
              <span>Vertical</span>
            </button>
            <button class="uid-mode-button" type="button" data-uid-mode="horizontal" aria-pressed="false">
              <span class="uid-mode-button__icon" aria-hidden="true">↔</span>
              <span>Horizontal</span>
            </button>
          </div>
        </div>
        <div class="uid-timeline uid-timeline--vertical" id="uidTimelineRail">${uidTimelineHtml(rows)}</div>
      </section>

      <div class="uid-detail-layout">
        <nav class="uid-detail-nav" aria-label="Case sections">
          <button class="uid-detail-nav__item is-active" type="button" data-uid-section="summary">
            <span class="uid-detail-nav__title">Case summary</span>
            <span class="uid-detail-nav__hint">Overview</span>
          </button>
          <button class="uid-detail-nav__item" type="button" data-uid-section="wants">
            <span class="uid-detail-nav__title">Repeated wants</span>
            <span class="uid-detail-nav__hint">${formatInt(wants.length)}</span>
          </button>
          <button class="uid-detail-nav__item" type="button" data-uid-section="categories">
            <span class="uid-detail-nav__title">Categories</span>
            <span class="uid-detail-nav__hint">${formatInt(categories.length)}</span>
          </button>
          <button class="uid-detail-nav__item" type="button" data-uid-section="open">
            <span class="uid-detail-nav__title">Open or failed</span>
            <span class="uid-detail-nav__hint">${formatInt(openFailed)}</span>
          </button>
          <button class="uid-detail-nav__item" type="button" data-uid-section="noban">
            <span class="uid-detail-nav__title">No-ban</span>
            <span class="uid-detail-nav__hint">${formatInt(noBanCount)}</span>
          </button>
          <button class="uid-detail-nav__item" type="button" data-uid-section="rows">
            <span class="uid-detail-nav__title">All rows</span>
            <span class="uid-detail-nav__hint">${formatInt(rows.length)}</span>
          </button>
          <button class="uid-detail-nav__item" type="button" data-uid-section="filtered" hidden>
            <span class="uid-detail-nav__title">Selected rows</span>
            <span class="uid-detail-nav__hint">—</span>
          </button>
        </nav>
        <div class="uid-detail-content">
          <section class="uid-detail-section is-active" data-uid-section-content="summary">
            <div class="uid-summary-strip">
              <button class="uid-summary-card" type="button" data-uid-open="rows">
                <span>Records</span><strong>${formatInt(rows.length)}</strong><small>Open row audit</small>
              </button>
              <button class="uid-summary-card" type="button" data-uid-open="wants">
                <span>Distinct wants</span><strong>${formatInt(wants.length)}</strong><small>Open want list</small>
              </button>
              <button class="uid-summary-card" type="button" data-uid-open="categories">
                <span>Categories</span><strong>${formatInt(categories.length)}</strong><small>Open category list</small>
              </button>
              <button class="uid-summary-card" type="button" data-uid-open="noban">
                <span>No-ban</span><strong>${formatInt(noBanCount)}</strong><small>Open evidence</small>
              </button>
            </div>
            <dl class="uid-facts">
              <div><dt>First seen</dt><dd><button class="uid-inline-link" type="button" data-uid-open="timeline">${escapeHtml(firstDate)}</button></dd></div>
              <div><dt>Latest record</dt><dd><button class="uid-inline-link" type="button" data-uid-open="timeline">${escapeHtml(latestDate)}</button></dd></div>
              <div><dt>Open or failed records</dt><dd><button class="uid-inline-link" type="button" data-uid-open="open">${formatInt(openFailed)}</button></dd></div>
              <div><dt>Evidence note</dt><dd>${escapeHtml(noBanLine)}</dd></div>
            </dl>
            <div class="uid-action">
              <span>What we see</span>
              <p>${escapeHtml(journey?.recommended_action || "Multiple records on file.")}</p>
            </div>
          </section>

          <section class="uid-detail-section" id="uidWantsPanel" data-uid-section-content="wants" hidden>
            <h3 class="uid-detail-section__head">Repeated wants</h3>
            <div class="uid-want-list">${wantListHtml(rows)}</div>
          </section>

          <section class="uid-detail-section" id="uidCategoriesPanel" data-uid-section-content="categories" hidden>
            <h3 class="uid-detail-section__head">Categories touched</h3>
            <div class="uid-want-list">${categoryListHtml(rows)}</div>
          </section>

          <section class="uid-detail-section" id="uidFilteredPanel" data-uid-section-content="filtered" hidden>
            <h3 class="uid-detail-section__head">Selected rows</h3>
            <div id="uidFilteredContent"></div>
          </section>

          <section class="uid-detail-section" id="uidOpenPanel" data-uid-section-content="open" hidden>
            <h3 class="uid-detail-section__head">Open or failed records</h3>
            <div class="table-wrap">${tableHtml(openFailedRows, [
              ["source_row", "Row"],
              ["date_raw", "Date"],
              ["category", "Category"],
              ["status_en", "Status"],
              ["display_want", "Mapped want"],
              ["question_flat", "Support text", "text-cell"]
            ])}</div>
          </section>

          <section class="uid-detail-section" id="uidNoBanPanel" data-uid-section-content="noban" hidden>
            <h3 class="uid-detail-section__head">No-ban evidence</h3>
            <div class="table-wrap">${tableHtml(noBanRows, [
              ["source_row", "Row"],
              ["date_raw", "Date"],
              ["category", "Category"],
              ["status_en", "Status"],
              ["display_want", "Mapped want"],
              ["question_flat", "No-ban context", "text-cell"]
            ])}</div>
          </section>

          <section class="uid-detail-section" id="uidRowsPanel" data-uid-section-content="rows" hidden>
            <h3 class="uid-detail-section__head">All rows for audit</h3>
            <div class="table-wrap">${tableHtml(rows, [
              ["source_row", "Row"],
              ["date_raw", "Date"],
              ["uid", "UID"],
              ["category", "Category"],
              ["status_en", "Status"],
              ["display_want", "Mapped want"],
              ["assignment_confidence", "Confidence"],
              ["question_flat", "Support text", "text-cell"]
            ])}</div>
          </section>
        </div>
      </div>`;
    byId("downloadUidRows").addEventListener("click", () => downloadRows(`uid_${uid}_support_trail.csv`, rowsForExport(state.currentLookupRows)));
    bindUidOpenButtons();
    bindUidTimelineModes();
  }

  function bindUidTimelineModes() {
    const rail = byId("uidTimelineRail");
    if (!rail) return;
    const syncRailWidth = () => {
      if (rail.classList.contains("uid-timeline--horizontal")) {
        rail.style.setProperty("--rail-content-width", `${rail.scrollWidth}px`);
      }
    };
    document.querySelectorAll(".uid-mode-button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.dataset.uidMode;
        rail.classList.remove("uid-timeline--vertical", "uid-timeline--horizontal");
        rail.classList.add(`uid-timeline--${mode}`);
        document.querySelectorAll(".uid-mode-button").forEach((other) => {
          const active = other === btn;
          other.classList.toggle("is-active", active);
          other.setAttribute("aria-pressed", String(active));
        });
        if (mode === "horizontal") {
          rail.scrollLeft = 0;
          requestAnimationFrame(syncRailWidth);
        }
      });
    });
    if (!window.__uidRailResizeBound) {
      window.__uidRailResizeBound = true;
      window.addEventListener("resize", debounce(() => {
        const r = byId("uidTimelineRail");
        if (r && r.classList.contains("uid-timeline--horizontal")) {
          r.style.setProperty("--rail-content-width", `${r.scrollWidth}px`);
        }
      }, 150));
    }
  }

  function hydrateLookupFromUrl() {
    const url = new URL(window.location.href);
    const uid = normalizeUid(url.searchParams.get("uid") || "");
    if (!uid) return;
    byId("uidSearch").value = uid;
    runUidSearch();
  }

  function updateUidUrl(uid) {
    const url = new URL(window.location.href);
    url.searchParams.set("uid", uid);
    window.history.replaceState({}, "", url);
  }

  function clearUidUrl() {
    const url = new URL(window.location.href);
    url.searchParams.delete("uid");
    window.history.replaceState({}, "", url);
  }

  function wantListHtml(rows) {
    const counts = [...groupCount(rows, (row) => row.want_title || row.display_want || "Unknown").entries()]
      .sort((a, b) => b[1] - a[1]);
    return counts.map(([want, count]) => `
      <button class="uid-want uid-want-button" type="button" data-uid-filter="want" data-uid-filter-value="${escapeAttr(want)}">
        <span>${escapeHtml(want)}</span>
        <strong>${formatInt(count)}</strong>
      </button>`).join("");
  }

  function categoryListHtml(rows) {
    const counts = [...groupCount(rows, (row) => row.category || "No category").entries()]
      .sort((a, b) => b[1] - a[1]);
    return counts.map(([category, count]) => `
      <button class="uid-want uid-want-button" type="button" data-uid-filter="category" data-uid-filter-value="${escapeAttr(category)}">
        <span>${escapeHtml(category)}</span>
        <strong>${formatInt(count)}</strong>
      </button>`).join("");
  }

  function bindUidOpenButtons() {
    document.querySelectorAll("[data-uid-open]").forEach((button) => {
      button.addEventListener("click", () => openUidEvidence(button.dataset.uidOpen));
    });
    document.querySelectorAll("[data-uid-filter]").forEach((button) => {
      button.addEventListener("click", () => openUidFilteredRows(button.dataset.uidFilter, button.dataset.uidFilterValue));
    });
    document.querySelectorAll("[data-uid-section]").forEach((button) => {
      button.addEventListener("click", () => selectUidSection(button.dataset.uidSection));
    });
  }

  function selectUidSection(key) {
    if (!key) return;
    document.querySelectorAll("[data-uid-section-content]").forEach((section) => {
      const match = section.dataset.uidSectionContent === key;
      section.hidden = !match;
      section.classList.toggle("is-active", match);
    });
    document.querySelectorAll("[data-uid-section]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.uidSection === key);
    });
  }

  function openUidFilteredRows(type, value) {
    const rows = state.currentLookupRows || [];
    const label = type === "category" ? "category" : "want";
    const filtered = rows.filter((row) => {
      const rowValue = type === "category"
        ? (row.category || "No category")
        : (row.want_title || row.display_want || "Unknown");
      return rowValue === value;
    });
    const content = byId("uidFilteredContent");
    if (!content) return;
    content.innerHTML = `
      <div class="uid-filtered-head">
        <div>
          <div class="panel__label">${escapeHtml(label)} drill-down</div>
          <h3>${escapeHtml(value)}</h3>
        </div>
        <span>${formatInt(filtered.length)} record${filtered.length === 1 ? "" : "s"}</span>
      </div>
      <div class="table-wrap">${tableHtml(filtered, [
        ["source_row", "Row"],
        ["date_raw", "Date"],
        ["uid", "UID"],
        ["category", "Category"],
        ["status_en", "Status"],
        ["display_want", "Mapped want"],
        ["question_flat", "Support text", "text-cell"]
      ])}</div>`;
    const navButton = document.querySelector('[data-uid-section="filtered"]');
    if (navButton) {
      navButton.hidden = false;
      const hint = navButton.querySelector(".uid-detail-nav__hint");
      if (hint) hint.textContent = formatInt(filtered.length);
    }
    selectUidSection("filtered");
  }

  function openUidEvidence(target) {
    if (target === "timeline") {
      const timeline = document.querySelector(".panel--uid-timeline");
      if (timeline) {
        timeline.scrollIntoView({ behavior: "smooth", block: "start" });
        timeline.classList.add("is-highlighted");
        window.setTimeout(() => timeline.classList.remove("is-highlighted"), 900);
      }
      return;
    }
    selectUidSection(target);
    const layout = document.querySelector(".uid-detail-layout");
    if (layout) layout.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function uidTimelineHtml(rows) {
    const trail = rows;
    const total = trail.length;
    return trail.map((row, index) => {
      const noBan = noBanPattern().test(row.question_flat || "");
      const side = index % 2 === 0 ? "left" : "right";
      const isLatest = index === total - 1;
      return `
        <article class="uid-event uid-event--${side} ${isLatest ? "is-latest" : ""} ${noBan ? "has-noban" : ""}">
          <div class="uid-event__node" aria-hidden="true">${index + 1}</div>
          <div class="uid-event__card">
            <div class="uid-event__meta">
              <span>${escapeHtml(row.date_raw || "-")}</span>
              <span>Row ${escapeHtml(row.source_row || "-")}</span>
              ${isLatest ? "<strong>Latest</strong>" : ""}
            </div>
            <h3>${escapeHtml(row.want_title || row.display_want || "Mapped want unavailable")}</h3>
            <div class="uid-event__badges">
              <span>${escapeHtml(row.category || "No category")}</span>
              <span>${escapeHtml(row.status_en || "No status")}</span>
              ${noBan ? "<strong>No-ban mention</strong>" : ""}
            </div>
            <p>${escapeHtml(excerpt(row.question_flat || "", 260))}</p>
          </div>
        </article>`;
    }).join("");
  }

  function excerpt(value, max = 220) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (text.length <= max) return text || "-";
    return `${text.slice(0, max - 1).trim()}…`;
  }

  function seedTimelineSelection() {
    const grouped = timelineSeries();
    const topKeys = [...grouped.values()]
      .sort((a, b) => b.total - a.total)
      .slice(0, 5)
      .map((series) => series.key);
    state.selectedTimeline = new Set(topKeys);
  }

  function timelineRows() {
    const includePartial = byId("includePartial").checked;
    const complete = new Set(completeMonths());
    return state.data.trends.filter((row) => includePartial || complete.has(row.month));
  }

  function timelineKey(row) {
    return byId("combineTitles").checked ? row.want_title : row.display_want;
  }

  function timelineSeries() {
    const grouped = new Map();
    for (const row of timelineRows()) {
      const key = timelineKey(row);
      if (!grouped.has(key)) {
        grouped.set(key, { key, values: new Map(), total: 0, ids: new Set(), titles: new Set() });
      }
      const series = grouped.get(key);
      const records = num(row.records);
      series.values.set(row.month, (series.values.get(row.month) || 0) + records);
      series.total += records;
      if (row.assigned_want_id) series.ids.add(String(row.assigned_want_id));
      if (row.want_title) series.titles.add(row.want_title);
      if (row.display_want) series.titles.add(row.display_want);
    }
    return grouped;
  }

  function renderTimeline() {
    const grouped = timelineSeries();
    const ordered = [...grouped.values()].sort((a, b) => b.total - a.total);
    if (state.selectedTimeline.size && ![...state.selectedTimeline].some((key) => grouped.has(key))) {
      state.selectedTimeline = new Set(ordered.slice(0, 5).map((series) => series.key));
    }
    byId("timelineChoices").innerHTML = ordered.slice(0, 12).map((series) => `
      <label class="chip">
        <input type="checkbox" value="${escapeAttr(series.key)}" ${state.selectedTimeline.has(series.key) ? "checked" : ""}>
        <span>${escapeHtml(series.key)}</span>
        <small>${formatInt(series.total)}</small>
      </label>`).join("");
    byId("timelineChoices").querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) state.selectedTimeline.add(input.value);
        else state.selectedTimeline.delete(input.value);
        drawTimeline(grouped);
        populateAuditControls();
      });
    });
    drawTimeline(grouped);
    populateAuditControls();
    renderAudit();
  }

  function drawTimeline(grouped) {
    const baseMonths = unique(timelineRows().map((row) => row.month)).sort();
    const series = [...state.selectedTimeline].filter((key) => grouped.has(key)).map((key) => grouped.get(key));
    if (!baseMonths.length || !series.length) {
      disposeChart("timeline");
      byId("timelineReadout").innerHTML = "";
      byId("timelineChart").innerHTML = `<div class="empty">Choose at least one want line.</div>`;
      byId("timelineLegend").innerHTML = "";
      return;
    }
    const forecastByKey = new Map(series.map((s) => [s.key, forecastForTimelineSeries(s)]).filter(([, row]) => row));
    byId("timelineReadout").innerHTML = timelineReadoutHtml(series, baseMonths, forecastByKey);
    if (!chartLibraryReady()) {
      disposeChart("timeline");
      byId("timelineChart").innerHTML = `<div class="empty">Chart library did not load. Upload vendor/echarts.min.js with this static package.</div>`;
      byId("timelineLegend").innerHTML = "";
      return;
    }
    const chartEl = byId("timelineChart");
    if (!visibleBox(chartEl)) return;
    disposeChart("timeline");
    chartEl.innerHTML = "";
    byId("timelineLegend").innerHTML = "";
    const months = unique([
      ...baseMonths,
      ...[...forecastByKey.values()].map((row) => row.forecast_month).filter(Boolean)
    ]).sort();
    const lastActualMonth = baseMonths.at(-1);
    const chart = echarts.init(chartEl, null, { renderer: "svg" });
    state.charts.timeline = chart;
    chart.setOption({
      color: COLORS,
      animationDuration: 450,
      tooltip: {
        trigger: "axis",
        formatter: chartTooltipFormatter
      },
      legend: {
        type: "scroll",
        data: series.map((s) => s.key),
        bottom: 0,
        itemWidth: 22,
        itemHeight: 4,
        textStyle: { color: "#4b5563" }
      },
      grid: { left: 54, right: 24, top: 28, bottom: 78, containLabel: true },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: months,
        axisLabel: { formatter: shortMonth, color: "#667085" },
        axisLine: { lineStyle: { color: "#dce4ef" } },
        axisTick: { show: false }
      },
      yAxis: {
        type: "value",
        name: "Mapped support records",
        nameTextStyle: { color: "#667085", align: "left" },
        axisLabel: { color: "#667085" },
        splitLine: { lineStyle: { color: "#e8eef6" } }
      },
      series: series.flatMap((s, idx) => {
        const color = COLORS[idx % COLORS.length];
        const forecast = forecastByKey.get(s.key);
        return [
          {
            name: s.key,
            type: "line",
            smooth: true,
            symbolSize: 6,
            lineStyle: { width: 3, color },
            itemStyle: { color },
            emphasis: { focus: "series" },
            data: months.map((month) => baseMonths.includes(month) ? (s.values.get(month) || 0) : null)
          },
          {
            name: `${s.key} projection`,
            type: "line",
            smooth: false,
            symbolSize: 6,
            lineStyle: { width: 3, type: "dashed", color, opacity: forecast ? 0.95 : 0 },
            itemStyle: { color, opacity: forecast ? 1 : 0 },
            emphasis: { focus: "series" },
            data: months.map((month) => {
              if (!forecast) return null;
              if (month === lastActualMonth) return { value: s.values.get(month) || 0, forecastStart: true };
              if (month === forecast.forecast_month) return { value: num(forecast.forecast_next_month), forecast: true };
              return null;
            })
          }
        ];
      })
    }, true);
  }

  function forecastForTimelineSeries(series) {
    return state.data.emerging.find((row) => series.ids.has(String(row.assigned_want_id)))
      || state.data.emerging.find((row) => series.titles.has(row.want_title))
      || null;
  }

  function timelineReadoutHtml(series, months, forecastByKey) {
    const total = series.reduce((sum, row) => sum + row.total, 0);
    const biggest = topBy(series, (row) => row.total);
    const latest = latestTimelineMove(series, months);
    const projection = timelineProjectionSignal(series, months.at(-1), forecastByKey);
    const cards = [
      {
        label: "Selected evidence",
        value: `${formatInt(total)} records`,
        detail: `${formatInt(series.length)} shown want${series.length === 1 ? "" : "s"}`
      },
      {
        label: "Largest selected line",
        value: biggest?.key || "-",
        detail: `${formatInt(biggest?.total || 0)} mapped records`
      },
      {
        label: "Latest movement",
        value: latest ? `${latest.delta > 0 ? "+" : ""}${formatInt(latest.delta)}` : "-",
        detail: latest ? `${latest.key}, ${shortMonth(latest.from)} to ${shortMonth(latest.to)}` : "Needs at least two complete months"
      },
      {
        label: "Projection signal",
        value: projection ? `${projection.delta > 0 ? "+" : ""}${formatFloat(projection.delta, 1)}` : "-",
        detail: projection ? `${projection.key}, projected ${formatFloat(projection.forecast, 1)} in ${shortMonth(projection.month)}` : "No projection for selected lines"
      }
    ];
    return cards.map((card) => `
      <article class="timeline-readout__card">
        <div class="timeline-readout__label">${escapeHtml(card.label)}</div>
        <div class="timeline-readout__value">${escapeHtml(card.value)}</div>
        <p>${escapeHtml(card.detail)}</p>
      </article>`).join("");
  }

  function latestTimelineMove(series, months) {
    if (months.length < 2) return null;
    const to = months.at(-1);
    const from = months.at(-2);
    return topBy(series.map((row) => ({
      key: row.key,
      from,
      to,
      delta: (row.values.get(to) || 0) - (row.values.get(from) || 0)
    })), (row) => row.delta);
  }

  function timelineProjectionSignal(series, lastActualMonth, forecastByKey) {
    const rows = series.map((row) => {
      const forecast = forecastByKey.get(row.key);
      if (!forecast) return null;
      const current = row.values.get(lastActualMonth) || 0;
      const projected = num(forecast.forecast_next_month);
      return {
        key: row.key,
        month: forecast.forecast_month,
        forecast: projected,
        delta: projected - current
      };
    }).filter(Boolean);
    return topBy(rows, (row) => Math.abs(row.delta));
  }

  function populateAuditControls() {
    const grouped = timelineSeries();
    const wants = [...state.selectedTimeline].filter((key) => grouped.has(key));
    const months = unique(timelineRows().map((row) => row.month)).sort();
    setOptions(byId("auditWant"), wants, (x) => x, byId("auditWant").value || wants[0]);
    setOptions(byId("auditMonth"), months, (x) => x, byId("auditMonth").value || months.at(-1));
  }

  const AUDIT_ROW_COLUMNS = [
    ["source_row", "Row"],
    ["date_raw", "Date"],
    ["uid", "UID"],
    ["category", "Category"],
    ["status_en", "Status"],
    ["display_want", "Want"],
    ["assignment_confidence", "Confidence"],
    ["question_flat", "Support text", "text-cell"]
  ];
  const AUDIT_USER_COLUMNS = [
    ["uid", "UID"],
    ["records", "Records"],
    ["latest_date", "Latest date"],
    ["latest_want", "Latest want"],
    ["latest_status", "Latest status"]
  ];

  function aggregateUniqueUsers(rows) {
    const map = new Map();
    for (const r of rows) {
      const uid = r.uid;
      if (!validUid(uid)) continue;
      const cur = map.get(uid);
      if (!cur) {
        map.set(uid, {
          uid,
          records: 1,
          latest_date: r.date_raw || "",
          latest_want: r.want_title || r.display_want || "",
          latest_status: r.status_en || ""
        });
      } else {
        cur.records += 1;
        if ((r.date_raw || "") > cur.latest_date) {
          cur.latest_date = r.date_raw || "";
          cur.latest_want = r.want_title || r.display_want || "";
          cur.latest_status = r.status_en || "";
        }
      }
    }
    return [...map.values()].sort((a, b) => b.records - a.records);
  }

  function renderAudit() {
    const want = byId("auditWant").value;
    const month = byId("auditMonth").value;
    const keyword = byId("auditKeyword").value.trim();
    const combine = byId("combineTitles").checked;
    const rows = state.data.assignments.filter((row) => {
      const key = combine ? row.want_title : row.display_want;
      return key === want && row.month_from_date === month;
    });
    const keywordRows = keyword
      ? state.data.assignments.filter((row) => row.month_from_date === month && (row.question_flat || "").toLowerCase().includes(keyword.toLowerCase()))
      : [];
    const allTimeRows = state.data.assignments.filter((row) => (combine ? row.want_title : row.display_want) === want);
    const uniqueUsers = aggregateUniqueUsers(rows);
    state.currentAuditRows = rows;
    state.auditViews = {
      semantic: {
        rows,
        columns: AUDIT_ROW_COLUMNS,
        caption: `${formatInt(rows.length)} records · ${escapeHtml(want)} in ${escapeHtml(month)}`
      },
      alltime: {
        rows: allTimeRows,
        columns: AUDIT_ROW_COLUMNS,
        caption: `${formatInt(allTimeRows.length)} records · ${escapeHtml(want)} across all months`
      },
      keyword: {
        rows: keywordRows,
        columns: AUDIT_ROW_COLUMNS,
        caption: keyword
          ? `${formatInt(keywordRows.length)} records contain "${escapeHtml(keyword)}" in ${escapeHtml(month)}`
          : `Type a keyword above to filter literal text matches in ${escapeHtml(month)}.`
      },
      unique: {
        rows: uniqueUsers,
        columns: AUDIT_USER_COLUMNS,
        caption: `${formatInt(uniqueUsers.length)} unique UIDs in ${escapeHtml(want)} · ${escapeHtml(month)}`
      }
    };
    const setNavValue = (id, value) => { const el = byId(id); if (el) el.textContent = formatInt(value); };
    setNavValue("auditSemanticCount", rows.length);
    setNavValue("auditAlltimeCount", allTimeRows.length);
    setNavValue("auditKeywordCount", keywordRows.length);
    setNavValue("auditUniqueCount", uniqueUsers.length);
    if (!state.auditView) state.auditView = "semantic";
    renderAuditView(state.auditView);
  }

  function renderAuditView(view) {
    state.auditView = view;
    const config = (state.auditViews || {})[view];
    if (!config) return;
    const caption = byId("auditCaption");
    if (caption) caption.innerHTML = config.caption;
    byId("auditTable").innerHTML = tableHtml(config.rows.slice(0, 200), config.columns);
    document.querySelectorAll("[data-audit-view]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.auditView === view);
    });
  }

  function setupNoBanFilters() {
    setOptions(byId("noBanCategory"), ["All", ...unique(state.noBanRows.map((row) => row.category).filter(Boolean)).sort()]);
    setOptions(byId("noBanStatus"), ["All", ...unique(state.noBanRows.map((row) => row.status_en).filter(Boolean)).sort()]);
    setOptions(byId("noBanWant"), ["All", ...unique(state.noBanRows.map((row) => row.want_title).filter(Boolean)).sort()]);
  }

  function renderNoBanTable() {
    const category = byId("noBanCategory").value;
    const status = byId("noBanStatus").value;
    const want = byId("noBanWant").value;
    const q = byId("noBanSearch").value.trim().toLowerCase();
    const rows = state.noBanRows.filter((row) => {
      if (category !== "All" && row.category !== category) return false;
      if (status !== "All" && row.status_en !== status) return false;
      if (want !== "All" && row.want_title !== want) return false;
      if (q && !(row.question_flat || "").toLowerCase().includes(q)) return false;
      return true;
    });
    state.currentNoBanRows = rows;
    byId("noBanTable").innerHTML = tableHtml(rows, [
      ["source_row", "Row"],
      ["date_raw", "Date"],
      ["uid", "UID"],
      ["category", "Category"],
      ["status_en", "Status"],
      ["want_title", "Mapped want"],
      ["question_flat", "No-ban context", "text-cell"]
    ]);
  }

  function renderJourneys() {
    const journeys = [...state.data.journeys].filter((row) => validUid(row.uid)).sort((a, b) => num(b.severity_score) - num(a.severity_score));
    const totalJourneyRecords = journeys.reduce((sum, row) => sum + num(row.records), 0);
    byId("journeyKpis").innerHTML = [
      ["Repeat users", formatInt(journeys.length), "UIDs with more than one record", "openJourneysQueue", "Open queue"],
      ["Records in journeys", formatInt(totalJourneyRecords), "Support records tied to repeat users", "openJourneysQueue", "Open queue"],
      ["Median active days", formatInt(median(journeys.map((row) => num(row.active_days)))), "Typical span from first to latest record", "openJourneysQueue", "Open queue"],
      ["Long-running cases", formatInt(journeys.filter((row) => num(row.active_days) >= 90).length), "UIDs active for 90+ days", "openJourneysLongRunning", "See long-running"]
    ].map(kpiHtml).join("");

    const archetypes = [...state.data.archetypes].sort((a, b) => num(b.users) - num(a.users));
    const maxUsers = Math.max(1, ...archetypes.map((row) => num(row.users)));
    byId("archetypeCards").innerHTML = `
      <ol class="archetype-rank" aria-label="User journey archetypes ranked by user count">
        ${archetypes.map((row, i) => {
          const name = titleCase(row.journey_pattern || "journey");
          const users = num(row.users);
          const pct = Math.max(3, (users / maxUsers) * 100);
          return `
            <li class="archetype-rank__row">
              <button class="archetype-rank__head" type="button" aria-expanded="false">
                <span class="archetype-rank__rank">${i + 1}</span>
                <span class="archetype-rank__name">${escapeHtml(name)}</span>
                <span class="archetype-rank__bar" aria-hidden="true">
                  <span class="archetype-rank__bar-fill" style="width:${pct}%"></span>
                </span>
                <span class="archetype-rank__count"><strong>${formatInt(users)}</strong> <em>users</em></span>
                <span class="archetype-rank__caret" aria-hidden="true">›</span>
              </button>
              <div class="archetype-rank__detail" hidden>
                <div class="archetype-rank__meta">${formatInt(row.records)} records · median ${formatFloat(row.median_records_per_user, 1)} per user</div>
                ${row.recommended_action ? `<p class="archetype-rank__note">${escapeHtml(row.recommended_action)}</p>` : ""}
              </div>
            </li>`;
        }).join("")}
      </ol>`;
    byId("archetypeCards").querySelectorAll(".archetype-rank__head").forEach((btn) => {
      btn.addEventListener("click", () => {
        const detail = btn.nextElementSibling;
        const willOpen = detail.hidden;
        detail.hidden = !willOpen;
        btn.setAttribute("aria-expanded", String(willOpen));
        btn.parentElement.classList.toggle("is-open", willOpen);
      });
    });
    state.currentJourneyRows = journeys;
    byId("journeyTable").innerHTML = tableHtml(journeys.slice(0, 120), [
      ["uid", "UID"],
      ["records", "Records"],
      ["active_days", "Active days"],
      ["unique_wants", "Wants"],
      ["failed_or_open_share", "Open/failed share"],
      ["latest_want", "Latest want"],
      ["top_wants", "Top wants", "text-cell"],
      ["recommended_action", "Pattern note", "text-cell"]
    ]);
    setOptions(byId("journeyUid"), journeys.slice(0, 220).map((row) => row.uid), (uid) => uid, byId("journeyUid").value || journeys[0]?.uid);
    renderJourneyDetail();
  }

  function renderJourneyDetail() {
    const uid = byId("journeyUid").value;
    const journey = state.data.journeys.find((row) => row.uid === uid);
    const events = state.data.events.filter((row) => row.uid === uid).sort((a, b) => num(a.event_index) - num(b.event_index));
    byId("journeySummary").innerHTML = journey ? `
      <div class="journey-summary">
        <div>
          <span class="mini-label">Selected UID</span>
          <strong>${escapeHtml(uid)}</strong>
        </div>
        <div class="journey-summary__stats">
          <span>${formatInt(journey.records)} records</span>
          <span>${formatInt(journey.active_days)} active days</span>
          <span>${formatInt(journey.unique_wants)} wants</span>
          <span>${formatPct(num(journey.failed_or_open_share || 0))} open/failed</span>
        </div>
        <div class="journey-summary__action">
          <span>What we see</span>
          <p>${escapeHtml(journey.recommended_action || "Multiple records on file.")}</p>
        </div>
        <div class="journey-summary__path">
          <span>Latest want</span>
          <strong>${escapeHtml(journey.latest_want || "-")}</strong>
        </div>
      </div>` : "Choose a UID.";
    byId("journeyEvents").innerHTML = `
      <div class="journey-events-note">
        Showing all ${formatInt(events.length)} records for this UID, oldest to newest.
      </div>
      ${tableHtml(events, [
      ["event_index", "#"],
      ["date", "Date"],
      ["want_title", "Want"],
      ["category", "Category"],
      ["status", "Status"],
      ["question", "Question / note", "text-cell"]
    ])}`;
  }

  function tableHtml(rows, columns) {
    if (!rows.length) return `<div class="empty">No rows match the current filters.</div>`;
    return `
      <table>
        <thead><tr>${columns.map(([, label]) => `<th>${escapeHtml(label)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `<tr>${columns.map(([key, , cls]) => `<td class="${cls || ""}">${formatCell(key, row[key])}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>`;
  }

  function formatCell(key, value) {
    if (value == null || value === "") return `<span class="muted">-</span>`;
    if (key.includes("share")) return escapeHtml(formatPct(num(value)));
    if (key.includes("confidence")) return escapeHtml(formatFloat(value, 3));
    return escapeHtml(String(value));
  }

  function kpiHtml([label, value, sub, action, openLabel]) {
    if (!action) {
      return `
        <div class="kpi">
          <div class="kpi__label">${escapeHtml(label)}</div>
          <div class="kpi__value">${value}</div>
          <div class="kpi__sub">${sub}</div>
        </div>`;
    }
    return `
      <button class="kpi kpi--clickable" type="button" data-action="${escapeAttr(action)}">
        <div class="kpi__label">${escapeHtml(label)}</div>
        <div class="kpi__value">${value}</div>
        <div class="kpi__sub">${sub}</div>
        <div class="kpi__open">${escapeHtml(openLabel || "Open")}<span aria-hidden="true">↗</span></div>
      </button>`;
  }

  function proofCardHtml(card) {
    if (!card.action) {
      return `
        <article class="proof-card">
          <div class="proof-card__label">${escapeHtml(card.label)}</div>
          <div class="proof-card__value">${escapeHtml(card.value)}</div>
          <p>${escapeHtml(card.detail)}</p>
        </article>`;
    }
    return `
      <button class="proof-card proof-card--clickable" type="button" data-action="${escapeAttr(card.action)}">
        <div class="proof-card__label">${escapeHtml(card.label)}</div>
        <div class="proof-card__value">${escapeHtml(card.value)}</div>
        <p>${escapeHtml(card.detail)}</p>
        <div class="proof-card__open">${escapeHtml(card.openLabel || "Open")}<span aria-hidden="true">↗</span></div>
      </button>`;
  }

  function summarizeWantsByTitle(rows) {
    const map = new Map();
    for (const row of rows) {
      const title = row.want_title || row.want_label || "Unknown want";
      const current = map.get(title) || { title, estimated: 0, confirmed: 0, clusters: 0 };
      current.estimated += num(row.estimated_tickets);
      current.confirmed += num(row.llm_confirmed_tickets);
      current.clusters += 1;
      map.set(title, current);
    }
    return [...map.values()];
  }

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let cell = "";
    let quote = false;
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      const next = text[i + 1];
      if (quote) {
        if (ch === '"' && next === '"') {
          cell += '"';
          i += 1;
        } else if (ch === '"') {
          quote = false;
        } else {
          cell += ch;
        }
      } else if (ch === '"') {
        quote = true;
      } else if (ch === ",") {
        row.push(cell);
        cell = "";
      } else if (ch === "\n") {
        row.push(cell);
        rows.push(row);
        row = [];
        cell = "";
      } else if (ch !== "\r") {
        cell += ch;
      }
    }
    if (cell.length || row.length) {
      row.push(cell);
      rows.push(row);
    }
    const header = rows.shift() || [];
    return rows.filter((r) => r.some((v) => v !== "")).map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
  }

  function completeMonths() {
    const longitudinal = state.data.longitudinalMeta || {};
    if (Array.isArray(longitudinal.complete_months)) return longitudinal.complete_months;
    const months = unique(state.data.trends.map((row) => row.month)).sort();
    return months.slice(0, -1);
  }

  function monthFromDate(raw) {
    const value = String(raw || "").trim();
    let m = value.match(/^(\d{4})-(\d{2})-\d{2}/);
    if (m) return `${m[1]}-${m[2]}`;
    m = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (m) return `${m[3]}-${String(m[2]).padStart(2, "0")}`;
    return "";
  }

  function dateSortValue(raw) {
    const value = String(raw || "").trim();
    let m = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    m = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (m) return Date.UTC(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
    return 0;
  }

  function normalizeUid(value) {
    return String(value || "").replace(/\D/g, "");
  }

  function noBanPattern() {
    return /\bno[\s_-]*ban\b/i;
  }

  function downloadRows(filename, rows) {
    if (!rows.length) {
      setHealth(`No rows to download for ${filename}.`, "bad");
      return;
    }
    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setHealth(`Downloaded ${formatInt(rows.length)} rows to ${filename}.`, "ok");
  }

  function toCsv(rows) {
    const headers = Object.keys(rows[0]);
    const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    return [headers.map(quote).join(","), ...rows.map((row) => headers.map((h) => quote(row[h])).join(","))].join("\n");
  }

  function rowsForExport(rows) {
    return rows.map((row) => Object.fromEntries(
      Object.entries(row).filter(([key]) => !personAttributionKey(key))
    ));
  }

  function personAttributionKey(key) {
    return PERSON_ATTRIBUTION_COLUMNS.has(String(key || "").trim().toLowerCase());
  }

  function setOptions(select, values, labeler = (x) => x, selected = null) {
    const existing = selected ?? select.value;
    select.innerHTML = values.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(labeler(value))}</option>`).join("");
    if (values.includes(existing)) select.value = existing;
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setHealth(message, status) {
    const el = byId("dataHealth");
    el.textContent = message;
    el.classList.remove("is-ok", "is-bad");
    if (status) el.classList.add(`is-${status}`);
  }

  function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function unique(values) {
    return [...new Set(values.filter((v) => v !== null && v !== undefined && v !== ""))];
  }

  function groupCount(rows, keyFn) {
    const map = new Map();
    for (const row of rows) {
      const key = keyFn(row);
      map.set(key, (map.get(key) || 0) + 1);
    }
    return map;
  }

  function topBy(rows, valueFn) {
    return rows.reduce((best, row) => (best == null || valueFn(row) > valueFn(best) ? row : best), null);
  }

  function chartLibraryReady() {
    return typeof window.echarts !== "undefined";
  }

  function chartTooltipFormatter(params) {
    const items = (Array.isArray(params) ? params : [params]).filter(chartTooltipHasValue);
    if (!items.length) return "";
    const title = shortMonth(items[0].axisValue || items[0].name || "");
    const rows = items.map((item) => {
      const value = Number(chartParamValue(item));
      const projected = String(item.seriesName || "").endsWith(" projection");
      const name = String(item.seriesName || "").replace(/ projection$/, "");
      const formatted = Number.isInteger(value) ? formatInt(value) : formatFloat(value, 1);
      return `
        <div class="chart-tooltip__row">
          ${item.marker || ""}
          <span>${escapeHtml(projected ? `${name} forecast` : name)}</span>
          <strong>${formatted}</strong>
        </div>`;
    }).join("");
    return `<div class="chart-tooltip"><div class="chart-tooltip__title">${escapeHtml(title)}</div>${rows}</div>`;
  }

  function chartTooltipHasValue(item) {
    const value = chartParamValue(item);
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  }

  function chartParamValue(item) {
    if (item?.data && typeof item.data === "object" && item.data.forecastStart) return null;
    if (item?.data && typeof item.data === "object" && "value" in item.data) return item.data.value;
    return Array.isArray(item?.value) ? item.value.at(-1) : item?.value;
  }

  function visibleBox(el) {
    return Boolean(el && el.offsetWidth > 0 && el.offsetHeight > 0);
  }

  function disposeChart(name) {
    const chart = state.charts[name];
    if (chart) chart.dispose();
    delete state.charts[name];
  }

  function resizeCharts() {
    Object.values(state.charts).forEach((chart) => chart?.resize?.());
  }

  function forecastLabel(row, rows) {
    const duplicates = duplicateValues(rows.map((item) => item.want_title));
    return duplicates.has(row.want_title) ? `${row.want_title} · ${row.assigned_want_id}` : row.want_title;
  }

  function duplicateValues(values) {
    const counts = groupCount(values, (value) => value || "");
    return new Set([...counts.entries()].filter(([value, count]) => value && count > 1).map(([value]) => value));
  }

  function validUid(uid) {
    return uid && uid !== "-" && uid !== "nan" && uid !== "None";
  }

  function confirmedRows() {
    return state.data.summary.reduce((sum, row) => sum + num(row.llm_confirmed_tickets), 0);
  }

  function basename(path) {
    return String(path).split(/[\\/]/).filter(Boolean).at(-1) || path;
  }

  function formatInt(value) {
    return new Intl.NumberFormat("en-US").format(num(value));
  }

  function formatFloat(value, digits = 1) {
    return num(value).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
  }

  function formatPct(value) {
    return `${formatFloat(value * 100, 1)}%`;
  }

  function median(values) {
    const clean = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
    if (!clean.length) return 0;
    const mid = Math.floor(clean.length / 2);
    return clean.length % 2 ? clean[mid] : (clean[mid - 1] + clean[mid]) / 2;
  }

  function formatDateTime(value) {
    if (!value) return "unknown";
    return String(value).replace("T", " ").replace("+00:00", " UTC");
  }

  function shortMonth(month) {
    const [year, m] = String(month).split("-");
    const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${names[Number(m) - 1] || m} ${year}`;
  }

  function nextMonth(month) {
    const [year, m] = String(month || "").split("-").map(Number);
    if (!year || !m) return "";
    const date = new Date(Date.UTC(year, m, 1));
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  }

  function niceMax(max) {
    const pow = Math.pow(10, Math.floor(Math.log10(max)));
    const step = max / pow;
    if (step <= 2) return 2 * pow;
    if (step <= 5) return 5 * pow;
    return 10 * pow;
  }

  function titleCase(value) {
    return String(value).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("`", "&#096;");
  }

  function debounce(fn, delay) {
    let timer = null;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), delay);
    };
  }
})();
