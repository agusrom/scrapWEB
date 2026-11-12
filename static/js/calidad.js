(() => {
  const form = document.querySelector("#quality-form");
  if (!form) return;

  const rows = [...form.querySelectorAll(".quality-row")];
  const groups = JSON.parse(document.querySelector("#quality-causes-data").textContent);
  const selectedCauses = JSON.parse(document.querySelector("#quality-selected-data").textContent);
  const operations = document.querySelector("#quality-operations");
  let operationTimer;
  const providerTimers = new WeakMap();
  const providerResults = new WeakMap();
  const providerActive = new WeakMap();

  const n = value => Number(value || 0);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);

  function renderCauses(row, selected = "") {
    const groupId = row.querySelector("[data-quality-group]").value;
    const select = row.querySelector("[data-quality-cause]");
    const group = groups.find(item => String(item.id) === String(groupId));
    select.disabled = !group;
    select.innerHTML = group
      ? `<option value="">Elegir causa…</option>${group.causas.map(cause =>
          `<option value="${cause.id}" ${String(cause.id) === String(selected) ? "selected" : ""}>${esc(cause.codigo)} · ${esc(cause.nombre)}</option>`
        ).join("")}`
      : '<option value="">Primero elegí un grupo</option>';
  }

  function updateCauseSummary(row) {
    const review = row.querySelector(".quality-cause-review");
    const group = row.querySelector("[data-quality-group]");
    const cause = row.querySelector("[data-quality-cause]");
    const corrected =
      String(group.value) !== String(review.dataset.originalGroup) ||
      String(cause.value) !== String(review.dataset.originalCause);
    const confirmed = row.querySelector("[data-quality-cause-confirmed]");
    row.querySelector("[data-quality-cause-caption]").textContent = corrected
      ? "CORRECCIÓN DE CALIDAD"
      : "INFORMADO POR PRODUCCIÓN";
    const summary = `${group.selectedOptions[0]?.textContent.trim() || "Sin grupo"} → ${
      cause.selectedOptions[0]?.textContent.trim() || "Sin causa"
    }`;
    row.querySelector("[data-quality-cause-summary]").textContent = summary;
    row.querySelector("[data-row-cause-summary]").textContent = summary;
    confirmed.classList.toggle("corrected", corrected);
    row.querySelector("[data-edit-quality-cause]").textContent = corrected
      ? "Volver a modificar"
      : "Modificar motivo";
  }

  function setCauseEditor(row, visible) {
    const editor = row.querySelector("[data-quality-cause-editor]");
    editor.classList.toggle("hidden", !visible);
    row.querySelector("[data-quality-cause-confirmed]").classList.toggle("hidden", visible);
    if (!visible) return;
    setTimeout(() => {
      const input = row.querySelector(
        "[data-quality-group] + .searchable-select-input, " +
        "[data-quality-group]"
      );
      const searchable = row.querySelector("[data-quality-group]")
        .closest(".searchable-select")
        ?.querySelector(".searchable-select-input");
      const target = searchable || input;
      if (!target) return;
      target.value = "";
      target.focus();
      target.dispatchEvent(new Event("input", {bubbles: true}));
    }, 0);
  }

  function updateCauseApplyButton(row) {
    row.querySelector("[data-apply-quality-cause]").disabled = !(
      row.querySelector("[data-quality-group]").value &&
      row.querySelector("[data-quality-cause]").value
    );
  }

  function setDisposition(row, type) {
    const total = n(row.dataset.quantity);
    const inputs = {
      SCRAP: row.querySelector('[data-qty="SCRAP"]'),
      RETRABAJO: row.querySelector('[data-qty="RETRABAJO"]'),
      LIBERADA: row.querySelector('[data-qty="LIBERADA"]')
    };
    const split = type === "DIVIDIR";
    Object.entries(inputs).forEach(([key, input]) => {
      if (!split) input.value = key === type ? total : 0;
      input.readOnly = !split;
    });
    row.querySelectorAll("[data-disposition]").forEach(button =>
      button.classList.toggle("selected", button.dataset.disposition === type));
    checkRow(row);
  }

  function updateDestinationSummary(row) {
    const type = inferDisposition(row);
    const total = n(row.dataset.quantity).toLocaleString("es-AR");
    const labels = {
      SCRAP: `Todo scrap · ${total}`,
      RETRABAJO: `Todo retrabajo · ${total}`,
      LIBERADA: `Liberar · ${total}`,
      DIVIDIR: "Cantidades divididas"
    };
    row.querySelector("[data-row-destination]").textContent = labels[type];
  }

  function setRowExpanded(row, expanded) {
    row.classList.toggle("expanded", expanded);
    row.querySelector("[data-quality-row-details]").classList.toggle("hidden", !expanded);
    const button = row.querySelector("[data-toggle-quality-row]");
    button.setAttribute("aria-expanded", String(expanded));
    button.querySelector("span").textContent = expanded ? "Cerrar" : "Ver detalle";
  }

  function inferDisposition(row) {
    const total = n(row.dataset.quantity);
    const scrap = n(row.querySelector('[data-qty="SCRAP"]').value);
    const rework = n(row.querySelector('[data-qty="RETRABAJO"]').value);
    const released = n(row.querySelector('[data-qty="LIBERADA"]').value);
    if (scrap === total && rework === 0 && released === 0) return "SCRAP";
    if (rework === total && scrap === 0 && released === 0) return "RETRABAJO";
    if (released === total && scrap === 0 && rework === 0) return "LIBERADA";
    return "DIVIDIR";
  }

  function updateResponsibility(row) {
    const state = row.querySelector("[data-resp-state]").value;
    const type = row.querySelector("[data-resp-type]");
    const editable = state === "CONFIRMADA" || state === "PROBABLE";
    type.disabled = !editable;
    const internal = editable && type.value === "INTERNO";
    const provider = editable && type.value === "PROVEEDOR";
    row.querySelectorAll("[data-internal-field]").forEach(field => {
      field.classList.toggle("hidden", !internal);
      field.querySelectorAll("input").forEach(input => input.disabled = !internal);
    });
    row.querySelectorAll("[data-provider-field]").forEach(field => {
      field.classList.toggle("hidden", !provider);
      field.querySelectorAll("input").forEach(input => input.disabled = !provider);
    });
    checkRow(row);
  }

  function useProposed(row) {
    const proposedType = row.dataset.proposedType;
    const hasProposal = proposedType === "PROVEEDOR"
      ? Boolean(row.dataset.proposedProvider)
      : Boolean(row.dataset.proposedCell && row.dataset.proposedCell !== "No determinada");
    row.querySelector("[data-resp-state]").value = hasProposal ? "PROBABLE" : "PENDIENTE";
    row.querySelector("[data-resp-type]").value = hasProposal ? proposedType : "";
    const values = {
      "resp_sector": row.dataset.proposedSector,
      "resp_celula": row.dataset.proposedCell,
      "resp_operacion": row.dataset.proposedOperation,
      "resp_legajo": row.dataset.proposedLegajo,
      "resp_proveedor_numero": row.dataset.proposedProviderNumber
    };
    Object.entries(values).forEach(([prefix, value]) => {
      const input = row.querySelector(`[name^="${prefix}_"]`);
      if (input) input.value = value || "";
    });
    row.querySelector("[data-quality-provider-description]").value =
      row.dataset.proposedProvider || "";
    row.querySelector("[data-quality-provider-search]").value =
      row.dataset.proposedProviderNumber
        ? `${row.dataset.proposedProviderNumber} · ${row.dataset.proposedProvider}`
        : "";
    updateResponsibility(row);
  }

  function renderProviders(row) {
    const found = providerResults.get(row) || [];
    const active = providerActive.get(row) || 0;
    const menu = row.querySelector("[data-quality-provider-results]");
    menu.innerHTML = found.length
      ? found.map((provider, index) => `
          <button type="button" data-quality-provider-option="${index}" class="${index === active ? "active" : ""}">
            <b>${esc(provider.numero)}</b><small>${esc(provider.descripcion)}</small>
          </button>`).join("")
      : '<div class="loading">Sin coincidencias</div>';
    menu.classList.remove("hidden");
  }

  function selectProvider(row, provider) {
    row.querySelector("[data-quality-provider-number]").value = provider.numero;
    row.querySelector("[data-quality-provider-description]").value = provider.descripcion;
    row.querySelector("[data-quality-provider-search]").value =
      `${provider.numero} · ${provider.descripcion}`;
    row.querySelector("[data-quality-provider-results]").classList.add("hidden");
    checkRow(row);
  }

  function searchProvider(row) {
    clearTimeout(providerTimers.get(row));
    const search = row.querySelector("[data-quality-provider-search]");
    const number = row.querySelector("[data-quality-provider-number]");
    const description = row.querySelector("[data-quality-provider-description]");
    const query = search.value.trim();
    number.value = "";
    description.value = "";
    row.querySelector("[data-quality-provider-results]").classList.add("hidden");
    if (!query) {
      checkRow(row);
      return;
    }
    providerTimers.set(row, setTimeout(async () => {
      try {
        const response = await fetch(`/api/proveedores?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (search.value.trim() !== query) return;
        providerResults.set(row, data);
        providerActive.set(row, 0);
        renderProviders(row);
      } catch (_) {
        description.value = "";
      }
      checkRow(row);
    }, 250));
  }

  function checkRow(row) {
    const hcp = row.querySelector("[data-quality-hcp]");
    const hcpDigits = Number(row.dataset.hcpDigits || 6);
    const hcpFormatOk = new RegExp(`^\\d{${hcpDigits}}$`).test(hcp.value.trim());
    const hcpOk = hcpFormatOk && row.dataset.hcpValidated === "true";
    const hcpStatus = row.querySelector("[data-hcp-status]");
    if (!hcpFormatOk) {
      hcpStatus.textContent = `Debe tener ${hcpDigits} números`;
    } else if (row.dataset.hcpMessage) {
      hcpStatus.textContent = row.dataset.hcpMessage;
    }
    hcpStatus.classList.toggle("ok", hcpOk);
    hcpStatus.classList.toggle("invalid", hcpFormatOk && !hcpOk);

    const total = n(row.dataset.quantity);
    const sum = [...row.querySelectorAll("[data-qty]")].reduce(
      (acc, input) => acc + n(input.value), 0
    );
    const inputs = [...row.querySelectorAll("[data-qty]")];
    const resolved = n(row.dataset.reworkResolved);
    const quantityOk = inputs.every(input => input.value !== "" && input.validity.valid
      && Number.isFinite(Number(input.value)) && Number(input.value) >= 0
      && (row.dataset.unit !== "PZS" || Number.isInteger(Number(input.value))))
      && n(row.querySelector('[data-qty="RETRABAJO"]').value) >= resolved
      && Math.abs(sum - total) < 0.0001;
    const check = row.querySelector("[data-quantity-check]");
    check.textContent = quantityOk
      ? `Correcto: ${sum.toLocaleString("es-AR")}`
      : (n(row.querySelector('[data-qty="RETRABAJO"]').value) < resolved
        ? `Ya se procesaron ${resolved} unidades de retrabajo.`
        : "Revisá las cantidades: deben ser válidas y sumar el total informado.");
    check.classList.toggle("ok", quantityOk);
    updateDestinationSummary(row);

    const comment = row.querySelector("[data-quality-item-comment]");
    const commentOk = Boolean(comment.value.trim());
    comment.required = true;
    row.querySelector("[data-quality-comment-field]").classList.add("required");
    row.querySelector("[data-quality-comment-required]").classList.remove("hidden");
    const commentHelp = row.querySelector("[data-quality-comment-help]");
    commentHelp.textContent = commentOk
      ? "Indicación cargada para este renglón."
      : "Indicá qué debe hacerse o por qué se toma la decisión.";
    commentHelp.classList.toggle("ok", commentOk);

    const state = row.querySelector("[data-resp-state]").value;
    const type = row.querySelector("[data-resp-type]").value;
    let responsibilityOk = true;
    if (state === "CONFIRMADA") {
      if (type === "INTERNO") {
        responsibilityOk = Boolean(
          row.querySelector('[name^="resp_celula_"]').value.trim() &&
          row.querySelector('[name^="resp_operacion_"]').value.trim()
        );
      } else if (type === "PROVEEDOR") {
        responsibilityOk = Boolean(
          row.querySelector("[data-quality-provider-number]").value.trim() &&
          row.querySelector("[data-quality-provider-description]").value.trim()
        );
      } else {
        responsibilityOk = false;
      }
    }
    if (state === "PROBABLE" && type === "PROVEEDOR") {
      responsibilityOk = Boolean(
        row.querySelector("[data-quality-provider-number]").value.trim() &&
        row.querySelector("[data-quality-provider-description]").value.trim()
      );
    }
    const rowOk = Boolean(
      hcpOk &&
      quantityOk &&
      commentOk &&
      row.querySelector("[data-quality-group]").value &&
      row.querySelector("[data-quality-cause]").value &&
      responsibilityOk
    );
    const detailOk = Boolean(
      hcpOk &&
      quantityOk &&
      row.querySelector("[data-quality-group]").value &&
      row.querySelector("[data-quality-cause]").value &&
      responsibilityOk
    );
    row.dataset.commentValid = String(commentOk);
    row.dataset.detailValid = String(detailOk);
    row.dataset.valid = String(rowOk);
    row.classList.toggle("quality-row-complete", rowOk);
    const rowStatus = row.querySelector("[data-row-status]");
    rowStatus.textContent = rowOk
      ? "Listo"
      : (!commentOk ? "Falta indicación" : "Revisar");
    rowStatus.classList.toggle("ok", rowOk);
  }

  rows.forEach(row => {
    const itemId = row.dataset.itemId;
    renderCauses(row, selectedCauses[itemId]);
    const causeReview = row.querySelector(".quality-cause-review");
    causeReview.dataset.confirmedGroup = row.querySelector("[data-quality-group]").value;
    causeReview.dataset.confirmedCause = row.querySelector("[data-quality-cause]").value;
    updateCauseSummary(row);
    updateCauseApplyButton(row);
    setDisposition(row, inferDisposition(row));
    updateResponsibility(row);

    row.dataset.hcpMessage = row.querySelector("[data-hcp-status]").textContent.trim();
    row.querySelector("[data-quality-group]").addEventListener("change", () => {
      renderCauses(row);
      updateCauseApplyButton(row);
      checkRow(row);
    });
    row.querySelector("[data-quality-cause]").addEventListener("change", () => {
      updateCauseApplyButton(row);
      checkRow(row);
    });
    row.querySelector("[data-edit-quality-cause]").addEventListener("click", () =>
      setCauseEditor(row, true));
    row.querySelector("[data-cancel-quality-cause]").addEventListener("click", () => {
      row.querySelector("[data-quality-group]").value = causeReview.dataset.confirmedGroup;
      renderCauses(row, causeReview.dataset.confirmedCause);
      updateCauseSummary(row);
      updateCauseApplyButton(row);
      setCauseEditor(row, false);
      checkRow(row);
    });
    row.querySelector("[data-apply-quality-cause]").addEventListener("click", () => {
      if (!row.querySelector("[data-quality-group]").value ||
          !row.querySelector("[data-quality-cause]").value) return;
      causeReview.dataset.confirmedGroup = row.querySelector("[data-quality-group]").value;
      causeReview.dataset.confirmedCause = row.querySelector("[data-quality-cause]").value;
      updateCauseSummary(row);
      setCauseEditor(row, false);
      checkRow(row);
    });
    row.querySelector("[data-toggle-quality-row]").addEventListener("click", () =>
      setRowExpanded(row, !row.classList.contains("expanded")));
    row.querySelector(".quality-row-summary").addEventListener("click", event => {
      if (event.target.closest("button, input, label")) return;
      setRowExpanded(row, !row.classList.contains("expanded"));
    });
    row.querySelectorAll("[data-disposition]").forEach(button =>
      button.addEventListener("click", () => setDisposition(row, button.dataset.disposition)));
    row.querySelectorAll("[data-qty]").forEach(input =>
      input.addEventListener("input", () => checkRow(row)));
    row.querySelector("[data-quality-item-comment]").addEventListener(
      "input", () => checkRow(row)
    );
    row.querySelector("[data-resp-state]").addEventListener("change", () => updateResponsibility(row));
    row.querySelector("[data-resp-type]").addEventListener("change", () => updateResponsibility(row));
    row.querySelectorAll(".quality-responsibility-grid input").forEach(input =>
      input.addEventListener("input", () => {
        checkRow(row);
        if (input.name.startsWith("resp_operacion_")) searchOperations(input.value);
        if (input.matches("[data-quality-provider-search]")) searchProvider(row);
      }));
    row.querySelector("[data-quality-provider-search]").addEventListener("keydown", event => {
      const found = providerResults.get(row) || [];
      let active = providerActive.get(row) || 0;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        active = Math.max(0, Math.min(found.length - 1, active + direction));
        providerActive.set(row, active);
        renderProviders(row);
      } else if (event.key === "Enter" && found[active]) {
        event.preventDefault();
        selectProvider(row, found[active]);
      } else if (event.key === "Escape") {
        row.querySelector("[data-quality-provider-results]").classList.add("hidden");
      }
    });
    row.querySelector("[data-quality-provider-results]").addEventListener("mousedown", event => {
      const button = event.target.closest("[data-quality-provider-option]");
      if (!button) return;
      event.preventDefault();
      selectProvider(
        row,
        (providerResults.get(row) || [])[Number(button.dataset.qualityProviderOption)]
      );
    });
    row.querySelector("[data-use-proposed]").addEventListener("click", () => useProposed(row));
  });

  form.querySelectorAll("[data-bulk-disposition]").forEach(button =>
    button.addEventListener("click", () =>
      rows.forEach(row => setDisposition(row, button.dataset.bulkDisposition))));
  document.querySelector("#bulk-proposed").addEventListener("click", () =>
    rows.forEach(useProposed));
  document.querySelector("#bulk-pending").addEventListener("click", () => {
    rows.forEach(row => {
      row.querySelector("[data-resp-state]").value = "PENDIENTE";
      updateResponsibility(row);
    });
  });

  async function searchOperations(query) {
    clearTimeout(operationTimer);
    if (!query.trim()) return;
    operationTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/operaciones?q=${encodeURIComponent(query)}`);
        if (!response.ok) return;
        const data = await response.json();
        operations.innerHTML = data.map(item =>
          `<option value="${esc(item.codigo)} · ${esc(item.titulo)}"></option>`
        ).join("");
      } catch (_) {}
    }, 250);
  }

  form.addEventListener("submit", event => {
    rows.forEach(checkRow);
    const invalidRows = rows.filter(row => row.dataset.valid !== "true");
    if (invalidRows.length) {
      event.preventDefault();
      invalidRows
        .filter(row => row.dataset.detailValid !== "true")
        .forEach(row => setRowExpanded(row, true));
      const firstMissingComment = invalidRows.find(
        row => row.dataset.commentValid !== "true"
      );
      if (firstMissingComment) {
        firstMissingComment.querySelector("[data-quality-item-comment]").focus();
        firstMissingComment.scrollIntoView({behavior: "smooth", block: "center"});
      } else {
        invalidRows[0].scrollIntoView({behavior: "smooth", block: "center"});
      }
      window.alert("Revisá los renglones marcados antes de guardar.");
    }
  });
})();
