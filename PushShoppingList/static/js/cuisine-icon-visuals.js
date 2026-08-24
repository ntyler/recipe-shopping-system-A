(function (global) {
    "use strict";

    const FLAG_LABELS = Object.freeze({
        ar: "Argentina",
        au: "Australia",
        br: "Brazil",
        ca: "Canada",
        cl: "Chile",
        cn: "China",
        co: "Colombia",
        cu: "Cuba",
        de: "Germany",
        es: "Spain",
        fr: "France",
        gb: "United Kingdom",
        gr: "Greece",
        id: "Indonesia",
        ie: "Ireland",
        in: "India",
        it: "Italy",
        jp: "Japan",
        kr: "South Korea",
        mx: "Mexico",
        my: "Malaysia",
        nz: "New Zealand",
        pe: "Peru",
        ph: "Philippines",
        pk: "Pakistan",
        pt: "Portugal",
        th: "Thailand",
        tr: "Turkey",
        us: "United States",
        vn: "Vietnam",
    });

    const SYMBOLS = Object.freeze({
        "symbol:bread": Object.freeze({ label: "Bread", glyph: "\u{1F35E}" }),
        "symbol:bowl": Object.freeze({ label: "Bowl", glyph: "\u{1F372}" }),
        "symbol:curry": Object.freeze({ label: "Curry", glyph: "\u{1F35B}" }),
        "symbol:globe": Object.freeze({ label: "Global / Fusion", glyph: "\u{1F30D}" }),
        "symbol:noodles": Object.freeze({ label: "Noodles", glyph: "\u{1F35C}" }),
        "symbol:plate": Object.freeze({ label: "Plate and utensils", glyph: "\u{1F37D}\uFE0F" }),
        "symbol:taco": Object.freeze({ label: "Taco", glyph: "\u{1F32E}" }),
    });

    const SVG_NS = "http://www.w3.org/2000/svg";
    const SUPPORTED_FLAG_CODES = Object.freeze(Object.keys(FLAG_LABELS));

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
            const supported = Boolean(FLAG_LABELS[code]);
            return Object.freeze({
                token,
                kind: "flag",
                label: supported ? `${FLAG_LABELS[code]} flag` : `${code.toUpperCase()} flag`,
                glyph: "",
                code: code.toUpperCase(),
                supported,
            });
        }
        if (SYMBOLS[token]) {
            return Object.freeze({
                token,
                kind: "symbol",
                label: SYMBOLS[token].label,
                glyph: SYMBOLS[token].glyph,
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

    function rect(x, y, width, height, fill, extra = "") {
        return `<rect x="${x}" y="${y}" width="${width}" height="${height}" fill="${fill}"${extra}/>`;
    }

    function circle(cx, cy, radius, fill, extra = "") {
        return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${fill}"${extra}/>`;
    }

    function polygon(points, fill, extra = "") {
        return `<polygon points="${points}" fill="${fill}"${extra}/>`;
    }

    function starPoints(cx, cy, outerRadius, innerRadius = outerRadius * 0.42, points = 5) {
        const values = [];
        for (let index = 0; index < points * 2; index += 1) {
            const radius = index % 2 ? innerRadius : outerRadius;
            const angle = -Math.PI / 2 + (index * Math.PI) / points;
            values.push(`${(cx + Math.cos(angle) * radius).toFixed(2)},${(cy + Math.sin(angle) * radius).toFixed(2)}`);
        }
        return values.join(" ");
    }

    function star(cx, cy, radius, fill) {
        return polygon(starPoints(cx, cy, radius), fill);
    }

    function horizontalBands(colors, weights = []) {
        const resolvedWeights = colors.map((_, index) => Number(weights[index]) || 1);
        const total = resolvedWeights.reduce((sum, weight) => sum + weight, 0);
        let y = 0;
        return colors.map((color, index) => {
            const height = (16 * resolvedWeights[index]) / total;
            const shape = rect(0, y, 24, height + 0.02, color);
            y += height;
            return shape;
        }).join("");
    }

    function verticalBands(colors, weights = []) {
        const resolvedWeights = colors.map((_, index) => Number(weights[index]) || 1);
        const total = resolvedWeights.reduce((sum, weight) => sum + weight, 0);
        let x = 0;
        return colors.map((color, index) => {
            const width = (24 * resolvedWeights[index]) / total;
            const shape = rect(x, 0, width + 0.02, 16, color);
            x += width;
            return shape;
        }).join("");
    }

    function crescent(cx, cy, radius, fill, cutout, offset = 1.2) {
        return circle(cx, cy, radius, fill) + circle(cx + offset, cy - 0.25, radius * 0.82, cutout);
    }

    function unionJackCanton(scale = 1) {
        return `
            <g transform="scale(${scale})">
                ${rect(0, 0, 24, 16, "#012169")}
                <path d="M0 0L24 16M24 0L0 16" stroke="#fff" stroke-width="3.2"/>
                <path d="M0 0L24 16M24 0L0 16" stroke="#c8102e" stroke-width="1.45"/>
                ${rect(0, 6, 24, 4, "#fff")}
                ${rect(10, 0, 4, 16, "#fff")}
                ${rect(0, 7, 24, 2, "#c8102e")}
                ${rect(11, 0, 2, 16, "#c8102e")}
            </g>`;
    }

    function flagMarkup(code) {
        switch (code) {
        case "ar":
            return horizontalBands(["#74acdf", "#fff", "#74acdf"]) + circle(12, 8, 1.15, "#f6b40e");
        case "au":
            return `${rect(0, 0, 24, 16, "#012169")}<g transform="scale(.46)">${unionJackCanton()}</g>${star(17.2, 9.8, 1.3, "#fff")}${star(20.6, 4.1, .85, "#fff")}${star(20.4, 13, .8, "#fff")}`;
        case "br":
            return `${rect(0, 0, 24, 16, "#009b3a")}${polygon("12,2 22,8 12,14 2,8", "#ffdf00")}${circle(12, 8, 3.2, "#002776")}<path d="M9 7.4c2.5-.8 5.1-.2 6.3.8" fill="none" stroke="#fff" stroke-width=".55"/>`;
        case "ca":
            return `${verticalBands(["#d80621", "#fff", "#d80621"], [1, 2, 1])}${polygon("12,3.1 12.9,5.7 15.3,4.6 14.4,7.1 16,8 13.2,9.1 13.7,11.9 12,10.7 10.3,11.9 10.8,9.1 8,8 9.6,7.1 8.7,4.6 11.1,5.7", "#d80621")}`;
        case "cl":
            return `${horizontalBands(["#fff", "#d52b1e"])}${rect(0, 0, 8, 8, "#0039a6")}${star(4, 4, 1.8, "#fff")}`;
        case "cn":
            return `${rect(0, 0, 24, 16, "#de2910")}${star(4.6, 4.2, 2, "#ffde00")}${star(8.4, 2.2, .65, "#ffde00")}${star(9.6, 4.6, .65, "#ffde00")}${star(9.1, 7.2, .65, "#ffde00")}`;
        case "co":
            return horizontalBands(["#fcd116", "#003893", "#ce1126"], [2, 1, 1]);
        case "cu": {
            const stripes = horizontalBands(["#002a8f", "#fff", "#002a8f", "#fff", "#002a8f"]);
            return `${stripes}${polygon("0,0 10,8 0,16", "#cf142b")}${star(3.5, 8, 1.65, "#fff")}`;
        }
        case "de":
            return horizontalBands(["#000", "#dd0000", "#ffce00"]);
        case "es":
            return horizontalBands(["#aa151b", "#f1bf00", "#aa151b"], [1, 2, 1]);
        case "fr":
            return verticalBands(["#0055a4", "#fff", "#ef4135"]);
        case "gb":
            return unionJackCanton();
        case "gr": {
            const stripes = horizontalBands(["#0d5eaf", "#fff", "#0d5eaf", "#fff", "#0d5eaf", "#fff", "#0d5eaf", "#fff", "#0d5eaf"]);
            return `${stripes}${rect(0, 0, 8.9, 8.9, "#0d5eaf")}${rect(3.5, 0, 1.9, 8.9, "#fff")}${rect(0, 3.5, 8.9, 1.9, "#fff")}`;
        }
        case "id":
            return horizontalBands(["#ce1126", "#fff"]);
        case "ie":
            return verticalBands(["#169b62", "#fff", "#ff883e"]);
        case "in":
            return `${horizontalBands(["#ff9933", "#fff", "#138808"])}${circle(12, 8, 1.55, "none", " stroke=\"#000080\" stroke-width=\".48\"")}${circle(12, 8, .3, "#000080")}`;
        case "it":
            return verticalBands(["#009246", "#fff", "#ce2b37"]);
        case "jp":
            return `${rect(0, 0, 24, 16, "#fff")}${circle(12, 8, 4, "#bc002d")}`;
        case "kr":
            return `${rect(0, 0, 24, 16, "#fff")}${circle(12, 8, 3.1, "#cd2e3a")}<path d="M8.9 8a3.1 3.1 0 0 0 6.2 0 1.55 1.55 0 0 1-3.1 0 1.55 1.55 0 0 0-3.1 0" fill="#0047a0"/><g stroke="#111" stroke-width=".55"><path d="M4 3l3 2M4.8 2l3 2M17 12l3 2M16.2 13l3 2"/></g>`;
        case "mx":
            return `${verticalBands(["#006847", "#fff", "#ce1126"])}${circle(12, 8, 1.05, "#8c6b32")}`;
        case "my": {
            const stripes = horizontalBands(["#cc0001", "#fff", "#cc0001", "#fff", "#cc0001", "#fff", "#cc0001", "#fff"]);
            return `${stripes}${rect(0, 0, 11, 8.1, "#010066")}${crescent(4.5, 4, 2.15, "#ffcc00", "#010066", .85)}${star(8.4, 4, 1.2, "#ffcc00")}`;
        }
        case "nz":
            return `${rect(0, 0, 24, 16, "#012169")}<g transform="scale(.46)">${unionJackCanton()}</g>${star(16.3, 5.1, .85, "#cc142b")}${star(20.2, 8.1, .85, "#cc142b")}${star(16.8, 12.2, .85, "#cc142b")}`;
        case "pe":
            return verticalBands(["#d91023", "#fff", "#d91023"]);
        case "ph":
            return `${horizontalBands(["#0038a8", "#ce1126"])}${polygon("0,0 9,8 0,16", "#fff")}${circle(3.2, 8, 1.1, "#fcd116")}${star(1.2, 2.1, .65, "#fcd116")}${star(1.2, 13.9, .65, "#fcd116")}`;
        case "pk":
            return `${verticalBands(["#fff", "#01411c"], [1, 3])}${crescent(14.2, 7.5, 3.25, "#fff", "#01411c", 1.3)}${star(17.7, 5, .9, "#fff")}`;
        case "pt":
            return `${verticalBands(["#046a38", "#da291c"], [2, 3])}${circle(9.5, 8, 1.7, "#ffcc00")}${circle(9.5, 8, .95, "#fff")}`;
        case "th":
            return horizontalBands(["#a51931", "#fff", "#2d2a4a", "#fff", "#a51931"], [1, 1, 2, 1, 1]);
        case "tr":
            return `${rect(0, 0, 24, 16, "#e30a17")}${crescent(9.2, 8, 3.55, "#fff", "#e30a17", 1.3)}${star(14.1, 8, 1.35, "#fff")}`;
        case "us": {
            const stripes = horizontalBands(["#b22234", "#fff", "#b22234", "#fff", "#b22234", "#fff", "#b22234"]);
            return `${stripes}${rect(0, 0, 10.4, 8.9, "#3c3b6e")}${[2, 5, 8].map(x => [2, 4.5, 7].map(y => circle(x, y, .38, "#fff")).join("")).join("")}`;
        }
        case "vn":
            return `${rect(0, 0, 24, 16, "#da251d")}${star(12, 8, 3.6, "#ff0")}`;
        default:
            return "";
        }
    }

    function createFlagSvg(code) {
        const normalizedCode = String(code || "").toLowerCase();
        const markup = FLAG_LABELS[normalizedCode] ? flagMarkup(normalizedCode) : "";
        if (!markup || typeof document === "undefined") return null;
        const svg = document.createElementNS(SVG_NS, "svg");
        svg.setAttribute("viewBox", "0 0 24 16");
        svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
        svg.setAttribute("focusable", "false");
        svg.setAttribute("aria-hidden", "true");
        svg.classList.add("cuisine-category-flag-svg");
        svg.innerHTML = markup;
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
                fallback.textContent = "◆";
                container.appendChild(fallback);
            }
        } else if (item.kind === "none") {
            container.textContent = "—";
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
        normalizeToken,
        render,
        supportedFlagCodes: SUPPORTED_FLAG_CODES,
        symbolTokens: Object.freeze(Object.keys(SYMBOLS)),
    });
})(typeof window !== "undefined" ? window : globalThis);
