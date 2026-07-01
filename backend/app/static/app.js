// Poll job status on the dashboard so download progress updates live.
(function () {
  const table = document.getElementById("jobs");
  if (!table) return;

  async function refresh() {
    try {
      const res = await fetch("/api/jobs");
      if (!res.ok) return;
      const jobs = await res.json();
      const byId = Object.fromEntries(jobs.map((j) => [j.id, j]));
      table.querySelectorAll("tr[data-id]").forEach((row) => {
        const job = byId[row.dataset.id];
        if (!job) return;
        const badge = row.querySelector(".status");
        if (badge && badge.textContent !== job.status) {
          badge.textContent = job.status;
          badge.className = "status " + job.status;
        }
      });
    } catch (e) {
      /* transient network error; try again next tick */
    }
  }

  // Expand/collapse the log for a job, fetching its full output on demand.
  table.addEventListener("click", async (ev) => {
    const link = ev.target.closest(".toggle-log");
    if (!link) return;
    ev.preventDefault();
    const row = link.closest("tr[data-id]");
    const logRow = table.querySelector(`tr[data-log-for="${row.dataset.id}"]`);
    if (!logRow) return;
    logRow.hidden = !logRow.hidden;
    if (!logRow.hidden) {
      const res = await fetch(`/api/jobs/${row.dataset.id}`);
      if (res.ok) {
        const job = await res.json();
        logRow.querySelector("pre").textContent = job.log || "(no output yet)";
      }
    }
  });

  setInterval(refresh, 3000);
})();
