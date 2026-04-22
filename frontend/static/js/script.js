document.addEventListener("DOMContentLoaded", () => {
  const visualizationButtons = document.querySelectorAll(".visualization-button");
  const loadingMessage = document.getElementById("loadingMessage");
  const chartCanvas = document.getElementById("publicDashboardChart");
  const fallbackImage = document.getElementById("visualizationImage");

  let dashboardChart = null;

  function setLoading(isLoading) {
    if (!loadingMessage) return;
    loadingMessage.style.display = isLoading ? "block" : "none";
  }

  function formatNumber(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? n.toLocaleString() : "--";
  }

  function renderSummaryCards(records, paroleRows) {
    const statTotal = document.getElementById("stat-total-records");
    const statCounties = document.getElementById("stat-unique-counties");
    const statParoleYears = document.getElementById("stat-parole-years");
    if (!statTotal || !statCounties || !statParoleYears) return;

    const counties = new Set(
      (records || [])
        .map((r) => (r.county || "").toString().trim())
        .filter(Boolean)
    );

    const paroleYears = new Set(
      (paroleRows || [])
        .map((r) => {
          const v = (r.parole_eligibility_date || "").toString().trim();
          if (!v) return "";
          const m = v.match(/^(\d{4})/);
          return m ? m[1] : "";
        })
        .filter(Boolean)
    );

    statTotal.textContent = formatNumber((records || []).length);
    statCounties.textContent = formatNumber(counties.size);
    statParoleYears.textContent = formatNumber(paroleYears.size);
  }

  async function fetchDataset(dataset) {
    const response = await fetch(`/api/stats?dataset=${encodeURIComponent(dataset)}`);
    if (!response.ok) {
      throw new Error(`Failed to load ${dataset}: ${response.status}`);
    }
    const payload = await response.json();
    return payload.data || [];
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

  function aggregateSentenceTypes(rows) {
    const counts = {};
    rows.forEach((row) => {
      const key = (row.isl_dsl || "Unknown").toString().trim() || "Unknown";
      counts[key] = (counts[key] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
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

    const ctx = chartCanvas.getContext("2d");
    if (dashboardChart) {
      dashboardChart.destroy();
    }

    let labels = [];
    let data = [];
    let chartType = "bar";
    let chartLabel = "";
    let horizontal = false;

    if (dataset === "years_reduced") {
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
    }

    dashboardChart = new Chart(ctx, {
      type: chartType,
      data: {
        labels,
        datasets: [
          {
            label: chartLabel,
            data,
            backgroundColor:
              chartType === "doughnut"
                ? [
                    "#1e3a5f",
                    "#2f5b8f",
                    "#6b8fb8",
                    "#9db5cf",
                    "#c7d4e2",
                    "#e3ebf3",
                    "#94a3b8",
                  ]
                : "rgba(30, 58, 95, 0.85)",
            borderColor: chartType === "doughnut" ? "#ffffff" : "rgba(21, 42, 69, 1)",
            borderWidth: 1,
            borderRadius: chartType === "bar" ? 5 : 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? "y" : "x",
        plugins: {
          legend: {
            display: chartType === "doughnut",
            position: "bottom",
          },
        },
      },
    });
  }

  async function loadDashboard(dataset) {
    try {
      setLoading(true);

      if (chartCanvas) {
        const [primaryRows, summaryRows, paroleRows] = await Promise.all([
          fetchDataset(dataset),
          fetchDataset("years_reduced"),
          fetchDataset("parole_eligibility"),
        ]);
        drawChart(dataset, primaryRows);
        renderSummaryCards(summaryRows, paroleRows);
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

    loadDashboard("years_reduced");
  }
});
