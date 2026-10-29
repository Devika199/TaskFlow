(() => {
  const palette = document.getElementById('commandPalette');
  const shortcutsHelp = document.getElementById('shortcutsHelp');
  const isAdmin = palette?.dataset.isAdmin === 'true';
  const urls = document.body.dataset;
  let lastGPress = 0;

  const isTypingTarget = (target) => target instanceof HTMLElement
    && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));

  const showModal = (element) => {
    if (element && window.bootstrap?.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(element).show();
    }
  };

  document.addEventListener('keydown', (event) => {
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === 'k') {
      event.preventDefault();
      event.stopPropagation();
      showModal(palette);
      return;
    }

    if (isTypingTarget(event.target) || event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }

    if (key === '?') {
      event.preventDefault();
      showModal(shortcutsHelp);
      return;
    }

    const now = Date.now();
    if (key === 'g') {
      lastGPress = now;
      return;
    }

    if (lastGPress && now - lastGPress <= 1000) {
      lastGPress = 0;
      if (key === 'd') {
        window.location.href = urls.dashboardUrl;
      } else if (key === 'k') {
        window.location.href = urls.kanbanUrl;
      }
      return;
    }

    lastGPress = 0;
    if (isAdmin && key === 'n') {
      const quickTaskModal = document.getElementById('quickNewTaskModal');
      if (quickTaskModal) {
        showModal(quickTaskModal);
      } else {
        window.location.href = urls.taskCreateUrl;
      }
    }
  }, true);
})();
