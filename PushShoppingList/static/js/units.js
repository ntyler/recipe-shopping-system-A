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

    function unitDraftSignature(values) {
        return JSON.stringify({
            canonical_name: cleanText(values.canonical_name),
            category: values.category,
            aliases: values.aliases.map(cleanText).sort(),
        });
    }

    function validateUnitDraft(values, registry, unitId = "") {
        const errors = { aliases: {} };
        const name = cleanText(values.canonical_name);
        const nameKey = unitKey(name);
        const owners = new Map();
        registry.units.filter(unit => String(unit.id) !== String(unitId)).forEach(unit => {
            [unit.name, ...(unit.aliases || [])].forEach(value => owners.set(unitKey(value), unit.name));
        });
        if (!name || !nameKey) errors.canonical_name = "Enter a canonical name.";
        else if (name.length > 60) errors.canonical_name = "Canonical names must be 60 characters or fewer.";
        else if (owners.has(nameKey)) errors.canonical_name = `“${name}” is already accepted by ${owners.get(nameKey)}.`;
        if (!registry.categories.some(category => category.key === values.category)) errors.category = "Choose a unit category.";
        const seen = new Set();
        values.aliases.forEach((value, index) => {
            const alias = cleanText(value), key = unitKey(alias);
            if (!alias || !key) errors.aliases[index] = "Enter an alias with letters or numbers.";
            else if (alias.length > 60) errors.aliases[index] = "Aliases must be 60 characters or fewer.";
            else if (key === nameKey) errors.aliases[index] = "The canonical name does not need to be an alias.";
            else if (seen.has(key)) errors.aliases[index] = `“${alias}” is already in this unit.`;
            else if (owners.has(key)) errors.aliases[index] = `“${alias}” is already accepted by ${owners.get(key)}.`;
            seen.add(key);
        });
        return errors;
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
        let usageScrollState = [];
        let orderPending = false;
        let mutationPending = false;
        let draggedRow = null;
        let rowDropTarget = null;
        let rowDropAfter = false;
        let originalDraft = null;
        let serverErrors = {};
        let showValidation = false;

        const source = document.getElementById("ingredientUnitConfig");
        const status = root.querySelector("[data-unit-master-status]");
        const search = root.querySelector("[data-unit-master-search]");
        const searchEmpty = root.querySelector("[data-unit-master-search-empty]");
        const categoryList = root.querySelector("[data-unit-master-category-list]");
        const form = root.querySelector("[data-unit-master-form]");
        const editorHome = root.querySelector("[data-unit-master-editor-home]");
        const addButtons = Array.from(root.querySelectorAll("[data-unit-master-add-button]"));
        const countLabel = root.querySelector("[data-unit-master-count-label]");
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
        const aliasPreview = root.querySelector("[data-unit-master-alias-preview]");
        const dirtyStatus = root.querySelector("[data-unit-master-dirty-status]");
        const editorUsage = root.querySelector("[data-unit-master-editor-usage]");
        const editorImpact = root.querySelector("[data-unit-master-editor-impact]");
        const editorPermissions = root.querySelector("[data-unit-master-editor-permissions]");
        const cancelButton = root.querySelector("[data-unit-master-cancel]");
        const importPanel = root.querySelector("[data-unit-master-import]");
        const importButton = root.querySelector("[data-unit-master-import-button]");
        const usageDialog = root.querySelector("[data-unit-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-unit-master-usage-title]");
        const usageContext = root.querySelector("[data-unit-master-usage-context]");
        const usageSummary = root.querySelector("[data-unit-master-usage-summary]");
        const usageResults = root.querySelector("[data-unit-master-usage-results]");

        const setStatus = (message, type = "success", announceOnly = false) => {
            status.classList.toggle("sr-only", announceOnly);
            status.textContent = String(message || "");
            status.dataset.status = type;
            status.hidden = !status.textContent;
        };

        const setFieldError = (input, output, message) => {
            const text = String(message || "");
            output.textContent = text;
            output.hidden = !text;
            if (text) input.setAttribute("aria-invalid", "true");
            else input.removeAttribute("aria-invalid");
        };

        const setEditorFeedback = (message, type = "error") => {
            editorFeedback.textContent = String(message || "");
            editorFeedback.dataset.status = type;
            editorFeedback.hidden = !editorFeedback.textContent;
        };

        const setAiPending = pending => {
            aiSuggestionPending = Boolean(pending);
            suggestButtonLabel.textContent = aiSuggestionPending ? "Suggesting…" : "Suggest aliases";
            syncEditorState();
        };

        const clearErrors = () => {
            editorAliasErrors = {};
            serverErrors = {};
            setFieldError(nameInput, nameError, "");
            setFieldError(categorySelect, categoryError, "");
            setFieldError(aliasInput, aliasError, "");
            setEditorFeedback("");
            renderAliasChips();
        };

        const unitById = unitId => registry.units.find(unit => String(unit.id) === String(unitId)) || null;

        const syncReadOnlyContext = unit => {
            categorySelect.hidden = Boolean(unit);
            categorySelect.disabled = Boolean(unit);
            const context = root.querySelector("[data-unit-master-category-readonly]");
            context.hidden = !unit;
            context.textContent = registry.categories.find(item => item.key === unit?.category)?.label || "";
            root.querySelector("[data-unit-master-category-help]").textContent = unit
                ? "Read-only. Editing a unit does not redefine its measurement."
                : "Choose the closest culinary group for this new unit.";
            root.querySelector("[data-unit-master-source-context]").hidden = !unit;
            root.querySelector("[data-unit-master-source-readonly]").textContent = unit?.seeded ? "System-seeded" : "User-created";
            editorPermissions.textContent = unit
                ? "Edit the canonical name and accepted aliases. The previous name remains an alias. Change recipe ingredients through Used in."
                    + (unit.seeded ? " System-seeded units cannot be deleted." : "")
                : "Choose a canonical name, category, and accepted aliases.";
        };

        const editorValues = (includePending = false) => ({
            canonical_name: cleanText(nameInput.value),
            category: categorySelect.value,
            aliases: [...editorAliases, ...(includePending && cleanText(aliasInput.value) ? [cleanText(aliasInput.value)] : [])],
        });
        const editorIsDirty = () => Boolean(originalDraft && (
            unitDraftSignature(editorValues()) !== unitDraftSignature(originalDraft) || cleanText(aliasInput.value)
        ));
        const editorValidation = () => {
            const local = validateUnitDraft(editorValues(true), registry, editorUnitId);
            return { ...local, ...serverErrors, aliases: { ...local.aliases, ...(serverErrors.aliases || {}) } };
        };
        const syncEditorState = () => {
            const errors = editorValidation();
            const invalid = Boolean(errors.canonical_name || errors.category || Object.keys(errors.aliases).length);
            const dirty = editorIsDirty();
            const busy = mutationPending || aiSuggestionPending || orderPending;
            form.setAttribute("aria-busy", String(mutationPending || aiSuggestionPending));
            form.classList.toggle("is-dirty", dirty);
            saveButton.disabled = busy || !dirty || invalid;
            suggestButton.disabled = busy || !unitKey(nameInput.value);
            [nameInput, aliasInput, aliasAddButton].forEach(control => { control.disabled = busy; });
            categorySelect.disabled = busy || Boolean(editorUnitId);
            cancelButton.disabled = mutationPending || orderPending;
            aliasChips.querySelectorAll("button").forEach(button => { button.disabled = busy; });
            setFieldError(nameInput, nameError, showValidation ? errors.canonical_name : "");
            setFieldError(categorySelect, categoryError, showValidation ? errors.category : "");
            setFieldError(aliasInput, aliasError, showValidation ? [...new Set(Object.values(errors.aliases))].join(" ") : "");
            editorAliasErrors = errors.aliases;
            Array.from(aliasChips.children).forEach((chip, index) => {
                const error = errors.aliases[index] || "";
                chip.classList.toggle("has-error", Boolean(error));
                chip.title = error;
            });
            const nextStatus = mutationPending ? "Saving changes…" : dirty ? "Unsaved changes" : "";
            if (dirtyStatus.textContent !== nextStatus) dirtyStatus.textContent = nextStatus;
            const aliases = editorValues(true).aliases.filter((_, index) => !errors.aliases[index]).slice(0, 2);
            const name = cleanText(nameInput.value);
            const preview = name ? aliases.length
                ? `${aliases.map(alias => `“${alias}”`).join(" and ")} will normalize to “${name}”.`
                : `“${name}” is accepted as the canonical unit.` : "";
            if (aliasPreview.textContent !== preview) aliasPreview.textContent = preview;
        };

        // Keep the expanded editor at the same viewport position when rows are rebuilt.
        const captureEditorScroll = (anchor = form) => {
            const top = anchor.getBoundingClientRect().top;
            const scrollers = [];
            for (let element = anchor.parentElement; element; element = element.parentElement) {
                if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) scrollers.push([element, element.scrollTop]);
            }
            scrollers.push([document.scrollingElement, document.scrollingElement.scrollTop]);
            return () => {
                scrollers.forEach(([element, position]) => { element.scrollTop = position; });
                if (anchor.isConnected && anchor.getClientRects().length) {
                    scrollers[0][0].scrollTop += anchor.getBoundingClientRect().top - top;
                }
            };
        };

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
                    serverErrors = {};
                    showValidation = true;
                    renderAliasChips();
                    setEditorFeedback("");
                    syncEditorState();
                    aliasInput.focus({ preventScroll: true });
                });
                chip.append(text, remove);
                aliasChips.appendChild(chip);
            });
        };

        const localAliasError = alias => {
            if (!alias) return "Enter an alias first.";
            return validateUnitDraft({ ...editorValues(), aliases: [...editorAliases, alias] }, registry, editorUnitId).aliases[editorAliases.length] || "";
        };

        const addPendingAlias = () => {
            if (mutationPending || orderPending || aiSuggestionPending) return false;
            const alias = cleanText(aliasInput.value);
            if (!alias) { aliasInput.focus({ preventScroll: true }); return false; }
            const error = localAliasError(alias);
            showValidation = true;
            syncEditorState();
            setFieldError(aliasInput, aliasError, error);
            if (error) return false;
            editorAliases.push(alias);
            aliasInput.value = "";
            renderAliasChips();
            setEditorFeedback("");
            syncEditorState();
            aliasInput.focus({ preventScroll: true });
            return true;
        };

        const renderStats = () => {
            root.querySelector("[data-unit-master-total-count]").textContent = String(registry.units.length);
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
            usage.dataset.mobileLabel = "Used in";
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

        const createOrderCell = (item, position) => {
            const label = item.name;
            const cell = document.createElement("div");
            cell.className = "store-section-master-order-cell unit-master-order-cell";
            cell.setAttribute("role", "cell");
            cell.setAttribute("aria-colindex", "1");
            cell.dataset.mobileLabel = "Order";

            const order = document.createElement("div");
            order.className = "store-section-master-order";

            const handle = document.createElement("button");
            handle.type = "button";
            handle.className = "store-section-master-drag-handle";
            handle.dataset.unitMasterDragHandle = "";
            handle.setAttribute("aria-label", `Drag ${label} to reorder`);
            handle.title = `Drag to reorder ${label}`;
            handle.setAttribute("aria-describedby", "unitMasterOrderHelp");
            handle.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown Home End");
            handle.innerHTML = [
                '<svg viewBox="0 0 16 20" aria-hidden="true">',
                '<circle cx="5" cy="4" r="1.4"></circle>',
                '<circle cx="11" cy="4" r="1.4"></circle>',
                '<circle cx="5" cy="10" r="1.4"></circle>',
                '<circle cx="11" cy="10" r="1.4"></circle>',
                '<circle cx="5" cy="16" r="1.4"></circle>',
                '<circle cx="11" cy="16" r="1.4"></circle>',
                "</svg>",
            ].join("");

            const up = document.createElement("button");
            up.type = "button";
            up.value = "move_up";
            up.dataset.unitMasterOrderAction = "up";
            up.setAttribute("aria-label", `Move ${label} up`);
            up.innerHTML = [
                '<svg viewBox="0 0 24 24" aria-hidden="true">',
                '<path d="M12 19V5"></path>',
                '<path d="m6 11 6-6 6 6"></path>',
                "</svg>",
            ].join("");

            const number = document.createElement("span");
            number.className = "store-section-master-order-step";
            number.dataset.unitMasterOrderNumber = "";
            number.textContent = String(position);
            number.setAttribute("aria-label", `Step ${position}`);

            const down = document.createElement("button");
            down.type = "button";
            down.value = "move_down";
            down.dataset.unitMasterOrderAction = "down";
            down.setAttribute("aria-label", `Move ${label} down`);
            down.innerHTML = [
                '<svg viewBox="0 0 24 24" aria-hidden="true">',
                '<path d="M12 5v14"></path>',
                '<path d="m6 13 6 6 6-6"></path>',
                "</svg>",
            ].join("");

            order.append(handle, up, number, down);
            cell.appendChild(order);
            return cell;
        };


        const createUnitRow = (unit, index) => {
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.unitMasterRow = "";
            row.dataset.unitId = unit.id;
            row.dataset.unitMasterSearchValue = `${unit.name} ${(unit.aliases || []).join(" ")}`;

            const name = document.createElement("strong");
            name.setAttribute("role", "cell");
            name.dataset.mobileLabel = "Canonical name";
            name.textContent = unit.name;
            const aliases = document.createElement("div");
            aliases.className = "unit-master-aliases";
            aliases.setAttribute("role", "cell");
            aliases.dataset.mobileLabel = "Accepted aliases";
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
            sourceBadge.textContent = unit.seeded ? "Built-in" : "User-created";
            const usage = createUsageCell(unit);
            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.unitMasterEditButton = "";
            edit.dataset.unitId = unit.id;
            edit.textContent = "Edit unit";
            edit.setAttribute("aria-label", `Edit unit ${unit.name}`);
            edit.setAttribute("aria-controls", "unitMasterInlineEditor");
            edit.setAttribute("aria-expanded", "false");
            const action = document.createElement("div");
            action.className = "unit-master-action-cell";
            action.setAttribute("role", "cell");
            action.appendChild(edit);
            const category = document.createElement("span");
            category.className = "unit-master-category-cell";
            category.setAttribute("role", "cell");
            category.dataset.mobileLabel = "Category";
            category.textContent = registry.categories.find(item => item.key === unit.category)?.label || unit.category;
            row.append(createOrderCell(unit, index + 1), name, aliases, category, usage, sourceBadge, action);
            return row;
        };

        const applySearch = () => {
            const query = unitKey(search.value);
            let visibleCount = 0;
            root.querySelectorAll("[data-unit-master-category]").forEach(category => {
                let categoryCount = 0;
                category.querySelectorAll("[data-unit-master-row]").forEach(row => {
                    // Keep a saved rename visible until its editor closes, even if it
                    // no longer matches the search, without changing the filter.
                    const visible = !query || unitKey(row.dataset.unitMasterSearchValue).includes(query)
                        || (!form.hidden && row.dataset.unitId === editorUnitId);
                    row.hidden = !visible;
                    if (visible) categoryCount += 1;
                });
                category.hidden = categoryCount === 0;
                category.querySelector("[data-unit-master-category-count-label]").textContent = `${categoryCount} unit${categoryCount === 1 ? "" : "s"}`;
                visibleCount += categoryCount;
            });
            searchEmpty.hidden = visibleCount > 0;
            countLabel.textContent = `Showing ${visibleCount} of ${registry.units.length} Unit${registry.units.length === 1 ? "" : "s"}.`;
            syncOrderControls();
        };

        const categoryRows = container => Array.from(container.querySelectorAll("[data-unit-master-row]"));
        const reorderIsBlocked = () => orderPending || mutationPending || Boolean(unitKey(search.value));
        const syncOrderControls = () => {
            const blocked = reorderIsBlocked();
            root.querySelectorAll("[data-unit-master-category-rows]").forEach(container => {
                const rows = categoryRows(container);
                rows.forEach((row, index) => {
                    const number = row.querySelector("[data-unit-master-order-number]");
                    number.textContent = String(index + 1);
                    number.setAttribute("aria-label", `Step ${index + 1}`);
                    const handle = row.querySelector("[data-unit-master-drag-handle]");
                    handle.draggable = !blocked;
                    handle.setAttribute("aria-disabled", String(blocked));
                    row.querySelector('[data-unit-master-order-action="up"]').disabled = blocked || index === 0;
                    row.querySelector('[data-unit-master-order-action="down"]').disabled = blocked || index === rows.length - 1;
                    row.querySelector("[data-unit-master-edit-button]").disabled = orderPending || mutationPending;
                });
            });
            addButtons.forEach(button => { button.disabled = orderPending || mutationPending; });
            importButton.disabled = orderPending || mutationPending;
            syncEditorState();
        };
        const placeRows = (container, rows) => {
            rows.forEach(row => {
                container.appendChild(row);
                // Keep an open editor and its unsaved aliases with the unit.
                if (!form.hidden && editorUnitId === row.dataset.unitId) container.appendChild(form);
            });
        };
        const moveRowTo = async (row, targetIndex, trigger) => {
            if (!row || reorderIsBlocked()) return;
            const container = row.closest("[data-unit-master-category-rows]");
            const previous = categoryRows(container);
            const current = previous.indexOf(row);
            const target = Math.max(0, Math.min(previous.length - 1, targetIndex));
            if (current === target) return;
            const ordered = [...previous];
            ordered.splice(target, 0, ordered.splice(current, 1)[0]);
            orderPending = true;
            placeRows(container, ordered);
            syncOrderControls();
            // Announce without inserting a banner above the table during a drag.
            setStatus("Saving unit order…", "info", true);
            try {
                const response = await fetch(root.dataset.updateUrlTemplate.replace("__UNIT_ID__", encodeURIComponent(row.dataset.unitId)), {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify({ action: "move_to", position: target + 1 }),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) throw new Error(result.error || "The unit order could not be saved.");
                registry = result.registry;
                source.textContent = JSON.stringify(registry);
                const category = container.closest("[data-unit-master-category]").dataset.category;
                const byId = new Map(previous.map(item => [item.dataset.unitId, item]));
                const saved = registry.units.filter(unit => unit.category === category);
                placeRows(container, saved.map((unit, index) => byId.get(String(unit.id)) || createUnitRow(unit, index)));
                setStatus(result.message || "Unit order saved.", "success", true);
            } catch (error) {
                placeRows(container, previous);
                status.classList.remove("sr-only");
                setStatus(error.message || "The unit order could not be saved. Try again.", "error");
            } finally {
                orderPending = false;
                applySearch();
                const focusTarget = trigger?.disabled ? row.querySelector("[data-unit-master-drag-handle]") : trigger;
                focusTarget?.focus({ preventScroll: true });
            }
        };
        const clearRowDropState = () => {
            categoryRows(categoryList).forEach(row => row.classList.remove("is-row-drop-before", "is-row-drop-after", "is-row-dragging"));
            rowDropTarget = null;
        };

        const parkEditor = () => {
            if (form.parentElement !== editorHome.parentElement || form.nextElementSibling !== editorHome) {
                editorHome.before(form);
            }
        };

        const renderRegistry = () => {
            parkEditor();
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
            if (match.edit_url) {
                const edit = document.createElement("a");
                edit.className = "unit-master-usage-match-edit";
                edit.href = match.edit_url;
                edit.target = "_blank";
                edit.rel = "noopener noreferrer";
                edit.textContent = "Edit ingredient";
                edit.setAttribute("aria-label", `Edit ingredient ${match.ingredient_name || "entry"} in recipe`);
                item.appendChild(edit);
            }
            return item;
        };

        const createUsageRecipeVisual = reference => {
            const editUrl = String(reference.edit_url || "");
            const recipeTitle = reference.recipe_title || reference.recipe_id || "Recipe";
            const visual = document.createElement(editUrl ? "a" : "span");
            visual.className = "unit-master-usage-recipe-visual";
            if (editUrl) {
                visual.href = editUrl;
                visual.target = "_blank";
                visual.rel = "noopener noreferrer";
                visual.setAttribute("aria-label", `Open ${recipeTitle}`);
            }

            const fallback = document.createElement("span");
            fallback.className = "unit-master-usage-recipe-fallback";
            fallback.setAttribute("aria-hidden", "true");
            const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
            svg.setAttribute("viewBox", "0 0 24 24");
            svg.setAttribute("focusable", "false");
            const documentOutline = document.createElementNS("http://www.w3.org/2000/svg", "path");
            documentOutline.setAttribute("d", "M6 3h8l4 4v14H6zM14 3v5h4");
            const recipeLines = document.createElementNS("http://www.w3.org/2000/svg", "path");
            recipeLines.setAttribute("d", "M9 12h6M9 16h6");
            svg.append(documentOutline, recipeLines);
            fallback.appendChild(svg);

            const imageUrl = String(reference.recipe_image_url || "");
            if (!imageUrl) {
                visual.appendChild(fallback);
                return visual;
            }

            visual.classList.add("has-image");
            const image = document.createElement("img");
            image.src = imageUrl;
            image.alt = String(reference.recipe_image_alt || `${recipeTitle} image`);
            image.loading = "lazy";
            image.decoding = "async";
            const srcset = String(reference.recipe_image_srcset || "");
            if (srcset) {
                image.srcset = srcset;
                image.sizes = "52px";
            }
            fallback.hidden = true;
            const revealFallback = () => {
                image.hidden = true;
                image.removeAttribute("srcset");
                visual.classList.remove("has-image");
                fallback.hidden = false;
            };
            image.addEventListener("error", revealFallback, { once: true });
            visual.append(image, fallback);
            if (image.complete && !image.naturalWidth) revealFallback();
            return visual;
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
                const visual = createUsageRecipeVisual(reference);
                const header = document.createElement("header");
                const heading = document.createElement("h3");
                const recipeTitle = reference.recipe_title || reference.recipe_id || "Recipe";
                if (reference.edit_url) {
                    const titleLink = document.createElement("a");
                    titleLink.href = reference.edit_url;
                    titleLink.target = "_blank";
                    titleLink.rel = "noopener noreferrer";
                    titleLink.textContent = recipeTitle;
                    heading.appendChild(titleLink);
                } else {
                    heading.textContent = recipeTitle;
                }
                header.appendChild(heading);
                if (reference.edit_url) {
                    const link = document.createElement("a");
                    link.href = reference.edit_url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = "Open Recipe";
                    header.appendChild(link);
                }
                card.append(visual, header);

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

        const restoreUsageContext = () => {
            usageScrollState.forEach(({element, overflow, padding, top, left}) => {
                element.style.overflow = overflow; element.style.paddingRight = padding;
                element.scrollTop = top; element.scrollLeft = left;
            });
            usageScrollState = [];
            if (usageReturnFocus?.isConnected) usageReturnFocus.focus({preventScroll: true});
            usageReturnFocus = null;
        };

        const closeUsage = () => {
            usageRequestToken += 1;
            if (usageDialog.open) usageDialog.close();
            restoreUsageContext();
        };

        const openUsage = async (unit, trigger) => {
            if (!unit || !usageDialog) return;
            if (!usageDialog.open) usageReturnFocus = trigger || document.activeElement;
            usageTitle.textContent = `Recipes using ${unit.name}`;
            usageContext.textContent = "Usage is calculated from saved recipe ingredients. Edit an ingredient in its recipe to change its amount or unit, then save the recipe.";
            setUsageState("Loading connected recipes…");
            if (!usageDialog.open) {
                usageScrollState = [...new Set([document.documentElement, document.body, document.getElementById("appContent")])].filter(Boolean).map(element => {
                    const state = {element, overflow: element.style.overflow, padding: element.style.paddingRight, top: element.scrollTop, left: element.scrollLeft};
                    const width = element.clientWidth;
                    const padding = parseFloat(getComputedStyle(element).paddingRight) || 0;
                    element.style.overflow = "hidden";
                    if (element.clientWidth > width) element.style.paddingRight = `${padding + element.clientWidth - width}px`;
                    return state;
                });
                usageDialog.showModal();
                usageDialog.querySelector('[data-unit-master-usage-close]').focus({preventScroll: true});
                usageScrollState.forEach(({element, top, left}) => { element.scrollTop = top; element.scrollLeft = left; });
            }

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
                let data = await response.json().catch(() => ({}));
                if (requestToken !== usageRequestToken || !usageDialog.open) return;
                if (!response.ok || data.ok === false) {
                    setUsageState(data.error || "Connected recipes could not be loaded.", "error");
                    return;
                }
                let offset = 0;
                while (data.next_offset != null) {
                    const next = Number(data.next_offset);
                    if (!Number.isInteger(next) || next <= offset) throw new Error("Invalid usage page.");
                    offset = next;
                    const url = new URL(referenceUrl, window.location.href);
                    url.searchParams.set("offset", String(offset));
                    const nextResponse = await fetch(url, {headers: {Accept: "application/json", "X-Requested-With": "fetch"}});
                    const page = await nextResponse.json();
                    if (requestToken !== usageRequestToken || !usageDialog.open) return;
                    if (!nextResponse.ok || page.ok === false) throw new Error("Unable to load remaining recipes.");
                    data = {...page, references: [...data.references, ...page.references]};
                }
                renderUsageReferences(data);
            } catch (error) {
                if (requestToken !== usageRequestToken) return;
                setUsageState("Connected recipes could not be loaded. Try again.", "error");
                console.error("Unable to load unit recipe usage.", error);
            }
        };

        const focusEditorName = () => {
            try {
                nameInput.focus({ preventScroll: true });
            } catch (_error) {
                nameInput.focus();
            }
            const rect = nameInput.getBoundingClientRect();
            if (rect.top < 0 || rect.bottom > window.innerHeight) {
                nameInput.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
        };

        const openEditor = (unit = null, trigger = null) => {
            if (orderPending || mutationPending) return;
            if (!form.hidden) {
                if (editorUnitId === String(unit?.id || "")) { focusEditorName(); return; }
                if (!closeEditor({ restoreFocus: false })) { focusEditorName(); return; }
            }
            suggestionRequestToken += 1;
            returnFocus = trigger || document.activeElement;
            editorUnitId = unit ? String(unit.id) : "";
            editorAliases = unit && Array.isArray(unit.aliases) ? [...unit.aliases] : [];
            editorTitle.textContent = unit ? `Edit ${unit.name}` : "Add Unit";
            editorKicker.textContent = unit?.seeded ? "System-seeded" : unit ? "User-created" : "New workspace unit";
            editorUsage.hidden = !unit;
            const count = Number(unit?.recipe_count || 0);
            editorUsage.textContent = `Used in ${count} recipe${count === 1 ? "" : "s"}`;
            editorImpact.hidden = !unit;
            syncReadOnlyContext(unit);
            saveButtonLabel = unit ? "Save changes" : "Add Unit";
            saveButton.textContent = saveButtonLabel;
            nameInput.value = unit?.name || "";
            categorySelect.value = unit?.category || "count_package";
            aliasInput.value = "";
            originalDraft = editorValues();
            showValidation = false;
            setAiPending(false);
            clearErrors();
            renderAliasChips();
            const row = unit
                ? root.querySelector(`[data-unit-master-row][data-unit-id="${CSS.escape(String(unit.id))}"]`)
                : null;
            if (row) {
                row.insertAdjacentElement("afterend", form);
            } else {
                editorHome.before(form);
            }
            form.hidden = false;
            form.classList.toggle("is-editing", Boolean(unit));
            addButtons.forEach(button => button.setAttribute("aria-expanded", String(!unit)));
            if (trigger) trigger.setAttribute("aria-expanded", "true");
            syncEditorState();
            requestAnimationFrame(focusEditorName);
        };

        const closeEditor = ({ restoreFocus = true, discard = false } = {}) => {
            if (mutationPending || orderPending) return false;
            if (!discard && !form.hidden && editorIsDirty() && !window.confirm("Discard unsaved changes to this unit?")) return false;
            const restoreScroll = captureEditorScroll(returnFocus?.isConnected ? returnFocus : form);
            suggestionRequestToken += 1;
            aiSuggestionPending = false;
            if (originalDraft) {
                nameInput.value = originalDraft.canonical_name;
                categorySelect.value = originalDraft.category;
                editorAliases = [...originalDraft.aliases];
            }
            aliasInput.value = "";
            clearErrors();
            syncEditorState();
            form.hidden = true;
            form.classList.remove("is-editing");
            parkEditor();
            addButtons.forEach(button => button.setAttribute("aria-expanded", "false"));
            returnFocus?.setAttribute("aria-expanded", "false");
            applySearch();
            const focusTarget = returnFocus?.isConnected && returnFocus.getClientRects().length ? returnFocus : search;
            if (restoreFocus) {
                try {
                    focusTarget.focus({ preventScroll: true });
                } catch (_error) {
                    focusTarget.focus();
                }
            }
            restoreScroll();
            returnFocus = null;
            return true;
        };

        const applyServerErrors = payload => {
            serverErrors = payload.errors || {};
            showValidation = true;
            syncEditorState();
            setEditorFeedback(payload.error || "Unable to save this unit.");
            const firstInvalid = form.querySelector('[aria-invalid="true"]');
            if (firstInvalid) firstInvalid.focus({ preventScroll: true });
        };

        const suggestUnitDetails = async () => {
            if (mutationPending || orderPending || aiSuggestionPending) return;
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
            setEditorFeedback("AI is suggesting aliases for this measurement.", "pending");
            try {
                const response = await fetch(root.dataset.suggestUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                    body: JSON.stringify(payload),
                });
                const result = await response.json().catch(() => ({}));
                if (requestToken !== suggestionRequestToken || form.hidden) return;
                if (!response.ok || !result.ok) {
                    setAiPending(false);
                    applyServerErrors(result);
                    return;
                }

                const suggestion = result.suggestion || {};
                editorAliases = Array.isArray(suggestion.aliases)
                    ? suggestion.aliases.map(cleanText).filter(Boolean)
                    : [...editorAliases];
                aliasInput.value = "";
                renderAliasChips();
                showValidation = true;
                const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
                setEditorFeedback(
                    [result.message || "Aliases suggested. Review before saving.", ...warnings].join(" "),
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
            if (orderPending || mutationPending || aiSuggestionPending) return;
            const activeControl = form.contains(document.activeElement) ? document.activeElement : nameInput;
            const restoreScroll = captureEditorScroll();
            showValidation = true;
            syncEditorState();
            if (saveButton.disabled) return;
            if (cleanText(aliasInput.value) && !addPendingAlias()) return;
            clearErrors();
            const payload = {
                canonical_name: cleanText(nameInput.value),
                category: categorySelect.value,
                aliases: [...editorAliases],
            };
            const url = editorUnitId
                ? root.dataset.updateUrlTemplate.replace("__UNIT_ID__", encodeURIComponent(editorUnitId))
                : root.dataset.createUrl;
            mutationPending = true;
            syncOrderControls();
            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            setEditorFeedback("Saving changes…", "pending");
            let saved = false;
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
                // Keep the editor expanded so feedback and keyboard context stay local.
                editorUnitId = String(result.unit_id || editorUnitId);
                updateRegistry(result.registry);
                const unit = unitById(result.unit_id || editorUnitId);
                editorUnitId = String(unit.id);
                const row = root.querySelector(`[data-unit-master-row][data-unit-id="${CSS.escape(editorUnitId)}"]`);
                row.insertAdjacentElement("afterend", form);
                returnFocus = row.querySelector("[data-unit-master-edit-button]");
                returnFocus.setAttribute("aria-expanded", "true");
                nameInput.value = unit.name;
                categorySelect.value = unit.category;
                syncReadOnlyContext(unit);
                editorAliases = [...unit.aliases];
                aliasInput.value = "";
                originalDraft = editorValues();
                editorTitle.textContent = `Edit ${unit.name}`;
                editorKicker.textContent = unit.seeded ? "System-seeded" : "User-created";
                editorUsage.hidden = false;
                const count = Number(unit.recipe_count || 0);
                editorUsage.textContent = `Used in ${count} recipe${count === 1 ? "" : "s"}`;
                editorImpact.hidden = false;
                form.classList.add("is-editing");
                addButtons.forEach(button => button.setAttribute("aria-expanded", "false"));
                saveButtonLabel = "Save changes";
                renderAliasChips();
                saved = true;
                const outsideSearch = unitKey(search.value) && !unitKey(row.dataset.unitMasterSearchValue).includes(unitKey(search.value));
                setEditorFeedback([
                    result.message || "Changes saved.",
                    outsideSearch ? "This unit no longer matches your search and will be hidden when you close the editor." : "",
                ].filter(Boolean).join(" "), "success");
            } catch (error) {
                setEditorFeedback("The unit could not be saved. Check your connection and try again.");
                console.error("Unable to save unit.", error);
            } finally {
                mutationPending = false;
                syncOrderControls();
                saveButton.textContent = saveButtonLabel;
                if (saved) {
                    (activeControl.isConnected && !activeControl.disabled ? activeControl : editorFeedback).focus({ preventScroll: true });
                    restoreScroll();
                } else {
                    form.querySelector('[aria-invalid="true"]')?.focus({ preventScroll: true });
                }
            }
        };

        addButtons.forEach(button => {
            button.addEventListener("click", event => openEditor(null, event.currentTarget));
        });
        categoryList.addEventListener("click", event => {
            const action = event.target.closest("[data-unit-master-order-action]");
            if (action) {
                const row = action.closest("[data-unit-master-row]");
                const rows = categoryRows(row.parentElement);
                moveRowTo(row, rows.indexOf(row) + (action.dataset.unitMasterOrderAction === "up" ? -1 : 1), action);
                return;
            }
            const usageButton = event.target.closest("[data-unit-master-usage-button]");
            if (usageButton) {
                openUsage(unitById(usageButton.dataset.unitId), usageButton);
                return;
            }
            const button = event.target.closest("[data-unit-master-edit-button]");
            if (!button) return;
            openEditor(unitById(button.dataset.unitId), button);
        });
        categoryList.addEventListener("keydown", event => {
            const handle = event.target.closest("[data-unit-master-drag-handle]");
            if (!handle || !["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const row = handle.closest("[data-unit-master-row]");
            const rows = categoryRows(row.parentElement);
            const target = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1
                : rows.indexOf(row) + (event.key === "ArrowUp" ? -1 : 1);
            moveRowTo(row, target, handle);
        });
        categoryList.addEventListener("dragstart", event => {
            const handle = event.target.closest("[data-unit-master-drag-handle]");
            if (!handle || reorderIsBlocked()) { event.preventDefault(); return; }
            draggedRow = handle.closest("[data-unit-master-row]");
            draggedRow.classList.add("is-row-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", draggedRow.dataset.unitId);
        });
        categoryList.addEventListener("dragover", event => {
            if (!draggedRow) return;
            event.preventDefault();
            clearRowDropState();
            const target = event.target.closest("[data-unit-master-row]");
            if (reorderIsBlocked() || !target || target === draggedRow || target.parentElement !== draggedRow.parentElement) {
                event.dataTransfer.dropEffect = "none";
                return;
            }
            event.dataTransfer.dropEffect = "move";
            draggedRow.classList.add("is-row-dragging");
            const rect = target.getBoundingClientRect();
            rowDropAfter = event.clientY > rect.top + rect.height / 2;
            rowDropTarget = target;
            target.classList.add(rowDropAfter ? "is-row-drop-after" : "is-row-drop-before");
        });
        categoryList.addEventListener("drop", event => {
            if (!draggedRow) return;
            event.preventDefault();
            if (!rowDropTarget || reorderIsBlocked()) return;
            const moving = draggedRow;
            const rows = categoryRows(moving.parentElement);
            let target = rows.indexOf(rowDropTarget) + (rowDropAfter ? 1 : 0);
            if (rows.indexOf(moving) < target) target -= 1;
            clearRowDropState();
            draggedRow = null;
            moveRowTo(moving, target, moving.querySelector("[data-unit-master-drag-handle]"));
        });
        categoryList.addEventListener("dragend", () => {
            clearRowDropState();
            draggedRow = null;
        });
        aliasAddButton.addEventListener("click", addPendingAlias);
        suggestButton.addEventListener("click", suggestUnitDetails);
        aliasInput.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addPendingAlias();
            }
        });
        cancelButton.addEventListener("click", () => closeEditor());
        form.addEventListener("input", event => {
            showValidation = true;
            if (event.target === nameInput) delete serverErrors.canonical_name;
            if (event.target === categorySelect) delete serverErrors.category;
            setEditorFeedback("");
            syncEditorState();
        });
        categorySelect.addEventListener("change", () => { delete serverErrors.category; showValidation = true; syncEditorState(); });
        window.addEventListener("beforeunload", event => {
            if (!form.hidden && (editorIsDirty() || mutationPending)) { event.preventDefault(); event.returnValue = ""; }
        });
        form.addEventListener("keydown", event => {
            if (event.key !== "Escape") return;
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
            if (!usageDialog.open) restoreUsageContext();
        });

        // Returning from a recipe editor refreshes calculated counts without replacing a unit draft.
        const refreshUsageCounts = async () => {
            if (mutationPending || document.visibilityState === "hidden") return;
            try {
                const response = await fetch(root.dataset.createUrl, {headers: {Accept: "application/json"}});
                const data = await response.json();
                if (!response.ok || !data.ok || mutationPending) return;
                (data.registry?.units || []).forEach(saved => {
                    const unit = unitById(saved.id);
                    if (!unit) return;
                    unit.recipe_count = saved.recipe_count;
                    const row = root.querySelector(`[data-unit-master-row][data-unit-id="${CSS.escape(String(unit.id))}"]`);
                    const previous = row?.querySelector('.unit-master-usage');
                    if (!previous) return;
                    const returningHere = previous.contains(usageReturnFocus);
                    const next = createUsageCell(unit);
                    previous.replaceWith(next);
                    if (returningHere) usageReturnFocus = next.querySelector('button') || row.querySelector('[data-unit-master-edit-button]');
                    if (!form.hidden && editorUnitId === String(unit.id)) editorUsage.textContent = `Used in ${unit.recipe_count} recipe${unit.recipe_count === 1 ? "" : "s"}`;
                });
                if (usageDialog.open && usageReturnFocus) {
                    await openUsage(unitById(usageReturnFocus.dataset.unitId), usageReturnFocus);
                }
            } catch (_) { /* The next usage open retries through the normal error state. */ }
        };
        window.addEventListener("focus", refreshUsageCounts);
        form.addEventListener("submit", saveUnit);
        let previousSearch = search.value;
        search.addEventListener("input", () => {
            const current = unitById(editorUnitId);
            const hidesEditor = !current || !unitKey(`${current.name} ${(current.aliases || []).join(" ")}`).includes(unitKey(search.value));
            if (!form.hidden && hidesEditor && !closeEditor()) { search.value = previousSearch; return; }
            previousSearch = search.value;
            applySearch();
        });

        const browserUnits = legacyUnitNames();
        const importDismissed = sessionStorage.getItem(IMPORT_DISMISSED_KEY) === "true";
        importPanel.hidden = !browserUnits.length || importDismissed;
        importButton.addEventListener("click", async () => {
            if (orderPending || mutationPending) return;
            if (!form.hidden && !closeEditor()) return;
            mutationPending = true;
            syncOrderControls();
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
                mutationPending = false;
                syncOrderControls();
                importButton.disabled = false;
                importButton.textContent = "Import units";
            }
        });
        root.querySelector("[data-unit-master-import-dismiss]").addEventListener("click", () => {
            sessionStorage.setItem(IMPORT_DISMISSED_KEY, "true");
            importPanel.hidden = true;
        });

        // Keep the finished server-rendered rows and controls through startup.
        renderStats();
        applySearch();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initUnitMasterPage, { once: true });
    } else {
        initUnitMasterPage();
    }
}());
