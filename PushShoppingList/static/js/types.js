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
        let usageReturnFocus = null;
        let usageRequestToken = 0;
        const drafts = new Map();

        const source = document.getElementById("ingredientTypeConfig");
        const status = root.querySelector("[data-type-master-status]");
        const search = root.querySelector("[data-type-master-search]");
        const rows = root.querySelector("[data-type-master-rows]");
        const countLabel = root.querySelector("[data-type-master-count-label]");
        const searchEmpty = root.querySelector("[data-type-master-search-empty]");
        const createForm = root.querySelector("[data-type-master-create-form]");
        const createName = root.querySelector("[data-type-master-create-name]");
        const createSubmit = root.querySelector("[data-type-master-create-submit]");
        const createError = root.querySelector("[data-type-master-create-error]");
        const addButtons = Array.from(root.querySelectorAll("[data-type-master-add-button]"));
        const importPanel = root.querySelector("[data-type-master-import]");
        const importButton = root.querySelector("[data-type-master-import-button]");
        const usageDialog = root.querySelector("[data-type-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-type-master-usage-title]");
        const usageContext = root.querySelector("[data-type-master-usage-context]");
        const usageSummary = root.querySelector("[data-type-master-usage-summary]");
        const usageResults = root.querySelector("[data-type-master-usage-results]");

        const typeById = typeId => registry.types.find(
            item => String(item.id) === String(typeId),
        ) || null;

        const setStatus = (message, type = "success") => {
            status.textContent = String(message || "");
            status.dataset.status = type;
            status.hidden = !status.textContent;
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

        const ensureDraft = item => {
            const id = String(item.id);
            if (!drafts.has(id)) {
                drafts.set(id, {
                    originalName: item.name,
                    name: item.name,
                    saving: false,
                    deleting: false,
                    errors: {},
                    feedback: "",
                });
            }
            return drafts.get(id);
        };

        const draftIsDirty = draft => cleanText(draft.name) !== cleanText(draft.originalName);

        const rowControls = row => ({
            name: row.querySelector("[data-type-master-row-name]"),
            save: row.querySelector("[data-type-master-row-save]"),
            delete: row.querySelector("[data-type-master-row-delete]"),
            error: row.querySelector("[data-type-master-row-error]"),
        });

        const syncRowState = row => {
            const item = typeById(row?.dataset.typeId);
            if (!item) return;
            const draft = ensureDraft(item);
            const controls = rowControls(row);
            const message = draft.errors.name || draft.feedback || "";
            const dirty = draftIsDirty(draft);
            row.classList.toggle("is-dirty", dirty);
            row.classList.toggle("is-saving", draft.saving);
            row.classList.toggle("has-error", Boolean(message));
            row.setAttribute("aria-busy", String(draft.saving || draft.deleting));
            controls.name.toggleAttribute("aria-invalid", Boolean(message));
            controls.name.disabled = draft.saving || draft.deleting;
            controls.save.disabled = !dirty || draft.saving || draft.deleting;
            controls.save.textContent = draft.saving ? "Saving…" : "Save";
            if (controls.delete) {
                controls.delete.disabled = draft.saving || draft.deleting;
                controls.delete.textContent = draft.deleting ? "Deleting…" : "Delete";
            }
            controls.error.textContent = message;
            controls.error.hidden = !message;
        };

        const createTypeRow = (item, index) => {
            const draft = ensureDraft(item);
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.typeMasterRow = "";
            row.dataset.typeId = item.id;
            row.dataset.typeMasterSearchValue = item.name;

            const nameField = document.createElement("label");
            nameField.className = "type-master-row-name-field";
            nameField.setAttribute("role", "cell");
            nameField.dataset.mobileLabel = "Type name";
            const nameLabel = document.createElement("span");
            nameLabel.className = "sr-only";
            nameLabel.textContent = `Type name for ${item.name}`;
            const name = document.createElement("input");
            name.type = "text";
            name.maxLength = 40;
            name.autocomplete = "off";
            name.required = true;
            name.value = draft.name;
            name.dataset.typeMasterRowName = "";
            name.setAttribute("aria-describedby", `typeMasterRowError${index}`);
            nameField.append(nameLabel, name);

            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${item.custom ? " user-created" : ""}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = item.custom ? "User-created" : "Built-in";

            const action = document.createElement("span");
            action.className = "unit-master-action-cell type-master-row-actions";
            action.setAttribute("role", "cell");
            action.dataset.mobileLabel = "Action";
            const save = document.createElement("button");
            save.type = "button";
            save.className = "unit-master-edit-button";
            save.dataset.typeMasterRowSave = "";
            save.dataset.typeId = item.id;
            save.textContent = "Save";
            save.setAttribute("aria-label", `Save ${item.name}`);
            action.appendChild(save);
            if (item.custom) {
                const deleteButton = document.createElement("button");
                deleteButton.type = "button";
                deleteButton.className = "danger type-master-row-delete";
                deleteButton.dataset.typeMasterRowDelete = "";
                deleteButton.dataset.typeId = item.id;
                deleteButton.textContent = "Delete";
                deleteButton.setAttribute("aria-label", `Delete ${item.name}`);
                action.appendChild(deleteButton);
            }

            const error = document.createElement("div");
            error.id = `typeMasterRowError${index}`;
            error.className = "unit-master-field-error type-master-row-error";
            error.setAttribute("role", "alert");
            error.dataset.typeMasterRowError = "";
            error.hidden = true;

            row.append(nameField, createUsageCell(item), sourceBadge, action, error);
            syncRowState(row);
            return row;
        };

        const renderStats = () => {
            root.querySelector("[data-type-master-total-count]").textContent = String(registry.types.length);
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
                const name = row.querySelector("[data-type-master-row-name]")?.value
                    || row.dataset.typeMasterSearchValue;
                const matches = !query || typeKey(name).includes(query);
                row.hidden = !matches;
                if (matches) visible += 1;
            });
            const total = registry.types.length;
            countLabel.textContent = `Showing ${visible} of ${total} Type${total === 1 ? "" : "s"}.`;
            searchEmpty.hidden = visible > 0;
        };

        const renderRegistry = () => {
            const liveIds = new Set(registry.types.map(item => String(item.id)));
            Array.from(drafts.keys()).forEach(id => {
                if (!liveIds.has(id)) drafts.delete(id);
            });
            rows.replaceChildren(...registry.types.map(createTypeRow));
            renderStats();
            applySearch();
        };

        const updateRegistry = (nextRegistry, options = {}) => {
            (options.resetTypeIds || []).forEach(id => drafts.delete(String(id)));
            registry = {
                types: Array.isArray(nextRegistry?.types) ? nextRegistry.types : [],
            };
            source.textContent = JSON.stringify(registry);
            renderRegistry();
        };

        const validateName = (name, item = null) => {
            if (!name) return "Enter a type name.";
            if (name.length > 40) return "Use 40 characters or fewer.";
            const duplicate = registry.types.some(candidate => (
                String(candidate.id) !== String(item?.id || "")
                && typeKey(candidate.name) === typeKey(name)
            ));
            return duplicate ? "A type with this name already exists." : "";
        };

        const captureRowDraft = row => {
            const item = typeById(row?.dataset.typeId);
            if (!item) return null;
            const draft = ensureDraft(item);
            draft.name = rowControls(row).name.value;
            draft.errors = {};
            draft.feedback = "";
            row.dataset.typeMasterSearchValue = draft.name;
            syncRowState(row);
            applySearch();
            return draft;
        };

        const saveTypeRow = async row => {
            const item = typeById(row?.dataset.typeId);
            if (!item) return;
            const draft = captureRowDraft(row);
            const name = cleanText(draft.name);
            const nameError = validateName(name, item);
            draft.name = name;
            draft.errors = nameError ? { name: nameError } : {};
            syncRowState(row);
            if (nameError) {
                rowControls(row).name.focus({ preventScroll: true });
                return;
            }
            if (!draftIsDirty(draft) || draft.saving) return;
            draft.saving = true;
            setStatus(`Saving ${item.name}…`, "info");
            syncRowState(row);
            let saved = false;
            try {
                const url = root.dataset.updateUrlTemplate.replace(
                    "__TYPE_ID__",
                    encodeURIComponent(item.id),
                );
                const { response, data } = await requestJson(url, {
                    method: "PATCH",
                    body: JSON.stringify({ name }),
                });
                if (!response.ok || data.ok === false) {
                    draft.saving = false;
                    draft.errors = data.errors || {};
                    draft.feedback = data.error || "The type could not be saved.";
                    syncRowState(row);
                    setStatus(draft.feedback, "error");
                    if (draft.errors.name) rowControls(row).name.focus({ preventScroll: true });
                    return;
                }
                saved = true;
                draft.saving = false;
                updateRegistry(data.registry, { resetTypeIds: [item.id] });
                setStatus(data.message || "Type saved.");
            } catch (error) {
                draft.saving = false;
                draft.feedback = "The type could not be saved. Try again.";
                syncRowState(row);
                setStatus(draft.feedback, "error");
                console.error("Unable to save ingredient type.", error);
            } finally {
                if (!saved && row.isConnected) syncRowState(row);
            }
        };

        const deleteTypeRow = async row => {
            const item = typeById(row?.dataset.typeId);
            if (!item?.custom) return;
            const draft = ensureDraft(item);
            const controls = rowControls(row);
            if (draft.saving || draft.deleting) return;
            if (Number(item.recipe_count) > 0) {
                draft.feedback = `${item.name} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}. Reassign or remove this type from those recipes before deleting it.`;
                syncRowState(row);
                controls.delete.focus({ preventScroll: true });
                return;
            }
            if (!window.confirm(`Delete custom type "${item.name}"?`)) return;
            draft.deleting = true;
            draft.errors = {};
            draft.feedback = "";
            setStatus(`Deleting ${item.name}…`, "info");
            syncRowState(row);
            try {
                const url = root.dataset.updateUrlTemplate.replace(
                    "__TYPE_ID__",
                    encodeURIComponent(item.id),
                );
                const { response, data } = await requestJson(url, { method: "DELETE" });
                if (!response.ok || data.ok === false) {
                    draft.deleting = false;
                    draft.errors = data.errors || {};
                    draft.feedback = data.error || "The type could not be deleted.";
                    syncRowState(row);
                    setStatus(draft.feedback, "error");
                    controls.delete.focus({ preventScroll: true });
                    return;
                }
                updateRegistry(data.registry);
                setStatus(data.message || "Type deleted.");
                addButtons.at(-1)?.focus({ preventScroll: true });
            } catch (error) {
                draft.deleting = false;
                draft.feedback = "The type could not be deleted. Try again.";
                syncRowState(row);
                setStatus(draft.feedback, "error");
                controls.delete.focus({ preventScroll: true });
                console.error("Unable to delete ingredient type.", error);
            }
        };

        const bottomViewportInset = () => {
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
            const mobileNavigation = document.querySelector(".app-mobile-bottom-nav");
            if (!mobileNavigation) return 0;
            const style = window.getComputedStyle(mobileNavigation);
            if (style.display === "none" || style.visibility === "hidden") return 0;
            const rect = mobileNavigation.getBoundingClientRect();
            if (rect.bottom <= 0 || rect.top >= viewportHeight) return 0;
            return Math.max(0, viewportHeight - Math.max(0, rect.top));
        };

        const createPanelIsFullyVisible = () => {
            const rect = createForm.getBoundingClientRect();
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
            const visibleBottom = viewportHeight - bottomViewportInset();
            const content = root.closest("#appContent") || root.closest(".app-content");
            const contentRect = content?.getBoundingClientRect();
            const visibleTop = Math.max(0, contentRect?.top || 0);
            const clippedBottom = Math.min(visibleBottom, contentRect?.bottom || visibleBottom);
            return rect.top >= visibleTop && rect.bottom <= clippedBottom;
        };

        const setCreateExpanded = expanded => {
            createForm.hidden = !expanded;
            addButtons.forEach(button => button.setAttribute("aria-expanded", String(expanded)));
            if (!expanded) {
                createForm.style.scrollMarginBottom = "";
                return;
            }
            createName.focus({ preventScroll: true });
            const bottomInset = bottomViewportInset();
            createForm.style.scrollMarginBottom = bottomInset ? `${Math.ceil(bottomInset)}px` : "";
            if (!createPanelIsFullyVisible()) {
                createForm.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
            setStatus("Add Type form focused.", "info");
        };

        const setCreateError = message => {
            const text = String(message || "");
            createError.textContent = text;
            createError.hidden = !text;
            createName.toggleAttribute("aria-invalid", Boolean(text));
            createForm.classList.toggle("has-error", Boolean(text));
        };

        const setCreateSaving = saving => {
            createForm.classList.toggle("is-saving", saving);
            createForm.setAttribute("aria-busy", String(saving));
            createName.disabled = saving;
            createSubmit.disabled = saving;
            createSubmit.textContent = saving ? "Saving…" : "Save";
        };

        const resetCreate = () => {
            createForm.reset();
            setCreateError("");
        };

        const cancelCreate = () => {
            if (createForm.classList.contains("is-saving")) return;
            resetCreate();
            setCreateExpanded(false);
            addButtons.at(-1)?.focus({ preventScroll: true });
            setStatus("New Type discarded.", "info");
        };

        const saveNewType = async event => {
            event.preventDefault();
            const name = cleanText(createName.value);
            createName.value = name;
            const errorMessage = validateName(name);
            setCreateError(errorMessage);
            if (errorMessage) {
                createName.focus({ preventScroll: true });
                return;
            }
            setCreateSaving(true);
            setStatus("Adding type…", "info");
            try {
                const { response, data } = await requestJson(root.dataset.createUrl, {
                    method: "POST",
                    body: JSON.stringify({ name }),
                });
                if (!response.ok || data.ok === false) {
                    const failureMessage = data.errors?.name || data.error || "The type could not be added.";
                    setCreateError(failureMessage);
                    setStatus(data.error || failureMessage, "error");
                    createName.focus({ preventScroll: true });
                    return;
                }
                updateRegistry(data.registry);
                resetCreate();
                setCreateExpanded(false);
                addButtons.at(-1)?.focus({ preventScroll: true });
                setStatus(data.message || "Type added.");
            } catch (error) {
                const failureMessage = "The type could not be added. Try again.";
                setCreateError(failureMessage);
                setStatus(failureMessage, "error");
                createName.focus({ preventScroll: true });
                console.error("Unable to add ingredient type.", error);
            } finally {
                setCreateSaving(false);
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
                const recipeTitle = reference.recipe_title || reference.recipe_id || "Recipe";
                const header = document.createElement("header");
                const heading = document.createElement("h3");
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
                    const openLink = document.createElement("a");
                    openLink.href = reference.edit_url;
                    openLink.target = "_blank";
                    openLink.rel = "noopener noreferrer";
                    openLink.textContent = "Open Recipe";
                    header.appendChild(openLink);
                }
                card.append(createUsageRecipeVisual(reference), header);
                const matches = document.createElement("ul");
                (reference.matches || []).forEach(match => {
                    const listItem = document.createElement("li");
                    const line = document.createElement("strong");
                    line.textContent = match.ingredient_line || match.ingredient_name || "Ingredient line";
                    listItem.appendChild(line);
                    if (match.context || match.kind === "option") {
                        const context = document.createElement("span");
                        context.textContent = match.kind === "option"
                            ? `Recipe option${match.context ? `: ${match.context}` : ""}`
                            : match.context;
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
            if (!item) return;
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

        addButtons.forEach(button => {
            button.addEventListener("click", event => {
                event.preventDefault();
                setCreateExpanded(true);
            });
        });
        root.querySelector("[data-type-master-create-cancel]").addEventListener("click", event => {
            event.preventDefault();
            cancelCreate();
        });
        createForm.addEventListener("submit", saveNewType);
        createName.addEventListener("input", () => setCreateError(""));
        search.addEventListener("input", applySearch);

        root.addEventListener("input", event => {
            if (!event.target.matches("[data-type-master-row-name]")) return;
            captureRowDraft(event.target.closest("[data-type-master-row]"));
        });
        root.addEventListener("keydown", event => {
            if (!event.target.matches("[data-type-master-row-name]")) return;
            const row = event.target.closest("[data-type-master-row]");
            if (event.key === "Enter") {
                event.preventDefault();
                saveTypeRow(row);
            } else if (event.key === "Escape") {
                const item = typeById(row?.dataset.typeId);
                if (!item) return;
                drafts.delete(String(item.id));
                const draft = ensureDraft(item);
                rowControls(row).name.value = draft.name;
                syncRowState(row);
                applySearch();
            }
        });
        root.addEventListener("click", event => {
            const save = event.target.closest("[data-type-master-row-save]");
            if (save) {
                saveTypeRow(save.closest("[data-type-master-row]"));
                return;
            }
            const deleteButton = event.target.closest("[data-type-master-row-delete]");
            if (deleteButton) {
                deleteTypeRow(deleteButton.closest("[data-type-master-row]"));
                return;
            }
            const usage = event.target.closest("[data-type-master-usage-button]");
            if (usage) openUsage(typeById(usage.dataset.typeId), usage);
        });

        root.querySelectorAll("[data-type-master-usage-close]").forEach(
            button => button.addEventListener("click", closeUsage),
        );
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
