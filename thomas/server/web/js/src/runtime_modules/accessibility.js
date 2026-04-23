/**
 * WCAG 2.1 AA Accessibility Module for Thomas
 * Provides runtime accessibility features including keyboard navigation,
 * ARIA live regions, focus management, and dynamic accessibility enhancements.
 */

export default `
(function initializeAccessibility() {
  'use strict';

  console.log('[Thomas] Initializing accessibility features...');

  // =========================================================================
  // 1. SKIP NAVIGATION LINK - Wire up skip link functionality
  // =========================================================================

  function initializeSkipLink() {
    const skipLink = document.querySelector('.skip-to-main-content');
    if (!skipLink) {
      // Create skip link if it doesn't exist
      const link = document.createElement('a');
      link.href = '#main-content';
      link.className = 'skip-to-main-content';
      link.textContent = 'Skip to main content';
      document.body.insertBefore(link, document.body.firstChild);
    }

    // Wire up click handler
    document.querySelector('.skip-to-main-content')?.addEventListener('click', (e) => {
      e.preventDefault();
      const main = document.querySelector('#main-content') || document.querySelector('main');
      if (main) {
        main.focus();
        main.scrollIntoView({ behavior: 'smooth' });
      }
    });
  }

  // =========================================================================
  // 2. KEYBOARD NAVIGATION - Tab order and Enter/Space activation
  // =========================================================================

  function initializeKeyboardNavigation() {
    document.addEventListener('keydown', (e) => {
      const target = e.target;

      // Enter/Space activation for custom buttons and elements with role="button"
      if ((e.key === 'Enter' || e.key === ' ') && target.getAttribute('role') === 'button') {
        e.preventDefault();
        target.click();
      }

      // Escape key to close modals
      if (e.key === 'Escape') {
        closeOpenModals();
      }

      // Tab key management - focus trap in modals
      if (e.key === 'Tab') {
        manageFocusInModal(e);
      }
    });
  }

  // Focus trap within modals
  function manageFocusInModal(e) {
    const openModal = document.querySelector('[role="dialog"][open], .modal:not([hidden])');
    if (!openModal) return;

    const focusableElements = openModal.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );

    if (focusableElements.length === 0) return;

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      }
    } else {
      if (document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }
  }

  // Close all open modals
  function closeOpenModals() {
    document.querySelectorAll('[role="dialog"], .modal').forEach((modal) => {
      modal.setAttribute('hidden', '');
      modal.removeAttribute('open');
      modal.style.display = 'none';
    });
  }

  // =========================================================================
  // 3. ARIA LIVE REGIONS - Announce status changes to screen readers
  // =========================================================================

  let liveRegion = null;
  let politeRegion = null;

  function initializeLiveRegions() {
    // Create assertive live region for important announcements
    liveRegion = document.createElement('div');
    liveRegion.setAttribute('role', 'log');
    liveRegion.setAttribute('aria-live', 'assertive');
    liveRegion.setAttribute('aria-atomic', 'true');
    liveRegion.className = 'sr-only';
    document.body.appendChild(liveRegion);

    // Create polite live region for less urgent announcements
    politeRegion = document.createElement('div');
    politeRegion.setAttribute('role', 'status');
    politeRegion.setAttribute('aria-live', 'polite');
    politeRegion.setAttribute('aria-atomic', 'true');
    politeRegion.className = 'sr-only';
    document.body.appendChild(politeRegion);
  }

  /**
   * Announce a message to screen readers
   * @param {string} message - The message to announce
   * @param {boolean} assertive - If true, use assertive; if false, use polite
   */
  window.announceToScreenReader = function (message, assertive = false) {
    const region = assertive ? liveRegion : politeRegion;
    if (region) {
      region.textContent = message;
      // Clear after announcement
      setTimeout(() => {
        region.textContent = '';
      }, 3000);
    }
  };

  // =========================================================================
  // 4. CHAT INTERFACE ENHANCEMENTS - Proper ARIA roles and labels
  // =========================================================================

  function enhanceChatInterface() {
    // Make chat container a log region for messages
    const chatMessages = document.querySelector('[class*="chat-messages"], #messages, .messages');
    if (chatMessages && !chatMessages.getAttribute('role')) {
      chatMessages.setAttribute('role', 'log');
      chatMessages.setAttribute('aria-live', 'polite');
      chatMessages.setAttribute('aria-label', 'Chat messages');
    }

    // Enhance individual chat messages
    document.querySelectorAll('[class*="message"], .chat-message, [role="article"]').forEach((msg) => {
      if (!msg.getAttribute('role')) {
        msg.setAttribute('role', 'article');
      }

      // Add aria-label with sender and time if available
      const sender = msg.getAttribute('data-sender') || msg.querySelector('[class*="sender"]')?.textContent;
      const time = msg.getAttribute('data-time') || msg.querySelector('[class*="time"]')?.textContent;

      if (sender && !msg.getAttribute('aria-label')) {
        const label = time ? \`Message from \${sender} at \${time}\` : \`Message from \${sender}\`;
        msg.setAttribute('aria-label', label);
      }
    });

    // Ensure send button has proper label
    const sendButton = document.querySelector('[class*="send"], button[aria-label*="send"], button[title*="Send"]');
    if (sendButton && !sendButton.getAttribute('aria-label')) {
      sendButton.setAttribute('aria-label', 'Send message');
    }

    // Ensure input has proper label
    const chatInput = document.querySelector('input[placeholder*="message"], textarea[placeholder*="message"]');
    if (chatInput && !chatInput.getAttribute('aria-label')) {
      chatInput.setAttribute('aria-label', 'Message input');
    }
  }

  // =========================================================================
  // 5. SETTINGS PANEL - Proper dialog role and modal attributes
  // =========================================================================

  function enhanceSettingsPanel() {
    const settingsPanel = document.querySelector('[id*="settings"], .settings-panel, [class*="settings"]');
    if (settingsPanel) {
      if (!settingsPanel.getAttribute('role')) {
        settingsPanel.setAttribute('role', 'dialog');
        settingsPanel.setAttribute('aria-modal', 'true');
        settingsPanel.setAttribute('aria-label', 'Settings');
      }

      // Find and enhance close button
      const closeBtn = settingsPanel.querySelector('button[class*="close"], [aria-label*="close"]');
      if (closeBtn && !closeBtn.getAttribute('aria-label')) {
        closeBtn.setAttribute('aria-label', 'Close settings');
      }
    }
  }

  // =========================================================================
  // 6. OFFICE WORKSPACE - Proper application role
  // =========================================================================

  function enhanceOfficeWorkspace() {
    const officeContainer = document.querySelector('[id*="office"], [class*="office"], [class*="workspace"]');
    if (officeContainer && !officeContainer.getAttribute('role')) {
      officeContainer.setAttribute('role', 'application');
      officeContainer.setAttribute('aria-label', 'Virtual office workspace');
    }
  }

  // =========================================================================
  // 7. AUTO-LABEL UNLABELED INPUTS - Find inputs without labels
  // =========================================================================

  function autoLabelUnlabeledInputs() {
    document.querySelectorAll('input, textarea, select').forEach((input) => {
      // Skip if already has label
      if (input.getAttribute('aria-label') || input.closest('label')) {
        return;
      }

      let label = '';

      // Try to get label from placeholder
      if (input.placeholder) {
        label = input.placeholder;
      }

      // Try to get label from nearby label element
      if (!label && input.id) {
        const associatedLabel = document.querySelector(\`label[for="\${input.id}"]\`);
        if (associatedLabel) {
          label = associatedLabel.textContent;
        }
      }

      // Try to get label from data attributes
      if (!label && input.dataset.label) {
        label = input.dataset.label;
      }

      // Set aria-label if we found a label
      if (label) {
        input.setAttribute('aria-label', label);
      } else if (input.type !== 'hidden') {
        // Default label for inputs without any label
        input.setAttribute('aria-label', \`\${input.type} field\`);
      }
    });
  }

  // =========================================================================
  // 8. ANNOUNCE ROUTE CHANGES - When switching between tabs/pages
  // =========================================================================

  function announceRouteChanges() {
    // Watch for tab/panel changes
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        // Check for active tab changes
        if (mutation.attributeName === 'class' || mutation.attributeName === 'aria-selected') {
          const target = mutation.target;
          if (target.getAttribute('aria-selected') === 'true') {
            const label = target.getAttribute('aria-label') || target.textContent;
            if (label) {
              window.announceToScreenReader(\`Switched to \${label}\`);
            }
          }
        }
      });
    });

    // Watch navigation buttons
    document.querySelectorAll('[role="tab"], .nav-item, [class*="nav"]').forEach((nav) => {
      observer.observe(nav, {
        attributes: true,
        attributeFilter: ['class', 'aria-selected'],
      });
    });
  }

  // =========================================================================
  // 9. FORM VALIDATION - Enhance error announcements
  // =========================================================================

  function enhanceFormValidation() {
    document.querySelectorAll('form').forEach((form) => {
      form.addEventListener('submit', (e) => {
        const invalidInputs = form.querySelectorAll(':invalid, [aria-invalid="true"]');
        if (invalidInputs.length > 0) {
          window.announceToScreenReader(
            \`Form has \${invalidInputs.length} error\${invalidInputs.length !== 1 ? 's' : ''}\`,
            true
          );
          invalidInputs[0].focus();
        }
      });

      // Real-time validation announcements
      form.querySelectorAll('input, textarea, select').forEach((field) => {
        field.addEventListener('blur', () => {
          if (field.hasAttribute('required') && !field.value) {
            field.setAttribute('aria-invalid', 'true');
            const errorMsg = \`\${field.getAttribute('aria-label') || 'This field'} is required\`;
            window.announceToScreenReader(errorMsg);
          } else {
            field.setAttribute('aria-invalid', 'false');
          }
        });
      });
    });
  }

  // =========================================================================
  // 10. REDUCED MOTION SUPPORT - Respect user preferences
  // =========================================================================

  function handleReducedMotion() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      document.documentElement.classList.add('no-motion');
    }

    // Listen for changes
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (e) => {
      if (e.matches) {
        document.documentElement.classList.add('no-motion');
      } else {
        document.documentElement.classList.remove('no-motion');
      }
    });
  }

  // =========================================================================
  // 11. INITIALIZATION - Call all setup functions
  // =========================================================================

  function initializeAllAccessibilityFeatures() {
    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', run);
    } else {
      run();
    }

    function run() {
      initializeSkipLink();
      initializeLiveRegions();
      initializeKeyboardNavigation();
      enhanceChatInterface();
      enhanceSettingsPanel();
      enhanceOfficeWorkspace();
      autoLabelUnlabeledInputs();
      announceRouteChanges();
      enhanceFormValidation();
      handleReducedMotion();

      console.log('[Thomas] Accessibility features initialized successfully');

      // Re-run enhancement functions when content is dynamically added
      const contentObserver = new MutationObserver(() => {
        enhanceChatInterface();
        enhanceSettingsPanel();
        autoLabelUnlabeledInputs();
      });

      contentObserver.observe(document.body, {
        childList: true,
        subtree: true,
      });
    }
  }

  // Start initialization
  initializeAllAccessibilityFeatures();
})();
`;
