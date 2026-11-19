/* Submission feedback only; validation, retries and CSRF stay server-controlled. */
(() => {
  // After a server-side refusal, associate the visible error with the first
  // invalid field and move keyboard focus there. Validation stays on the server.
  const invalid = document.querySelector('[aria-invalid="true"]');
  if (invalid) invalid.focus();
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post' || event.defaultPrevented) return;
    let status = form.querySelector('[data-submit-status]');
    if (!status) {
      status = document.createElement('p');
      status.dataset.submitStatus = '';
      status.setAttribute('role', 'status');
      form.append(status);
    }
    status.textContent = 'Submitting… Keep this page open until the response arrives.';
    form.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('[data-submit-status]').forEach((status) => {
      status.closest('form').removeAttribute('aria-busy');
      status.remove();
    });
  });
})();
