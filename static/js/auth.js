document.querySelectorAll('[data-password-toggle]').forEach((button) => {
  const password = document.getElementById(button.dataset.passwordToggle);
  const icon = button.querySelector('i');

  if (!password || !icon) {
    return;
  }

  button.addEventListener('click', () => {
    const showPassword = password.type === 'password';
    password.type = showPassword ? 'text' : 'password';
    button.setAttribute('aria-label', showPassword ? 'Hide password' : 'Show password');
    button.setAttribute('aria-pressed', String(showPassword));
    icon.className = showPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
  });
});

const registerForm = document.getElementById('registerForm');
if (registerForm) {
  const role = registerForm.querySelector('#id_role');
  const adminCodeField = registerForm.querySelector('#adminAccessCodeField');
  const adminCode = registerForm.querySelector('#id_admin_access_code');

  const toggleAdminCode = () => {
    const showAdminCode = role.value === 'ADMIN';
    adminCodeField.hidden = !showAdminCode;
    if (!showAdminCode) {
      adminCode.value = '';
    }
  };

  role.addEventListener('change', toggleAdminCode);
  toggleAdminCode();

  const password = registerForm.querySelector('#id_password');
  const confirmation = registerForm.querySelector('#id_confirm_password');
  const confirmationError = registerForm.querySelector('#confirm_password-error');

  const validatePasswordMatch = () => {
    const passwordsMatch = !password.value || !confirmation.value || password.value === confirmation.value;
    const message = passwordsMatch ? '' : 'Passwords do not match.';

    confirmation.setCustomValidity(message);
    confirmation.setAttribute('aria-invalid', String(!passwordsMatch));
    confirmationError.textContent = message;
  };

  password.addEventListener('input', validatePasswordMatch);
  confirmation.addEventListener('input', validatePasswordMatch);
}

document.querySelectorAll('.auth-form').forEach((form) => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (!button) {
      return;
    }

    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.classList.add('is-loading');
    button.querySelector('.submit-label').textContent = 'Please wait...';
  });
});
