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
        let orderPending = false;
        let mutationPending = false;
        let draggedRow = null;
        let rowDropTarget = null;
        let rowDropAfter = false;

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
            input.toggleAttribute("aria-invalid", Boolean(text));
        };

        const setEditorFeedback = (message, type = "error") => {
            editorFeedback.textContent = String(message || "");
            editorFeedback.dataset.status = type;
            editorFeedback.hidden = !editorFeedback.textContent;
        };

        const setAiPending = pending => {
            aiSuggestionPending = Boolean(pending);
            form.toggleAttribute("aria-busy", aiSuggestionPending);
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
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", `Edit ${unit.name}`);
            const action = document.createElement("div");
            action.className = "unit-master-action-cell";
            action.setAttribute("role", "cell");
            action.appendChild(edit);
            row.append(createOrderCell(unit, index + 1), name, aliases, usage, sourceBadge, action);
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
            saveButton.disabled = orderPending || mutationPending || aiSuggestionPending;
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
            addButtons.forEach(button => button.setAttribute("aria-expanded", "true"));
            requestAnimationFrame(focusEditorName);
        };

        const closeEditor = ({ restoreFocus = true } = {}) => {
            if (mutationPending) return;
            suggestionRequestToken += 1;
            form.hidden = true;
            form.classList.remove("is-editing");
            parkEditor();
            addButtons.forEach(button => button.setAttribute("aria-expanded", "false"));
            if (restoreFocus && returnFocus?.isConnected && typeof returnFocus.focus === "function") {
                try {
                    returnFocus.focus({ preventScroll: true });
                } catch (_error) {
                    returnFocus.focus();
                }
            }
            returnFocus = null;
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
                if (requestToken !== suggestionRequestToken || form.hidden) return;
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
            if (orderPending || mutationPending || aiSuggestionPending) return;
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
            mutationPending = true;
            syncOrderControls();
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
                mutationPending = false;
                closeEditor({ restoreFocus: false });
                updateRegistry(result.registry);
                setStatus(result.message || "Unit saved.");
            } catch (error) {
                setEditorFeedback("The unit could not be saved. Check your connection and try again.");
                console.error("Unable to save unit.", error);
            } finally {
                mutationPending = false;
                syncOrderControls();
                saveButton.disabled = false;
                saveButton.textContent = saveButtonLabel;
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
        root.querySelector("[data-unit-master-cancel]").addEventListener("click", closeEditor);
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
            if (usageReturnFocus && usageReturnFocus.isConnected) usageReturnFocus.focus();
            usageReturnFocus = null;
        });
        form.addEventListener("submit", saveUnit);
        search.addEventListener("input", applySearch);

        const browserUnits = legacyUnitNames();
        const importDismissed = sessionStorage.getItem(IMPORT_DISMISSED_KEY) === "true";
        importPanel.hidden = !browserUnits.length || importDismissed;
        importButton.addEventListener("click", async () => {
            if (orderPending || mutationPending) return;
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
