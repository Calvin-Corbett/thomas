const PART_FILES = [
    "./063_module_studio_comfy_style_id_bootstrap.js",
    "./063_module_studio_comfy_style_id_helpers.js",
    "./063_module_studio_comfy_style_id_workspace.js",
];

if (typeof document === "undefined") {
    throw new Error("063 module loader requires DOM document environment");
}

const chunks = await Promise.all(
    PART_FILES.map(async (part) => {
        const response = await fetch(new URL(part, import.meta.url).href);
        if (!response.ok) {
            throw new Error(`Unable to load monolith chunk: ${part}`);
        }
        return response.text();
    })
);
const source = chunks.join("\n");
const script = document.createElement("script");
script.type = "text/javascript";
script.textContent = source;
document.head.appendChild(script);
script.remove();
