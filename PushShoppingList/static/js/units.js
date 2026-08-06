(function () {
    "use strict";

    const CUSTOM_UNITS_KEY = "recipeIngredientCustomUnits";

    function cleanName(value) {
        return String(value || "").trim().replace(/\s+/g, " ").slice(0, 40);
    }

    function unitKey(value) {
        if (typeof recipeIngredientUnitKey === "function") {
            return recipeIngredientUnitKey(value);
        }
        return cleanName(value)
            .toLowerCase()
            .replace(/\./g, "")
            .replace(/[_-]+/g, " ")
            .replace(/\s+/g, " ");
    }

    function customUnitNames() {
        if (typeof recipeIngredientCustomUnitNames === "function") {
            return recipeIngredientCustomUnitNames();
        }
        try {
            const values = JSON.parse(localStorage.getItem(CUSTOM_UNITS_KEY) || "[]");
            return Array.isArray(values) ? values.map(cleanName).filter(Boolean) : [];
        } catch (error) {
            console.warn("Unable to load custom ingredient units.", error);
            return [];
        }
    }

    function storeCustomUnitNames(values) {
        if (typeof storeRecipeIngredientCustomUnitNames === "function") {
            return storeRecipeIngredientCustomUnitNames(values);
        }
        const names = [];
        const seen = new Set();
        values.forEach(value => {
            const name = cleanName(value);
            const key = unitKey(name);
            if (name && !seen.has(key)) {
                names.push(name);
                seen.add(key);
            }
        });
        localStorage.setItem(CUSTOM_UNITS_KEY, JSON.stringify(names));
        return names;
    }

    function unitRegistry() {
        if (typeof recipeIngredientUnitRegistry === "function") {
            return recipeIngredientUnitRegistry();
        }
        const source = document.getElementById("ingredientUnitConfig");
        const payload = JSON.parse(source?.textContent || '{"units":[],"aliases":{}}');
        const units = Array.isArray(payload.units) ? payload.units : [];
        return {
            units,
            aliases: payload.aliases || {},
            byName: new Map(units.map(unit => [String(unit.name || "").toLowerCase(), unit])),
        };
    }

    function builtInMatch(value) {
        const registry = unitRegistry();
        const canonicalName = registry.aliases[unitKey(value)] || "";
        const unit = registry.byName.get(String(canonicalName).toLowerCase()) || null;
        return unit && !unit.custom ? unit : null;
    }

    function initUnitMasterPage() {
        const root = document.querySelector("[data-unit-master-page]");
        if (!root) return;

        const addForm = root.querySelector("[data-unit-master-add-form]");
        const addInput = root.querySelector("[data-unit-master-add-input]");
        const list = root.querySelector("[data-unit-master-custom-list]");
        const empty = root.querySelector("[data-unit-master-custom-empty]");
        const count = root.querySelector("[data-unit-master-custom-count]");
        const status = root.querySelector("[data-unit-master-status]");
        const search = root.querySelector("[data-unit-master-search]");
        const searchEmpty = root.querySelector("[data-unit-master-search-empty]");

        const setStatus = (message, type = "success") => {
            status.textContent = String(message || "");
            status.dataset.status = type;
            status.hidden = !status.textContent;
        };

        const validateName = (name, previousName = "") => {
            if (!name) return "Enter a unit name.";
            const builtIn = builtInMatch(name);
            if (builtIn) return `${builtIn.name} is already available as a built-in unit.`;
            const key = unitKey(name);
            const previousKey = unitKey(previousName);
            const duplicate = customUnitNames().find(item => (
                unitKey(item) === key && unitKey(item) !== previousKey
            ));
            return duplicate ? `${duplicate} is already in your custom units.` : "";
        };

        const renderCustomUnits = () => {
            const names = customUnitNames();
            list.replaceChildren();
            names.forEach(name => {
                const row = document.createElement("form");
                row.className = "unit-master-custom-row";
                row.dataset.unitMasterCustomRow = "";
                row.dataset.originalName = name;

                const label = document.createElement("label");
                const labelText = document.createElement("span");
                labelText.textContent = "Custom unit";
                const input = document.createElement("input");
                input.type = "text";
                input.maxLength = 40;
                input.value = name;
                input.setAttribute("aria-label", `Custom unit ${name}`);
                label.append(labelText, input);

                const save = document.createElement("button");
                save.type = "submit";
                save.textContent = "Save";
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "danger";
                remove.textContent = "Remove";

                row.addEventListener("submit", event => {
                    event.preventDefault();
                    const nextName = cleanName(input.value);
                    const validation = validateName(nextName, name);
                    if (validation) {
                        setStatus(validation, "error");
                        input.focus();
                        return;
                    }
                    const nextNames = customUnitNames().map(item => (
                        unitKey(item) === unitKey(name) ? nextName : item
                    ));
                    storeCustomUnitNames(nextNames);
                    setStatus(`Custom unit renamed to ${nextName}.`);
                    renderCustomUnits();
                });
                remove.addEventListener("click", () => {
                    if (!window.confirm(`Remove custom unit "${name}" from this browser?`)) return;
                    storeCustomUnitNames(
                        customUnitNames().filter(item => unitKey(item) !== unitKey(name)),
                    );
                    setStatus(`Custom unit ${name} removed.`);
                    renderCustomUnits();
                });

                row.append(label, save, remove);
                list.appendChild(row);
            });
            count.textContent = String(names.length);
            empty.hidden = names.length > 0;
        };

        addForm.addEventListener("submit", event => {
            event.preventDefault();
            const name = cleanName(addInput.value);
            const validation = validateName(name);
            if (validation) {
                setStatus(validation, "error");
                addInput.focus();
                return;
            }
            storeCustomUnitNames([...customUnitNames(), name]);
            addInput.value = "";
            setStatus(`Custom unit ${name} added.`);
            renderCustomUnits();
            addInput.focus();
        });

        search.addEventListener("input", () => {
            const query = unitKey(search.value);
            let visibleCount = 0;
            root.querySelectorAll("[data-unit-master-category]").forEach(category => {
                let categoryCount = 0;
                category.querySelectorAll("[data-unit-master-built-in-row]").forEach(row => {
                    const visible = !query || unitKey(row.dataset.unitMasterSearchValue).includes(query);
                    row.hidden = !visible;
                    if (visible) categoryCount += 1;
                });
                category.hidden = categoryCount === 0;
                visibleCount += categoryCount;
            });
            searchEmpty.hidden = visibleCount > 0;
        });

        window.addEventListener("storage", event => {
            if (event.key === CUSTOM_UNITS_KEY) renderCustomUnits();
        });
        renderCustomUnits();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initUnitMasterPage, { once: true });
    } else {
        initUnitMasterPage();
    }
}());
