(() => {
  const endpoint = "/logistica/validaciones/contenido";
  const status = document.querySelector("#logistics-live-status");
  let timer;
  let loading = false;

  function schedule(delay = 5000) {
    clearTimeout(timer);
    if (!document.hidden) timer = setTimeout(refresh, delay);
  }

  function setStatus(type, text) {
    if (!status) return;
    status.className = `quality-live-status production-live-status ${type}`;
    status.querySelector("span").textContent = text;
  }

  async function refresh() {
    if (loading || document.hidden) return;
    if (document.activeElement?.closest("[data-logistics-form]")) {
      schedule();
      return;
    }
    loading = true;
    setStatus("updating", "Buscando pendientes…");
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
      const nextDocument = new DOMParser().parseFromString(html, "text/html");
      const next = nextDocument.querySelector("#logistics-live-snapshot");
      const current = document.querySelector("#logistics-live-snapshot");
      if (!next || !current) throw new Error("Respuesta incompleta");
      current.replaceWith(next);
      window.initializeLegajoValidation?.(next);
      const now = new Date().toLocaleTimeString("es-AR", {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
      setStatus("online", `Actualizado ${now}`);
      schedule();
    } catch (error) {
      setStatus("offline", "Sin conexión · reintentando");
      schedule(15000);
    } finally {
      loading = false;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(timer);
    else refresh();
  });
  schedule();
})();
