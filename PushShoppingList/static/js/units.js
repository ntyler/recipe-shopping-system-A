(function () {
    "use strict";

    const LEGACY_CUSTOM_UNITS_KEY = "recipeIngredientCustomUnits";
    const IMPORT_DISMISSED_KEY = "recipeIngredientCustomUnitsImportDismissed";

    function cleanText(value) {
        return String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ");
    }

    function unitKey(value) {
        return cleanText(value)
            .toLowerCase()
            .replace(/\./g, "")
            .replace(/[_-]+/g, " ")
            .replace(/\s+/g, " ");
    }

    function parseRegistry() {
        const source = document.getElementById("ingredientUnitConfig");
        try {
            const payload = JSON.parse(source?.textContent || "{}");
            return {
                units: Array.isArray(payload.units) ? payload.units : [],
                aliases: payload.aliases && typeof payload.aliases === "object" ? payload.aliases : {},
                categories: Array.isArray(payload.categories) ? payload.categories : [],
            };
        } catch (error) {
            console.error("Unable to load the unit registry.", error);
            return { units: [], aliases: {}, categories: [] };
        }
    }

    function legacyUnitNames() {
        try {
            const values = JSON.parse(localStorage.getItem(LEGACY_CUSTOM_UNITS_KEY) || "[]");
            const names = [];
            const seen = new Set();
            (Array.isArray(values) ? values : []).forEach(value => {
                const name = cleanText(value);
                const key = unitKey(name);
                if (name && key && !seen.has(key)) {
                    names.push(name);
                    seen.add(key);
                }
            });
            return names;
        } catch (error) {
            console.warn("Unable to read legacy browser units.", error);
            return [];
        }
    }

    function initUnitMasterPage() {
        const root = document.querySelector("[data-unit-master-page]");
        if (!root) return;

        let registry = parseRegistry();
        let editorUnitId = "";
        let editorAliases = [];
        let editorAliasErrors = {};
        let returnFocus = null;

        const source = document.getElementById("ingredientUnitConfig");
        const status = root.querySelector("[data-unit-master-status]");
        const search = root.querySelector("[data-unit-master-search]");
        const searchEmpty = root.querySelector("[data-unit-master-search-empty]");
        const categoryList = root.querySelector("[data-unit-master-category-list]");
        const dialog = root.querySelector("[data-unit-master-dialog]");
        const form = root.querySelector("[data-unit-master-form]");
        const nameInput = root.querySelector("[data-unit-master-name]");
        const categorySelect = root.querySelector("[data-unit-master-category-select]");
        const aliasInput = root.querySelector("[data-unit-master-alias-input]");
        const aliasChips = root.querySelector("[data-unit-master-alias-chips]");
        const saveButton = root.querySelector("[data-unit-master-save]");
        const editorTitle = root.querySelector("[data-unit-master-editor-title]");
        const editorKicker = root.querySelector("[data-unit-master-editor-kicker]");
        const editorFeedback = root.querySelector("[data-unit-master-editor-feedback]");
        const nameError = root.querySelector("[data-unit-master-name-error]");
        const categoryError = root.querySelector("[data-unit-master-category-error]");
        const aliasError = root.querySelector("[data-unit-master-alias-error]");
        const importPanel = root.querySelector("[data-unit-master-import]");
        const importButton = root.querySelector("[data-unit-master-import-button]");

        const setStatus = (message, type = "success") => {
            status.textContent = String(message || "");
            status.dataset.status = type;
            status.hidden = !status.textContent;
        };

        const setFieldError = (input, output, message) => {
            const text = String(message || "");
            output.textContent = text;
            output.hidden = !text;
            input.toggleAttribute("aria-invalid", Boolean(text));
        };

        const clearErrors = () => {
            editorAliasErrors = {};
            setFieldError(nameInput, nameError, "");
            setFieldError(categorySelect, categoryError, "");
            setFieldError(aliasInput, aliasError, "");
            editorFeedback.textContent = "";
            editorFeedback.hidden = true;
            renderAliasChips();
        };

        const unitById = unitId => registry.units.find(unit => String(unit.id) === String(unitId)) || null;

        const renderAliasChips = () => {
            aliasChips.replaceChildren();
            editorAliases.forEach((alias, index) => {
                const chip = document.createElement("span");
                chip.className = "unit-master-alias-chip";
                if (editorAliasErrors[String(index)]) chip.classList.add("has-error");

                const text = document.createElement("span");
                text.textContent = alias;
                const remove = document.createElement("button");
                remove.type = "button";
                remove.textContent = "×";
                remove.setAttribute("aria-label", `Remove alias ${alias}`);
                remove.addEventListener("click", () => {
                    editorAliases.splice(index, 1);
                    editorAliasErrors = {};
                    renderAliasChips();
                    aliasInput.focus();
                });
                chip.append(text, remove);
                if (editorAliasErrors[String(index)]) {
                    const error = document.createElement("small");
                    error.textContent = editorAliasErrors[String(index)];
                    chip.append(error);
                }
                aliasChips.appendChild(chip);
            });
        };

        const localAliasError = alias => {
            const nameKey = unitKey(nameInput.value);
            const aliasKey = unitKey(alias);
            if (!alias) return "Enter an alias first.";
            if (!aliasKey) return "Enter an alias with letters or numbers.";
            if (aliasKey === nameKey) return "The canonical name does not need to be an alias.";
            if (editorAliases.some(value => unitKey(value) === aliasKey)) return "That alias is already in this unit.";

            const current = unitById(editorUnitId);
            const conflictName = registry.aliases[aliasKey];
            if (conflictName) {
                const conflict = registry.units.find(unit => unitKey(unit.name) === unitKey(conflictName));
                if (!current || !conflict || String(conflict.id) !== String(current.id)) {
                    return `${alias} is already accepted by ${conflictName}.`;
                }
            }
            return "";
        };

        const addPendingAlias = () => {
            const alias = cleanText(aliasInput.value);
            const error = localAliasError(alias);
            setFieldError(aliasInput, aliasError, error);
            if (error) return false;
            editorAliases.push(alias);
            aliasInput.value = "";
            renderAliasChips();
            aliasInput.focus();
            return true;
        };

        const renderStats = () => {
            root.querySelector("[data-unit-master-seeded-count]").textContent = String(
                registry.units.filter(unit => unit.seeded).length,
            );
            root.querySelector("[data-unit-master-custom-count]").textContent = String(
                registry.units.filter(unit => !unit.seeded).length,
            );
            root.querySelector("[data-unit-master-alias-count]").textContent = String(
                registry.units.reduce((total, unit) => total + (Array.isArray(unit.aliases) ? unit.aliases.length : 0), 0),
            );
            root.querySelector("[data-unit-master-category-count]").textContent = String(
                new Set(registry.units.map(unit => unit.category)).size,
            );
        };

        const createUnitRow = unit => {
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.unitMasterRow = "";
            row.dataset.unitId = unit.id;
            row.dataset.unitMasterSearchValue = `${unit.name} ${(unit.aliases || []).join(" ")}`;

            const name = document.createElement("strong");
            name.setAttribute("role", "cell");
            name.textContent = unit.name;
            const aliases = document.createElement("div");
            aliases.className = "unit-master-aliases";
            aliases.setAttribute("role", "cell");
            if (unit.aliases?.length) {
                unit.aliases.forEach(alias => {
                    const code = document.createElement("code");
                    code.textContent = alias;
                    aliases.appendChild(code);
                });
            } else {
                const empty = document.createElement("span");
                empty.textContent = "Canonical name only";
                aliases.appendChild(empty);
            }
            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${unit.seeded ? "" : " user-created"}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = unit.seeded ? "System-seeded" : "User-created";
            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.unitMasterEditButton = "";
            edit.dataset.unitId = unit.id;
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", `Edit ${unit.name}`);
            row.append(name, aliases, sourceBadge, edit);
            return row;
        };

        const applySearch = () => {
            const query = unitKey(search.value);
            let visibleCount = 0;
            root.querySelectorAll("[data-unit-master-category]").forEach(category => {
                let categoryCount = 0;
                category.querySelectorAll("[data-unit-master-row]").forEach(row => {
                    const visible = !query || unitKey(row.dataset.unitMasterSearchValue).includes(query);
                    row.hidden = !visible;
                    if (visible) categoryCount += 1;
                });
                category.hidden = categoryCount === 0;
                category.querySelector("[data-unit-master-category-count-label]").textContent = `${categoryCount} unit${categoryCount === 1 ? "" : "s"}`;
                visibleCount += categoryCount;
            });
            searchEmpty.hidden = visibleCount > 0;
        };

        const renderRegistry = () => {
            root.querySelectorAll("[data-unit-master-category]").forEach(category => {
                const rows = category.querySelector("[data-unit-master-category-rows]");
                const units = registry.units.filter(unit => unit.category === category.dataset.category);
                rows.replaceChildren(...units.map(createUnitRow));
            });
            renderStats();
            applySearch();
        };

        const updateRegistry = nextRegistry => {
            registry = {
                units: Array.isArray(nextRegistry?.units) ? nextRegistry.units : [],
                aliases: nextRegistry?.aliases && typeof nextRegistry.aliases === "object" ? nextRegistry.aliases : {},
                categories: Array.isArray(nextRegistry?.categories) ? nextRegistry.categories : registry.categories,
            };
            source.textContent = JSON.stringify(registry);
            if (typeof recipeIngredientUnitRegistryCache !== "undefined") {
                recipeIngredientUnitRegistryCache = null;
            }
            renderRegistry();
        };

        const openEditor = (unit = null, trigger = null) => {
            returnFocus = trigger || document.activeElement;
            editorUnitId = unit ? String(unit.id) : "";
            editorAliases = unit && Array.isArray(unit.aliases) ? [...unit.aliases] : [];
            editorTitle.textContent = unit ? `Edit ${unit.name}` : "Add Unit";
            editorKicker.textContent = unit?.seeded ? "System-seeded unit" : unit ? "User-created unit" : "New workspace unit";
            nameInput.value = unit?.name || "";
            categorySelect.value = unit?.category || "count_package";
            aliasInput.value = "";
            clearErrors();
            renderAliasChips();
            dialog.showModal();
            requestAnimationFrame(() => nameInput.focus());
        };

        const closeEditor = () => {
            if (dialog.open) dialog.close();
            if (returnFocus && typeof returnFocus.focus === "function") {
                returnFocus.focus();
            }
        };

        const applyServerErrors = payload => {
            const errors = payload.errors || {};
            setFieldError(nameInput, nameError, errors.canonical_name || "");
            setFieldError(categorySelect, categoryError, errors.category || "");
            editorAliasErrors = errors.aliases || {};
            renderAliasChips();
            const aliasMessages = Object.values(editorAliasErrors);
            setFieldError(aliasInput, aliasError, aliasMessages.length ? "Review the highlighted aliases." : "");
            editorFeedback.textContent = payload.error || "Unable to save this unit.";
            editorFeedback.hidden = false;
            const firstInvalid = form.querySelector('[aria-invalid="true"]');
            if (firstInvalid) firstInvalid.focus();
        };

        const saveUnit = async event => {
            event.preventDefault();
            if (aliasInput.value && !addPendingAlias()) return;
            clearErrors();
            const payload = {
                canonical_name: cleanText(nameInput.value),
                category: categorySelect.value,
                aliases: [...editorAliases],
            };
            const url = editorUnitId
                ? root.dataset.updateUrlTemplate.replace("__UNIT_ID__", encodeURIComponent(editorUnitId))
                : root.dataset.createUrl;
            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            try {
                const response = await fetch(url, {
                    method: editorUnitId ? "PUT" : "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify(payload),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) {
                    applyServerErrors(result);
                    return;
                }
                updateRegistry(result.registry);
                closeEditor();
                setStatus(result.message || "Unit saved.");
            } catch (error) {
                editorFeedback.textContent = "The unit could not be saved. Check your connection and try again.";
                editorFeedback.hidden = false;
                console.error("Unable to save unit.", error);
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = "Save Unit";
            }
        };

        root.querySelector("[data-unit-master-add-button]").addEventListener("click", event => openEditor(null, event.currentTarget));
        categoryList.addEventListener("click", event => {
            const button = event.target.closest("[data-unit-master-edit-button]");
            if (!button) return;
            openEditor(unitById(button.dataset.unitId), button);
        });
        root.querySelector("[data-unit-master-alias-add]").addEventListener("click", addPendingAlias);
        aliasInput.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addPendingAlias();
            }
        });
        root.querySelector("[data-unit-master-close]").addEventListener("click", closeEditor);
        root.querySelector("[data-unit-master-cancel]").addEventListener("click", closeEditor);
        dialog.addEventListener("cancel", event => {
            event.preventDefault();
            closeEditor();
        });
        form.addEventListener("submit", saveUnit);
        search.addEventListener("input", applySearch);

        const browserUnits = legacyUnitNames();
        const importDismissed = sessionStorage.getItem(IMPORT_DISMISSED_KEY) === "true";
        importPanel.hidden = !browserUnits.length || importDismissed;
        importButton.addEventListener("click", async () => {
            importButton.disabled = true;
            importButton.textContent = "Importing…";
            try {
                const response = await fetch(root.dataset.importUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify({ units: browserUnits }),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) throw new Error(result.error || "Import failed");
                updateRegistry(result.registry);
                localStorage.removeItem(LEGACY_CUSTOM_UNITS_KEY);
                importPanel.hidden = true;
                setStatus(result.message || "Browser units imported.");
            } catch (error) {
                setStatus("Browser units could not be imported. Try again.", "error");
                console.error("Unable to import browser units.", error);
            } finally {
                importButton.disabled = false;
                importButton.textContent = "Import units";
            }
        });
        root.querySelector("[data-unit-master-import-dismiss]").addEventListener("click", () => {
            sessionStorage.setItem(IMPORT_DISMISSED_KEY, "true");
            importPanel.hidden = true;
        });

        renderRegistry();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initUnitMasterPage, { once: true });
    } else {
        initUnitMasterPage();
    }
}());
