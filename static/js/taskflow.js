/**
 * TaskFlow - Core Client JavaScript Utilities
 */

// CSRF Token Extractor
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

const csrftoken = getCookie('csrftoken');

// Toast Notification Dispatcher
function showToast(message, type = 'success') {
  if (typeof Swal !== 'undefined') {
    const Toast = Swal.mixin({
      toast: true,
      position: 'top-end',
      showConfirmButton: false,
      timer: 3000,
      timerProgressBar: true,
      didOpen: (toast) => {
        toast.addEventListener('mouseenter', Swal.stopTimer);
        toast.addEventListener('mouseleave', Swal.resumeTimer);
      }
    });
    Toast.fire({
      icon: type,
      title: message
    });
  } else {
    // Fallback alert
    alert(message);
  }
}

// Confirmation Dialog Helper
function confirmAction(options, callback) {
  if (typeof Swal !== 'undefined') {
    Swal.fire({
      title: options.title || 'Are you sure?',
      text: options.text || "You won't be able to revert this!",
      icon: options.icon || 'warning',
      showCancelButton: true,
      confirmButtonColor: '#4f46e5',
      cancelButtonColor: '#ef4444',
      confirmButtonText: options.confirmText || 'Yes, proceed',
      cancelButtonText: 'Cancel'
    }).then((result) => {
      if (result.isConfirmed && typeof callback === 'function') {
        callback();
      }
    });
  } else {
    if (confirm(options.title + "\n" + (options.text || ''))) {
      callback();
    }
  }
}

