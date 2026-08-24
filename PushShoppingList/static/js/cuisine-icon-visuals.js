(function (global) {
    "use strict";

    const catalog = global.CountryTerritoryCatalog;
    const flagEntries = Object.freeze(Array.from(catalog?.entries || []));
    const flagLabels = Object.freeze(Object.fromEntries(
        flagEntries.map(entry => [entry.code, entry.name]),
    ));
    const supportedFlagCodes = Object.freeze(flagEntries.map(entry => entry.code));
    const currentScript = typeof document !== "undefined" ? document.currentScript : null;
    const flagSpriteUrl = (
        currentScript?.dataset?.cuisineFlagSpriteUrl
        || "/static/vendor/flag-icons/flags-4x3.svg"
    );

    const symbols = Object.freeze({
        "symbol:bread": Object.freeze({ label: "Bread", glyph: "\u{1F35E}" }),
        "symbol:bowl": Object.freeze({ label: "Bowl", glyph: "\u{1F372}" }),
        "symbol:curry": Object.freeze({ label: "Curry", glyph: "\u{1F35B}" }),
        "symbol:globe": Object.freeze({ label: "Global / Fusion", glyph: "\u{1F30D}" }),
        "symbol:noodles": Object.freeze({ label: "Noodles", glyph: "\u{1F35C}" }),
        "symbol:plate": Object.freeze({ label: "Plate and utensils", glyph: "\u{1F37D}\uFE0F" }),
        "symbol:taco": Object.freeze({ label: "Taco", glyph: "\u{1F32E}" }),
    });

    const svgNamespace = "http://www.w3.org/2000/svg";

    function clean(value) {
        return String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ");
    }

    function normalizeToken(value) {
        const token = clean(value);
        const match = token.match(/^(flag|symbol):([a-z0-9_-]+)$/i);
        return match ? `${match[1].toLowerCase()}:${match[2].toLowerCase()}` : token;
    }

    function flagCode(value) {
        const match = normalizeToken(value).match(/^flag:([a-z]{2})$/);
        return match ? match[1] : "";
    }

    function descriptor(value) {
        const token = normalizeToken(value);
        if (!token) {
            return Object.freeze({
                token: "",
                kind: "none",
                label: "None",
                glyph: "",
                code: "",
                supported: true,
            });
        }

        const code = flagCode(token);
        if (code) {
            const supported = Boolean(flagLabels[code]);
            return Object.freeze({
                token,
                kind: "flag",
                label: supported ? `${flagLabels[code]} flag` : `${code.toUpperCase()} flag`,
                glyph: "",
                code: code.toUpperCase(),
                supported,
            });
        }

        if (symbols[token]) {
            return Object.freeze({
                token,
                kind: "symbol",
                label: symbols[token].label,
                glyph: symbols[token].glyph,
                code: "",
                supported: true,
            });
        }

        return Object.freeze({
            token,
            kind: "custom",
            label: `Custom symbol ${token}`,
            glyph: token,
            code: "",
            supported: true,
        });
    }

    function createFlagSvg(code) {
        const normalizedCode = catalog?.normalizeCode?.(code) || clean(code).toLowerCase();
        if (!flagLabels[normalizedCode] || typeof document === "undefined") return null;

        const svg = document.createElementNS(svgNamespace, "svg");
        svg.setAttribute("viewBox", "0 0 640 480");
        svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
        svg.setAttribute("focusable", "false");
        svg.setAttribute("aria-hidden", "true");
        svg.classList.add("cuisine-category-flag-svg");

        const use = document.createElementNS(svgNamespace, "use");
        use.setAttribute("href", `${flagSpriteUrl}#flag-icons-${normalizedCode}`);
        svg.appendChild(use);
        return svg;
    }

    function render(container, value) {
        if (!container) return descriptor(value);
        const item = descriptor(value);
        container.classList.add("cuisine-category-icon-visual");
        container.classList.remove("is-none", "is-flag", "is-symbol", "is-custom", "is-unsupported");
        container.classList.add(`is-${item.kind}`);
        container.classList.toggle("is-unsupported", !item.supported);
        container.dataset.cuisineIconToken = item.token;
        container.replaceChildren();

        if (item.kind === "flag") {
            const svg = createFlagSvg(item.code.toLowerCase());
            if (svg) {
                container.appendChild(svg);
            } else {
                const fallback = document.createElement("span");
                fallback.className = "cuisine-category-flag-generic";
                fallback.setAttribute("aria-hidden", "true");
                fallback.textContent = "\u25C6";
                container.appendChild(fallback);
            }
        } else if (item.kind === "none") {
            container.textContent = "\u2014";
        } else {
            container.textContent = item.glyph;
        }
        return item;
    }

    function create(value) {
        if (typeof document === "undefined") return null;
        const container = document.createElement("span");
        render(container, value);
        container.setAttribute("aria-hidden", "true");
        return container;
    }

    global.CuisineIconVisuals = Object.freeze({
        create,
        createFlagSvg,
        descriptor,
        flagCode,
        flagEntries,
        flagSpriteUrl,
        normalizeToken,
        render,
        supportedFlagCodes,
        symbolTokens: Object.freeze(Object.keys(symbols)),
    });
})(typeof window !== "undefined" ? window : globalThis);
