(function () {
    "use strict";

    const LEGACY_CUSTOM_TYPES_KEY = "recipeIngredientCustomTypes";
    const IMPORT_DISMISSED_KEY = "recipeIngredientCustomTypesImportDismissed";

    function cleanText(value) {
        return String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ");
    }

    function typeKey(value) {
        return cleanText(value).toLowerCase().replace(/[_-]+/g, " ");
    }

    function parseRegistry() {
        const source = document.getElementById("ingredientTypeConfig");
        try {
            const payload = JSON.parse(source?.textContent || "{}");
            return { types: Array.isArray(payload.types) ? payload.types : [] };
        } catch (error) {
            console.error("Unable to load the ingredient type registry.", error);
            return { types: [] };
        }
    }

    function legacyTypeNames() {
        try {
            const values = JSON.parse(localStorage.getItem(LEGACY_CUSTOM_TYPES_KEY) || "[]");
            const names = [];
            const seen = new Set();
            (Array.isArray(values) ? values : []).forEach(value => {
                const name = cleanText(value).slice(0, 40);
                const key = typeKey(name);
                if (name && key && !seen.has(key)) {
                    names.push(name);
                    seen.add(key);
                }
            });
            return names;
        } catch (error) {
            console.warn("Unable to read legacy browser types.", error);
            return [];
        }
    }

    function initTypeMasterPage() {
        const root = document.querySelector("[data-type-master-page]");
        if (!root) return;

        let registry = parseRegistry();
        let editorTypeId = "";
        let returnFocus = null;
        let usageReturnFocus = null;
        let usageRequestToken = 0;

        const source = document.getElementById("ingredientTypeConfig");
        const status = root.querySelector("[data-type-master-status]");
        const search = root.querySelector("[data-type-master-search]");
        const rows = root.querySelector("[data-type-master-rows]");
        const countLabel = root.querySelector("[data-type-master-count-label]");
        const searchEmpty = root.querySelector("[data-type-master-search-empty]");
        const dialog = root.querySelector("[data-type-master-dialog]");
        const form = root.querySelector("[data-type-master-form]");
        const nameInput = root.querySelector("[data-type-master-name]");
        const nameHelp = root.querySelector("[data-type-master-name-help]");
        const nameError = root.querySelector("[data-type-master-name-error]");
        const editorTitle = root.querySelector("[data-type-master-editor-title]");
        const editorKicker = root.querySelector("[data-type-master-editor-kicker]");
        const editorFeedback = root.querySelector("[data-type-master-editor-feedback]");
        const saveButton = root.querySelector("[data-type-master-save]");
        const deleteButton = root.querySelector("[data-type-master-delete]");
        const importPanel = root.querySelector("[data-type-master-import]");
        const importButton = root.querySelector("[data-type-master-import-button]");
        const usageDialog = root.querySelector("[data-type-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-type-master-usage-title]");
        const usageContext = root.querySelector("[data-type-master-usage-context]");
        const usageSummary = root.querySelector("[data-type-master-usage-summary]");
        const usageResults = root.querySelector("[data-type-master-usage-results]");

        const typeById = typeId => registry.types.find(item => String(item.id) === String(typeId)) || null;

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

        const createUsageCell = item => {
            const usage = document.createElement("div");
            usage.className = "unit-master-usage";
            usage.setAttribute("role", "cell");
            const recipeCount = Math.max(0, Number(item.recipe_count) || 0);
            if (!recipeCount) {
                const empty = document.createElement("span");
                empty.className = "unit-master-usage-empty";
                empty.textContent = "0";
                empty.setAttribute("aria-label", `No recipes use ${item.name}`);
                empty.title = `No recipes currently use ${item.name}`;
                usage.appendChild(empty);
                return usage;
            }
            const button = document.createElement("button");
            button.type = "button";
            button.className = "unit-master-usage-button";
            button.dataset.typeMasterUsageButton = "";
            button.dataset.typeId = item.id;
            button.setAttribute("aria-haspopup", "dialog");
            button.setAttribute("aria-controls", "typeMasterUsageDialog");
            button.setAttribute(
                "aria-label",
                `Show ${recipeCount} recipe${recipeCount === 1 ? "" : "s"} using ${item.name}`,
            );
            button.title = `Show recipes using ${item.name}`;
            const count = document.createElement("strong");
            count.textContent = String(recipeCount);
            const label = document.createElement("span");
            label.textContent = recipeCount === 1 ? "recipe" : "recipes";
            button.append(count, label);
            usage.appendChild(button);
            return usage;
        };

        const createTypeRow = item => {
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.typeMasterRow = "";
            row.dataset.typeId = item.id;
            row.dataset.typeMasterSearchValue = item.name;

            const name = document.createElement("strong");
            name.setAttribute("role", "cell");
            name.textContent = item.name;

            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${item.custom ? " user-created" : ""}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = item.custom ? "User-created" : "Built-in";

            const action = document.createElement("span");
            action.className = "unit-master-action-cell";
            action.setAttribute("role", "cell");
            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.typeMasterEditButton = "";
            edit.dataset.typeId = item.id;
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", `Edit ${item.name}`);
            action.appendChild(edit);

            row.append(name, createUsageCell(item), sourceBadge, action);
            return row;
        };

        const renderStats = () => {
            root.querySelector("[data-type-master-seeded-count]").textContent = String(
                registry.types.filter(item => item.seeded).length,
            );
            root.querySelector("[data-type-master-custom-count]").textContent = String(
                registry.types.filter(item => item.custom).length,
            );
            root.querySelector("[data-type-master-used-count]").textContent = String(
                registry.types.filter(item => Number(item.recipe_count) > 0).length,
            );
        };

        const applySearch = () => {
            const query = typeKey(search.value);
            let visible = 0;
            root.querySelectorAll("[data-type-master-row]").forEach(row => {
                const matches = !query || typeKey(row.dataset.typeMasterSearchValue).includes(query);
                row.hidden = !matches;
                if (matches) visible += 1;
            });
            countLabel.textContent = `${visible} type${visible === 1 ? "" : "s"}`;
            searchEmpty.hidden = visible > 0;
        };

        const renderRegistry = () => {
            rows.replaceChildren(...registry.types.map(createTypeRow));
            renderStats();
            applySearch();
        };

        const updateRegistry = nextRegistry => {
            registry = {
                types: Array.isArray(nextRegistry?.types) ? nextRegistry.types : [],
            };
            source.textContent = JSON.stringify(registry);
            renderRegistry();
        };

        const clearEditorErrors = () => {
            setFieldError(nameInput, nameError, "");
            setEditorFeedback("");
        };

        const closeEditor = () => {
            if (dialog.open) dialog.close();
        };

        const openEditor = (item = null, trigger = null) => {
            editorTypeId = String(item?.id || "");
            returnFocus = trigger || document.activeElement;
            clearEditorErrors();
            nameInput.value = item?.name || "";
            nameInput.disabled = false;
            nameHelp.textContent = item?.seeded
                ? "You can change this display name; its system-seeded ID and recipe behavior remain stable."
                : "Custom type names can be changed without losing their recipe assignments.";
            editorTitle.textContent = item ? `Edit ${item.name}` : "Add Type";
            editorKicker.textContent = item?.seeded
                ? "System-seeded type"
                : (item ? "User-created type" : "New workspace type");
            saveButton.textContent = item ? "Save Changes" : "Add Type";
            deleteButton.hidden = !item?.custom;
            deleteButton.dataset.typeId = item?.id || "";
            if (item?.custom && Number(item.recipe_count) > 0) {
                deleteButton.title = `${item.name} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}.`;
            } else {
                deleteButton.removeAttribute("title");
            }
            if (!dialog.open) dialog.showModal();
            window.requestAnimationFrame(() => nameInput.focus());
        };

        const requestJson = async (url, options = {}) => {
            const response = await fetch(url, {
                ...options,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                    ...(options.headers || {}),
                },
            });
            const data = await response.json().catch(() => ({}));
            return { response, data };
        };

        const saveType = async event => {
            event.preventDefault();
            clearEditorErrors();
            const payload = {
                name: cleanText(nameInput.value),
            };
            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            try {
                const url = editorTypeId
                    ? root.dataset.updateUrlTemplate.replace("__TYPE_ID__", encodeURIComponent(editorTypeId))
                    : root.dataset.createUrl;
                const { response, data } = await requestJson(url, {
                    method: editorTypeId ? "PATCH" : "POST",
                    body: JSON.stringify(payload),
                });
                if (!response.ok || data.ok === false) {
                    const errors = data.errors || {};
                    setFieldError(nameInput, nameError, errors.name || "");
                    setEditorFeedback(data.error || "The type could not be saved.");
                    return;
                }
                updateRegistry(data.registry);
                setStatus(data.message || "Type saved.");
                closeEditor();
            } catch (error) {
                setEditorFeedback("The type could not be saved. Try again.");
                console.error("Unable to save ingredient type.", error);
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = editorTypeId ? "Save Changes" : "Add Type";
            }
        };

        const deleteType = async () => {
            const item = typeById(editorTypeId);
            if (!item?.custom) return;
            if (Number(item.recipe_count) > 0) {
                setEditorFeedback(
                    `${item.name} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}. Reassign or remove this type from those recipes before deleting it.`,
                    "warning",
                );
                deleteButton.focus();
                return;
            }
            if (!window.confirm(`Delete custom type "${item.name}"?`)) return;
            deleteButton.disabled = true;
            try {
                const url = root.dataset.updateUrlTemplate.replace(
                    "__TYPE_ID__",
                    encodeURIComponent(item.id),
                );
                const { response, data } = await requestJson(url, { method: "DELETE" });
                if (!response.ok || data.ok === false) {
                    setEditorFeedback(data.error || "The type could not be deleted.");
                    return;
                }
                updateRegistry(data.registry);
                setStatus(data.message || "Type deleted.");
                closeEditor();
            } catch (error) {
                setEditorFeedback("The type could not be deleted. Try again.");
                console.error("Unable to delete ingredient type.", error);
            } finally {
                deleteButton.disabled = false;
            }
        };

        const setUsageState = (message, state = "loading") => {
            usageSummary.textContent = "";
            usageResults.replaceChildren();
            const output = document.createElement("div");
            output.className = `unit-master-usage-state is-${state}`;
            output.textContent = message;
            usageResults.appendChild(output);
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
            fallback.innerHTML = '<svg viewBox="0 0 24 24" focusable="false"><path d="M6 3h8l4 4v14H6zM14 3v5h4"></path><path d="M9 12h6M9 16h6"></path></svg>';
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
            if (reference.recipe_image_srcset) {
                image.srcset = String(reference.recipe_image_srcset);
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
                setUsageState("No connected recipes were found for this type.", "empty");
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
                    const link = document.createElement("a");
                    link.href = reference.edit_url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = recipeTitle;
                    heading.appendChild(link);
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
                (reference.matches || []).forEach(match => {
                    const listItem = document.createElement("li");
                    const line = document.createElement("strong");
                    line.textContent = match.ingredient_line || match.ingredient_name || "Ingredient line";
                    listItem.appendChild(line);
                    if (match.context) {
                        const context = document.createElement("span");
                        context.textContent = match.kind === "option"
                            ? `Recipe option: ${match.context}`
                            : match.context;
                        listItem.appendChild(context);
                    } else if (match.kind === "option") {
                        const context = document.createElement("span");
                        context.textContent = "Recipe option";
                        listItem.appendChild(context);
                    }
                    matches.appendChild(listItem);
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

        const openUsage = async (item, trigger) => {
            usageReturnFocus = trigger || document.activeElement;
            usageTitle.textContent = `Recipes using ${item.name}`;
            usageContext.textContent = `Review every ingredient line assigned to ${item.name}.`;
            setUsageState("Loading connected recipes…");
            if (!usageDialog.open) usageDialog.showModal();
            const requestToken = ++usageRequestToken;
            const url = root.dataset.usageUrlTemplate.replace("__TYPE_ID__", encodeURIComponent(item.id));
            try {
                const { response, data } = await requestJson(url, { method: "GET" });
                if (requestToken !== usageRequestToken || !usageDialog.open) return;
                if (!response.ok || data.ok === false) {
                    setUsageState(data.error || "Connected recipes could not be loaded.", "error");
                    return;
                }
                renderUsageReferences(data);
            } catch (error) {
                if (requestToken !== usageRequestToken) return;
                setUsageState("Connected recipes could not be loaded. Try again.", "error");
                console.error("Unable to load type recipe usage.", error);
            }
        };

        const closeUsage = () => {
            usageRequestToken += 1;
            if (usageDialog.open) usageDialog.close();
        };

        const legacyNames = legacyTypeNames();
        const workspaceKeys = new Set(registry.types.map(item => typeKey(item.name)));
        const importableNames = legacyNames.filter(name => !workspaceKeys.has(typeKey(name)));
        importPanel.hidden = !importableNames.length || localStorage.getItem(IMPORT_DISMISSED_KEY) === "true";

        root.addEventListener("click", event => {
            const add = event.target.closest("[data-type-master-add-button]");
            if (add) {
                openEditor(null, add);
                return;
            }
            const edit = event.target.closest("[data-type-master-edit-button]");
            if (edit) {
                openEditor(typeById(edit.dataset.typeId), edit);
                return;
            }
            const usage = event.target.closest("[data-type-master-usage-button]");
            if (usage) {
                openUsage(typeById(usage.dataset.typeId), usage);
            }
        });
        search.addEventListener("input", applySearch);
        form.addEventListener("submit", saveType);
        deleteButton.addEventListener("click", deleteType);
        root.querySelectorAll("[data-type-master-close], [data-type-master-cancel]").forEach(button => {
            button.addEventListener("click", closeEditor);
        });
        dialog.addEventListener("close", () => {
            returnFocus?.focus({ preventScroll: true });
            returnFocus = null;
        });
        root.querySelectorAll("[data-type-master-usage-close]").forEach(button => {
            button.addEventListener("click", closeUsage);
        });
        usageDialog.addEventListener("close", () => {
            usageReturnFocus?.focus({ preventScroll: true });
            usageReturnFocus = null;
        });
        importButton.addEventListener("click", async () => {
            importButton.disabled = true;
            try {
                const { response, data } = await requestJson(root.dataset.importUrl, {
                    method: "POST",
                    body: JSON.stringify({ types: importableNames }),
                });
                if (!response.ok || data.ok === false) {
                    setStatus(data.error || "Browser types could not be imported.", "error");
                    return;
                }
                updateRegistry(data.registry);
                localStorage.removeItem(LEGACY_CUSTOM_TYPES_KEY);
                importPanel.hidden = true;
                setStatus(data.message || "Browser types imported.");
            } catch (error) {
                setStatus("Browser types could not be imported. Try again.", "error");
                console.error("Unable to import browser ingredient types.", error);
            } finally {
                importButton.disabled = false;
            }
        });
        root.querySelector("[data-type-master-import-dismiss]").addEventListener("click", () => {
            localStorage.setItem(IMPORT_DISMISSED_KEY, "true");
            importPanel.hidden = true;
        });

        renderRegistry();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initTypeMasterPage, { once: true });
    } else {
        initTypeMasterPage();
    }
})();
