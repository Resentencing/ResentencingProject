document.addEventListener("DOMContentLoaded", () => {
  const visualizationButtons = document.querySelectorAll(".visualization-button");
  const visualizationButtonRow = visualizationButtons.length > 0 ? visualizationButtons[0].parentElement : null;
  const loadingMessage = document.getElementById("loadingMessage");
  const chartCanvas = document.getElementById("publicDashboardChart");
  const fallbackImage = document.getElementById("visualizationImage");

  let dashboardChart = null;
  let professorChart = null;

  function setLoading(isLoading) {
    if (!loadingMessage) return;
    if (isLoading) {
      loadingMessage.textContent = "Loading...";
      loadingMessage.style.display = "block";
      return;
    }
    if ((loadingMessage.textContent || "").trim() === "Loading...") {
      loadingMessage.style.display = "none";
    }
  }

  function formatNumber(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? n.toLocaleString() : "--";
  }

  function formatMetric(value, measurementLabel = "Value") {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return "--";
    if (measurementLabel.toLowerCase().includes("years")) {
      return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })} years`;
    }
    if (Math.abs(n) % 1 !== 0) {
      return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return n.toLocaleString();
  }

  // Modern, widely used qualitative palette (Tableau-style)
  const CATEGORICAL_PALETTE = [
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
  ];

  // Keep single-series charts clean and consistent.
  const SINGLE_SERIES_COLOR = "rgba(59, 130, 246, 0.85)";

  function buildCategoryColors(length, alpha = 0.86) {
    const toRgba = (hex, a) => {
      const c = hex.replace("#", "");
      const n = parseInt(c, 16);
      const r = (n >> 16) & 255;
      const g = (n >> 8) & 255;
      const b = n & 255;
      return `rgba(${r}, ${g}, ${b}, ${a})`;
    };
    const colors = [];
    for (let i = 0; i < length; i += 1) {
      colors.push(toRgba(CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length], alpha));
    }
    return colors;
  }

  function ensurePosterBadgeContainer() {
    if (!chartCanvas) return null;
    const canvasWrap = chartCanvas.closest(".rad-chart-canvas-wrap");
    if (!canvasWrap || !canvasWrap.parentElement) return null;

    let badges = document.getElementById("poster-impact-badges");
    if (!badges) {
      badges = document.createElement("div");
      badges.id = "poster-impact-badges";
      badges.className = "rad-poster-badges";
      canvasWrap.parentElement.insertBefore(badges, canvasWrap);
    }
    return badges;
  }

  function setPosterImpactBadges(impact, visible) {
    const badges = ensurePosterBadgeContainer();
    if (!badges) return;
    if (!visible) {
      badges.style.display = "none";
      badges.innerHTML = "";
      return;
    }

    const avgYears = Number(impact?.avg_years_reduced_success || 0);
    const totalYears = Number(impact?.total_years_reduced_success || 0);
    const successRate = Number(impact?.success_rate_from_all_letters || 0);
    badges.innerHTML = `
      <span class="rad-poster-badge">Avg years reduced (favorable): ${avgYears.toFixed(2)}</span>
      <span class="rad-poster-badge">Total years reduced (favorable): ${formatNumber(totalYears)}</span>
      <span class="rad-poster-badge">Favorable rate vs. considered: ${successRate.toFixed(1)}%</span>
    `;
    badges.style.display = "flex";
  }

  function ensurePosterExitButton() {
    if (!visualizationButtonRow) return null;
    let exitBtn = visualizationButtonRow.querySelector(".poster-exit-btn");
    if (!exitBtn) {
      exitBtn = document.createElement("button");
      exitBtn.type = "button";
      exitBtn.className = "visualization-button poster-exit-btn";
      exitBtn.textContent = "Show all charts";
      exitBtn.style.display = "none";
      exitBtn.addEventListener("click", () => {
        visualizationButtonRow.classList.remove("poster-focus-mode");
        exitBtn.style.display = "none";
      });
      visualizationButtonRow.appendChild(exitBtn);
    }
    return exitBtn;
  }

  function formatFreshnessDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  }

  function escFreshnessHint(s) {
    if (s == null || String(s).trim() === "") return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderSummaryCards(summary) {
    const statLetters = document.getElementById("stat-total-letters");
    const statIndividuals = document.getElementById("stat-total-individuals");
    const statCounties = document.getElementById("stat-total-counties");
    if (!statLetters || !statIndividuals || !statCounties) return;

    statLetters.textContent = formatNumber(summary?.total_letters || 0);
    statIndividuals.textContent = formatNumber(summary?.total_individuals || 0);
    statCounties.textContent = formatNumber(summary?.total_counties || 0);

    const logCoverageEl = document.getElementById("rad-log-coverage");
    const logCoverageBody = document.getElementById("rad-log-coverage-body");
    if (logCoverageEl && logCoverageBody) {
      const logTotal   = summary?.log_total   ?? 0;
      const logMatched = summary?.log_matched  ?? null;  // exact reconcile count
      const logMissing = summary?.log_missing  ?? null;
      const dbLetters  = summary?.total_letters ?? 0;
      // Only show reconcile numbers when the log looks like a real full log (> 10 rows).
      const logLooksReal = logTotal > 10;
      let coverageHtml = "";
      if (logLooksReal && logMatched !== null && logMissing !== null) {
        coverageHtml =
          `<strong>1170(d) log coverage:</strong> ` +
          `${dbLetters.toLocaleString()} letters in our database · ` +
          `CDCR tracking log shows ${logTotal.toLocaleString()} generated · ` +
          `${logMatched.toLocaleString()} matched` +
          (logMissing > 0
            ? ` · <strong>${logMissing.toLocaleString()} still pending</strong> — requested from CDCR, will be added as received`
            : " · all log entries matched");
      } else if (dbLetters > 0) {
        coverageHtml =
          `<strong>Letter coverage:</strong> ${dbLetters.toLocaleString()} letters in our database · ` +
          `additional letters have been requested from CDCR and will be added as they are received`;
      }
      if (coverageHtml) {
        logCoverageBody.innerHTML = coverageHtml;
        logCoverageEl.style.display = "";
      }
    }

    const freshBody = document.getElementById("rad-data-freshness-body");
    if (freshBody) {
      const f = summary?.data_freshness || {};
      const logD = formatFreshnessDate(f.main_log?.as_of);
      const raceD = formatFreshnessDate(f.race_data?.as_of);
      const lettersD = formatFreshnessDate(f.letters_db?.as_of);
      const logHint = f.main_log?.source_file ? ` <span class="rad-data-freshness__hint">(${escFreshnessHint(f.main_log.source_file)})</span>` : "";
      const raceHint = f.race_data?.source_file ? ` <span class="rad-data-freshness__hint">(${escFreshnessHint(f.race_data.source_file)})</span>` : "";
      const lettersHint = f.letters_db?.source_file ? ` <span class="rad-data-freshness__hint">(${escFreshnessHint(f.letters_db.source_file)})</span>` : "";
      const any = f.main_log?.as_of || f.race_data?.as_of || f.letters_db?.as_of;
      if (!any) {
        freshBody.innerHTML =
          "Set <code>PUBLIC_FRESHNESS_*</code> in <code>.env</code> for interim dates, or upload the 1170(d) log, race spreadsheet, and run a letter database sync on the backend—then timestamps come from the database automatically.";
      } else {
        freshBody.innerHTML = [
          `<strong>1170(d) tracking log</strong> (spreadsheet) as of ${logD}${logHint}`,
          `<strong>Race / ethnicity data</strong> (spreadsheet) as of ${raceD}${raceHint}`,
          `<strong>Letter database</strong> last synced ${lettersD}${lettersHint}`,
        ].join("; ");
      }
    }
  }

  async function fetchDashboardSummary() {
    const response = await fetch("/api/public_summary");
    if (!response.ok) {
      throw new Error(`Failed to load summary metrics: ${response.status}`);
    }
    return response.json();
  }

  async function fetchDataset(dataset) {
    const response = await fetch(`/api/stats?dataset=${encodeURIComponent(dataset)}`);
    if (!response.ok) {
      throw new Error(`Failed to load ${dataset}: ${response.status}`);
    }
    const payload = await response.json();
    return payload.data || [];
  }

  async function fetchPosterView() {
    const response = await fetch("/api/poster_view");
    if (!response.ok) {
      throw new Error(`Failed to load poster view: ${response.status}`);
    }
    return response.json();
  }

  async function fetchProfessorVariables() {
    const response = await fetch("/api/prof/variables");
    if (!response.ok) {
      throw new Error(`Failed to load variable list: ${response.status}`);
    }
    const payload = await response.json();
    return payload.variables || [];
  }

  async function fetchProfessorValueOptions(field, mode, filters) {
    const params = new URLSearchParams({
      field,
      mode,
      limit: "300",
    });
    if (filters && Object.keys(filters).length > 0) {
      params.set("filters", JSON.stringify(filters));
    }
    const response = await fetch(`/api/prof/value_options?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Failed to load value options: ${response.status}`);
    }
    return response.json();
  }

  async function fetchProfessorReport({
    xField,
    seriesField,
    xMode,
    seriesMode,
    measurement,
    topX,
    topSeries,
    filters,
  }) {
    const params = new URLSearchParams({
      x_field: xField,
      series_field: seriesField,
      x_mode: xMode,
      series_mode: seriesMode,
      measurement,
      top_x: String(topX),
      top_series: String(topSeries),
    });
    if (filters && Object.keys(filters).length > 0) {
      params.set("filters", JSON.stringify(filters));
    }
    const response = await fetch(`/api/prof/report?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Failed to load report data: ${response.status}`);
    }
    return response.json();
  }

  function aggregateYearsReduced(rows) {
    const totals = {};
    rows.forEach((row) => {
      const county = (row.county || "Unknown").toString().trim() || "Unknown";
      const years = Number(row.years_reduced) || 0;
      totals[county] = (totals[county] || 0) + years;
    });

    return Object.entries(totals)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);
  }

  function aggregateLettersByCounty(rows) {
    const counts = {};
    rows.forEach((row) => {
      const county = (row.county || "Unknown").toString().trim() || "Unknown";
      counts[county] = (counts[county] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);
  }

  function aggregateSentenceTypes(rows) {
    const counts = {};
    rows.forEach((row) => {
      const key = (row.isl_dsl || "Unknown").toString().trim() || "Unknown";
      counts[key] = (counts[key] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }

  function aggregateCategoryCounts(rows, key, topN = 20) {
    const counts = {};
    rows.forEach((row) => {
      const v = (row?.[key] || "Unknown").toString().trim() || "Unknown";
      counts[v] = (counts[v] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, topN);
  }

  function isSuccessfulAction(actionTaken) {
    const v = (actionTaken || "").toString().toLowerCase();
    return (
      v.includes("resentenced") ||
      v.includes("released") ||
      v.includes("grant") ||
      v.includes("approved") ||
      v.includes("recalled")
    );
  }

  function aggregateOutcomeByField(rows, fieldKey, topN = 12) {
    const grouped = {};
    rows.forEach((row) => {
      const fieldValue = (row?.[fieldKey] || "Unknown").toString().trim() || "Unknown";
      const status = isSuccessfulAction(row?.action_taken) ? "Favorable outcome" : "Other / unknown";
      if (!grouped[fieldValue]) {
        grouped[fieldValue] = { "Favorable outcome": 0, "Other / unknown": 0, Total: 0 };
      }
      grouped[fieldValue][status] += 1;
      grouped[fieldValue].Total += 1;
    });

    const sorted = Object.entries(grouped)
      .sort((a, b) => b[1].Total - a[1].Total)
      .slice(0, topN);

    return {
      labels: sorted.map(([k]) => k),
      successful: sorted.map(([, v]) => v["Favorable outcome"]),
      other: sorted.map(([, v]) => v["Other / unknown"]),
    };
  }

  function aggregateParoleYears(rows) {
    const counts = {};
    rows.forEach((row) => {
      const raw = (row.parole_eligibility_date || "").toString().trim();
      if (!raw) return;
      const m = raw.match(/^(\d{4})/);
      if (!m) return;
      const year = m[1];
      counts[year] = (counts[year] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => Number(a[0]) - Number(b[0]));
  }

  function drawChart(dataset, rows) {
    if (!chartCanvas || typeof Chart === "undefined") return;
    setPosterImpactBadges(null, false);

    const ctx = chartCanvas.getContext("2d");
    if (dashboardChart) {
      dashboardChart.destroy();
    }

    let labels = [];
    let data = [];
    let datasets = [];
    let chartType = "bar";
    let chartLabel = "";
    let horizontal = false;
    let stacked = false;

    if (dataset === "poster_view") {
      const stages = rows?.stages || [];
      const impact = rows?.impact || {};
      labels = stages.map((s) => s.label || "");
      const counts = stages.map((s) => Number(s.value || 0));
      const rates = stages.map((s) => Number(s.rate_from_start || 0));

      if (!labels.length || !counts.some((v) => v > 0)) {
        if (loadingMessage) {
          loadingMessage.style.display = "block";
          loadingMessage.textContent = "No data available for this chart.";
        }
        return;
      }

      setPosterImpactBadges(impact, true);

      const posterBarValueLabelsPlugin = {
        id: "posterBarValueLabels",
        afterDatasetsDraw(chart) {
          const barMeta = chart.getDatasetMeta(0);
          const ctx2 = chart.ctx;
          ctx2.save();
          ctx2.fillStyle = "#1f2937";
          ctx2.font = "600 12px 'Source Sans 3', sans-serif";
          ctx2.textAlign = "center";
          ctx2.textBaseline = "bottom";
          barMeta.data.forEach((barElement, idx) => {
            const value = Number(chart.data.datasets[0].data[idx] || 0);
            const pos = barElement.tooltipPosition();
            ctx2.fillText(formatNumber(value), pos.x, pos.y - 6);
          });
          ctx2.restore();
        },
      };

      dashboardChart = new Chart(ctx, {
        plugins: [posterBarValueLabelsPlugin],
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "Records",
              data: counts,
              backgroundColor: ["rgba(59, 130, 246, 0.9)", "rgba(14, 165, 233, 0.88)", "rgba(16, 185, 129, 0.88)"],
              borderColor: "#ffffff",
              borderWidth: 1,
              borderRadius: 8,
              yAxisID: "y",
            },
            {
              type: "line",
              label: "Rate from Start (%)",
              data: rates,
              borderColor: "rgba(239, 68, 68, 0.95)",
              backgroundColor: "rgba(239, 68, 68, 0.15)",
              pointBackgroundColor: "rgba(239, 68, 68, 1)",
              pointRadius: 6,
              pointHoverRadius: 7,
              borderWidth: 3,
              tension: 0.25,
              yAxisID: "y1",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: "index",
            intersect: false,
          },
          scales: {
            y: {
              beginAtZero: true,
              grace: "8%",
              ticks: {
                callback: (value) => formatNumber(value),
              },
              title: {
                display: true,
                text: "Record count",
              },
            },
            y1: {
              beginAtZero: true,
              max: 100,
              position: "right",
              grid: {
                drawOnChartArea: false,
              },
              ticks: {
                callback: (value) => `${value}%`,
              },
              title: {
                display: true,
                text: "Rate From Start",
              },
            },
          },
          plugins: {
            title: {
              display: true,
              text: "Case progression: considered → letters sent → resentenced",
              color: "#152a45",
              font: { size: 18, weight: "700" },
              padding: { top: 8, bottom: 6 },
            },
            subtitle: {
              display: true,
              text: "Counts are from the letter metadata table; expand “How metrics are defined” above.",
              color: "#4b5563",
              font: { size: 12, weight: "400" },
              padding: { bottom: 12 },
            },
            legend: {
              display: true,
              position: "bottom",
            },
            tooltip: {
              callbacks: {
                afterTitle: (items) => {
                  const idx = items[0]?.dataIndex;
                  const def = stages[idx]?.definition;
                  return def ? def : "";
                },
                label: (ctx) => {
                  if (ctx.dataset.yAxisID === "y1") {
                    return `${ctx.dataset.label}: ${Number(ctx.parsed.y || 0).toFixed(1)}%`;
                  }
                  return `${ctx.dataset.label}: ${formatNumber(ctx.parsed.y || 0)}`;
                },
              },
            },
          },
        },
      });
      return;
    }

    if (dataset === "letters_by_county") {
      const aggregated = aggregateLettersByCounty(rows);
      labels = aggregated.map((entry) => entry[0]);
      data = aggregated.map((entry) => entry[1]);
      chartLabel = "Letters";
      chartType = "bar";
      horizontal = true;
    } else if (dataset === "years_reduced") {
      const aggregated = aggregateYearsReduced(rows);
      labels = aggregated.map((entry) => entry[0]);
      data = aggregated.map((entry) => Number(entry[1].toFixed(2)));
      chartLabel = "Total Years Reduced";
      chartType = "bar";
      horizontal = true;
    } else if (dataset === "sentence_type") {
      const aggregated = aggregateSentenceTypes(rows);
      labels = aggregated.map((entry) => entry[0]);
      data = aggregated.map((entry) => entry[1]);
      chartLabel = "Records";
      chartType = "doughnut";
    } else if (dataset === "parole_eligibility") {
      const aggregated = aggregateParoleYears(rows);
      labels = aggregated.map((entry) => entry[0]);
      data = aggregated.map((entry) => entry[1]);
      chartLabel = "Count by Year";
      chartType = "bar";
      horizontal = false;
    } else if (dataset === "action_taken") {
      const aggregated = aggregateCategoryCounts(rows, "action_taken", 20);
      labels = aggregated.map((entry) => entry[0]);
      data = aggregated.map((entry) => entry[1]);
      chartLabel = "Cases";
      chartType = "bar";
      horizontal = true;
    } else if (dataset === "race_distribution") {
      const outcome = aggregateOutcomeByField(rows, "race", 12);
      labels = outcome.labels;
      chartType = "bar";
      horizontal = true;
      stacked = true;
      datasets = [
        {
          label: "Favorable outcome",
          data: outcome.successful,
          backgroundColor: "rgba(16, 185, 129, 0.88)",
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: "Other / unknown",
          data: outcome.other,
          backgroundColor: "rgba(148, 163, 184, 0.95)",
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3,
        },
      ];
    } else if (dataset === "ethnicity_distribution") {
      const outcome = aggregateOutcomeByField(rows, "ethnicity", 12);
      labels = outcome.labels;
      chartType = "bar";
      horizontal = true;
      stacked = true;
      datasets = [
        {
          label: "Favorable outcome",
          data: outcome.successful,
          backgroundColor: "rgba(16, 185, 129, 0.88)",
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: "Other / unknown",
          data: outcome.other,
          backgroundColor: "rgba(148, 163, 184, 0.95)",
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3,
        },
      ];
    } else if (dataset === "isl_dsl_outcome") {
      const outcome = aggregateOutcomeByField(rows, "isl_dsl", 6);
      labels = outcome.labels;
      chartType = "bar";
      horizontal = false;
      stacked = true;
      datasets = [
        {
          label: "Favorable outcome",
          data: outcome.successful,
          backgroundColor: "rgba(16, 185, 129, 0.88)",
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: "Other / unknown",
          data: outcome.other,
          backgroundColor: "rgba(148, 163, 184, 0.95)",
          borderColor: "#ffffff",
          borderWidth: 1,
          borderRadius: 3,
        },
      ];
    }

    if (!datasets.length) {
      const fallbackColors = buildCategoryColors(labels.length);
      datasets = [
        {
          label: chartLabel,
          data,
          backgroundColor:
            chartType === "doughnut"
              ? fallbackColors
              : SINGLE_SERIES_COLOR,
          borderColor: chartType === "doughnut" ? "#ffffff" : "rgba(21, 42, 69, 1)",
          borderWidth: 1,
          borderRadius: chartType === "bar" ? 5 : 0,
        },
      ];
    }

    const hasData = datasets.some((d) => (d.data || []).some((v) => Number(v || 0) > 0));
    if (!labels.length || !hasData) {
      if (loadingMessage) {
        loadingMessage.style.display = "block";
        loadingMessage.textContent = "No data available for this chart.";
      }
      return;
    }

    dashboardChart = new Chart(ctx, {
      type: chartType,
      data: {
        labels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? "y" : "x",
        interaction: {
          mode: "index",
          intersect: false,
        },
        scales:
          chartType === "doughnut"
            ? undefined
            : {
                x: {
                  stacked,
                  ticks: {
                    callback: function (value) {
                      if (horizontal) return formatNumber(value);
                      return this.getLabelForValue ? this.getLabelForValue(value) : String(value);
                    },
                  },
                },
                y: {
                  stacked,
                  ticks: {
                    callback: function (value) {
                      if (!horizontal) return formatNumber(value);
                      return this.getLabelForValue ? this.getLabelForValue(value) : String(value);
                    },
                  },
                },
              },
        plugins: {
          title: {
            display: true,
            text:
              dataset === "letters_by_county"
                ? "Letter records by county"
                : dataset === "years_reduced"
                ? "Sum of years reduced by county (non-null values)"
                : dataset === "sentence_type"
                ? "ISL vs DSL (sentence type)"
                : dataset === "parole_eligibility"
                ? "Parole eligibility year (recorded dates)"
                : dataset === "action_taken"
                ? "Outcomes (action taken, top categories)"
                : dataset === "race_distribution"
                ? "Race × outcome (favorable vs. other / unknown)"
                : dataset === "ethnicity_distribution"
                ? "Ethnicity × outcome (favorable vs. other / unknown)"
                : "ISL/DSL × outcome",
            color: "#152a45",
            font: { size: 14, weight: "600" },
            padding: { top: 4, bottom: 10 },
          },
          legend: {
            display: chartType === "doughnut" || datasets.length > 1,
            position: "bottom",
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed?.x ?? ctx.parsed?.y ?? ctx.parsed ?? 0;
                return `${ctx.dataset.label}: ${formatMetric(v, ctx.dataset.label || chartLabel)}`;
              },
            },
          },
        },
      },
    });
  }

  function destroyProfessorChart() {
    if (professorChart) {
      professorChart.destroy();
      professorChart = null;
    }
  }

  function drawProfessorChart(payload, chartKind) {
    const canvas = document.getElementById("professorExplorerChart");
    if (!canvas || typeof Chart === "undefined") return;
    const ctx = canvas.getContext("2d");
    destroyProfessorChart();

    const labels = payload.x_labels || [];
    const palette = [
      "#2563EB",
      "#0EA5E9",
      "#14B8A6",
      "#22C55E",
      "#84CC16",
      "#F59E0B",
      "#F97316",
      "#EF4444",
      "#D946EF",
      "#8B5CF6",
      "#6366F1",
      "#64748B",
    ];

    const rawSeries = payload.series || [];
    const normalized = chartKind === "stacked_bar_100" || chartKind === "stacked_column_100";
    const xTotals = labels.map((_, xIdx) =>
      rawSeries.reduce((sum, s) => sum + Number((s.data || [])[xIdx] || 0), 0)
    );

    const datasets = rawSeries.map((series, idx) => {
      const rawData = (series.data || []).map((v) => Number(v || 0));
      const plotData = normalized
        ? rawData.map((v, xIdx) => {
            const total = xTotals[xIdx] || 0;
            return total > 0 ? Number(((v / total) * 100).toFixed(2)) : 0;
          })
        : rawData;
      return {
      label: series.series,
      data: plotData,
      rawData,
      backgroundColor: palette[idx % palette.length],
      borderColor: "#ffffff",
      borderWidth: 1,
      borderRadius: chartKind === "grouped_column" ? 4 : 0,
      };
    });

    let type = "bar";
    let indexAxis = "y";
    let stacked = true;
    if (chartKind === "stacked_column" || chartKind === "stacked_column_100") {
      type = "bar";
      indexAxis = "x";
      stacked = true;
    } else if (chartKind === "grouped_column") {
      type = "bar";
      indexAxis = "x";
      stacked = false;
    } else {
      type = "bar";
      indexAxis = "y";
      stacked = true;
    }

    professorChart = new Chart(ctx, {
      type,
      data: {
        labels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis,
        interaction: {
          mode: "index",
          intersect: false,
        },
        scales: {
          x: {
            stacked,
            min: normalized && indexAxis === "x" ? 0 : undefined,
            max: normalized && indexAxis === "x" ? 100 : undefined,
            ticks: {
              callback: function (value) {
                if (indexAxis === "x") {
                  if (normalized) return `${value}%`;
                  return formatNumber(value);
                }
                return this.getLabelForValue ? this.getLabelForValue(value) : String(value);
              },
            },
          },
          y: {
            stacked,
            min: normalized && indexAxis === "y" ? 0 : undefined,
            max: normalized && indexAxis === "y" ? 100 : undefined,
            ticks: {
              callback: function (value) {
                if (indexAxis === "y") {
                  if (normalized) return `${value}%`;
                  return formatNumber(value);
                }
                return this.getLabelForValue ? this.getLabelForValue(value) : String(value);
              },
            },
          },
        },
        plugins: {
          title: {
            display: true,
            text: `${payload.x_label || "Category"} by ${payload.series_label || "Series"} (${payload.measurement_label || "Number of cases"})`,
            color: "#152a45",
            font: { size: 14, weight: "600" },
            padding: { top: 4, bottom: 10 },
          },
          legend: {
            display: true,
            position: "bottom",
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const dataset = ctx.dataset || {};
                const raw = Number((dataset.rawData || [])[ctx.dataIndex] || 0);
                const plotted = Number(ctx.parsed?.x ?? ctx.parsed?.y ?? ctx.parsed ?? 0);
                if (normalized) {
                  return `${dataset.label}: ${plotted.toFixed(1)}% (${formatMetric(raw, payload.measurement_label || "Number of cases")})`;
                }
                return `${dataset.label}: ${formatMetric(plotted, payload.measurement_label || "Number of cases")}`;
              },
            },
          },
        },
      },
    });
  }

  async function initializeProfessorExplorer() {
    const xVariableSelect = document.getElementById("prof-x-variable-select");
    const seriesVariableSelect = document.getElementById("prof-series-variable-select");
    const yearFilterSelect = document.getElementById("prof-year-filter-select");
    const countyFilterSelect = document.getElementById("prof-county-filter-select");
    const eventFilterSelect = document.getElementById("prof-event-filter-select");
    const raceFilterSelect = document.getElementById("prof-race-filter-select");
    const offenseFilterSelect = document.getElementById("prof-offense-filter-select");
    const measurementSelect = document.getElementById("prof-measurement-select");
    const topXSelect = document.getElementById("prof-topx-select");
    const chartTypeSelect = document.getElementById("prof-chart-type-select");
    const refreshBtn = document.getElementById("prof-refresh-btn");
    const loadingEl = document.getElementById("prof-loading-message");
    const metaField = document.getElementById("prof-meta-field");
    const metaMode = document.getElementById("prof-meta-mode");

    if (
      !xVariableSelect ||
      !seriesVariableSelect ||
      !yearFilterSelect ||
      !countyFilterSelect ||
      !eventFilterSelect ||
      !raceFilterSelect ||
      !offenseFilterSelect ||
      !measurementSelect ||
      !topXSelect ||
      !chartTypeSelect ||
      !refreshBtn
    ) {
      return;
    }

    const setProfLoading = (isLoading) => {
      if (!loadingEl) return;
      loadingEl.style.display = isLoading ? "block" : "none";
    };

    const toLabelMap = {};

    const pickField = (variables, candidates) => {
      const keys = new Set(variables.map((v) => v.key));
      return candidates.find((c) => keys.has(c)) || "";
    };

    const getMultiSelectedValues = (el) =>
      Array.from(el.selectedOptions || [])
        .map((opt) => (opt.value || "").trim())
        .filter(Boolean);

    const setMultiOptions = (el, options, selectedValues = []) => {
      if (!el) return;
      const selected = new Set(selectedValues);
      el.innerHTML = "";
      options.forEach((item) => {
        const opt = document.createElement("option");
        opt.value = item.value;
        opt.textContent = `${item.label} (${Number(item.count || 0).toLocaleString()})`;
        if (selected.has(item.value)) {
          opt.selected = true;
        }
        el.appendChild(opt);
      });
    };

    const fieldMap = {
      year: "",
      county: "",
      event: "",
      race: "",
      offense: "",
    };

    try {
      setProfLoading(true);
      const variables = await fetchProfessorVariables();
      variables.forEach((v) => {
        toLabelMap[v.key] = v.label || v.key;
      });

      xVariableSelect.innerHTML = "";
      seriesVariableSelect.innerHTML = "";
      variables.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.key;
        opt.textContent = v.label;
        xVariableSelect.appendChild(opt);

        const optSeries = document.createElement("option");
        optSeries.value = v.key;
        optSeries.textContent = v.label;
        seriesVariableSelect.appendChild(optSeries);
      });

      fieldMap.year = pickField(variables, ["sentence_date", "parole_eligibility_date", "hearing_date"]);
      fieldMap.county = pickField(variables, ["county"]);
      fieldMap.event = pickField(variables, ["action_taken", "sec_decision", "event_point"]);
      fieldMap.race = pickField(variables, ["race", "ethnicity"]);
      fieldMap.offense = pickField(variables, ["offense", "isl_dsl", "commitment_offense"]);

      if (fieldMap.county) xVariableSelect.value = fieldMap.county;
      if (fieldMap.race) seriesVariableSelect.value = fieldMap.race;

      const baseFilters = {};
      if (fieldMap.year) {
        const yearPayload = await fetchProfessorValueOptions(fieldMap.year, "year", baseFilters);
        setMultiOptions(yearFilterSelect, yearPayload.options || []);
      }
      if (fieldMap.county) {
        const countyPayload = await fetchProfessorValueOptions(fieldMap.county, "raw", baseFilters);
        setMultiOptions(countyFilterSelect, countyPayload.options || []);
      }
      if (fieldMap.event) {
        const eventPayload = await fetchProfessorValueOptions(fieldMap.event, "raw", baseFilters);
        setMultiOptions(eventFilterSelect, eventPayload.options || []);
      }
      if (fieldMap.race) {
        const racePayload = await fetchProfessorValueOptions(fieldMap.race, "raw", baseFilters);
        setMultiOptions(raceFilterSelect, racePayload.options || []);
      }
      if (fieldMap.offense) {
        const offensePayload = await fetchProfessorValueOptions(fieldMap.offense, "raw", baseFilters);
        setMultiOptions(offenseFilterSelect, offensePayload.options || []);
      }
    } catch (err) {
      console.error("Failed to initialize professor variables", err);
      if (loadingEl) loadingEl.textContent = "Unable to load chart options.";
      return;
    } finally {
      setProfLoading(false);
    }

    async function refreshProfessorChart() {
      const xField = xVariableSelect.value;
      const seriesField = seriesVariableSelect.value;
      const xMode = "auto";
      const seriesMode = "auto";
      const measurement = measurementSelect.value || "count";
      const topX = Number(topXSelect.value || 14);
      const topSeries = 8;
      const chartType = chartTypeSelect.value;
      if (!xField || !seriesField) return;
      if (xField === seriesField) {
        if (loadingEl) {
          loadingEl.style.display = "block";
          loadingEl.textContent = "Compare and Split by should be two different categories.";
        }
        return;
      }

      const filters = {};
      if (fieldMap.year) {
        const selectedYears = getMultiSelectedValues(yearFilterSelect);
        if (selectedYears.length > 0) {
          filters[fieldMap.year] = selectedYears;
        }
      }
      if (fieldMap.county) {
        const selectedCounties = getMultiSelectedValues(countyFilterSelect);
        if (selectedCounties.length > 0) {
          filters[fieldMap.county] = selectedCounties;
        }
      }
      if (fieldMap.event) {
        const selectedEvents = getMultiSelectedValues(eventFilterSelect);
        if (selectedEvents.length > 0) {
          filters[fieldMap.event] = selectedEvents;
        }
      }
      if (fieldMap.race) {
        const selectedRaces = getMultiSelectedValues(raceFilterSelect);
        if (selectedRaces.length > 0) {
          filters[fieldMap.race] = selectedRaces;
        }
      }
      if (fieldMap.offense) {
        const selectedOffenses = getMultiSelectedValues(offenseFilterSelect);
        if (selectedOffenses.length > 0) {
          filters[fieldMap.offense] = selectedOffenses;
        }
      }

      try {
        setProfLoading(true);
        const payload = await fetchProfessorReport({
          xField,
          seriesField,
          xMode,
          seriesMode,
          measurement,
          topX,
          topSeries,
          filters,
        });
        drawProfessorChart(payload, chartType);
        if (metaField) metaField.textContent = `Compare: ${payload.x_label || toLabelMap[xField] || xField}`;
        if (metaMode) metaMode.textContent = `Split by: ${payload.series_label || toLabelMap[seriesField] || seriesField}`;
      } catch (err) {
        console.error("Failed to refresh professor chart", err);
        if (loadingEl) loadingEl.textContent = "Unable to load chart.";
      } finally {
        setProfLoading(false);
      }
    }

    refreshBtn.addEventListener("click", refreshProfessorChart);
    chartTypeSelect.addEventListener("change", refreshProfessorChart);
    measurementSelect.addEventListener("change", refreshProfessorChart);

    // Initial render
    await refreshProfessorChart();
  }

  async function loadDashboard(dataset) {
    try {
      setLoading(true);
      if (visualizationButtonRow) {
        visualizationButtonRow.classList.toggle("poster-focus-mode", dataset === "poster_view");
        const exitBtn = ensurePosterExitButton();
        if (exitBtn) {
          exitBtn.style.display = dataset === "poster_view" ? "inline-flex" : "none";
        }
      }

      if (chartCanvas) {
        const [primaryRows, summary] = await Promise.all([
          dataset === "poster_view" ? fetchPosterView() : fetchDataset(dataset),
          fetchDashboardSummary(),
        ]);
        drawChart(dataset, primaryRows);
        renderSummaryCards(summary);
      } else if (fallbackImage) {
        const timestamp = Date.now();
        fallbackImage.src = `/visualize?dataset=${dataset}&_=${timestamp}`;
      }
    } catch (err) {
      console.error("Dashboard load failed", err);
      if (loadingMessage) {
        loadingMessage.textContent = "Unable to load visualization right now.";
      }
    } finally {
      setLoading(false);
    }
  }

  if (visualizationButtons.length > 0) {
    visualizationButtons.forEach((button) => {
      button.addEventListener("click", (event) => {
        const dataset = event.target.getAttribute("data-dataset");
        visualizationButtons.forEach((btn) => btn.classList.remove("active"));
        event.target.classList.add("active");
        loadDashboard(dataset);
      });
    });

    loadDashboard("letters_by_county");
  }

  initializeProfessorExplorer();
});
