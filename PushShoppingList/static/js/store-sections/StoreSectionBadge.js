(function initializeStoreSectionBadge(global) {
    "use strict";

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function markup(options = {}) {
        const section = String(options.section || "");
        const label = String(options.label || section || "Misc");
        const iconName = String(options.iconName || "basket");
        const resolved = global.StoreSectionColorMap.get(section, iconName);
        const className = [
            "store-section-badge",
            String(options.className || "").trim(),
        ].filter(Boolean).join(" ");
        return `
            <span class="${escapeHtml(className)}"
                  data-store-section-badge
                  data-store-section="${escapeHtml(section)}"
                  style="--store-section-color:${escapeHtml(resolved.color)}">
                ${String(options.iconHtml || "")}
                <span class="store-section-badge-label">${escapeHtml(label)}</span>
            </span>
        `;
    }

    function create(options = {}) {
        const template = document.createElement("template");
        template.innerHTML = markup(options).trim();
        return template.content.firstElementChild;
    }

    global.StoreSectionBadge = Object.freeze({
        create,
        markup,
    });
}(window));
