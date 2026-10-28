(() => {
  const notifyThemeChange = (theme) => {
    window.dispatchEvent(new CustomEvent('taskflow:theme-changed', { detail: { theme } }));
  };

  const updateButtons = () => {
    const dark = document.documentElement.dataset.theme === 'dark';
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      button.setAttribute('title', dark ? 'Switch to light mode' : 'Switch to dark mode');
      button.innerHTML = dark
        ? '<i class="bi bi-sun-fill" aria-hidden="true"></i><span class="visually-hidden">Switch to light mode</span>'
        : '<i class="bi bi-moon-stars-fill" aria-hidden="true"></i><span class="visually-hidden">Switch to dark mode</span>';
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    updateButtons();
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.addEventListener('click', () => {
        const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = theme;
        document.documentElement.dataset.bsTheme = theme;
        try {
          localStorage.setItem('taskflow-theme', theme);
        } catch (error) {
          console.warn('Unable to persist the TaskFlow theme preference.', error);
        }
        updateButtons();
        notifyThemeChange(theme);
      });
    });

    const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
    systemTheme.addEventListener('change', (event) => {
      try {
        if (localStorage.getItem('taskflow-theme')) return;
      } catch (error) {
        console.warn('Unable to read the TaskFlow theme preference.', error);
      }
      const theme = event.matches ? 'dark' : 'light';
      document.documentElement.dataset.theme = theme;
      document.documentElement.dataset.bsTheme = theme;
      updateButtons();
      notifyThemeChange(theme);
    });
  });
})();
