(() => {
  const endpoint = "/calidad/bandeja/contenido";
  const intervalMs = 5000;
  const counter = document.querySelector("#quality-counter");
  const status = document.querySelector("#quality-live-status");
  const refreshButton = document.querySelector("#quality-refresh");
  let timer = null;
  let loading = false;

  const idsFrom = snapshot => new Set(
    (snapshot?.dataset.alertIds || "").split(",").filter(Boolean)
  );

  function schedule(delay = intervalMs) {
    clearTimeout(timer);
    if (!document.hidden) timer = setTimeout(refresh, delay);
  }

  function setStatus(type, text) {
    status.className = `quality-live-status ${type}`;
    status.querySelector("span").textContent = text;
  }

  async function refresh() {
    if (loading || document.hidden) return;
    loading = true;
    refreshButton.disabled = true;
    setStatus("updating", "Buscando alertas…");
    const current = document.querySelector("#quality-live-snapshot");
    const previousIds = idsFrom(current);

    try {
      const response = await fetch(endpoint, {
        cache: "no-store",
        headers: {"X-Requested-With": "fetch"},
      });
      if (response.status === 401 || (response.redirected && response.url.includes("/login"))) {
        window.location.assign("/login");
        return;
      }
      if (!response.ok) throw new Error("No se pudo actualizar");
      const html = await response.text();
      const documentNext = new DOMParser().parseFromString(html, "text/html");
      const next = documentNext.querySelector("#quality-live-snapshot");
      if (!next) throw new Error("Respuesta incompleta");

      current.replaceWith(next);
      const count = Number(next.dataset.alertCount || 0);
      counter.textContent = `${count} por decidir`;
      document.title = count
        ? `(${count}) Bandeja de Calidad`
        : "Bandeja de Calidad";

      idsFrom(next).forEach(id => {
        if (!previousIds.has(id)) {
          next.querySelector(`[data-alert-id="${CSS.escape(id)}"]`)
            ?.classList.add("is-new");
        }
      });

      const now = new Date().toLocaleTimeString("es-AR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      setStatus("online", `Actualizado ${now}`);
      schedule();
    } catch (error) {
      setStatus("offline", "Sin conexión · reintentando");
      schedule(15000);
    } finally {
      loading = false;
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener("click", refresh);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(timer);
    else refresh();
  });
  schedule(1000);
})();
