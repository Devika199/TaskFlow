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
});
