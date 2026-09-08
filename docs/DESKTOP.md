# Desktop application

Thomas includes an optional Electron desktop shell under `desktop/`. It connects to the same local Thomas server used by the browser interface.

## Start on Windows

1. Complete the browser setup using `run-ui.cmd`.
2. Run `desktop.cmd` from the source checkout.
3. Keep the local Thomas server available while using the application.

Node.js and npm are needed for the desktop dependency setup. See `desktop/package.json` for the pinned Electron version and supported scripts.

## Application-control restrictions

Windows application-control policies may block an unsigned desktop build. If the shell does not launch, use `http://127.0.0.1:8899` in your browser. Follow your organization's software approval process for desktop installation.

## Implementation

- `desktop/main.js`: main process and window lifecycle.
- `desktop/preload.js`: controlled bridge between renderer and desktop functions.
- `thomas/server/web/`: browser workspace and UI.

Browser-based pages cannot provide every capability of an Electron window. Some sites also prevent embedding in frames.