// Sidebar Mobile Toggle
document.addEventListener('DOMContentLoaded', () => {
  const updateChartTheme = () => {
    if (typeof Chart === 'undefined') return;
    const dark = document.documentElement.dataset.theme === 'dark';
    Chart.defaults.color = dark ? '#cbd5e1' : '#666';
    Chart.defaults.borderColor = dark ? '#303747' : '#e2e8f0';
    Object.values(Chart.instances || {}).forEach((chart) => chart.update());
  };
  updateChartTheme();
  window.addEventListener('taskflow:theme-changed', updateChartTheme);

  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('appSidebar');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.toggle('show');
      if (sidebarBackdrop) sidebarBackdrop.classList.toggle('d-none');
    });
  }

  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', () => {
      sidebar.classList.remove('show');
      sidebarBackdrop.classList.add('d-none');
    });
  }

  // Bind notification mark-all-read button in navbar
  const markAllReadBtn = document.getElementById('markAllReadNavbarBtn');
  if (markAllReadBtn) {
    markAllReadBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        const response = await fetch('/notifications/mark-all-read/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
          }
        });
        const data = await response.json();
        if (data.success) {
          const badge = document.getElementById('notificationBadge');
          if (badge) badge.style.display = 'none';
          document.querySelectorAll('.dropdown-item-notif.unread').forEach(el => {
            el.classList.remove('unread', 'bg-light');
          });
          showToast('All notifications marked as read.', 'success');
        }
      } catch (err) {
        console.error('Failed to mark notifications read', err);
      }
    });
  }

  const palette = document.getElementById('commandPalette');
  const paletteInput = document.getElementById('commandPaletteInput');
  const paletteResults = document.getElementById('commandPaletteResults');
  const paletteModal = palette && window.bootstrap
    ? bootstrap.Modal.getOrCreateInstance(palette)
    : null;
  let searchController = null;
  let selectedResult = 0;
  const isAdmin = palette?.dataset.isAdmin === 'true';
  const pageUrls = document.body.dataset;
  const commandPages = [
    { title: 'Dashboard', url: pageUrls.dashboardUrl, icon: 'bi-grid-1x2-fill', keywords: 'home overview' },
    { title: 'Kanban Board', url: pageUrls.kanbanUrl, icon: 'bi-kanban', keywords: 'board workflow' },
    { title: 'Calendar', url: pageUrls.calendarUrl, icon: 'bi-calendar3', keywords: 'due dates schedule' },
    { title: 'My Tasks', url: pageUrls.taskListUrl, icon: 'bi-check2-square', keywords: 'task list' }
  ];

  const activateSelectedResult = () => {
    const items = paletteResults?.querySelectorAll('[role="option"]');
    const item = items?.[selectedResult];
    if (item) item.click();
  };

  const setSelectedResult = (nextIndex) => {
    const items = paletteResults?.querySelectorAll('[role="option"]');
    if (!items?.length) return;
    selectedResult = (nextIndex + items.length) % items.length;
    items.forEach((item, index) => {
      item.setAttribute('aria-selected', String(index === selectedResult));
      item.classList.toggle('is-active', index === selectedResult);
    });
    paletteInput?.setAttribute('aria-activedescendant', items[selectedResult].id);
    items[selectedResult].scrollIntoView({ block: 'nearest' });
  };

  const addPaletteOption = (title, description, icon, action) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'command-palette-option';
    item.id = `command-palette-option-${paletteResults.childElementCount}`;
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', 'false');
    const iconElement = document.createElement('i');
    iconElement.className = `bi ${icon}`;
    iconElement.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('span');
    copy.className = 'command-palette-copy';
    const titleElement = document.createElement('strong');
    titleElement.textContent = title;
    const descriptionElement = document.createElement('small');
    descriptionElement.textContent = description;
    copy.append(titleElement, descriptionElement);
    item.append(iconElement, copy);
    item.addEventListener('click', action);
    paletteResults.appendChild(item);
  };

  const renderPalette = async (term = '') => {
    if (!paletteResults) return;
    if (searchController) searchController.abort();
    paletteResults.replaceChildren();
    paletteInput?.removeAttribute('aria-activedescendant');
    selectedResult = 0;
    const normalized = term.trim().toLowerCase();
    commandPages
      .filter((entry) => !normalized || `${entry.title} ${entry.keywords}`.toLowerCase().includes(normalized))
      .forEach((entry) => addPaletteOption(
        entry.title,
        'Go to page',
        entry.icon,
        () => { window.location.href = entry.url; }
      ));

    if (isAdmin && (!normalized || 'new task create'.includes(normalized))) {
      addPaletteOption('New task', 'Create a task', 'bi-plus-circle', () => {
        paletteModal?.hide();
        const quickModal = document.getElementById('quickNewTaskModal');
        if (quickModal && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(quickModal).show();
        } else {
          window.location.href = pageUrls.taskCreateUrl;
        }
      });
    }

    if (term.trim().length >= 2) {
      searchController = new AbortController();
      try {
        const endpoint = new URL(palette.dataset.searchUrl, window.location.origin);
        endpoint.searchParams.set('q', term.trim());
        const response = await fetch(endpoint, { signal: searchController.signal });
        if (!response.ok) throw new Error(`Search failed (${response.status}).`);
        const data = await response.json();
        data.results.forEach((task) => addPaletteOption(
          task.title,
          `${task.status} · ${task.priority}`,
          'bi-check2-square',
          () => { window.location.href = task.url; }
        ));
      } catch (error) {
        if (error.name !== 'AbortError') {
          const message = document.createElement('p');
          message.className = 'command-palette-message text-danger';
          message.setAttribute('role', 'alert');
          message.textContent = 'Task search is unavailable. Please try again.';
          paletteResults.appendChild(message);
          console.error(error);
        }
      }
    } else if (normalized && !commandPages.some((entry) => `${entry.title} ${entry.keywords}`.toLowerCase().includes(normalized))) {
      const message = document.createElement('p');
      message.className = 'command-palette-message';
      message.textContent = 'Type at least two characters to search tasks.';
      paletteResults.appendChild(message);
    }
    setSelectedResult(0);
  };

  if (palette && paletteInput) {
    palette.addEventListener('shown.bs.modal', () => {
      paletteInput.value = '';
      renderPalette();
      paletteInput.focus();
    });
    paletteInput.addEventListener('input', () => renderPalette(paletteInput.value));
    paletteInput.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSelectedResult(selectedResult + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSelectedResult(selectedResult - 1);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        activateSelectedResult();
      }
    });
    palette.addEventListener('hidden.bs.modal', () => {
      searchController?.abort();
      document.querySelector('.command-palette-trigger')?.focus();
    });
  }

});
