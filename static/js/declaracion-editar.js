(() => {
  const form = document.querySelector('.admin-declaration-form');
  if (!form) return;
  function validate() {
    form.querySelectorAll('[data-admin-item]').forEach(row => {
      const field = suffix => row.querySelector(`[name$="_${suffix}"]`);
      const total = field('cantidad_detectada');
      const scrap = field('cantidad_scrap_directo');
      const rework = field('cantidad_a_retrabajo');
      const released = field('cantidad_liberada');
      const step = field('unidad').value.trim().toUpperCase() === 'PZS' ? '1' : '0.001';
      total.min = step;
      [total, scrap, rework, released].filter(Boolean).forEach(input => {
        input.step = step;
        input.setCustomValidity('');
      });
      if (rework) {
        if (Number(rework.value) < Number(row.dataset.resolved)) {
          rework.setCustomValidity('El retrabajo no puede ser menor que la cantidad ya procesada.');
        } else if (Math.abs(Number(scrap.value) + Number(rework.value) + Number(released.value) - Number(total.value)) > 0.0001) {
          total.setCustomValidity('Scrap + retrabajo + liberadas debe coincidir con la cantidad informada.');
        }
      }
    });
  }
  form.addEventListener('invalid', event => {
    const row = event.target.closest('[data-admin-item]');
    if (row) row.open = true;
  }, true);
  form.addEventListener('input', validate);
  form.addEventListener('submit', event => {
    validate();
    if (!form.checkValidity()) {
      event.preventDefault();
      form.querySelectorAll('[data-admin-item]').forEach(row => {
        if (row.querySelector(':invalid')) row.open = true;
      });
      form.reportValidity();
    }
  });
  validate();
})();
