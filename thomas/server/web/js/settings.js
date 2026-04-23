(() => {
  const endpoint = "/api/preferences";
  async function loadPreferences() {
    const response = await fetch(endpoint, { method: "GET", headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`Failed to load preferences: ${response.status}`);
    }
    return response.json();
  }

  window.THOMAS_SETTINGS_API = {
    endpoint,
    loadPreferences,
  };
})();
