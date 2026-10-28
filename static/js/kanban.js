/**
 * TaskFlow - Interactive Kanban Board with SortableJS
 */

document.addEventListener('DOMContentLoaded', () => {
  const columns = document.querySelectorAll('.kanban-card-list');
  if (!columns.length) return;

  function updateColumnCounts() {
    ['TODO', 'IN_PROGRESS', 'COMPLETED'].forEach(status => {
      const col = document.querySelector(`.kanban-column[data-status="${status}"]`);
      if (col) {
        const count = col.querySelectorAll('.kanban-card').length;
        const countBadge = col.querySelector('.column-count-badge');
        if (countBadge) countBadge.textContent = count;

        const emptyPlaceholder = col.querySelector('.kanban-empty-placeholder');
        if (emptyPlaceholder) {
          emptyPlaceholder.style.display = count === 0 ? 'block' : 'none';
        }
      }
    });
  }

  function restoreCardPosition(list, item, oldIndex) {
    const originalPosition = list.children[oldIndex];
    list.insertBefore(item, originalPosition || null);
    updateColumnCounts();
  }

  columns.forEach(col => {
    new Sortable(col, {
      group: 'taskflow-kanban',
      animation: 180,
      delay: 150,
      delayOnTouchOnly: true,
      touchStartThreshold: 5,
      fallbackTolerance: 5,
      draggable: '.kanban-card',
      ghostClass: 'sortable-ghost',
      chosenClass: 'sortable-chosen',
      dragClass: 'sortable-drag',
      handle: '.kanban-card-drag-handle',
      onEnd: async function (evt) {
        const itemEl = evt.item;
        const taskId = itemEl.getAttribute('data-task-id');
        const newStatus = evt.to.getAttribute('data-status');
        const oldStatus = evt.from.getAttribute('data-status');

        if (newStatus === oldStatus) return;

        // Optimistically update counts
        updateColumnCounts();

        try {
          const response = await fetch(`/api/v1/tasks/${taskId}/update-status/`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ status: newStatus })
          });

          const data = await response.json();

          if (!response.ok) {
            // Revert card position on error
            restoreCardPosition(evt.from, itemEl, evt.oldIndex);
            showToast(data.detail || 'Failed to update task status.', 'error');
            return;
          }

          // Visual feedback
          showToast(`Task moved to ${data.status_display}`, 'success');

          // If moved to completed, update badge styling inside card
          const statusBadge = itemEl.querySelector('.task-status-badge');
          if (statusBadge) {
            statusBadge.className = `badge task-status-badge badge-status-${newStatus.toLowerCase().replace('_', '-')}`;
            statusBadge.textContent = data.status_display;
          }

        } catch (error) {
          console.error('Network error during status update:', error);
          restoreCardPosition(evt.from, itemEl, evt.oldIndex);
          showToast('Network error while updating status.', 'error');
        }
      }
    });
  });

  updateColumnCounts();
});
