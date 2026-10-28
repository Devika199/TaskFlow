(function () {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const navCollapse = document.getElementById('landingNav');

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', (event) => {
      const id = anchor.getAttribute('href');
      if (!id || id === '#') {
        return;
      }
      const target = document.querySelector(id);
      if (!target) {
        return;
      }
      event.preventDefault();
      target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      if (typeof target.focus === 'function') {
        target.setAttribute('tabindex', '-1');
        target.focus({ preventScroll: true });
      }
      if (navCollapse && navCollapse.classList.contains('show') && window.bootstrap) {
        window.bootstrap.Collapse.getOrCreateInstance(navCollapse).hide();
      }
    });
  });
})();
