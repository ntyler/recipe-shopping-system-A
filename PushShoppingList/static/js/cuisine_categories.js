(function () {
    "use strict";

    const LEGACY_CUSTOM_CUISINES_KEY = "recipeCuisineCategories";
    const IMPORT_DISMISSED_KEY = "recipeCuisineCategoriesImportDismissed";

    function cleanText(value) {
        return String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ");
    }

    function categoryKey(value) {
        return cleanText(value)
            .normalize("NFKD")
            .toLocaleLowerCase()
            .replace(/[^\p{L}\p{N}]+/gu, " ")
            .trim();
    }

    function parseRegistry() {
        const source = document.getElementById("cuisineCategoryConfig");
        try {
            const payload = JSON.parse(source?.textContent || "{}");
            return {
                ...payload,
                categories: Array.isArray(payload.categories) ? payload.categories : [],
            };
        } catch (error) {
            console.error("Unable to load the cuisine category registry.", error);
            return { categories: [] };
        }
    }

    function legacyCategoryNames() {
        try {
            const values = JSON.parse(localStorage.getItem(LEGACY_CUSTOM_CUISINES_KEY) || "[]");
            const names = [];
            const seen = new Set();
            (Array.isArray(values) ? values : []).forEach(value => {
                const name = cleanText(value).slice(0, 60);
                const key = categoryKey(name);
                if (name && key && !seen.has(key)) {
                    names.push(name);
                    seen.add(key);
                }
            });
            return names;
        } catch (error) {
            console.warn("Unable to read legacy browser cuisine categories.", error);
            return [];
        }
    }

    function initCuisineCategoryMasterPage() {
        const root = document.querySelector("[data-cuisine-category-master-page]");
        if (!root) return;

        let registry = parseRegistry();
        let editorCategoryId = "";
        let returnFocus = null;
        let usageReturnFocus = null;
        let usageRequestToken = 0;

        const source = document.getElementById("cuisineCategoryConfig");
        const status = root.querySelector("[data-cuisine-category-master-status]");
        const search = root.querySelector("[data-cuisine-category-master-search]");
        const rows = root.querySelector("[data-cuisine-category-master-rows]");
        const countLabel = root.querySelector("[data-cuisine-category-master-count-label]");
        const searchEmpty = root.querySelector("[data-cuisine-category-master-search-empty]");
        const dialog = root.querySelector("[data-cuisine-category-master-dialog]");
        const form = root.querySelector("[data-cuisine-category-master-form]");
        const nameInput = root.querySelector("[data-cuisine-category-master-name]");
        const nameHelp = root.querySelector("[data-cuisine-category-master-name-help]");
        const nameError = root.querySelector("[data-cuisine-category-master-name-error]");
        const activeInput = root.querySelector("[data-cuisine-category-master-active]");
        const activeError = root.querySelector("[data-cuisine-category-master-active-error]");
        const editorTitle = root.querySelector("[data-cuisine-category-master-editor-title]");
        const editorKicker = root.querySelector("[data-cuisine-category-master-editor-kicker]");
        const editorFeedback = root.querySelector("[data-cuisine-category-master-editor-feedback]");
        const saveButton = root.querySelector("[data-cuisine-category-master-save]");
        const deleteButton = root.querySelector("[data-cuisine-category-master-delete]");
        const importPanel = root.querySelector("[data-cuisine-category-master-import]");
        const importButton = root.querySelector("[data-cuisine-category-master-import-button]");
        const usageDialog = root.querySelector("[data-cuisine-category-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-cuisine-category-master-usage-title]");
        const usageContext = root.querySelector("[data-cuisine-category-master-usage-context]");
        const usageSummary = root.querySelector("[data-cuisine-category-master-usage-summary]");
        const usageResults = root.querySelector("[data-cuisine-category-master-usage-results]");

        const categoryById = categoryId => (
            registry.categories.find(item => String(item.id) === String(categoryId)) || null
        );

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
                usage.appendChild(empty);
                return usage;
            }

            const button = document.createElement("button");
            button.type = "button";
            button.className = "unit-master-usage-button";
            button.dataset.cuisineCategoryMasterUsageButton = "";
            button.dataset.categoryId = item.id;
            button.setAttribute("aria-haspopup", "dialog");
            button.setAttribute("aria-controls", "cuisineCategoryMasterUsageDialog");
            button.setAttribute(
                "aria-label",
                `Show ${recipeCount} recipe${recipeCount === 1 ? "" : "s"} using ${item.name}`,
            );
            const count = document.createElement("strong");
            count.textContent = String(recipeCount);
            const label = document.createElement("span");
            label.textContent = recipeCount === 1 ? "recipe" : "recipes";
            button.append(count, label);
            usage.appendChild(button);
            return usage;
        };

        const createCategoryRow = item => {
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.cuisineCategoryMasterRow = "";
            row.dataset.categoryId = item.id;
            row.dataset.cuisineCategoryMasterSearchValue = item.name;

            const name = document.createElement("strong");
            name.setAttribute("role", "cell");
            name.textContent = item.name;

            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${item.custom ? " user-created" : ""}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = item.custom ? "User-created" : "System-seeded";

            const state = document.createElement("span");
            state.className = `type-master-status-badge${item.active ? "" : " is-inactive"}`;
            state.setAttribute("role", "cell");
            state.textContent = item.active ? "Active" : "Inactive";

            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.cuisineCategoryMasterEditButton = "";
            edit.dataset.categoryId = item.id;
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", `Edit ${item.name}`);

            const actionCell = document.createElement("span");
            actionCell.className = "unit-master-action-cell";
            actionCell.setAttribute("role", "cell");
            actionCell.appendChild(edit);

            row.append(name, createUsageCell(item), sourceBadge, state, actionCell);
            return row;
        };

        const renderStats = () => {
            root.querySelector("[data-cuisine-category-master-seeded-count]").textContent = String(
                registry.categories.filter(item => item.seeded).length,
            );
            root.querySelector("[data-cuisine-category-master-custom-count]").textContent = String(
                registry.categories.filter(item => item.custom).length,
            );
            root.querySelector("[data-cuisine-category-master-active-count]").textContent = String(
                registry.categories.filter(item => item.active).length,
            );
            root.querySelector("[data-cuisine-category-master-used-count]").textContent = String(
                registry.categories.filter(item => Number(item.recipe_count) > 0).length,
            );
        };

        const applySearch = () => {
            const query = categoryKey(search.value);
            let visible = 0;
            root.querySelectorAll("[data-cuisine-category-master-row]").forEach(row => {
                const searchValue = row.dataset.cuisineCategoryMasterSearchValue;
                const matches = !query || categoryKey(searchValue).includes(query);
                row.hidden = !matches;
                if (matches) visible += 1;
            });
            countLabel.textContent = `${visible} categor${visible === 1 ? "y" : "ies"}`;
            searchEmpty.hidden = visible > 0;
        };

        const renderRegistry = () => {
            rows.replaceChildren(...registry.categories.map(createCategoryRow));
            renderStats();
            applySearch();
        };

        const updateRegistry = nextRegistry => {
            registry = {
                ...(nextRegistry || {}),
                categories: Array.isArray(nextRegistry?.categories)
                    ? nextRegistry.categories
                    : [],
            };
            source.textContent = JSON.stringify(registry);
            renderRegistry();
        };

        const clearEditorErrors = () => {
            setFieldError(nameInput, nameError, "");
            setFieldError(activeInput, activeError, "");
            setEditorFeedback("");
        };

        const closeEditor = () => {
            if (dialog.open) dialog.close();
        };

        const openEditor = (item = null, trigger = null) => {
            editorCategoryId = String(item?.id || "");
            returnFocus = trigger || document.activeElement;
            clearEditorErrors();
            nameInput.value = item?.name || "";
            nameInput.disabled = Boolean(item?.seeded);
            nameHelp.textContent = item?.seeded
                ? "Built-in names stay tied to stable cuisine labels. You can change availability."
                : "Recognized national cuisine names automatically receive a matching flag. Renaming preserves recipe assignments.";
            activeInput.checked = item ? Boolean(item.active) : true;
            activeInput.disabled = false;
            editorTitle.textContent = item ? `Edit ${item.name}` : "Add Cuisine Category";
            editorKicker.textContent = item?.seeded ? "Built-in cuisine" : "Workspace cuisine";
            saveButton.textContent = item ? "Save Changes" : "Add Cuisine Category";
            deleteButton.hidden = !item?.custom;
            deleteButton.style.display = item?.custom ? "" : "none";
            deleteButton.dataset.categoryId = item?.id || "";
            if (item?.custom && Number(item.recipe_count) > 0) {
                deleteButton.title = `${item.name} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}.`;
            } else {
                deleteButton.removeAttribute("title");
            }
            if (!dialog.open) dialog.showModal();
            window.requestAnimationFrame(() => (nameInput.disabled ? activeInput : nameInput).focus());
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

        const saveCategory = async event => {
            event.preventDefault();
            clearEditorErrors();
            const current = categoryById(editorCategoryId);
            const payload = {
                name: current?.seeded ? current.name : cleanText(nameInput.value),
                active: activeInput.checked,
            };
            saveButton.disabled = true;
            saveButton.textContent = "Saving…";
            try {
                const url = editorCategoryId
                    ? root.dataset.updateUrlTemplate.replace(
                        "__CATEGORY_ID__",
                        encodeURIComponent(editorCategoryId),
                    )
                    : root.dataset.createUrl;
                const { response, data } = await requestJson(url, {
                    method: editorCategoryId ? "PATCH" : "POST",
                    body: JSON.stringify(payload),
                });
                if (!response.ok || data.ok === false) {
                    const errors = data.errors || {};
                    setFieldError(nameInput, nameError, errors.name || "");
                    setFieldError(activeInput, activeError, errors.active || "");
                    setEditorFeedback(data.error || "The cuisine category could not be saved.");
                    return;
                }
                updateRegistry(data.registry);
                setStatus(data.message || "Cuisine category saved.");
                closeEditor();
            } catch (error) {
                setEditorFeedback("The cuisine category could not be saved. Try again.");
                console.error("Unable to save cuisine category.", error);
            } finally {
                saveButton.disabled = false;
                saveButton.textContent = editorCategoryId
                    ? "Save Changes"
                    : "Add Cuisine Category";
            }
        };

        const deleteCategory = async () => {
            const item = categoryById(editorCategoryId);
            if (!item?.custom) return;
            if (Number(item.recipe_count) > 0) {
                setEditorFeedback(
                    `${item.name} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}. Deactivate it instead.`,
                    "warning",
                );
                activeInput.focus();
                return;
            }
            if (!window.confirm(`Delete custom cuisine category "${item.name}"?`)) return;
            deleteButton.disabled = true;
            try {
                const url = root.dataset.updateUrlTemplate.replace(
                    "__CATEGORY_ID__",
                    encodeURIComponent(item.id),
                );
                const { response, data } = await requestJson(url, { method: "DELETE" });
                if (!response.ok || data.ok === false) {
                    setEditorFeedback(data.error || "The cuisine category could not be deleted.");
                    return;
                }
                updateRegistry(data.registry);
                setStatus(data.message || "Cuisine category deleted.");
                closeEditor();
            } catch (error) {
                setEditorFeedback("The cuisine category could not be deleted. Try again.");
                console.error("Unable to delete cuisine category.", error);
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
            usageSummary.textContent = `${total} recipe${total === 1 ? "" : "s"}`;
            if (!references.length) {
                setUsageState("No connected recipes were found for this cuisine category.", "empty");
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
                    const openLink = document.createElement("a");
                    openLink.href = reference.edit_url;
                    openLink.target = "_blank";
                    openLink.rel = "noopener noreferrer";
                    openLink.textContent = "Open Recipe";
                    header.appendChild(openLink);
                }
                card.append(visual, header);
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
            usageContext.textContent = `Review every recipe assigned to ${item.name}.`;
            setUsageState("Loading connected recipes…");
            if (!usageDialog.open) usageDialog.showModal();
            const requestToken = ++usageRequestToken;
            const url = root.dataset.usageUrlTemplate.replace(
                "__CATEGORY_ID__",
                encodeURIComponent(item.id),
            );
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
                console.error("Unable to load cuisine category recipe usage.", error);
            }
        };

        const closeUsage = () => {
            usageRequestToken += 1;
            if (usageDialog.open) usageDialog.close();
        };

        const legacyNames = legacyCategoryNames();
        const workspaceKeys = new Set(
            registry.categories.map(item => categoryKey(item.name)),
        );
        const importableNames = legacyNames.filter(
            name => !workspaceKeys.has(categoryKey(name)),
        );
        importPanel.hidden = (
            !importableNames.length
            || localStorage.getItem(IMPORT_DISMISSED_KEY) === "true"
        );

        root.addEventListener("click", event => {
            const add = event.target.closest("[data-cuisine-category-master-add-button]");
            if (add) {
                openEditor(null, add);
                return;
            }
            const edit = event.target.closest("[data-cuisine-category-master-edit-button]");
            if (edit) {
                openEditor(categoryById(edit.dataset.categoryId), edit);
                return;
            }
            const usage = event.target.closest("[data-cuisine-category-master-usage-button]");
            if (usage) {
                openUsage(categoryById(usage.dataset.categoryId), usage);
            }
        });
        search.addEventListener("input", applySearch);
        form.addEventListener("submit", saveCategory);
        deleteButton.addEventListener("click", deleteCategory);
        root.querySelectorAll(
            "[data-cuisine-category-master-close], [data-cuisine-category-master-cancel]",
        ).forEach(button => button.addEventListener("click", closeEditor));
        dialog.addEventListener("close", () => {
            returnFocus?.focus({ preventScroll: true });
            returnFocus = null;
        });
        root.querySelectorAll("[data-cuisine-category-master-usage-close]").forEach(
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
                    body: JSON.stringify({ categories: importableNames }),
                });
                if (!response.ok || data.ok === false) {
                    setStatus(data.error || "Browser cuisines could not be imported.", "error");
                    return;
                }
                updateRegistry(data.registry);
                localStorage.removeItem(LEGACY_CUSTOM_CUISINES_KEY);
                importPanel.hidden = true;
                setStatus(data.message || "Browser cuisines imported.");
            } catch (error) {
                setStatus("Browser cuisines could not be imported. Try again.", "error");
                console.error("Unable to import browser cuisine categories.", error);
            } finally {
                importButton.disabled = false;
            }
        });
        root.querySelector("[data-cuisine-category-master-import-dismiss]").addEventListener(
            "click",
            () => {
                localStorage.setItem(IMPORT_DISMISSED_KEY, "true");
                importPanel.hidden = true;
            },
        );

        renderRegistry();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initCuisineCategoryMasterPage, {
            once: true,
        });
    } else {
        initCuisineCategoryMasterPage();
    }
})();
