(() => {
  const form = document.querySelector("#production-form");
  const modo = form.dataset.modo;
  const scrapCalidad = form.dataset.scrapCalidad === "true";
  const digitos = Number(form.dataset.digitos || 6);
  const buscador = document.querySelector("#prod-buscador");
  const resultados = document.querySelector("#prod-resultados");
  const estructura = document.querySelector("#prod-estructura");
  const cuerpo = document.querySelector("#prod-items-body");
  const responsibilityItems = document.querySelector("#responsibility-items");
  const tabla = document.querySelector("#prod-items");
  const vacio = document.querySelector("#prod-vacio");
  const bulk = document.querySelector("#bulk-bar");
  const jsonInput = document.querySelector("#prod-items-json");
  const listaOperaciones = document.querySelector("#prod-operaciones");
  const turnoSelect = document.querySelector("#prod-turno");
  const celulaSelect = document.querySelector("#prod-celula");
  const equipoSelect = document.querySelector("#prod-equipo");
  const unidadLabel = document.querySelector("#prod-unidad");
  const equipoInfo = document.querySelector("#prod-equipo-info");
  const catalogos = JSON.parse(document.querySelector("#prod-catalogos-data").textContent);
  const gruposMotivo = JSON.parse(document.querySelector("#prod-motivos-data").textContent);
  let paso = 1;
  let items = [];
  let timer;
  let proveedorGeneralTimer;
  const hcpTimers = new Map();
  const proveedorItemTimers = new Map();
  const proveedorItemResultados = new Map();
  const proveedorItemActivos = new Map();

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[c]);
  const numero = value => Number(value || 0);
  const uid = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const opciones = (valores, seleccionado, vacioTexto = "Elegir…") =>
    `<option value="">${vacioTexto}</option>${valores.map(x =>
      `<option value="${esc(x)}" ${String(x) === String(seleccionado) ? "selected" : ""}>${esc(x)}</option>`
    ).join("")}`;

  function reiniciarEquipo(mensaje = "Primero elegí la célula") {
    equipoSelect.disabled = true;
    equipoSelect.innerHTML = `<option value="">${esc(mensaje)}</option>`;
    equipoInfo.textContent = "Se muestran los equipos disponibles para la célula.";
    actualizarBotones();
  }

  turnoSelect.addEventListener("change", () => {
    const habilitar = Boolean(turnoSelect.value);
    celulaSelect.disabled = !habilitar;
    celulaSelect.value = "";
    celulaSelect.options[0].textContent = habilitar
      ? "Elegir célula…"
      : "Primero elegí el turno";
    unidadLabel.textContent = "Unidad de gestión: —";
    reiniciarEquipo();
    if (scrapCalidad && habilitar && celulaSelect.options.length === 2) {
      celulaSelect.selectedIndex = 1;
      celulaSelect.dispatchEvent(new Event("change", {bubbles: true}));
    }
  });

  celulaSelect.addEventListener("change", async () => {
    const opcion = celulaSelect.selectedOptions[0];
    unidadLabel.textContent = opcion?.dataset.unidad
      ? `Unidad de gestión: ${opcion.dataset.unidad} · código equipos: ${opcion.dataset.codigoEquipos}`
      : "Unidad de gestión: —";
    if (!celulaSelect.value) {
      reiniciarEquipo();
      return;
    }
    equipoSelect.disabled = true;
    equipoSelect.innerHTML = '<option value="">Consultando equipos…</option>';
    equipoInfo.textContent = "Buscando equipos disponibles…";
    try {
      const response = await fetch(`/api/equipos?codigo_celula=${encodeURIComponent(opcion.dataset.codigoEquipos)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "No se pudieron consultar los equipos");
      equipoSelect.innerHTML = data.length
        ? `<option value="">Elegir equipo…</option>${data.map(item =>
            `<option value="${esc(item.equipo)}" data-description="${esc(item.descripcion)}">${esc(item.equipo)} · ${esc(item.descripcion)}</option>`
          ).join("")}`
        : '<option value="">No hay equipos para esta célula</option>';
      equipoSelect.disabled = !data.length;
      equipoInfo.textContent = data.length
        ? `${data.length} equipo${data.length === 1 ? "" : "s"} disponible${data.length === 1 ? "" : "s"}.`
        : "No hay equipos asociados a la célula seleccionada.";
      if (data.length) {
        setTimeout(() => equipoSelect.closest(".searchable-select")
          ?.querySelector(".searchable-select-input")?.focus(), 0);
      }
    } catch (error) {
      equipoSelect.innerHTML = '<option value="">Error al consultar</option>';
      equipoInfo.textContent = error.message;
    }
    actualizarBotones();
  });

  equipoSelect.addEventListener("change", () => {
    const opcion = equipoSelect.selectedOptions[0];
    equipoInfo.textContent = opcion?.dataset.description || "Equipo disponible para la célula.";
    actualizarBotones();
  });

  const proveedorNumero = document.querySelector("#proveedor-numero");
  const proveedorBusqueda = document.querySelector("#proveedor-busqueda");
  const proveedorDescripcion = document.querySelector("#proveedor-descripcion");
  const proveedorEstado = document.querySelector("#proveedor-estado");
  const proveedorResultados = document.querySelector("#proveedor-resultados");
  let proveedoresEncontrados = [];
  let proveedorActivo = 0;

  function seleccionarProveedorGeneral(proveedor) {
    proveedorNumero.value = proveedor.numero;
    proveedorBusqueda.value = `${proveedor.numero} · ${proveedor.descripcion}`;
    proveedorDescripcion.value = proveedor.descripcion;
    proveedorEstado.className = "provider-validation valid";
    proveedorEstado.textContent = `Proveedor válido · ${proveedor.descripcion}`;
    proveedorResultados.classList.add("hidden");
    actualizarBotones();
    setTimeout(() => window.focusNextField?.(proveedorBusqueda), 0);
  }

  function pintarProveedores() {
    proveedorResultados.innerHTML = proveedoresEncontrados.length
      ? proveedoresEncontrados.map((proveedor, index) => `
          <button type="button" data-provider-option="${index}" class="${index === proveedorActivo ? "active" : ""}">
            <b>${esc(proveedor.numero)}</b><small>${esc(proveedor.descripcion)}</small>
          </button>`).join("")
      : '<div class="loading">Sin coincidencias</div>';
    proveedorResultados.classList.remove("hidden");
  }

  proveedorBusqueda?.addEventListener("input", () => {
    clearTimeout(proveedorGeneralTimer);
    const consulta = proveedorBusqueda.value.trim();
    proveedorNumero.value = "";
    proveedorDescripcion.value = "";
    proveedorEstado.className = "provider-validation";
    proveedorEstado.textContent = consulta ? "Buscando proveedor…" : "Ingresá número o nombre.";
    proveedorResultados.classList.add("hidden");
    actualizarBotones();
    if (!consulta) return;
    proveedorGeneralTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/proveedores?q=${encodeURIComponent(consulta)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (proveedorBusqueda.value.trim() !== consulta) return;
        proveedoresEncontrados = data;
        proveedorActivo = 0;
        pintarProveedores();
      } catch (error) {
        proveedorEstado.className = "provider-validation invalid";
        proveedorEstado.textContent = error.message || "No se pudo buscar el proveedor";
      }
    }, 250);
  });
  proveedorBusqueda?.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      proveedorActivo = Math.max(
        0,
        Math.min(proveedoresEncontrados.length - 1, proveedorActivo + direction)
      );
      pintarProveedores();
    } else if (event.key === "Enter" && proveedoresEncontrados[proveedorActivo]) {
      event.preventDefault();
      seleccionarProveedorGeneral(proveedoresEncontrados[proveedorActivo]);
    } else if (event.key === "Escape") {
      proveedorResultados.classList.add("hidden");
    }
  });
  proveedorResultados?.addEventListener("mousedown", event => {
    const button = event.target.closest("[data-provider-option]");
    if (!button) return;
    event.preventDefault();
    seleccionarProveedorGeneral(
      proveedoresEncontrados[Number(button.dataset.providerOption)]
    );
  });

  function pintarProveedoresItem(index, row) {
    const item = items[index];
    const resultadosItem = proveedorItemResultados.get(item.clave) || [];
    const activo = proveedorItemActivos.get(item.clave) || 0;
    const menu = row.querySelector("[data-provider-item-results]");
    menu.innerHTML = resultadosItem.length
      ? resultadosItem.map((proveedor, optionIndex) => `
          <button type="button" data-provider-item-option="${optionIndex}" class="${optionIndex === activo ? "active" : ""}">
            <b>${esc(proveedor.numero)}</b><small>${esc(proveedor.descripcion)}</small>
          </button>`).join("")
      : '<div class="loading">Sin coincidencias</div>';
    menu.classList.remove("hidden");
  }

  function seleccionarProveedorItem(index, row, proveedor) {
    const item = items[index];
    item.responsable_proveedor_numero = proveedor.numero;
    item.responsable_proveedor = proveedor.descripcion;
    item.responsable_proveedor_busqueda = `${proveedor.numero} · ${proveedor.descripcion}`;
    row.querySelector("[data-provider-item-search]").value =
      item.responsable_proveedor_busqueda;
    row.querySelector("[data-provider-description]").value = proveedor.descripcion;
    const estado = row.querySelector("[data-provider-status]");
    estado.className = "provider-validation valid";
    estado.textContent = `Proveedor válido · ${proveedor.descripcion}`;
    row.querySelector("[data-provider-item-results]").classList.add("hidden");
    jsonInput.value = JSON.stringify(items);
    actualizarBotones();
    setTimeout(() => window.focusNextField?.(
      row.querySelector("[data-provider-item-search]")
    ), 0);
  }

  function buscarProveedorItem(index, row) {
    const item = items[index];
    clearTimeout(proveedorItemTimers.get(item.clave));
    const consulta = row.querySelector("[data-provider-item-search]").value.trim();
    item.responsable_proveedor_busqueda = consulta;
    item.responsable_proveedor_numero = "";
    item.responsable_proveedor = "";
    row.querySelector("[data-provider-description]").value = "";
    const estado = row.querySelector("[data-provider-status]");
    estado.className = "provider-validation";
    estado.textContent = consulta ? "Buscando proveedor…" : "Ingresá número o nombre.";
    row.querySelector("[data-provider-item-results]").classList.add("hidden");
    actualizarBotones();
    if (!consulta) return;
    proveedorItemTimers.set(item.clave, setTimeout(async () => {
      try {
        const response = await fetch(`/api/proveedores?q=${encodeURIComponent(consulta)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (items[index]?.responsable_proveedor_busqueda !== consulta) return;
        proveedorItemResultados.set(item.clave, data);
        proveedorItemActivos.set(item.clave, 0);
        const actualRow = responsibilityItems.querySelector(
          `.production-item-card[data-index="${index}"]`
        );
        if (actualRow) pintarProveedoresItem(index, actualRow);
      } catch (error) {
        estado.className = "provider-validation invalid";
        estado.textContent = error.message || "No se pudo buscar el proveedor";
      }
      jsonInput.value = JSON.stringify(items);
      actualizarBotones();
    }, 250));
  }

  const motivoTemplate = document.querySelector("#prod-motivos-options");
  const accionesMotivo = {};
  motivoTemplate.content.querySelectorAll("option").forEach(option => {
    accionesMotivo[String(option.value)] = option.dataset.action || "NINGUNA";
  });
  const opcionesMotivos = seleccionado => {
    const select = document.createElement("select");
    select.append(motivoTemplate.content.cloneNode(true));
    select.querySelectorAll("option").forEach(option => {
      option.selected = String(option.value) === String(seleccionado);
    });
    return select.innerHTML;
  };
  const accionMotivo = item => {
    for (const grupo of gruposMotivo) {
      const causa = grupo.causas.find(x => String(x.id) === String(item.motivo_id));
      if (causa) return causa.accion || "NINGUNA";
    }
    return accionesMotivo[String(item.motivo_id)] || "NINGUNA";
  };
  const opcionesGrupos = seleccionado =>
    `<option value="">Elegir grupo…</option>${gruposMotivo.map(grupo =>
      `<option value="${grupo.id}" ${String(grupo.id) === String(seleccionado) ? "selected" : ""}>${esc(grupo.codigo)} · ${esc(grupo.nombre)}</option>`
    ).join("")}`;
  const opcionesCausas = (grupoId, seleccionado) => {
    const grupo = gruposMotivo.find(x => String(x.id) === String(grupoId));
    if (!grupo) return '<option value="">Primero elegí un grupo</option>';
    return `<option value="">Elegir causa…</option>${grupo.causas.map(causa =>
      `<option value="${causa.id}" ${String(causa.id) === String(seleccionado) ? "selected" : ""}>${esc(causa.nombre)}</option>`
    ).join("")}`;
  };
  const modoResponsabilidad = () =>
    document.querySelector('input[name="responsabilidad_modo"]:checked')?.value || "";

  function aviso(texto) {
    let box = document.querySelector(".production-inline-error");
    if (!box) {
      box = document.createElement("div");
      box.className = "production-inline-error";
      form.prepend(box);
    }
    box.textContent = texto;
    box.scrollIntoView({behavior: "smooth", block: "center"});
    setTimeout(() => box.remove(), 5000);
  }

  function mostrarPaso(nuevo) {
    paso = nuevo;
    document.querySelectorAll(".wizard-step").forEach(x =>
      x.classList.toggle("active", Number(x.dataset.step) === paso));
    document.querySelector("#paso-actual").textContent = paso;
    document.querySelector("#progreso").style.width = `${paso / 4 * 100}%`;
    document.querySelector("#anterior").classList.toggle("hidden", paso === 1);
    document.querySelector("#siguiente").classList.toggle("hidden", paso === 4);
    document.querySelector("#guardar").classList.toggle("hidden", paso !== 4);
    if (paso === 3) renderResponsibilityStep();
    if (paso === 4) {
      renderResultadoRetrabajo();
      actualizarResumen();
    }
    actualizarBotones();
    window.scrollTo({top: 0, behavior: "smooth"});
  }

  function validarPaso1() {
    const campos = [...document.querySelector('[data-step="1"]').querySelectorAll("[required]")];
    const invalido = campos.find(x => !x.value.trim());
    if (invalido) {
      const buscable = invalido.closest(".searchable-select")
        ?.querySelector(".searchable-select-input");
      (buscable || invalido).focus();
      aviso("Completá los datos para continuar.");
      return false;
    }
    return true;
  }

  function paso1Completo() {
    return [...document.querySelector('[data-step="1"]').querySelectorAll("[required]")]
      .every(campo => campo.value.trim());
  }

  function paso2Completo() {
    if (!items.length) return false;
    return items.every(item => {
      if (scrapCalidad && !String(item.observacion || "").trim()) return false;
      if (!new RegExp(`^\\d{${digitos}}$`).test(item.trazabilidad || "") ||
          item.hcp_estado !== "VALIDO" ||
          item.operaciones_estado !== "LISTO" ||
          (item.operaciones.length && !item.operacion_codigo) ||
          numero(item.cantidad) <= 0 ||
          !Number.isInteger(numero(item.cantidad)) ||
          !item.grupo_id || !item.motivo_id) return false;
      const accion = accionMotivo(item);
      if (accion === "COMPONENTE") return Boolean(
        item.afectado_codigo && item.afectado_tipo === "COMPONENTE"
      );
      if (accion === "MATERIA_PRIMA") return Boolean(
        item.afectado_codigo && item.afectado_componente_codigo &&
        item.afectado_tipo === "MATERIA_PRIMA"
      );
      if (accion === "PROCESO") return Boolean(
        item.afectado_codigo && item.afectado_tipo === "PROCESO"
      );
      return true;
    });
  }

  function paso3Completo() {
    const modalidad = modoResponsabilidad();
    if (!modalidad) return false;
    if (modalidad === "COMUN") {
      const origen = document.querySelector('input[name="origen_simple"]:checked')?.value;
      if (origen === "OTRA") {
        return Boolean(
          document.querySelector("#origen-celula").value &&
          document.querySelector("#origen-operacion").value.trim()
        );
      }
      if (origen === "PROVEEDOR") {
        return Boolean(proveedorNumero.value.trim() && proveedorDescripcion.value.trim());
      }
      return Boolean(origen);
    }
    return items.every(item => {
      if (item.responsable_modo === "OTRA") {
        return Boolean(item.responsable_celula && item.responsable_operacion);
      }
      if (item.responsable_modo === "PROVEEDOR") {
        return Boolean(item.responsable_proveedor_numero && item.responsable_proveedor);
      }
      return true;
    });
  }

  function actualizarBotones() {
    const siguiente = document.querySelector("#siguiente");
    if (paso === 1) siguiente.disabled = !paso1Completo();
    if (paso === 2) siguiente.disabled = !paso2Completo();
    if (paso === 3) siguiente.disabled = !paso3Completo();
  }

  function validarPaso2() {
    if (!items.length) {
      aviso("Agregá al menos una pieza o material.");
      return false;
    }
    for (const item of items) {
      if (scrapCalidad && !String(item.observacion || "").trim()) {
        aviso(`Indicá el ensayo o motivo del scrap de ${item.codigo}.`);
        return false;
      }
      if (!new RegExp(`^\\d{${digitos}}$`).test(item.trazabilidad || "") ||
          numero(item.cantidad) <= 0 || !item.grupo_id || !item.motivo_id) {
        aviso(`Revisá HCP, cantidad, grupo y causa de ${item.codigo}.`);
        return false;
      }
      if (item.operaciones_estado !== "LISTO") {
        aviso(`Esperá la consulta de operaciones de ${item.codigo}.`);
        return false;
      }
      if (item.operaciones.length && !item.operacion_codigo) {
        aviso(`Elegí la operación de ${item.codigo}.`);
        return false;
      }
      if (item.hcp_estado !== "VALIDO") {
        aviso(`Validá el HCP de ${item.codigo} antes de continuar.`);
        return false;
      }
      const accion = accionMotivo(item);
      if (accion === "COMPONENTE" && (!item.afectado_codigo || item.afectado_tipo !== "COMPONENTE")) {
        aviso(`Elegí el componente afectado en el renglón de ${item.codigo}.`);
        return false;
      }
      if (accion === "MATERIA_PRIMA" &&
          (!item.afectado_codigo || !item.afectado_componente_codigo ||
           item.afectado_tipo !== "MATERIA_PRIMA")) {
        aviso(`Elegí la materia prima afectada en el renglón de ${item.codigo}.`);
        return false;
      }
      if (accion === "PROCESO" &&
          (!item.afectado_codigo || item.afectado_tipo !== "PROCESO")) {
        aviso(`Elegí el proceso relacionado en el renglón de ${item.codigo}.`);
        return false;
      }
    }
    return true;
  }

  function validarPaso3() {
    if (!modoResponsabilidad()) {
      aviso("Elegí si el responsable será el mismo o se cargará pieza por pieza.");
      return false;
    }
    if (modoResponsabilidad() === "COMUN") {
      const origen = document.querySelector('input[name="origen_simple"]:checked')?.value;
      if (origen === "OTRA" && (
        !document.querySelector("#origen-celula").value ||
        !document.querySelector("#origen-operacion").value.trim()
      )) {
        aviso("Completá la célula y la operación del responsable.");
        return false;
      }
      if (origen === "PROVEEDOR" &&
          (!proveedorNumero.value.trim() || !proveedorDescripcion.value.trim())) {
        aviso("Ingresá un proveedor válido.");
        return false;
      }
      return true;
    }
    for (const item of items) {
      if (item.responsable_modo === "OTRA" &&
          (!item.responsable_celula || !item.responsable_operacion)) {
        aviso(`Completá la célula y operación responsable de ${item.codigo}.`);
        return false;
      }
      if (item.responsable_modo === "PROVEEDOR" &&
          (!item.responsable_proveedor_numero || !item.responsable_proveedor)) {
        aviso(`Ingresá un proveedor válido para ${item.codigo}.`);
        return false;
      }
    }
    return true;
  }

  document.querySelector("#siguiente").addEventListener("click", () => {
    if (paso === 1 && !validarPaso1()) return;
    if (paso === 2 && !validarPaso2()) return;
    if (paso === 3 && !validarPaso3()) return;
    mostrarPaso(paso + 1);
  });
  document.querySelector("#anterior").addEventListener("click", () => mostrarPaso(paso - 1));

  document.querySelectorAll('input[name="responsabilidad_modo"]').forEach(radio => {
    radio.addEventListener("change", () => {
      document.querySelectorAll(".responsibility-mode").forEach(x =>
        x.classList.remove("selected"));
      radio.closest(".responsibility-mode").classList.add("selected");
      const comun = radio.value === "COMUN";
      document.querySelector("#responsable-comun-box").classList.toggle("hidden", !comun);
      renderResponsibilityStep();
      actualizarBotones();
      setTimeout(() => {
        if (!comun) {
          responsibilityItems.querySelector(".searchable-select-input")?.focus();
        }
      }, 0);
    });
  });

  async function cargarEstructura(codigo) {
    estructura.classList.remove("hidden");
    estructura.innerHTML = '<div class="loading">Cargando estructura…</div>';
    try {
      const response = await fetch(`/api/estructura/${encodeURIComponent(codigo)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      const principal = data.pieza || {codigo, descripcion: "Pieza principal"};
      const filas = [{...principal, nivel: 0, uso: 1}, ...data.componentes];
      estructura._filas = filas;
      estructura._padre = principal.codigo;
      estructura.innerHTML = `
        <div class="production-tree-head">
          <div>
            <b>Estructura ${esc(principal.codigo)}</b>
            <small id="tree-selection-mode">Estructura completa: se agregará únicamente ${esc(principal.codigo)}.</small>
          </div>
          <button type="button" id="agregar-estructura">Agregar seleccionados</button>
        </div>
        ${filas.map((p, i) => `<label style="--nivel:${p.nivel || 0}">
          <input type="checkbox" data-tree="${i}" checked>
          <b>${esc(p.codigo)}</b><span>${esc(p.descripcion)}</span>
          <small>${p.material ? `MP ${esc(p.material)}` : `Uso ${esc(p.uso || 1)}`}</small>
        </label>`).join("")}`;
    } catch (error) {
      estructura.innerHTML = `<div class="production-inline-error">${esc(error.message)}</div>`;
    }
  }

  async function buscarPiezas(q, abrirPrimera = false) {
    resultados.innerHTML = '<div class="loading">Buscando…</div>';
    try {
      const response = await fetch(`/api/piezas?q=${encodeURIComponent(q)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      resultados.innerHTML = data.length ? data.map((p, index) => `
        <button type="button" class="prod-result ${index === 0 ? "active" : ""}" data-code="${esc(p.codigo)}">
          <b>${esc(p.codigo)}</b><span>${esc(p.descripcion)}</span><strong>${index === 0 ? "Enter ↵" : "Elegir →"}</strong>
        </button>`).join("") : '<div class="loading">No se encontraron piezas.</div>';
      if (abrirPrimera && data[0]) await cargarEstructura(data[0].codigo);
    } catch (error) {
      resultados.innerHTML = `<div class="production-inline-error">${esc(error.message)}</div>`;
    }
  }

  buscador.addEventListener("input", () => {
    clearTimeout(timer);
    const q = buscador.value.trim();
    if (q.length < 2) {
      resultados.innerHTML = "";
      return;
    }
    timer = setTimeout(() => buscarPiezas(q), 180);
  });
  buscador.addEventListener("keydown", event => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    clearTimeout(timer);
    const q = buscador.value.trim();
    const primeroVisible = resultados.querySelector("[data-code]");
    if (primeroVisible) {
      cargarEstructura(primeroVisible.dataset.code);
    } else if (q.length >= 2) {
      buscarPiezas(q, true);
    }
  });

  resultados.addEventListener("click", event => {
    const boton = event.target.closest("[data-code]");
    if (!boton) return;
    cargarEstructura(boton.dataset.code);
  });

  function descendientesDe(filas, index) {
    const nivel = Number(filas[index]?.nivel || 0);
    const indices = [];
    for (let i = index + 1; i < filas.length; i++) {
      const nivelActual = Number(filas[i]?.nivel || 0);
      if (nivelActual <= nivel) break;
      indices.push(i);
    }
    return indices;
  }

  function hijosDirectosDe(filas, index) {
    const nivel = Number(filas[index]?.nivel || 0);
    return descendientesDe(filas, index).filter(
      i => Number(filas[i]?.nivel || 0) === nivel + 1
    );
  }

  function actualizarSeleccionEstructura() {
    const filas = estructura._filas || [];
    const checks = [...estructura.querySelectorAll("[data-tree]")];
    for (let index = filas.length - 1; index >= 0; index--) {
      const hijos = hijosDirectosDe(filas, index);
      if (!hijos.length) continue;
      const estados = hijos.map(i => checks[i]);
      const todos = estados.every(check => check.checked && !check.indeterminate);
      const alguno = estados.some(check => check.checked || check.indeterminate);
      checks[index].checked = todos;
      checks[index].indeterminate = alguno && !todos;
    }
    const todosMarcados = checks.length > 0 && checks.every(check => check.checked);
    const cantidadMarcada = checks.filter(check => check.checked).length;
    const mensaje = estructura.querySelector("#tree-selection-mode");
    const boton = estructura.querySelector("#agregar-estructura");
    if (mensaje) {
      mensaje.textContent = todosMarcados
        ? `Estructura completa: se agregará únicamente ${estructura._padre}.`
        : `Selección parcial: se agregarán sólo los componentes marcados, sin ${estructura._padre}.`;
    }
    if (boton) boton.disabled = cantidadMarcada === 0;
  }

  estructura.addEventListener("change", event => {
    const check = event.target.closest("[data-tree]");
    if (!check) return;
    const filas = estructura._filas || [];
    const index = Number(check.dataset.tree);
    descendientesDe(filas, index).forEach(i => {
      const descendiente = estructura.querySelector(`[data-tree="${i}"]`);
      descendiente.checked = check.checked;
      descendiente.indeterminate = false;
    });
    actualizarSeleccionEstructura();
  });

  function nuevoItem(pieza, padre, filas, manual = false) {
    return {
      clave: uid(),
      codigo: pieza.codigo,
      descripcion: pieza.descripcion || "",
      codigo_padre: padre,
      codigo_cliente: pieza.codigo_cliente || "",
      material: pieza.material || "",
      uso: pieza.uso || 1,
      tipo_material: manual ? "MATERIA_PRIMA" :
        (Number(pieza.nivel || 0) > 0 ? "COMPONENTE" : "PIEZA_TERMINADA"),
      trazabilidad: "",
      operacion_codigo: "",
      operacion_descripcion: "",
      operaciones: [],
      operaciones_estado: "CARGANDO",
      hcp_estado: "PENDIENTE",
      hcp_mensaje: "Primero resolvé la operación.",
      cantidad: 1,
      observacion: "",
      grupo_id: "",
      motivo_id: "",
      unidad: "PZS",
      estructura: filas.filter(x => Number(x.nivel || 0) > 0).map(x => ({
        codigo: x.codigo,
        descripcion: x.descripcion || "",
        material: x.material || "",
        padre: x.padre || padre,
        nivel: Number(x.nivel || 1)
      })),
      afectado_tipo: "",
      afectado_codigo: "",
      afectado_descripcion: "",
      afectado_componente_codigo: "",
      responsable_modo: "DESCONOCIDO",
      responsable_celula: "",
      responsable_operacion: "",
      responsable_legajo: "",
      responsable_proveedor_busqueda: "",
      responsable_proveedor_numero: "",
      responsable_proveedor: "",
      responsable_remito: "",
      cantidad_ok: 0,
      cantidad_scrap_final: 0,
      motivo_scrap_final: "",
      manual
    };
  }

  function renderOperacion(item) {
    if (item.operaciones_estado === "CARGANDO") {
      return `<label class="operation-field" data-operation-container>Operación
        <input value="Buscando operaciones…" disabled>
      </label>`;
    }
    if (item.operaciones_estado === "ERROR") {
      return `<label class="operation-field" data-operation-container>Operación
        <input value="No se pudieron cargar las operaciones" disabled>
      </label>`;
    }
    if (!item.operaciones.length) {
      return `<label class="operation-field" data-operation-container>Operación
        <input value="No aplica · la pieza no tiene operaciones" disabled>
      </label>`;
    }
    return `<label class="operation-field" data-operation-container>Operación
      <select data-field="operacion_codigo" data-searchable data-no-auto-next>
        <option value="">Elegir operación…</option>
        ${item.operaciones.map(op => `
          <option value="${esc(op.codigo)}" ${String(op.codigo) === String(item.operacion_codigo) ? "selected" : ""}>
            ${esc(op.codigo)} · ${esc(op.titulo)}
          </option>`).join("")}
      </select>
    </label>`;
  }

  function materiasDisponibles(item) {
    const candidatos = [];
    if (item.material) {
      candidatos.push({
        codigo: item.codigo,
        descripcion: item.descripcion || "",
        material: item.material,
        padre: item.codigo_padre || item.codigo,
        nivel: 0
      });
    }
    (item.estructura || []).forEach(componente => {
      if (componente.material) candidatos.push(componente);
    });
    const claves = new Set();
    return candidatos.filter(candidato => {
      const clave = `${String(candidato.material).trim()}|${String(candidato.codigo).trim()}`;
      if (claves.has(clave)) return false;
      claves.add(clave);
      return true;
    });
  }

  function actualizarEstadoHcp(index) {
    const item = items[index];
    const estado = cuerpo.querySelector(
      `.production-item-card[data-index="${index}"] [data-hcp-item-status]`
    );
    if (!estado) return;
    estado.textContent = item.hcp_mensaje;
    estado.className = `hcp-validation-status ${item.hcp_estado.toLowerCase()}`;
    const input = estado.closest(".hcp-entry-field")?.querySelector(
      '[data-field="trazabilidad"]'
    );
    if (input) {
      input.disabled = item.operaciones_estado !== "LISTO" ||
        (item.operaciones.length > 0 && !item.operacion_codigo);
    }
    actualizarBotones();
  }

  async function validarHcpItem(index) {
    const item = items[index];
    clearTimeout(hcpTimers.get(item.clave));
    item.hcp_estado = "PENDIENTE";
    if (item.operaciones_estado !== "LISTO") {
      item.hcp_mensaje = "Esperando operaciones…";
      actualizarEstadoHcp(index);
      return;
    }
    if (item.operaciones.length && !item.operacion_codigo) {
      item.hcp_mensaje = "Elegí la operación para validar.";
      actualizarEstadoHcp(index);
      return;
    }
    if (!new RegExp(`^\\d{${digitos}}$`).test(item.trazabilidad || "")) {
      item.hcp_mensaje = `Ingresá ${digitos} números.`;
      actualizarEstadoHcp(index);
      return;
    }
    item.hcp_mensaje = "Validando HCP…";
    actualizarEstadoHcp(index);
    const clave = item.clave;
    hcpTimers.set(clave, setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          codigo: item.codigo,
          operacion: item.operacion_codigo || "",
          hcp: item.trazabilidad,
          tipo_material: item.tipo_material,
        });
        const response = await fetch(`/api/hcp/validar?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        const actual = items.find(x => x.clave === clave);
        if (!actual) return;
        actual.hcp_estado = data.valido ? "VALIDO" : "INVALIDO";
        actual.hcp_mensaje = data.mensaje;
        actualizarEstadoHcp(items.indexOf(actual));
      } catch (error) {
        item.hcp_estado = "INVALIDO";
        item.hcp_mensaje = error.message || "No se pudo validar el HCP.";
        actualizarEstadoHcp(index);
      }
    }, 300));
  }

  async function cargarOperacionesItem(index, enfocar = false) {
    const item = items[index];
    const clave = item.clave;
    item.operaciones_estado = "CARGANDO";
    try {
      const response = await fetch(
        `/api/piezas/${encodeURIComponent(item.codigo)}/operaciones`
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      const actual = items.find(x => x.clave === clave);
      if (!actual) return;
      actual.operaciones = data;
      actual.operaciones_estado = "LISTO";
      if (!data.some(op => String(op.codigo) === String(actual.operacion_codigo))) {
        actual.operacion_codigo = "";
        actual.operacion_descripcion = "";
      }
      const actualIndex = items.indexOf(actual);
      const row = cuerpo.querySelector(
        `.production-item-card[data-index="${actualIndex}"]`
      );
      const container = row?.querySelector("[data-operation-container]");
      if (container) {
        container.outerHTML = renderOperacion(actual);
        window.enhanceSearchable?.(row);
      }
      validarHcpItem(actualIndex);
      if (enfocar) {
        setTimeout(() => {
          const objetivo = actual.operaciones.length
            ? row?.querySelector(".operation-field .searchable-select-input")
            : row?.querySelector('[data-field="trazabilidad"]');
          objetivo?.focus();
        }, 0);
      }
    } catch (error) {
      item.operaciones = [];
      item.operaciones_estado = "ERROR";
      item.hcp_estado = "INVALIDO";
      item.hcp_mensaje = error.message || "No se pudieron cargar las operaciones.";
      const row = cuerpo.querySelector(
        `.production-item-card[data-index="${index}"]`
      );
      const container = row?.querySelector("[data-operation-container]");
      if (container) {
        container.innerHTML = `Operación<input value="${esc(item.hcp_mensaje)}" disabled>`;
      }
      actualizarEstadoHcp(index);
    }
  }

  estructura.addEventListener("click", event => {
    if (!event.target.closest("#agregar-estructura")) return;
    const filas = estructura._filas || [];
    const primerIndiceNuevo = items.length;
    const checks = [...estructura.querySelectorAll("[data-tree]")];
    const estructuraCompleta = checks.length > 0 &&
      checks.every(check => check.checked && !check.indeterminate);
    let indicesSeleccionados;
    if (estructuraCompleta) {
      indicesSeleccionados = [0];
    } else {
      const padres = [];
      filas.forEach((fila, index) => {
        const nivel = Number(fila.nivel || 0);
        while (padres.length > nivel) padres.pop();
        fila._indicePadreVisual = nivel > 0 ? padres[nivel - 1] : null;
        padres[nivel] = index;
      });
      indicesSeleccionados = checks
        .map((check, index) => ({check, index}))
        .filter(({check, index}) => {
          if (index === 0 || !check.checked || check.indeterminate) return false;
          let padre = filas[index]._indicePadreVisual;
          while (padre !== null && padre !== 0) {
            if (checks[padre].checked && !checks[padre].indeterminate) return false;
            padre = filas[padre]._indicePadreVisual;
          }
          return true;
        })
        .map(x => x.index);
    }
    if (!indicesSeleccionados.length) {
      aviso("Marcá al menos un componente de la estructura.");
      return;
    }
    indicesSeleccionados.forEach(index => {
      const pieza = filas[index];
      const nivelBase = Number(pieza.nivel || 0);
      const filasDelItem = index === 0
        ? filas
        : [
            {...pieza, nivel: 0},
            ...descendientesDe(filas, index).map(descIndex => ({
              ...filas[descIndex],
              nivel: Number(filas[descIndex].nivel || 0) - nivelBase,
            })),
          ];
      items.push(nuevoItem(pieza, estructura._padre, filasDelItem));
    });
    renderItems();
    for (let index = primerIndiceNuevo; index < items.length; index++) {
      cargarOperacionesItem(index, index === primerIndiceNuevo);
    }
    estructura.classList.add("hidden");
    resultados.innerHTML = "";
    buscador.value = "";
  });

  document.querySelector("#prod-manual")?.addEventListener("click", () => {
    const indice = items.length;
    items.push(nuevoItem({
      codigo: `SIN-COD-${items.length + 1}`,
      descripcion: "Materia prima / material sin código",
      nivel: 0,
      uso: 1
    }, "", [], true));
    renderItems();
    cargarOperacionesItem(indice);
    setTimeout(() => cuerpo.querySelector(
      `.production-item-card[data-index="${indice}"] [data-field="codigo"]`
    )?.focus(), 0);
  });

  function renderAfectado(item) {
    const accion = accionMotivo(item);
    if (accion === "NINGUNA") return "";
    if (accion === "PROCESO") {
      return `<label class="affected-field">Proceso relacionado
        <input data-affect-process list="prod-operaciones"
          value="${esc(item.afectado_tipo === "PROCESO" ? item.afectado_codigo : "")}"
          placeholder="Código o nombre del proceso">
      </label>`;
    }
    if (accion === "COMPONENTE") {
      const componentes = item.estructura || [];
      if (!componentes.length) {
        return `<div class="row-alert">Esta pieza no tiene componentes disponibles en la estructura.</div>`;
      }
      return `<label class="affected-field">Componente que causó el defecto
        <select data-affect="COMPONENTE" data-searchable>
          <option value="">Elegir componente…</option>
          ${componentes.map((x, index) => `<option value="${index}" ${
            item.afectado_tipo === "COMPONENTE" && item.afectado_codigo === x.codigo ? "selected" : ""
          }>${esc(x.codigo)} · ${esc(x.descripcion)}</option>`).join("")}
        </select>
      </label>`;
    }
    const materias = materiasDisponibles(item);
    if (!materias.length) {
      return `<div class="row-alert">No se encontró materia prima asociada a esta pieza ni a sus componentes. Elegí otra causa o revisá los datos de la pieza.</div>`;
    }
    return `<label class="affected-field">Materia prima que causó el defecto
      <select data-affect="MATERIA_PRIMA" data-searchable>
        <option value="">Elegir entre ${materias.length} MP disponible${materias.length === 1 ? "" : "s"}…</option>
        ${materias.map((x, index) => `<option value="${index}" ${
          item.afectado_tipo === "MATERIA_PRIMA" &&
          item.afectado_codigo === x.material &&
          item.afectado_componente_codigo === x.codigo ? "selected" : ""
        }>${esc(x.material)} · componente ${esc(x.codigo)}</option>`).join("")}
      </select>
    </label>`;
  }

  function renderResponsable(item) {
    const modoResponsable =
      !item.responsable_modo || item.responsable_modo === "GENERAL"
        ? "DESCONOCIDO"
        : item.responsable_modo;
    let campos = "";
    if (modoResponsable === "OTRA") {
      campos = `<div class="row-responsible-fields">
        <label>Célula responsable<select data-field="responsable_celula" data-searchable>${opciones(catalogos.celulas, item.responsable_celula)}</select></label>
        <label>Operación<input data-field="responsable_operacion" list="prod-operaciones" value="${esc(item.responsable_operacion)}" placeholder="Código o nombre"></label>
        <label>Legajo relacionado<input data-field="responsable_legajo" data-legajo value="${esc(item.responsable_legajo)}" placeholder="Opcional"></label>
      </div>`;
    } else if (modoResponsable === "PROVEEDOR") {
      campos = `<div class="row-responsible-fields">
        <label class="provider-search-field">Buscar proveedor
          <input data-provider-item-search autocomplete="off" value="${esc(item.responsable_proveedor_busqueda || (item.responsable_proveedor_numero ? `${item.responsable_proveedor_numero} · ${item.responsable_proveedor}` : ""))}" placeholder="Número o nombre">
          <div class="autocomplete-results hidden" data-provider-item-results></div>
        </label>
        <label>Proveedor<input data-provider-description readonly value="${esc(item.responsable_proveedor)}" placeholder="Se completa al seleccionar un proveedor"></label>
        <label>Remito<input data-field="responsable_remito" value="${esc(item.responsable_remito)}" placeholder="Opcional"></label>
        <small class="provider-validation ${item.responsable_proveedor ? "valid" : ""}" data-provider-status>${item.responsable_proveedor ? `Proveedor válido · ${esc(item.responsable_proveedor)}` : "Ingresá el número para validarlo."}</small>
      </div>`;
    }
    return `<div class="row-responsible">
      <div class="row-responsible-summary">Responsable de este renglón: <b>${{
        MISMA: "esta célula",
        OTRA: "otra célula",
        PROVEEDOR: "proveedor",
        DESCONOCIDO: "sin asignar"
      }[modoResponsable]}</b></div>
      <label class="responsible-choice">Asignación
        <select data-field="responsable_modo" data-searchable data-no-auto-next>
          <option value="MISMA" ${modoResponsable === "MISMA" ? "selected" : ""}>Esta célula</option>
          <option value="OTRA" ${modoResponsable === "OTRA" ? "selected" : ""}>Otra célula / proceso</option>
          <option value="PROVEEDOR" ${modoResponsable === "PROVEEDOR" ? "selected" : ""}>Proveedor</option>
          <option value="DESCONOCIDO" ${modoResponsable === "DESCONOCIDO" ? "selected" : ""}>No asignar</option>
        </select>
      </label>
      ${campos}
    </div>`;
  }

  function renderResponsibilityStep() {
    const individual = modoResponsabilidad() === "POR_PIEZA";
    responsibilityItems.classList.toggle("hidden", !individual);
    responsibilityItems.innerHTML = individual ? `
      <div class="material-section-heading">
        <h3>Responsable por renglón</h3>
        <p>Podés dejar un renglón sin asignar y completarlo más adelante.</p>
      </div>
      ${items.map((item, index) => `
        <article class="production-item-card responsibility-item-card" data-index="${index}">
          <header>
            <div class="production-piece">
              <span>Renglón ${index + 1}</span>
              <b>${esc(item.codigo)}</b>
              <small>${esc(item.descripcion)} · ${esc(item.cantidad)} ${esc(item.unidad)}</small>
            </div>
          </header>
          ${renderResponsable(item)}
        </article>`).join("")}` : "";
    window.enhanceSearchable?.(responsibilityItems);
  }

  function renderItems() {
    vacio.classList.toggle("hidden", items.length > 0);
    tabla.classList.toggle("hidden", !items.length);
    bulk.classList.toggle("hidden", !items.length);
    cuerpo.innerHTML = items.map((item, index) => {
      const requiereAfectado = accionMotivo(item) !== "NINGUNA";
      return `
      <article class="production-item-card" data-index="${index}">
        <header>
          <div class="production-piece">
            <span>Renglón ${index + 1}</span>
            ${item.manual ? `<input data-field="codigo" value="${esc(item.codigo)}">` : `<b>${esc(item.codigo)}</b>`}
            <small>${esc(item.descripcion)}</small>
          </div>
          <div class="row-actions">
            <button type="button" class="prod-duplicate" title="Agregar otra causa para esta pieza">Duplicar</button>
            <button type="button" class="prod-remove" title="Quitar">×</button>
          </div>
        </header>
        <div class="production-item-fields">
          ${renderOperacion(item)}
          <label class="hcp-entry-field">${item.tipo_material === "MATERIA_PRIMA" ? "Lote MP" : "HCP"}
            <input data-field="trazabilidad" value="${esc(item.trazabilidad)}"
              maxlength="${digitos}" inputmode="numeric" placeholder="${digitos} números"
              ${item.operaciones_estado !== "LISTO" || (item.operaciones.length && !item.operacion_codigo) ? "disabled" : ""}>
            <small data-hcp-item-status class="hcp-validation-status ${item.hcp_estado.toLowerCase()}">${esc(item.hcp_mensaje)}</small>
          </label>
          <label class="quantity-field">Cantidad
            <div class="quantity-input">
              <button type="button" data-minus aria-label="Restar una pieza">−</button>
              <input data-field="cantidad" type="number" min="1" step="1"
                inputmode="numeric" value="${esc(item.cantidad)}">
              <button type="button" data-plus aria-label="Sumar una pieza">+</button>
            </div>
          </label>
          <label class="group-field">Grupo<select data-field="grupo_id" data-searchable data-no-auto-next>${opcionesGrupos(item.grupo_id)}</select></label>
          <label class="cause-field">Causa<select data-field="motivo_id" data-searchable data-no-auto-next ${item.grupo_id ? "" : "disabled"}>${opcionesCausas(item.grupo_id, item.motivo_id)}</select></label>
          ${renderAfectado(item)}
          <label class="row-observation-field ${requiereAfectado ? "" : "full"}">${scrapCalidad ? "Indicación de Calidad (obligatoria)" : "Observaciones del renglón"}
            <input data-field="observacion" value="${esc(item.observacion)}"
              maxlength="255" ${scrapCalidad ? "required" : ""} placeholder="${scrapCalidad ? "Ej.: corte de probeta para ensayo de soldadura" : "Ej.: componente con rajaduras"}">
          </label>
        </div>
      </article>`;
    }).join("");
    window.enhanceSearchable?.(cuerpo);
    renderResponsibilityStep();
    jsonInput.value = JSON.stringify(items);
    actualizarBotones();
  }

  function actualizarItem(event) {
    const row = event.target.closest(".production-item-card");
    if (!row) return;
    const index = Number(row.dataset.index);
    if (event.target.matches("[data-provider-item-search]")) {
      buscarProveedorItem(index, row);
      return;
    }
    const field = event.target.dataset.field;
    if (field) {
      if (field === "trazabilidad") {
        event.target.value = event.target.value.replace(/\D/g, "").slice(0, digitos);
      }
      items[index][field] = event.target.value;
      if (field === "trazabilidad") {
        validarHcpItem(index);
      } else if (field === "operacion_codigo") {
        const operacion = items[index].operaciones.find(
          op => String(op.codigo) === String(event.target.value)
        );
        items[index].operacion_descripcion = operacion?.titulo || "";
        validarHcpItem(index);
        setTimeout(() => {
          const hcp = cuerpo.querySelector(
            `.production-item-card[data-index="${index}"] [data-field="trazabilidad"]`
          );
          if (event.target.value) hcp?.focus();
        }, 0);
      } else if (field === "codigo") {
        items[index].hcp_estado = "PENDIENTE";
        items[index].hcp_mensaje = "Ingresá el código completo para validar.";
        if (event.type === "change") cargarOperacionesItem(index);
      } else if (field === "grupo_id") {
        Object.assign(items[index], {
          motivo_id: "",
          afectado_tipo: "",
          afectado_codigo: "",
          afectado_descripcion: "",
          afectado_componente_codigo: ""
        });
        renderItems();
        setTimeout(() => cuerpo.querySelector(
          `.production-item-card[data-index="${index}"] .cause-field .searchable-select-input`
        )?.focus(), 0);
      } else if (field === "motivo_id") {
        Object.assign(items[index], {
          afectado_tipo: "",
          afectado_codigo: "",
          afectado_descripcion: "",
          afectado_componente_codigo: ""
        });
        renderItems();
        setTimeout(() => {
          const rowActual = cuerpo.querySelector(
            `.production-item-card[data-index="${index}"]`
          );
          const next = rowActual?.querySelector(
            ".affected-field .searchable-select-input, .affected-field input"
          );
          if (next) next.focus();
          else window.focusNextField?.(
            rowActual?.querySelector(".cause-field .searchable-select-input")
          );
        }, 0);
      } else if (field === "responsable_modo") {
        renderResponsibilityStep();
        setTimeout(() => {
          const rowActual = responsibilityItems.querySelector(
            `.production-item-card[data-index="${index}"]`
          );
          const next = rowActual?.querySelector(
            ".row-responsible-fields .searchable-select-input, " +
            ".row-responsible-fields input:not([readonly])"
          );
          if (next) next.focus();
          else window.focusNextField?.(
            rowActual?.querySelector(".responsible-choice .searchable-select-input")
          );
        }, 0);
      } else if (field === "responsable_operacion") {
        buscarOperaciones(event.target.value);
      }
      jsonInput.value = JSON.stringify(items);
      actualizarBotones();
      return;
    }
    const tipoAfectado = event.target.dataset.affect;
    if (event.target.matches("[data-affect-process]")) {
      Object.assign(items[index], {
        afectado_tipo: event.target.value.trim() ? "PROCESO" : "",
        afectado_codigo: event.target.value.trim(),
        afectado_descripcion: event.target.value.trim(),
        afectado_componente_codigo: ""
      });
      buscarOperaciones(event.target.value);
      jsonInput.value = JSON.stringify(items);
      actualizarBotones();
      return;
    }
    if (!tipoAfectado) return;
    const seleccionado = Number(event.target.value);
    if (event.target.value === "") {
      Object.assign(items[index], {
        afectado_tipo: "",
        afectado_codigo: "",
        afectado_descripcion: "",
        afectado_componente_codigo: ""
      });
      jsonInput.value = JSON.stringify(items);
      actualizarBotones();
      return;
    }
    if (tipoAfectado === "COMPONENTE") {
      const componente = items[index].estructura[seleccionado];
      Object.assign(items[index], {
        afectado_tipo: "COMPONENTE",
        afectado_codigo: componente.codigo,
        afectado_descripcion: componente.descripcion,
        afectado_componente_codigo: componente.codigo
      });
    } else {
      const materias = materiasDisponibles(items[index]);
      const componente = materias[seleccionado];
      Object.assign(items[index], {
        afectado_tipo: "MATERIA_PRIMA",
        afectado_codigo: componente.material,
        afectado_descripcion: `MP de ${componente.codigo}`,
        afectado_componente_codigo: componente.codigo
      });
    }
    jsonInput.value = JSON.stringify(items);
    actualizarBotones();
  }

  function manejarTecladoProveedorItem(event) {
    if (!event.target.matches("[data-provider-item-search]")) return;
    const row = event.target.closest(".production-item-card");
    const index = Number(row.dataset.index);
    const item = items[index];
    const encontrados = proveedorItemResultados.get(item.clave) || [];
    let activo = proveedorItemActivos.get(item.clave) || 0;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      activo = Math.max(0, Math.min(encontrados.length - 1, activo + direction));
      proveedorItemActivos.set(item.clave, activo);
      pintarProveedoresItem(index, row);
    } else if (event.key === "Enter" && encontrados[activo]) {
      event.preventDefault();
      seleccionarProveedorItem(index, row, encontrados[activo]);
    } else if (event.key === "Escape") {
      row.querySelector("[data-provider-item-results]").classList.add("hidden");
    }
  }

  function seleccionarProveedorDesdeClick(event) {
    const row = event.target.closest(".production-item-card");
    if (!row) return false;
    const index = Number(row.dataset.index);
    const providerOption = event.target.closest("[data-provider-item-option]");
    if (!providerOption) return false;
    seleccionarProveedorItem(
      index,
      row,
      (proveedorItemResultados.get(items[index].clave) || [])[
        Number(providerOption.dataset.providerItemOption)
      ]
    );
    return true;
  }

  cuerpo.addEventListener("input", actualizarItem);
  cuerpo.addEventListener("change", actualizarItem);
  cuerpo.addEventListener("keydown", manejarTecladoProveedorItem);
  responsibilityItems.addEventListener("input", actualizarItem);
  responsibilityItems.addEventListener("change", actualizarItem);
  responsibilityItems.addEventListener("keydown", manejarTecladoProveedorItem);
  responsibilityItems.addEventListener("click", seleccionarProveedorDesdeClick);
  cuerpo.addEventListener("click", event => {
    const row = event.target.closest(".production-item-card");
    if (!row) return;
    const index = Number(row.dataset.index);
    if (seleccionarProveedorDesdeClick(event)) return;
    if (event.target.closest(".prod-remove")) {
      items.splice(index, 1);
      renderItems();
    } else if (event.target.closest(".prod-duplicate")) {
      const copia = JSON.parse(JSON.stringify(items[index]));
      Object.assign(copia, {
        clave: uid(),
        grupo_id: "",
        motivo_id: "",
        observacion: "",
        afectado_tipo: "",
        afectado_codigo: "",
        afectado_descripcion: "",
        afectado_componente_codigo: ""
      });
      items.splice(index + 1, 0, copia);
      renderItems();
    } else if (event.target.closest("[data-plus]")) {
      items[index].cantidad = Math.floor(numero(items[index].cantidad)) + 1;
      renderItems();
    } else if (event.target.closest("[data-minus]")) {
      items[index].cantidad = Math.max(
        1,
        Math.ceil(numero(items[index].cantidad)) - 1
      );
      renderItems();
    }
  });

  const grupoComun = document.querySelector("#grupo-comun");
  const motivoComun = document.querySelector("#motivo-comun");
  const aplicarMotivo = document.querySelector("#aplicar-motivo");
  grupoComun.addEventListener("change", () => {
    motivoComun.innerHTML = opcionesCausas(grupoComun.value, "");
    motivoComun.disabled = !grupoComun.value;
    aplicarMotivo.disabled = true;
  });
  motivoComun.addEventListener("change", () => {
    aplicarMotivo.disabled = !motivoComun.value;
  });
  aplicarMotivo.addEventListener("click", () => {
    const grupo = grupoComun.value;
    const motivo = motivoComun.value;
    if (!grupo || !motivo) return;
    items.forEach(item => {
      Object.assign(item, {
        grupo_id: grupo,
        motivo_id: motivo,
        afectado_tipo: "",
        afectado_codigo: "",
        afectado_descripcion: "",
        afectado_componente_codigo: ""
      });
    });
    renderItems();
  });

  document.querySelectorAll('input[name="origen_simple"]').forEach(radio => {
    radio.addEventListener("change", () => {
      document.querySelectorAll(".origin-simple").forEach(x => x.classList.remove("selected"));
      radio.closest(".origin-simple").classList.add("selected");
      document.querySelector("#otra-origen").classList.toggle("hidden", radio.value !== "OTRA");
      document.querySelector("#proveedor-origen").classList.toggle("hidden", radio.value !== "PROVEEDOR");
      actualizarResumen();
      setTimeout(() => {
        const next = radio.value === "OTRA"
          ? document.querySelector("#otra-origen .searchable-select-input")
          : radio.value === "PROVEEDOR"
            ? proveedorBusqueda
            : null;
        if (next) next.focus();
        else document.querySelector("#siguiente:not(:disabled)")?.focus();
      }, 0);
    });
  });

  document.querySelectorAll('input[name="retrabajo_simple"]').forEach(radio => {
    radio.addEventListener("change", () => {
      document.querySelectorAll(".yes-no label").forEach(x => x.classList.remove("selected"));
      radio.closest("label").classList.add("selected");
      document.querySelector("#resultado-retrabajo").classList.toggle("hidden", radio.value !== "REALIZADO");
      renderResultadoRetrabajo();
    });
  });

  function renderResultadoRetrabajo() {
    const contenedor = document.querySelector("#prod-resultados-retrabajo");
    if (!contenedor) return;
    contenedor.innerHTML = items.map((item, index) => `
      <div class="rework-result-row" data-result="${index}">
        <div><b>${esc(item.codigo)}</b><small>Renglón ${index + 1} · ${esc(item.cantidad)} enviadas</small></div>
        <label>Recuperadas<input data-result-field="cantidad_ok" type="number" min="0" step="0.001" value="${esc(item.cantidad_ok)}"></label>
        <label>Scrap final<input data-result-field="cantidad_scrap_final" type="number" min="0" step="0.001" value="${esc(item.cantidad_scrap_final)}"></label>
        <label>Motivo scrap<select data-result-field="motivo_scrap_final" data-searchable>${opcionesMotivos(item.motivo_scrap_final)}</select></label>
      </div>`).join("");
    window.enhanceSearchable?.(contenedor);
  }

  document.querySelector("#prod-resultados-retrabajo")?.addEventListener("input", actualizarResultado);
  document.querySelector("#prod-resultados-retrabajo")?.addEventListener("change", actualizarResultado);
  function actualizarResultado(event) {
    const field = event.target.dataset.resultField;
    if (!field) return;
    const index = Number(event.target.closest("[data-result]").dataset.result);
    items[index][field] = event.target.value;
  }

  ["#origen-operacion", "#rt-operacion"].forEach(selector => {
    document.querySelector(selector)?.addEventListener("input", event => buscarOperaciones(event.target.value));
  });
  async function buscarOperaciones(q) {
    if (!q.trim()) return;
    try {
      const response = await fetch(`/api/operaciones?q=${encodeURIComponent(q)}`);
      const data = await response.json();
      if (!response.ok) return;
      listaOperaciones.innerHTML = data.map(x =>
        `<option value="${esc(x.codigo)} · ${esc(x.titulo)}"></option>`
      ).join("");
    } catch (_) {}
  }

  const cantidadFormateada = value =>
    new Intl.NumberFormat("es-AR", {maximumFractionDigits: 3}).format(numero(value));

  function datosMotivo(item) {
    const grupo = gruposMotivo.find(x => String(x.id) === String(item.grupo_id));
    const causa = grupo?.causas.find(x => String(x.id) === String(item.motivo_id));
    return {
      grupo: grupo ? `${grupo.codigo} · ${grupo.nombre}` : "Sin grupo",
      causa: causa?.nombre || "Sin causa"
    };
  }

  function textoAfectado(item) {
    if (!item.afectado_codigo) return {
      principal: "No requiere selección",
      detalle: "—"
    };
    if (item.afectado_tipo === "MATERIA_PRIMA") {
      return {
        principal: item.afectado_codigo,
        detalle: item.afectado_componente_codigo
          ? `MP del componente ${item.afectado_componente_codigo}`
          : "Materia prima"
      };
    }
    return {
      principal: item.afectado_codigo,
      detalle: item.afectado_descripcion || {
        COMPONENTE: "Componente",
        PROCESO: "Proceso relacionado"
      }[item.afectado_tipo] || "Detalle informado"
    };
  }

  function textoResponsableComun() {
    const origen = document.querySelector('input[name="origen_simple"]:checked')?.value;
    if (origen === "MISMA") return {principal: "Esta célula", detalle: "Responsable común"};
    if (origen === "OTRA") {
      return {
        principal: document.querySelector("#origen-celula").value || "Otra célula",
        detalle: document.querySelector("#origen-operacion").value.trim() || "Proceso anterior"
      };
    }
    if (origen === "PROVEEDOR") {
      return {
        principal: proveedorNumero.value
          ? `${proveedorNumero.value} · ${proveedorDescripcion.value}`
          : "Proveedor",
        detalle: document.querySelector("#remito").value.trim()
          ? `Remito ${document.querySelector("#remito").value.trim()}`
          : "Responsable común"
      };
    }
    return {principal: "Pendiente", detalle: "Sin responsable asignado", pendiente: true};
  }

  function textoResponsableItem(item) {
    if (modoResponsabilidad() === "COMUN") return textoResponsableComun();
    if (item.responsable_modo === "MISMA") {
      return {principal: "Esta célula", detalle: "Detectó y originó"};
    }
    if (item.responsable_modo === "OTRA") {
      return {
        principal: item.responsable_celula || "Otra célula",
        detalle: item.responsable_operacion || "Proceso anterior"
      };
    }
    if (item.responsable_modo === "PROVEEDOR") {
      return {
        principal: item.responsable_proveedor_numero
          ? `${item.responsable_proveedor_numero} · ${item.responsable_proveedor}`
          : "Proveedor",
        detalle: item.responsable_remito ? `Remito ${item.responsable_remito}` : "Proveedor externo"
      };
    }
    return {principal: "Pendiente", detalle: "Sin responsable asignado", pendiente: true};
  }

  function renderResumenItems() {
    const contenedor = document.querySelector("#review-items-body");
    contenedor.innerHTML = items.map((item, index) => {
      const motivo = datosMotivo(item);
      const afectado = textoAfectado(item);
      const responsable = textoResponsableItem(item);
      const operacion = item.operacion_codigo
        ? `${item.operacion_codigo}${item.operacion_descripcion ? ` · ${item.operacion_descripcion}` : ""}`
        : "No aplica";
      const trazabilidad = item.tipo_material === "MATERIA_PRIMA" ? "Lote" : "HCP";
      return `
        <div class="review-item-row">
          <div class="review-item-cell review-item-code">
            <small>RENGLÓN ${index + 1}</small>
            <b>${esc(item.codigo)}</b>
            <small title="${esc(item.descripcion)}">${esc(item.descripcion || item.tipo_material)}</small>
          </div>
          <div class="review-item-cell">
            <small title="${esc(operacion)}">${esc(operacion)}</small>
            <b>${trazabilidad} ${esc(item.trazabilidad)}</b>
          </div>
          <div class="review-item-cell review-item-quantity">
            <b>${cantidadFormateada(item.cantidad)}</b>
            <small>${esc(item.unidad || "PZS")}</small>
          </div>
          <div class="review-item-cell">
            <small title="${esc(motivo.grupo)}">${esc(motivo.grupo)}</small>
            <b title="${esc(motivo.causa)}">${esc(motivo.causa)}</b>
          </div>
          <div class="review-item-cell">
            <b title="${esc(afectado.principal)}">${esc(afectado.principal)}</b>
            <small title="${esc(afectado.detalle)}">${esc(afectado.detalle)}</small>
          </div>
          <div class="review-item-cell review-item-responsible ${responsable.pendiente ? "pending" : ""}">
            <b title="${esc(responsable.principal)}">${esc(responsable.principal)}</b>
            <small title="${esc(responsable.detalle)}">${esc(responsable.detalle)}</small>
          </div>
          ${item.observacion ? `
            <div class="review-item-observation">
              <small>OBSERVACIÓN</small><span>${esc(item.observacion)}</span>
            </div>` : ""}
        </div>`;
    }).join("");
  }

  function actualizarResumen() {
    const total = items.reduce((s, x) => s + numero(x.cantidad), 0);
    const modalidad = modoResponsabilidad();
    const origen = document.querySelector('input[name="origen_simple"]:checked')?.value;
    const textos = {
      MISMA: "esta célula",
      OTRA: "otra célula",
      PROVEEDOR: "un proveedor",
      DESCONOCIDO: "sin responsable general"
    };
    const propios = items.filter(x => x.responsable_modo !== "GENERAL").length;
    document.querySelector("#resumen-final").textContent =
      `${items.length} renglón${items.length === 1 ? "" : "es"} · ${total} ${
        modo === "ALERTA" ? "unidades informadas" : (modo === "SCRAP" ? "a scrap" : "a retrabajo")
      } · ${modalidad === "COMUN" ? `responsable común: ${textos[origen]}` :
        `${propios} asignación${propios === 1 ? "" : "es"} por renglón`}`;

    document.querySelector("#review-row-count").textContent = items.length;
    document.querySelector("#review-unit-count").textContent = cantidadFormateada(total);
    document.querySelector("#review-code-count").textContent =
      new Set(items.map(item => item.codigo)).size;
    document.querySelector("#review-unit-label").textContent = modo === "ALERTA"
      ? "Unidades informadas"
      : (modo === "SCRAP" ? "Unidades a scrap" : "Unidades a retrabajo");

    const responsabilidadResumen = modalidad === "COMUN"
      ? textoResponsableComun()
      : {
          principal: "Por renglón",
          detalle: `${items.filter(item => !textoResponsableItem(item).pendiente).length} de ${items.length} asignados`
        };
    document.querySelector("#review-responsibility-mode").textContent =
      modalidad === "COMUN" ? "Común" : responsabilidadResumen.principal;
    document.querySelector("#review-responsibility-detail").textContent =
      modalidad === "COMUN"
        ? responsabilidadResumen.principal
        : responsabilidadResumen.detalle;

    const fecha = form.elements.fecha.value.split("-");
    document.querySelector("#review-date").textContent =
      fecha.length === 3 ? `${fecha[2]}/${fecha[1]}/${fecha[0]}` : "—";
    document.querySelector("#review-shift").textContent =
      turnoSelect.selectedOptions[0]?.textContent.trim() || "—";
    document.querySelector("#review-unit").textContent =
      celulaSelect.selectedOptions[0]?.dataset.unidad || "—";
    document.querySelector("#review-cell").textContent =
      celulaSelect.value || "—";
    const equipoOpcion = equipoSelect.selectedOptions[0];
    document.querySelector("#review-equipment").textContent = equipoSelect.value
      ? `${equipoSelect.value}${equipoOpcion?.dataset.description ? ` · ${equipoOpcion.dataset.description}` : ""}`
      : "—";
    document.querySelector("#review-employee").textContent =
      form.elements.legajo_declara.value || "—";

    const observacionGeneral = form.elements.observaciones.value.trim();
    const cajaObservacion = document.querySelector("#review-general-observation");
    cajaObservacion.classList.toggle("hidden", !observacionGeneral);
    document.querySelector("#review-general-observation-text").textContent = observacionGeneral;
    renderResumenItems();
  }

  function origenGeneral() {
    if (scrapCalidad) return {
      tipo_origen: "INTERNO", tipo_imputacion: "CONFIRMADA",
      sector_origen: celulaSelect.selectedOptions[0]?.dataset.unidad || "Calidad",
      celula_origen: celulaSelect.value, operacion_origen: "Ensayos de Calidad",
      legajo_origen: form.elements.legajo_declara.value.trim()
    };
    if (modoResponsabilidad() === "POR_PIEZA") {
      return {
        tipo_origen: "DESCONOCIDO", sector_origen: "No determinado",
        celula_origen: "No determinada", operacion_origen: "No determinada",
        tipo_imputacion: "NO_DETERMINADA", legajo_origen: ""
      };
    }
    const origen = document.querySelector('input[name="origen_simple"]:checked').value;
    const sectorDeclara =
      celulaSelect.selectedOptions[0]?.dataset.unidad || "Producción";
    const celulaDetecta = form.elements.celula_detecta.value;
    if (origen === "MISMA") {
      return {
        tipo_origen: "INTERNO", sector_origen: sectorDeclara,
        celula_origen: celulaDetecta, operacion_origen: "Misma célula",
        tipo_imputacion: "CONFIRMADA", legajo_origen: ""
      };
    }
    if (origen === "OTRA") {
      const celula = document.querySelector("#origen-celula").value;
      const operacion = document.querySelector("#origen-operacion").value.trim();
      if (!celula || !operacion) {
        throw new Error("Completá la célula y operación del responsable general.");
      }
      return {
        tipo_origen: "INTERNO", sector_origen: "Producción",
        celula_origen: celula, operacion_origen: operacion,
        tipo_imputacion: "CONFIRMADA",
        legajo_origen: document.querySelector("#origen-legajo").value.trim()
      };
    }
    if (origen === "PROVEEDOR") {
      const proveedorNumeroValor = proveedorNumero.value.trim();
      const proveedor = proveedorDescripcion.value.trim();
      if (!proveedorNumeroValor || !proveedor) {
        throw new Error("Ingresá un número de proveedor válido.");
      }
      return {
        tipo_origen: "PROVEEDOR", sector_origen: "Proveedor",
        celula_origen: proveedor, operacion_origen: "Material recibido no conforme",
        tipo_imputacion: "CONFIRMADA", legajo_origen: "",
        proveedor_numero: proveedorNumeroValor, proveedor,
        remito: document.querySelector("#remito").value.trim()
      };
    }
    return {
      tipo_origen: "DESCONOCIDO", sector_origen: "No determinado",
      celula_origen: "No determinada", operacion_origen: "No determinada",
      tipo_imputacion: "NO_DETERMINADA", legajo_origen: ""
    };
  }

  function origenDelItem(item, general) {
    if (scrapCalidad) return general;
    if (modoResponsabilidad() === "COMUN") return general;
    if (!item.responsable_modo || item.responsable_modo === "GENERAL") return general;
    if (item.responsable_modo === "MISMA") {
      return {
        tipo_origen: "INTERNO",
        sector_origen: celulaSelect.selectedOptions[0]?.dataset.unidad || "Producción",
        celula_origen: form.elements.celula_detecta.value,
        operacion_origen: "Misma célula", tipo_imputacion: "CONFIRMADA",
        legajo_origen: ""
      };
    }
    if (item.responsable_modo === "OTRA") {
      return {
        tipo_origen: "INTERNO", sector_origen: "Producción",
        celula_origen: item.responsable_celula,
        operacion_origen: item.responsable_operacion,
        legajo_origen: item.responsable_legajo || "",
        tipo_imputacion: "CONFIRMADA"
      };
    }
    if (item.responsable_modo === "PROVEEDOR") {
      return {
        tipo_origen: "PROVEEDOR", sector_origen: "Proveedor",
        celula_origen: item.responsable_proveedor,
        operacion_origen: "Material recibido no conforme",
        legajo_origen: "", tipo_imputacion: "CONFIRMADA",
        proveedor_numero: item.responsable_proveedor_numero,
        proveedor: item.responsable_proveedor,
        remito: item.responsable_remito || ""
      };
    }
    return {
      tipo_origen: "DESCONOCIDO", sector_origen: "No determinado",
      celula_origen: "No determinada", operacion_origen: "No determinada",
      tipo_imputacion: "NO_DETERMINADA", legajo_origen: ""
    };
  }

  function prepararPayload() {
    const general = origenGeneral();
    const realizado = modo === "RETRABAJO" &&
      document.querySelector('input[name="retrabajo_simple"]:checked').value === "REALIZADO";
    let tiempos = [];
    if (realizado) {
      const minutos = numero(document.querySelector("#rt-minutos").value);
      const operacion = document.querySelector("#rt-operacion").value.trim();
      const celula = document.querySelector("#rt-celula").value.trim();
      const legajo = document.querySelector("#rt-legajo").value.trim();
      if (!minutos || minutos < items.length || !operacion || !celula || !legajo) {
        throw new Error(`Completá el retrabajo. El tiempo debe ser al menos ${items.length} minuto(s).`);
      }
      const totalCantidad = items.reduce((s, x) => s + numero(x.cantidad), 0);
      tiempos = items.map(x => Math.max(1, Math.floor(minutos * numero(x.cantidad) / totalCantidad)));
      let diferencia = minutos - tiempos.reduce((s, x) => s + x, 0);
      let cursor = 0;
      while (diferencia !== 0) {
        if (diferencia > 0) {
          tiempos[cursor % tiempos.length]++;
          diferencia--;
        } else if (tiempos[cursor % tiempos.length] > 1) {
          tiempos[cursor % tiempos.length]--;
          diferencia++;
        }
        cursor++;
      }
    }

    return items.map((item, index) => {
      const cantidad = numero(item.cantidad);
      const {
        estructura: _estructura,
        operaciones: _operaciones,
        operaciones_estado: _operacionesEstado,
        hcp_estado: _hcpEstado,
        hcp_mensaje: _hcpMensaje,
        responsable_modo: _responsableModo,
        responsable_celula: _responsableCelula,
        responsable_operacion: _responsableOperacion,
        responsable_legajo: _responsableLegajo,
        responsable_proveedor_busqueda: _responsableProveedorBusqueda,
        responsable_proveedor_numero: _responsableProveedorNumero,
        responsable_proveedor: _responsableProveedor,
        responsable_remito: _responsableRemito,
        ...datosItem
      } = item;
      const payload = {
        ...datosItem,
        ...origenDelItem(item, general),
        cantidad_detectada: cantidad,
        cantidad_scrap_directo: modo === "SCRAP" ? cantidad : 0,
        cantidad_a_retrabajo: modo === "RETRABAJO" ? cantidad : 0
      };
      if (realizado) {
        const ok = numero(item.cantidad_ok);
        const scrap = numero(item.cantidad_scrap_final);
        if (ok + scrap <= 0 || ok + scrap > cantidad) {
          throw new Error(`Revisá el resultado del renglón ${index + 1} (${item.codigo}).`);
        }
        if (scrap > 0 && !item.motivo_scrap_final) {
          throw new Error(`Elegí el motivo del scrap final del renglón ${index + 1}.`);
        }
        Object.assign(payload, {
          retrabajo_estado: "REALIZADO",
          fecha_retrabajo: document.querySelector("#rt-fecha").value,
          operacion_retrabajo: document.querySelector("#rt-operacion").value.trim(),
          celula_retrabajo: document.querySelector("#rt-celula").value.trim(),
          legajo_retrabajo: document.querySelector("#rt-legajo").value.trim(),
          minutos_retrabajo: tiempos[index],
          personas_retrabajo: numero(document.querySelector("#rt-personas").value),
          cantidad_ok: ok,
          cantidad_scrap_retrabajo: scrap,
          motivo_scrap_retrabajo_id: item.motivo_scrap_final
        });
      } else {
        payload.retrabajo_estado = "PENDIENTE";
      }
      return payload;
    });
  }

  form.addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.defaultPrevented) return;
    if (event.target.matches("textarea, button")) return;
    event.preventDefault();
    window.focusNextField?.(event.target);
  });

  form.addEventListener("submit", event => {
    event.preventDefault();
    try {
      if (!validarPaso2()) return;
      if (!validarPaso3()) return;
      jsonInput.value = JSON.stringify(prepararPayload());
      form.submit();
    } catch (error) {
      aviso(error.message);
    }
  });

  form.addEventListener("input", actualizarBotones);
  form.addEventListener("change", actualizarBotones);

  mostrarPaso(1);
})();
