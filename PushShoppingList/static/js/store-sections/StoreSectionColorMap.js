(function initializeStoreSectionColorMap(global) {
    "use strict";

    const sections = Object.freeze({
        "PRODUCE": Object.freeze({
            icon: "leaf",
            color: "#4ade80",
            aliases: ["PRODUCE"],
        }),
        "MEAT & SEAFOOD": Object.freeze({
            icon: "fish",
            color: "#60a5fa",
            aliases: ["MEAT & SEAFOOD", "MEAT AND SEAFOOD", "MEAT", "SEAFOOD"],
        }),
        "DAIRY & EGGS": Object.freeze({
            icon: "dairy",
            color: "#7dd3fc",
            aliases: ["DAIRY & EGGS", "DAIRY AND EGGS", "DAIRY", "EGGS"],
        }),
        "FROZEN": Object.freeze({
            icon: "snowflake",
            color: "#22d3ee",
            aliases: ["FROZEN", "FROZEN FOODS"],
        }),
        "DRY GOODS": Object.freeze({
            icon: "package",
            color: "#a78bfa",
            aliases: ["DRY GOODS", "DRY"],
        }),
        "PASTA, RICE & GRAINS": Object.freeze({
            icon: "wheat",
            color: "#eab308",
            aliases: [
                "PASTA, RICE & GRAINS",
                "PASTA RICE & GRAINS",
                "PASTA RICE AND GRAINS",
                "PASTA/RICE",
                "PASTA",
                "RICE",
                "GRAINS",
            ],
        }),
        "BAKING": Object.freeze({
            icon: "whisk",
            color: "#f59e0b",
            aliases: ["BAKING", "BAKING SUPPLIES"],
        }),
        "CANNED": Object.freeze({
            icon: "can",
            color: "#fb923c",
            aliases: ["CANNED", "CANNED GOODS"],
        }),
        "SAUCES & CONDIMENTS": Object.freeze({
            icon: "sauce",
            color: "#ef4444",
            aliases: [
                "SAUCES & CONDIMENTS",
                "SAUCES AND CONDIMENTS",
                "SAUCES",
                "CONDIMENTS",
            ],
        }),
        "SNACKS": Object.freeze({
            icon: "cookie",
            color: "#facc15",
            aliases: ["SNACKS", "SNACK"],
        }),
        "BEVERAGES": Object.freeze({
            icon: "cup",
            color: "#2dd4bf",
            aliases: ["BEVERAGES", "BEVERAGE", "DRINKS"],
        }),
        "SPICES & SEASONINGS": Object.freeze({
            icon: "jar",
            color: "#e11d48",
            aliases: [
                "SPICES & SEASONINGS",
                "SPICES AND SEASONINGS",
                "SPICES",
                "SEASONINGS",
            ],
        }),
        "OILS & VINEGARS": Object.freeze({
            icon: "oil",
            color: "#84a33f",
            aliases: [
                "OILS & VINEGARS",
                "OILS AND VINEGARS",
                "OILS",
                "VINEGARS",
            ],
        }),
        "BAKERY": Object.freeze({
            icon: "bread",
            color: "#d6a16a",
            aliases: ["BAKERY", "BREAD"],
        }),
        "DELI": Object.freeze({
            icon: "sandwich",
            color: "#f472b6",
            aliases: ["DELI"],
        }),
        "HOUSEHOLD": Object.freeze({
            icon: "broom",
            color: "#94a3b8",
            aliases: ["HOUSEHOLD", "HOUSEHOLD SUPPLIES"],
        }),
        "PERSONAL CARE": Object.freeze({
            icon: "personal-care",
            color: "#c084fc",
            aliases: ["PERSONAL CARE", "HEALTH & BEAUTY", "HEALTH AND BEAUTY"],
        }),
        "PET SUPPLIES": Object.freeze({
            icon: "paw",
            color: "#a16207",
            aliases: ["PET SUPPLIES", "PETS", "PET"],
        }),
        "MISC": Object.freeze({
            icon: "basket",
            color: "#94a3b8",
            aliases: ["MISC", "MISCELLANEOUS", "OTHER", "UNASSIGNED"],
        }),
    });

    const iconColors = Object.freeze({
        leaf: "#4ade80",
        fish: "#60a5fa",
        dairy: "#7dd3fc",
        snowflake: "#22d3ee",
        package: "#a78bfa",
        wheat: "#eab308",
        whisk: "#f59e0b",
        can: "#fb923c",
        sauce: "#ef4444",
        cookie: "#facc15",
        cup: "#2dd4bf",
        jar: "#e11d48",
        oil: "#84a33f",
        bread: "#d6a16a",
        sandwich: "#f472b6",
        broom: "#94a3b8",
        home: "#94a3b8",
        "personal-care": "#c084fc",
        heart: "#c084fc",
        paw: "#a16207",
        basket: "#94a3b8",
    });

    function normalize(value) {
        return String(value || "")
            .trim()
            .toUpperCase()
            .replace(/[_-]+/g, " ")
            .replace(/\s*\/\s*/g, "/")
            .replace(/\s+/g, " ");
    }

    const aliases = new Map();
    Object.entries(sections).forEach(([key, section]) => {
        aliases.set(normalize(key), key);
        section.aliases.forEach(alias => aliases.set(normalize(alias), key));
    });

    function canonicalKey(value) {
        const normalized = normalize(value);
        if (!normalized) {
            return "MISC";
        }
        if (aliases.has(normalized)) {
            return aliases.get(normalized);
        }
        for (const [alias, key] of aliases.entries()) {
            if (alias.length >= 5 && normalized.includes(alias)) {
                return key;
            }
        }
        return "";
    }

    function configuredIconName(iconName) {
        return String(iconName || "")
            .trim()
            .toLowerCase()
            .replace(/[_\s]+/g, "-");
    }

    function get(value, configuredIcon = "") {
        const key = canonicalKey(value);
        const builtIn = key ? sections[key] : null;
        const customIcon = configuredIconName(configuredIcon) || "basket";
        return Object.freeze({
            key: key || normalize(value),
            icon: builtIn ? builtIn.icon : customIcon,
            color: builtIn ? builtIn.color : (iconColors[customIcon] || iconColors.basket),
            isBuiltIn: Boolean(builtIn),
        });
    }

    function iconNameFromElement(element) {
        const iconClass = Array.from(element.classList || [])
            .find(className => className.startsWith("is-"));
        return iconClass ? iconClass.slice(3) : "basket";
    }

    function sectionNameFromElement(element) {
        if (element.dataset && element.dataset.storeSection) {
            return element.dataset.storeSection;
        }
        const owner = element.closest && element.closest(
            "[data-store-section], [data-store-section-name], [data-store-section-key]"
        );
        return owner
            ? owner.dataset.storeSection
                || owner.dataset.storeSectionName
                || owner.dataset.storeSectionKey
                || ""
            : "";
    }

    function apply(root = document) {
        const icons = root.matches && root.matches(".recipe-edit-store-section-icon")
            ? [root]
            : Array.from(root.querySelectorAll(".recipe-edit-store-section-icon"));
        icons.forEach(icon => {
            const section = sectionNameFromElement(icon);
            const resolved = get(section, iconNameFromElement(icon));
            icon.style.setProperty("--store-section-color", resolved.color);
            icon.style.color = "var(--store-section-color)";
        });
    }

    global.StoreSectionColorMap = Object.freeze({
        sections,
        iconColors,
        normalize,
        canonicalKey,
        get,
        apply,
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => apply(document), { once: true });
    } else {
        apply(document);
    }
}(window));
