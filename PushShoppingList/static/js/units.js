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
        let saveButtonLabel = "Add Unit";
        let aiSuggestionPending = false;
        let suggestionRequestToken = 0;
        let usageRequestToken = 0;
        let usageReturnFocus = null;

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
        const suggestButton = root.querySelector("[data-unit-master-ai-suggest]");
        const suggestButtonLabel = root.querySelector("[data-unit-master-ai-suggest-label]");
        const aliasAddButton = root.querySelector("[data-unit-master-alias-add]");
        const editorTitle = root.querySelector("[data-unit-master-editor-title]");
        const editorKicker = root.querySelector("[data-unit-master-editor-kicker]");
        const editorFeedback = root.querySelector("[data-unit-master-editor-feedback]");
        const nameError = root.querySelector("[data-unit-master-name-error]");
        const categoryError = root.querySelector("[data-unit-master-category-error]");
        const aliasError = root.querySelector("[data-unit-master-alias-error]");
        const importPanel = root.querySelector("[data-unit-master-import]");
        const importButton = root.querySelector("[data-unit-master-import-button]");
        const usageDialog = root.querySelector("[data-unit-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-unit-master-usage-title]");
        const usageContext = root.querySelector("[data-unit-master-usage-context]");
        const usageSummary = root.querySelector("[data-unit-master-usage-summary]");
        const usageResults = root.querySelector("[data-unit-master-usage-results]");

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

        const setEditorFeedback = (message, type = "error") => {
            editorFeedback.textContent = String(message || "");
            editorFeedback.dataset.status = type;
            editorFeedback.hidden = !editorFeedback.textContent;
        };

        const setAiPending = pending => {
            aiSuggestionPending = Boolean(pending);
            dialog.toggleAttribute("aria-busy", aiSuggestionPending);
            suggestButton.disabled = aiSuggestionPending;
            suggestButtonLabel.textContent = aiSuggestionPending ? "Suggesting…" : "Suggest details";
            saveButton.disabled = aiSuggestionPending;
            nameInput.disabled = aiSuggestionPending;
            categorySelect.disabled = aiSuggestionPending;
            aliasInput.disabled = aiSuggestionPending;
            aliasAddButton.disabled = aiSuggestionPending;
            aliasChips.querySelectorAll("button").forEach(button => {
                button.disabled = aiSuggestionPending;
            });
        };

        const clearErrors = () => {
            editorAliasErrors = {};
            setFieldError(nameInput, nameError, "");
            setFieldError(categorySelect, categoryError, "");
            setFieldError(aliasInput, aliasError, "");
            setEditorFeedback("");
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
                remove.disabled = aiSuggestionPending;
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

        const createUsageCell = unit => {
            const usage = document.createElement("div");
            usage.className = "unit-master-usage";
            usage.setAttribute("role", "cell");
            const recipeCount = Math.max(0, Number(unit.recipe_count) || 0);
            if (!recipeCount) {
                const empty = document.createElement("span");
                empty.className = "unit-master-usage-empty";
                empty.textContent = "0";
                empty.setAttribute("aria-label", `No recipes use ${unit.name}`);
                empty.title = `No recipes currently use ${unit.name}`;
                usage.appendChild(empty);
                return usage;
            }

            const button = document.createElement("button");
            button.type = "button";
            button.className = "unit-master-usage-button";
            button.dataset.unitMasterUsageButton = "";
            button.dataset.unitId = unit.id;
            button.setAttribute("aria-haspopup", "dialog");
            button.setAttribute("aria-controls", "unitMasterUsageDialog");
            button.setAttribute(
                "aria-label",
                `Show ${recipeCount} recipe${recipeCount === 1 ? "" : "s"} using ${unit.name}`,
            );
            button.title = `Show recipes using ${unit.name}`;
            const count = document.createElement("strong");
            count.textContent = String(recipeCount);
            const label = document.createElement("span");
            label.textContent = recipeCount === 1 ? "recipe" : "recipes";
            button.append(count, label);
            usage.appendChild(button);
            return usage;
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
            const usage = createUsageCell(unit);
            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.unitMasterEditButton = "";
            edit.dataset.unitId = unit.id;
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", `Edit ${unit.name}`);
            row.append(name, aliases, usage, sourceBadge, edit);
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

        const setUsageState = (message, state = "loading") => {
            usageSummary.textContent = "";
            usageResults.replaceChildren();
            const output = document.createElement("div");
            output.className = `unit-master-usage-state is-${state}`;
            output.textContent = message;
            usageResults.appendChild(output);
        };

        const renderUsageMatch = match => {
            const item = document.createElement("li");
            const line = document.createElement("strong");
            line.textContent = match.ingredient_line || match.ingredient_name || "Ingredient line";
            item.appendChild(line);

            const details = [];
            if (match.kind === "option") {
                details.push(match.context ? `Recipe option: ${match.context}` : "Recipe option");
            } else if (match.context) {
                details.push(match.context);
            }
            if (match.is_alias_match && match.matched_as) {
                details.push(`Matched alias: ${match.matched_as}`);
            }
            if (match.optional) details.push("Optional");
            if (details.length) {
                const meta = document.createElement("span");
                meta.textContent = details.join(" · ");
                item.appendChild(meta);
            }
            return item;
        };

        const renderUsageReferences = data => {
            usageResults.replaceChildren();
            const references = Array.isArray(data.references) ? data.references : [];
            const total = Math.max(0, Number(data.total) || references.length);
            const lineCount = Math.max(0, Number(data.total_reference_count) || 0);
            usageSummary.textContent = `${total} distinct recipe${total === 1 ? "" : "s"} · ${lineCount} matching ingredient line${lineCount === 1 ? "" : "s"}`;

            if (!references.length) {
                setUsageState("No connected recipes were found for this unit.", "empty");
                return;
            }

            references.forEach(reference => {
                const card = document.createElement("article");
                card.className = "unit-master-usage-recipe";
                const header = document.createElement("header");
                const heading = document.createElement("h3");
                heading.textContent = reference.recipe_title || reference.recipe_id || "Recipe";
                header.appendChild(heading);
                if (reference.edit_url) {
                    const link = document.createElement("a");
                    link.href = reference.edit_url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = "Open Recipe";
                    header.appendChild(link);
                }
                card.appendChild(header);

                const matches = document.createElement("ul");
                (Array.isArray(reference.matches) ? reference.matches : []).forEach(match => {
                    matches.appendChild(renderUsageMatch(match || {}));
                });
                card.appendChild(matches);
                usageResults.appendChild(card);
            });

            if (total > references.length) {
                const note = document.createElement("p");
                note.className = "unit-master-usage-limit-note";
                note.textContent = `Showing the first ${references.length} recipes.`;
                usageResults.appendChild(note);
            }
        };

        const closeUsage = () => {
            usageRequestToken += 1;
            if (usageDialog.open) usageDialog.close();
        };

        const openUsage = async (unit, trigger) => {
            if (!unit || !usageDialog) return;
            usageReturnFocus = trigger || document.activeElement;
            usageTitle.textContent = `Recipes using ${unit.name}`;
            const aliases = Array.isArray(unit.aliases) ? unit.aliases : [];
            usageContext.textContent = aliases.length
                ? `Connections include ${unit.name} and its accepted aliases: ${aliases.join(", ")}.`
                : `Connections include ingredient lines normalized to ${unit.name}.`;
            setUsageState("Loading connected recipes…");
            if (!usageDialog.open) usageDialog.showModal();

            const requestToken = ++usageRequestToken;
            const referenceUrl = root.dataset.usageUrlTemplate.replace(
                "__UNIT_ID__",
                encodeURIComponent(unit.id),
            );
            try {
                const response = await fetch(referenceUrl, {
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "fetch",
                    },
                });
                const data = await response.json().catch(() => ({}));
                if (requestToken !== usageRequestToken || !usageDialog.open) return;
                if (!response.ok || data.ok === false) {
                    setUsageState(data.error || "Connected recipes could not be loaded.", "error");
                    return;
                }
                renderUsageReferences(data);
            } catch (error) {
                if (requestToken !== usageRequestToken) return;
                setUsageState("Connected recipes could not be loaded. Try again.", "error");
                console.error("Unable to load unit recipe usage.", error);
            }
        };

        const openEditor = (unit = null, trigger = null) => {
            suggestionRequestToken += 1;
            returnFocus = trigger || document.activeElement;
            editorUnitId = unit ? String(unit.id) : "";
            editorAliases = unit && Array.isArray(unit.aliases) ? [...unit.aliases] : [];
            editorTitle.textContent = unit ? `Edit ${unit.name}` : "Add Unit";
            editorKicker.textContent = unit?.seeded ? "System-seeded unit" : unit ? "User-created unit" : "New workspace unit";
            saveButtonLabel = unit ? "Save Changes" : "Add Unit";
            saveButton.textContent = saveButtonLabel;
            nameInput.value = unit?.name || "";
            categorySelect.value = unit?.category || "count_package";
            aliasInput.value = "";
            setAiPending(false);
            clearErrors();
            renderAliasChips();
            dialog.showModal();
            requestAnimationFrame(() => nameInput.focus());
        };

        const closeEditor = () => {
            suggestionRequestToken += 1;
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
            setEditorFeedback(payload.error || "Unable to save this unit.");
            const firstInvalid = form.querySelector('[aria-invalid="true"]');
            if (firstInvalid) firstInvalid.focus();
        };

        const suggestUnitDetails = async () => {
            const canonicalName = cleanText(nameInput.value);
            if (!canonicalName) {
                setFieldError(nameInput, nameError, "Enter a canonical name before asking AI for suggestions.");
                nameInput.focus();
                return;
            }

            const pendingAlias = cleanText(aliasInput.value);
            const payload = {
                unit_id: editorUnitId,
                canonical_name: canonicalName,
                category: categorySelect.value,
                aliases: [...editorAliases, ...(pendingAlias ? [pendingAlias] : [])],
            };
            clearErrors();
            const requestToken = ++suggestionRequestToken;
            setAiPending(true);
            setEditorFeedback("AI is reviewing the unit name and possible aliases.", "pending");
            try {
                const response = await fetch(root.dataset.suggestUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify(payload),
                });
                const result = await response.json().catch(() => ({}));
                if (requestToken !== suggestionRequestToken || !dialog.open) return;
                if (!response.ok || !result.ok) {
                    setAiPending(false);
                    applyServerErrors(result);
                    return;
                }

                const suggestion = result.suggestion || {};
                nameInput.value = cleanText(suggestion.canonical_name) || canonicalName;
                if (registry.categories.some(category => category.key === suggestion.category)) {
                    categorySelect.value = suggestion.category;
                }
                editorAliases = Array.isArray(suggestion.aliases)
                    ? suggestion.aliases.map(cleanText).filter(Boolean)
                    : [...editorAliases];
                aliasInput.value = "";
                renderAliasChips();
                const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
                setEditorFeedback(
                    [result.message || "Unit details suggested. Review before saving.", ...warnings].join(" "),
                    warnings.length ? "warning" : "success",
                );
            } catch (error) {
                if (requestToken !== suggestionRequestToken) return;
                setEditorFeedback("AI suggestions are unavailable right now. Your entered values were not changed.");
                console.error("Unable to suggest unit details.", error);
            } finally {
                if (requestToken === suggestionRequestToken) setAiPending(false);
            }
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
                setEditorFeedback("The unit could not be saved. Check your connection and try again.");
                console.error("Unable to save unit.", error);
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = saveButtonLabel;
            }
        };

        root.querySelector("[data-unit-master-add-button]").addEventListener("click", event => openEditor(null, event.currentTarget));
        categoryList.addEventListener("click", event => {
            const usageButton = event.target.closest("[data-unit-master-usage-button]");
            if (usageButton) {
                openUsage(unitById(usageButton.dataset.unitId), usageButton);
                return;
            }
            const button = event.target.closest("[data-unit-master-edit-button]");
            if (!button) return;
            openEditor(unitById(button.dataset.unitId), button);
        });
        aliasAddButton.addEventListener("click", addPendingAlias);
        suggestButton.addEventListener("click", suggestUnitDetails);
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
        root.querySelectorAll("[data-unit-master-usage-close]").forEach(button => {
            button.addEventListener("click", closeUsage);
        });
        usageDialog.addEventListener("cancel", event => {
            event.preventDefault();
            closeUsage();
        });
        usageDialog.addEventListener("click", event => {
            if (event.target === usageDialog) closeUsage();
        });
        usageDialog.addEventListener("close", () => {
            if (usageReturnFocus && usageReturnFocus.isConnected) usageReturnFocus.focus();
            usageReturnFocus = null;
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
