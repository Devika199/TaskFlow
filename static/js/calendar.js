/**
 * TaskFlow - Interactive Calendar Drag-and-Drop Rescheduling with SortableJS
 */

document.addEventListener('DOMContentLoaded', () => {
  const dropzones = document.querySelectorAll('[data-calendar-dropzone="true"]');
  if (!dropzones.length || typeof Sortable === 'undefined') return;

  function restoreTaskPosition(container, item, oldIndex) {
    const children = Array.from(container.children).filter(el => !el.classList.contains('calendar-week-empty-slot'));
    const referenceNode = children[oldIndex] || null;
    container.insertBefore(item, referenceNode);
  }

  function updateEmptyPlaceholders() {
    document.querySelectorAll('.calendar-week-col').forEach(col => {
      const taskList = col.querySelector('.calendar-week-task-list');
      if (!taskList) return;
      const cards = taskList.querySelectorAll('.calendar-week-task-card');
      let emptySlot = taskList.querySelector('.calendar-week-empty-slot');
      if (cards.length === 0) {
        if (!emptySlot) {
          emptySlot = document.createElement('div');
          emptySlot.className = 'calendar-week-empty-slot text-center py-4 text-muted small';
          emptySlot.innerHTML = '<span>No tasks</span>';
          taskList.appendChild(emptySlot);
        }
        emptySlot.style.display = 'block';
      } else if (emptySlot) {
        emptySlot.style.display = 'none';
      }
    });
  }

  function highlightDropzones(active) {
    dropzones.forEach(dz => {
      if (active) {
        dz.classList.add('calendar-dropzone-active');
      } else {
        dz.classList.remove('calendar-dropzone-active');
      }
    });
  }

  dropzones.forEach(dropzone => {
    // Avoid initializing SortableJS more than once on the same element
    if (Sortable.get(dropzone)) return;

    new Sortable(dropzone, {
      group: 'taskflow-calendar-reschedule',
      animation: 160,
      delay: 150,
      delayOnTouchOnly: true,
      touchStartThreshold: 5,
      fallbackTolerance: 5,
      draggable: '.calendar-task[data-can-edit="true"], .calendar-week-task-card[data-can-edit="true"]',
      handle: '.calendar-drag-handle',
      filter: '.calendar-week-empty-slot, a',
      preventOnFilter: false,
      ghostClass: 'calendar-sortable-ghost',
      chosenClass: 'calendar-sortable-chosen',
      dragClass: 'calendar-sortable-drag',
      onStart: function () {
        highlightDropzones(true);
      },
      onEnd: async function (evt) {
        highlightDropzones(false);

        const itemEl = evt.item;
        const fromDropzone = evt.from;
        const toDropzone = evt.to;
        const oldDate = fromDropzone.getAttribute('data-date');
        const newDate = toDropzone.getAttribute('data-date');
        const taskId = itemEl.getAttribute('data-task-id');
        const rescheduleUrl = itemEl.getAttribute('data-reschedule-url') || `/tasks/${taskId}/reschedule/`;

        // If dropped back in the same date dropzone, do nothing
        if (oldDate === newDate) {
          updateEmptyPlaceholders();
          return;
        }

        // Prevent duplicate submissions
        if (itemEl.classList.contains('is-rescheduling')) {
          return;
        }

        // Set pending visual feedback
        itemEl.classList.add('is-rescheduling');
        updateEmptyPlaceholders();

        try {
          const csrfToken = (typeof getCookie === 'function' ? getCookie('csrftoken') : null) ||
            (document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').getAttribute('content') : '') ||
            '';

          const response = await fetch(rescheduleUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrfToken,
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ due_date: newDate })
          });

          const data = await response.json();

          if (!response.ok || !data.success) {
            restoreTaskPosition(fromDropzone, itemEl, evt.oldIndex);
            const errorMsg = (data && (data.error || data.detail || data.message)) || 'Failed to reschedule task.';
            if (typeof showToast === 'function') {
              showToast(errorMsg, 'error');
            } else {
              alert(errorMsg);
            }
            return;
          }

          // Visual feedback on success
          const successMsg = data.message || `Task rescheduled to ${newDate}.`;
          if (typeof showToast === 'function') {
            showToast(successMsg, 'success');
          }

        } catch (error) {
          console.error('Network error during task rescheduling:', error);
          restoreTaskPosition(fromDropzone, itemEl, evt.oldIndex);
          if (typeof showToast === 'function') {
            showToast('Network error while rescheduling task.', 'error');
          } else {
            alert('Network error while rescheduling task.');
          }
        } finally {
          itemEl.classList.remove('is-rescheduling');
          updateEmptyPlaceholders();
        }
      }
    });
  });

  updateEmptyPlaceholders();
});

