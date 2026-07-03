// Live dashboard: poll job status and offer pause/resume/cancel controls.
(function () {
  const table = document.getElementById("jobs");
  if (!table) return;

  function button(id, action, label, cls) {
    return `<button class="job-action mini ${cls}" data-id="${id}" ` +
      `data-action="${action}">${label}</button>`;
  }

  // Which controls make sense for a given status.
  function actionsFor(id, status) {
    if (status === "queued") return button(id, "cancel", "Cancel", "danger");
    if (status === "running")
      return button(id, "pause", "Pause", "") +
             button(id, "cancel", "Cancel", "danger");
    if (status === "paused")
      return button(id, "resume", "Resume", "") +
             button(id, "cancel", "Cancel", "danger");
    return "";  // done / failed / cancelled -> no actions
  }

  async function refresh() {
    try {
      const res = await fetch("/api/jobs");
      if (!res.ok) return;
      const byId = Object.fromEntries((await res.json()).map((j) => [j.id, j]));
      table.querySelectorAll("tr[data-id]").forEach((row) => {
        const job = byId[row.dataset.id];
        if (!job) return;
        const badge = row.querySelector(".status");
        if (badge && badge.textContent !== job.status) {
          badge.textContent = job.status;
          badge.className = "status " + job.status;
        }
        const res = row.querySelector(".result");
        if (res && res.textContent !== (job.result || "")) {
          res.textContent = job.result || "";
        }
        const cell = row.querySelector(".actions");
        const markup = actionsFor(row.dataset.id, job.status);
        if (cell && cell.dataset.status !== job.status) {
          cell.innerHTML = markup;
          cell.dataset.status = job.status;
        }
      });
    } catch (e) {
      /* transient network error; try again next tick */
    }
  }

  table.addEventListener("click", async (ev) => {
    // Pause / resume / cancel controls.
    const btn = ev.target.closest(".job-action");
    if (btn) {
      ev.preventDefault();
      btn.disabled = true;
      const { id, action } = btn.dataset;
      try {
        await fetch(`/api/jobs/${id}/${action}`, { method: "POST" });
      } finally {
        refresh();
      }
      return;
    }

    // Expand/collapse the log for a job, fetching its full output on demand.
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

  refresh();               // render controls immediately on load
  setInterval(refresh, 3000);
})();
