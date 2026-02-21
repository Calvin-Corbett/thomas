/**
 * Legacy entrypoint shim.
 *
 * The active chat UI uses /static/js/app.js. This file remains so older links to
 * /static/app.js do not crash when DOM ids change.
 */
(() => {
  const hasModernChatDom = Boolean(document.getElementById("composerTextarea"));
  if (hasModernChatDom) {
    return;
  }

  const script = document.createElement("script");
  script.type = "module";
  script.src = "/static/js/app.js";
  document.head.appendChild(script);
})();
