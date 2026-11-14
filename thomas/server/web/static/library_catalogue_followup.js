// A partial first list must be replaced by the existing Library renderer when ready.
(function () {
    var checking = false;
    var completed = false;

    async function check() {
        if (checking || completed) return;
        checking = true;
        try {
            var button = document.getElementById('refreshButton');
            if (!button) return;
            var response = await fetch('/api/local/projects');
            if (response.status === 404) completed = true; // the list is turned off: stop asking
            if (!response.ok) return;
            var listing = await response.json();
            if (listing.refreshing) return;
            completed = true;
            button.click();
        } catch (_error) {
            // Retry a transient failure without replacing the Library's own error UI.
        } finally {
            checking = false;
            if (!completed) setTimeout(check, 1100);
        }
    }

    window.addEventListener('DOMContentLoaded', function () {
        setTimeout(check, 1100);
    });
})();
