(() => {
  /**
   * Helper to get CSRF token from page cookie or hidden input
   */
  const getCsrfToken = (root) => {
    const input = root?.querySelector("[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    const cookieMatch = document.cookie.match(/csrftoken=([^;]+)/);
    return cookieMatch ? cookieMatch[1] : "";
  };

  /**
   * Safe text escaper and basic formatter for assistant responses
   */
  const formatAssistantText = (text) => {
    if (!text) return "";
    const container = document.createElement("div");
    // Escape HTML first
    const escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Format simple code blocks `code`
    const withCode = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Format bold **bold**
    const withBold = withCode.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

    // Format line breaks
    container.innerHTML = withBold.replace(/\n/g, "<br>");
    return container.innerHTML;
  };

  /**
   * Controller instance for an assistant interface (drawer or full page)
   */
  class AssistantController {
    constructor(root) {
      this.root = root;
      this.form = root.querySelector("form.assistant-composer, form.assistant-composer-form, #assistantForm, #drawerAssistantForm");
      this.input = root.querySelector("textarea");
      this.sendButton = root.querySelector("button[type=submit]");
      this.messages = root.querySelector(".assistant-messages, #assistantMessages, #drawerAssistantMessages");
      this.errorBox = root.querySelector(".assistant-error, #assistantError, #drawerAssistantError");
      this.confirmation = root.querySelector(".assistant-confirmation, #assistantConfirmation, #drawerAssistantConfirmation");
      this.confirmationText = root.querySelector(".assistant-confirmation-body, #assistantConfirmationText, #drawerAssistantConfirmationText");
      this.confirmBtn = root.querySelector("#assistantConfirmButton, #drawerAssistantConfirmBtn");
      this.cancelBtn = root.querySelector("#assistantCancelButton, #drawerAssistantCancelBtn");
      this.loadingIndicator = root.querySelector(".assistant-loading-indicator, #drawerAssistantLoading, #assistantLoading");
      this.charCount = root.querySelector(".char-count");
      this.endpoint = root.dataset.chatUrl || "/assistant/message/";
      this.actionId = null;
      this.busy = false;

      if (!this.form || !this.input || !this.messages) return;

      this.initEvents();
    }

    initEvents() {
      this.form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (this.busy) return;
        const msg = this.input.value.trim();
        if (!msg) return;
        this.input.value = "";
        this.updateCharCount();
        this.submitMessage(msg);
      });

      this.input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this.form.requestSubmit();
        }
      });

      this.input.addEventListener("input", () => {
        this.updateCharCount();
        this.autoResizeTextarea();
      });

      if (this.confirmBtn) {
        this.confirmBtn.addEventListener("click", () => this.confirmAction(true));
      }
      if (this.cancelBtn) {
        this.cancelBtn.addEventListener("click", () => this.confirmAction(false));
      }

      // Quick chips within this container
      this.root.querySelectorAll("[data-quick-prompt]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          const prompt = btn.dataset.quickPrompt;
          if (prompt && !this.busy) {
            this.input.value = prompt;
            this.updateCharCount();
            this.form.requestSubmit();
          }
        });
      });
    }

    autoResizeTextarea() {
      if (!this.input) return;
      this.input.style.height = "auto";
      this.input.style.height = `${Math.min(this.input.scrollHeight, 160)}px`;
    }

    updateCharCount() {
      if (!this.charCount || !this.input) return;
      const len = this.input.value.length;
      this.charCount.textContent = `${len}/4000`;
    }

    showError(text) {
      if (!this.errorBox) return;
      if (!text) {
        this.errorBox.textContent = "";
        this.errorBox.hidden = true;
        this.errorBox.classList.add("d-none");
      } else {
        this.errorBox.textContent = text;
        this.errorBox.hidden = false;
        this.errorBox.classList.remove("d-none");
      }
    }

    setBusy(value) {
      this.busy = value;
      if (this.sendButton) this.sendButton.disabled = value;
      if (this.input) this.input.disabled = value;
      if (this.confirmBtn) this.confirmBtn.disabled = value;
      if (this.cancelBtn) this.cancelBtn.disabled = value;

      if (this.loadingIndicator) {
        if (value) {
          this.loadingIndicator.classList.remove("d-none");
          this.loadingIndicator.hidden = false;
        } else {
          this.loadingIndicator.classList.add("d-none");
          this.loadingIndicator.hidden = true;
        }
      }
    }

    appendMessage(role, text) {
      const article = document.createElement("article");
      article.className = `assistant-message assistant-message-${role}`;

      const label = document.createElement("div");
      label.className = "assistant-message-label";
      if (role === "user") {
        label.innerHTML = '<i class="bi bi-person-fill"></i> You';
      } else {
        label.innerHTML = '<i class="bi bi-stars text-primary"></i> TaskFlow Assistant';
      }

      const body = document.createElement("div");
      body.className = "assistant-message-body";
      body.innerHTML = formatAssistantText(text);

      article.append(label, body);
      this.messages.appendChild(article);
      this.messages.scrollTop = this.messages.scrollHeight;
    }

    async post(payload) {
      const csrf = getCsrfToken(this.root);
      const response = await fetch(this.endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
        },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "The request could not be completed.");
      }
      return result;
    }

    handleResult(result) {
      if (result.status === "confirmation_required") {
        this.actionId = result.action_id;
        if (this.confirmationText) {
          this.confirmationText.textContent = result.confirmation;
        }
        if (this.confirmation) {
          this.confirmation.hidden = false;
          this.confirmation.classList.remove("d-none");
        }
        if (this.confirmBtn) this.confirmBtn.focus();
        return;
      }

      this.actionId = null;
      if (this.confirmation) {
        this.confirmation.hidden = true;
        this.confirmation.classList.add("d-none");
      }
      this.appendMessage("model", result.message);
    }

    async submitMessage(message) {
      this.setBusy(true);
      this.showError("");
      this.appendMessage("user", message);
      try {
        const result = await this.post({ message });
        this.handleResult(result);
      } catch (err) {
        this.showError(err.message);
      } finally {
        this.setBusy(false);
        if (!this.actionId && this.input) {
          this.input.focus();
        }
      }
    }

    async confirmAction(confirm) {
      if (!this.actionId || this.busy) return;
      this.setBusy(true);
      this.showError("");
      const actionToConfirm = this.actionId;
      try {
        const result = await this.post({ action_id: actionToConfirm, confirm });
        this.handleResult(result);
      } catch (err) {
        this.actionId = null;
        if (this.confirmation) {
          this.confirmation.hidden = true;
          this.confirmation.classList.add("d-none");
        }
        this.showError(err.message);
      } finally {
        this.setBusy(false);
        if (!this.actionId && this.input) {
          this.input.focus();
        }
      }
    }
  }

  // Initialize on page load
  document.addEventListener("DOMContentLoaded", () => {
    let activeDrawerController = null;
    let activePageController = null;

    // Standalone page
    const pageEl = document.querySelector(".assistant-page");
    if (pageEl) {
      activePageController = new AssistantController(pageEl);
    }

    // Drawer component
    const drawerEl = document.getElementById("aiAssistantDrawer");
    if (drawerEl) {
      activeDrawerController = new AssistantController(drawerEl);
    }

    // Global Copilot chips (e.g. on Dashboard)
    document.querySelectorAll("[data-assistant-prompt]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const prompt = btn.dataset.assistantPrompt;
        if (!prompt) return;

        // If on assistant page, use page controller
        if (activePageController) {
          activePageController.input.value = prompt;
          activePageController.form.requestSubmit();
          return;
        }

        // Otherwise open the drawer
        if (drawerEl && window.bootstrap?.Offcanvas) {
          const offcanvasInstance = window.bootstrap.Offcanvas.getOrCreateInstance(drawerEl);
          offcanvasInstance.show();
          if (activeDrawerController) {
            activeDrawerController.input.value = prompt;
            setTimeout(() => {
              activeDrawerController.form.requestSubmit();
            }, 300);
          }
        }
      });
    });

    // Keyboard shortcut: Ctrl + J or Alt + A to toggle assistant drawer
    document.addEventListener("keydown", (e) => {
      const isTyping = e.target instanceof HTMLElement &&
        (e.target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName));
      if (isTyping) return;

      if ((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")) {
        e.preventDefault();
        if (drawerEl && window.bootstrap?.Offcanvas) {
          const offcanvasInstance = window.bootstrap.Offcanvas.getOrCreateInstance(drawerEl);
          offcanvasInstance.toggle();
        }
      }
    });
  });
})();
