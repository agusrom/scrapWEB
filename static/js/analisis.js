(() => {
  const form = document.querySelector('#analysis-filters');
  if (!form) return;
  const from = form.elements.desde;
  const until = form.elements.hasta;
  function validateDates() {
    until.setCustomValidity(from.value && until.value && from.value > until.value
      ? 'La fecha hasta debe ser posterior o igual a desde.' : '');
  }
  from.addEventListener('input', validateDates);
  until.addEventListener('input', validateDates);
  validateDates();
})();
