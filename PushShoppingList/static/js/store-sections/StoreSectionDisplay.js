(function initializeStoreSectionDisplay(global) {
    "use strict";

    function create(options = {}) {
        const button = document.createElement("button");
        const label = String(options.label || options.section || "Misc");
        button.type = "button";
        button.className = [
            "store-section-display",
            String(options.className || "").trim(),
        ].filter(Boolean).join(" ");
        button.dataset.storeSectionDisplay = "true";
        button.setAttribute("aria-label", `Store Section: ${label}. Click to edit.`);
        button.disabled = Boolean(options.disabled);
        button.innerHTML = `
            ${global.StoreSectionBadge.markup(options)}
            <span class="store-section-display-chevron" aria-hidden="true">
                ${String(options.indicatorHtml || "")}
            </span>
        `;
        if (typeof options.onActivate === "function") {
            button.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                options.onActivate(button, event);
            });
        }
        return button;
    }

    global.StoreSectionDisplay = Object.freeze({
        create,
    });
}(window));
