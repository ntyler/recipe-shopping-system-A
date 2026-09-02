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
        let iconChoiceExplicit = false;
        let suggestedIconToken = "";

        const source = document.getElementById("cuisineCategoryConfig");
        const status = root.querySelector("[data-cuisine-category-master-status]");
        const search = root.querySelector("[data-cuisine-category-master-search]");
        const rows = root.querySelector("[data-cuisine-category-master-rows]");
        const countLabel = root.querySelector("[data-cuisine-category-master-count-label]");
        const searchEmpty = root.querySelector("[data-cuisine-category-master-search-empty]");
        const dialog = root.querySelector("[data-cuisine-category-master-dialog]");
        const form = root.querySelector("[data-cuisine-category-master-form]");
        const iconPicker = root.querySelector("[data-cuisine-category-master-icon-picker]");
        const iconInput = root.querySelector("[data-cuisine-category-master-icon]");
        const iconTrigger = root.querySelector("[data-cuisine-category-master-icon-trigger]");
        const iconPreview = root.querySelector("[data-cuisine-category-master-icon-preview]");
        const iconLabel = root.querySelector("[data-cuisine-category-master-icon-label]");
        const iconMenu = root.querySelector("[data-cuisine-category-master-icon-menu]");
        const iconSearch = root.querySelector("[data-cuisine-category-master-icon-search]");
        const iconListbox = root.querySelector("[data-cuisine-category-master-icon-listbox]");
        const iconEmpty = root.querySelector("[data-cuisine-category-master-icon-empty]");
        const iconError = root.querySelector("[data-cuisine-category-master-icon-error]");
        const abbreviationInput = root.querySelector("[data-cuisine-category-master-abbreviation]");
        const abbreviationError = root.querySelector("[data-cuisine-category-master-abbreviation-error]");
        const nameInput = root.querySelector("[data-cuisine-category-master-name]");
        const nameHelp = root.querySelector("[data-cuisine-category-master-name-help]");
        const nameError = root.querySelector("[data-cuisine-category-master-name-error]");
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

        const categoryName = item => (
            cleanText(item?.category_name)
            || cleanText(item?.canonical_name)
            || cleanText(item?.name)
        );

        const categoryDisplayLabel = item => categoryName(item) || "Cuisine category";

        const countryCatalog = window.CountryTerritoryCatalog;
        const iconVisuals = window.CuisineIconVisuals;
        const iconDescriptor = value => (
            iconVisuals?.descriptor(value)
            || {
                token: cleanText(value),
                kind: cleanText(value) ? "custom" : "none",
                label: cleanText(value) ? `Custom symbol ${cleanText(value)}` : "None",
                glyph: cleanText(value),
                code: "",
                supported: true,
            }
        );

        const renderIconVisual = (container, value) => {
            if (!container) return iconDescriptor(value);
            if (iconVisuals?.render) return iconVisuals.render(container, value);
            const item = iconDescriptor(value);
            container.textContent = item.glyph || (item.kind === "none" ? "—" : "◆");
            return item;
        };

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
                empty.setAttribute("aria-label", `No recipes use ${categoryDisplayLabel(item)}`);
                empty.title = `No recipes currently use ${categoryDisplayLabel(item)}`;
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
                `Show ${recipeCount} recipe${recipeCount === 1 ? "" : "s"} using ${categoryDisplayLabel(item)}`,
            );
            button.title = `Show recipes using ${categoryDisplayLabel(item)}`;
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
            row.dataset.cuisineCategoryMasterSearchValue = [
                item.icon,
                iconDescriptor(item.icon).label,
                item.abbreviation,
                categoryName(item),
            ].filter(Boolean).join(" ");

            const icon = document.createElement("span");
            icon.className = "cuisine-category-master-icon cuisine-category-icon-visual";
            icon.setAttribute("role", "cell");
            const iconItem = renderIconVisual(icon, item.icon);
            icon.setAttribute(
                "aria-label",
                iconItem.kind === "none" ? "No icon" : `Icon: ${iconItem.label}`,
            );

            const abbreviation = document.createElement("strong");
            abbreviation.className = "cuisine-category-master-abbreviation";
            abbreviation.setAttribute("role", "cell");
            abbreviation.textContent = item.abbreviation || "—";

            const name = document.createElement("strong");
            name.className = "cuisine-category-master-name";
            name.setAttribute("role", "cell");
            name.textContent = categoryName(item);

            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${item.custom ? " user-created" : ""}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = item.custom ? "User-created" : "System-seeded";

            const edit = document.createElement("button");
            edit.type = "button";
            edit.className = "unit-master-edit-button";
            edit.dataset.cuisineCategoryMasterEditButton = "";
            edit.dataset.categoryId = item.id;
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", `Edit ${categoryDisplayLabel(item)}`);

            const actionCell = document.createElement("span");
            actionCell.className = "unit-master-action-cell";
            actionCell.setAttribute("role", "cell");
            actionCell.appendChild(edit);

            row.append(
                icon,
                abbreviation,
                name,
                createUsageCell(item),
                sourceBadge,
                actionCell,
            );
            return row;
        };

        const renderStats = () => {
            root.querySelector("[data-cuisine-category-master-seeded-count]").textContent = String(
                registry.categories.filter(item => item.seeded).length,
            );
            root.querySelector("[data-cuisine-category-master-custom-count]").textContent = String(
                registry.categories.filter(item => item.custom).length,
            );
            root.querySelector("[data-cuisine-category-master-used-count]").textContent = String(
                registry.categories.filter(item => Number(item.recipe_count) > 0).length,
            );
        };

        const applySearch = () => {
            const rawQuery = cleanText(search.value).toLocaleLowerCase();
            const semanticQuery = categoryKey(rawQuery);
            let visible = 0;
            root.querySelectorAll("[data-cuisine-category-master-row]").forEach(row => {
                const searchValue = cleanText(
                    row.dataset.cuisineCategoryMasterSearchValue,
                );
                const matches = (
                    !rawQuery
                    || searchValue.toLocaleLowerCase().includes(rawQuery)
                    || (
                        Boolean(semanticQuery)
                        && categoryKey(searchValue).includes(semanticQuery)
                    )
                );
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

        const populateFlagOptions = () => {
            const marker = iconInput.querySelector("[data-cuisine-category-master-flag-options]");
            const entries = Array.from(countryCatalog?.entries || []);
            if (!marker || !entries.length) return;

            const regionOrder = [
                "Africa",
                "Asia",
                "Europe",
                "North America",
                "South America",
                "Oceania",
                "Antarctica",
                "Other",
            ];
            const entriesByRegion = new Map(regionOrder.map(region => [region, []]));
            entries.forEach(entry => {
                const region = entriesByRegion.has(entry.region) ? entry.region : "Other";
                entriesByRegion.get(region).push(entry);
            });

            const groups = regionOrder.flatMap(region => {
                const regionEntries = entriesByRegion.get(region);
                if (!regionEntries.length) return [];
                const group = document.createElement("optgroup");
                group.label = `Flags \u2014 ${region}`;
                group.dataset.cuisineCategoryMasterFlagRegion = region;
                regionEntries.forEach(entry => {
                    const option = document.createElement("option");
                    option.value = `flag:${entry.code}`;
                    option.textContent = `${entry.name} flag (${entry.code.toUpperCase()})`;
                    option.dataset.iconKind = "flag";
                    option.dataset.countryCode = entry.code;
                    option.dataset.searchAliases = Array.from(entry.aliases || []).join(" ");
                    group.appendChild(option);
                });
                return [group];
            });
            marker.replaceWith(...groups);
        };

        const iconOptionRecords = () => Array.from(iconInput.options).map(option => {
            const token = iconVisuals?.normalizeToken(option.value) || cleanText(option.value);
            const item = iconDescriptor(token);
            const parentLabel = option.parentElement?.tagName === "OPTGROUP"
                ? cleanText(option.parentElement.label)
                : "Selection";
            return {
                token,
                label: cleanText(option.textContent) || item.label,
                group: cleanText(option.dataset.iconGroup) || parentLabel,
                search: [
                    option.textContent,
                    option.dataset.searchAliases,
                    option.parentElement?.label,
                    item.label,
                    item.code,
                    token,
                ].filter(Boolean).join(" "),
                item,
            };
        });

        const ensureLegacyIconOption = value => {
            iconInput.querySelectorAll("option[data-cuisine-category-custom-icon]")
                .forEach(option => option.remove());
            const token = iconVisuals?.normalizeToken(value) || cleanText(value);
            if (!token || Array.from(iconInput.options).some(option => option.value === token)) {
                return token;
            }
            const item = iconDescriptor(token);
            const option = document.createElement("option");
            option.value = token;
            option.textContent = item.kind === "custom" ? `Current symbol: ${token}` : item.label;
            option.dataset.iconGroup = "Current icon";
            option.dataset.cuisineCategoryCustomIcon = "";
            iconInput.appendChild(option);
            return token;
        };

        const visibleIconOptions = () => Array.from(
            iconListbox.querySelectorAll("[data-cuisine-category-master-icon-option]"),
        );

        const createIconOption = record => {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "cuisine-category-master-icon-option";
            option.dataset.cuisineCategoryMasterIconOption = record.token;
            option.setAttribute("role", "option");
            option.setAttribute("aria-selected", String(record.token === iconInput.value));
            option.tabIndex = -1;
            option.classList.toggle("is-selected", record.token === iconInput.value);

            const visual = iconVisuals?.create(record.token) || document.createElement("span");
            if (!iconVisuals?.create) renderIconVisual(visual, record.token);
            visual.classList.add("cuisine-category-master-icon-option-visual");

            const copy = document.createElement("span");
            copy.className = "cuisine-category-master-icon-option-copy";
            const label = document.createElement("strong");
            label.textContent = record.item.label;
            copy.appendChild(label);
            if (record.item.kind === "flag") {
                const detail = document.createElement("small");
                detail.textContent = record.item.code;
                copy.appendChild(detail);
            }

            const state = document.createElement("span");
            state.className = "cuisine-category-master-icon-option-state";
            state.setAttribute("aria-hidden", "true");
            state.textContent = suggestedIconToken
                && record.token === suggestedIconToken
                && !iconChoiceExplicit
                ? "Suggested"
                : record.token === iconInput.value
                    ? "✓"
                    : "";
            option.append(visual, copy, state);
            return option;
        };

        const renderIconOptions = () => {
            const query = categoryKey(iconSearch.value);
            const records = iconOptionRecords().filter(record => (
                !query || categoryKey(record.search).includes(query)
            ));
            const groups = new Map();
            records.forEach(record => {
                if (!groups.has(record.group)) groups.set(record.group, []);
                groups.get(record.group).push(record);
            });
            const fragments = [];
            let groupIndex = 0;
            groups.forEach((groupRecords, groupName) => {
                groupIndex += 1;
                const group = document.createElement("div");
                group.className = "cuisine-category-master-icon-group";
                group.setAttribute("role", "group");
                const heading = document.createElement("div");
                heading.className = "cuisine-category-master-icon-group-label";
                heading.id = `cuisineCategoryIconGroup${groupIndex}`;
                heading.textContent = groupName;
                group.setAttribute("aria-labelledby", heading.id);
                group.append(heading, ...groupRecords.map(createIconOption));
                fragments.push(group);
            });
            iconListbox.replaceChildren(...fragments);
            iconEmpty.hidden = records.length > 0;
        };

        const syncIconPicker = () => {
            const item = renderIconVisual(iconPreview, iconInput.value);
            iconLabel.textContent = item.label;
            iconTrigger.title = item.label;
            renderIconOptions();
        };

        const setIconSelection = (value, options = {}) => {
            const token = ensureLegacyIconOption(value);
            iconInput.value = token;
            if (options.explicit) {
                iconChoiceExplicit = true;
                suggestedIconToken = "";
            }
            setFieldError(iconTrigger, iconError, "");
            syncIconPicker();
        };

        const positionIconMenu = () => {
            if (iconMenu.hidden) return;
            const rect = iconTrigger.getBoundingClientRect();
            const gutter = 10;
            const width = Math.min(
                Math.max(300, rect.width),
                Math.max(240, window.innerWidth - gutter * 2),
            );
            const left = Math.max(
                gutter,
                Math.min(rect.left, window.innerWidth - width - gutter),
            );
            const below = window.innerHeight - rect.bottom - gutter;
            const above = rect.top - gutter;
            const openAbove = below < 310 && above > below;
            const available = Math.max(220, Math.min(430, openAbove ? above : below));
            iconMenu.style.width = `${Math.round(width)}px`;
            iconMenu.style.maxHeight = `${Math.round(available)}px`;
            iconMenu.style.left = `${Math.round(left)}px`;
            iconMenu.style.top = openAbove ? "auto" : `${Math.round(rect.bottom + 6)}px`;
            iconMenu.style.bottom = openAbove
                ? `${Math.round(window.innerHeight - rect.top + 6)}px`
                : "auto";
        };

        const closeIconPicker = (options = {}) => {
            if (!iconMenu.hidden) {
                iconMenu.hidden = true;
                iconPicker.classList.remove("is-open");
                iconTrigger.setAttribute("aria-expanded", "false");
                ["width", "max-height", "left", "top", "bottom"].forEach(
                    property => iconMenu.style.removeProperty(property),
                );
            }
            iconSearch.value = "";
            renderIconOptions();
            if (options.focusTrigger) iconTrigger.focus({ preventScroll: true });
        };

        const openIconPicker = (options = {}) => {
            if (!iconMenu.hidden) {
                if (options.focusOption) {
                    const selected = iconListbox.querySelector('[role="option"][aria-selected="true"]');
                    (selected || visibleIconOptions()[0])?.focus({ preventScroll: true });
                }
                return;
            }
            iconSearch.value = "";
            renderIconOptions();
            iconMenu.hidden = false;
            iconPicker.classList.add("is-open");
            iconTrigger.setAttribute("aria-expanded", "true");
            positionIconMenu();
            const selected = iconListbox.querySelector('[role="option"][aria-selected="true"]');
            selected?.scrollIntoView({ block: "nearest" });
            if (options.focusOption) {
                (selected || visibleIconOptions()[0])?.focus({ preventScroll: true });
            }
        };

        const chooseIconOption = option => {
            if (!option) return;
            setIconSelection(option.dataset.cuisineCategoryMasterIconOption, { explicit: true });
            closeIconPicker({ focusTrigger: true });
        };

        const moveIconOptionFocus = (current, key) => {
            const options = visibleIconOptions();
            if (!options.length) return;
            const currentIndex = options.indexOf(current);
            const nextIndex = key === "Home"
                ? 0
                : key === "End"
                    ? options.length - 1
                    : (Math.max(0, currentIndex) + (key === "ArrowDown" ? 1 : -1) + options.length)
                        % options.length;
            options[nextIndex]?.focus({ preventScroll: true });
        };

        const suggestFlagFromAbbreviation = () => {
            if (iconChoiceExplicit) return;
            const code = cleanText(abbreviationInput.value).toLowerCase();
            const supportedCodes = new Set(iconVisuals?.supportedFlagCodes || []);
            const token = /^[a-z]{2}$/.test(code) && supportedCodes.has(code)
                ? `flag:${code}`
                : "";
            suggestedIconToken = token;
            setIconSelection(token);
        };

        const enhanceIconPicker = () => {
            iconInput.tabIndex = -1;
            iconInput.setAttribute("aria-hidden", "true");
            iconPicker.classList.add("is-enhanced");
            iconTrigger.hidden = false;
            setIconSelection(iconInput.value);
        };

        const clearEditorErrors = () => {
            setFieldError(iconTrigger, iconError, "");
            setFieldError(abbreviationInput, abbreviationError, "");
            setFieldError(nameInput, nameError, "");
            setEditorFeedback("");
        };

        const closeEditor = () => {
            closeIconPicker();
            if (dialog.open) dialog.close();
        };

        const openEditor = (item = null, trigger = null) => {
            editorCategoryId = String(item?.id || "");
            returnFocus = trigger || document.activeElement;
            closeIconPicker();
            clearEditorErrors();
            abbreviationInput.value = item?.abbreviation || "";
            // Existing blank icons are intentional saved choices. Suggestions apply
            // only while creating a new category before the user chooses an icon.
            iconChoiceExplicit = Boolean(item);
            suggestedIconToken = "";
            setIconSelection(item?.icon || "");
            if (!iconChoiceExplicit) suggestFlagFromAbbreviation();
            nameInput.value = categoryName(item);
            nameInput.disabled = Boolean(item?.seeded);
            nameHelp.textContent = item?.seeded
                ? "Built-in category names stay tied to stable cuisine labels. You can edit the icon and abbreviation."
                : "Enter the full category name shown in the recipe editor. Renaming preserves recipe assignments.";
            editorTitle.textContent = item
                ? `Edit ${categoryDisplayLabel(item)}`
                : "Add Cuisine Category";
            editorKicker.textContent = item?.seeded ? "Built-in cuisine" : "Workspace cuisine";
            saveButton.textContent = item ? "Save Changes" : "Add Cuisine Category";
            deleteButton.hidden = !item?.custom;
            deleteButton.style.display = item?.custom ? "" : "none";
            deleteButton.dataset.categoryId = item?.id || "";
            if (item?.custom && Number(item.recipe_count) > 0) {
                deleteButton.title = `${categoryDisplayLabel(item)} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}.`;
            } else {
                deleteButton.removeAttribute("title");
            }
            if (!dialog.open) dialog.showModal();
            window.requestAnimationFrame(() => iconTrigger.focus({ preventScroll: true }));
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
            const icon = cleanText(iconInput.value);
            const abbreviation = cleanText(abbreviationInput.value);
            const name = current?.seeded ? categoryName(current) : cleanText(nameInput.value);
            setFieldError(nameInput, nameError, name ? "" : "Enter a cuisine category name.");
            const firstInvalidInput = form.querySelector('[aria-invalid="true"]');
            if (firstInvalidInput) {
                setEditorFeedback("Complete the required cuisine category fields.");
                firstInvalidInput.focus();
                return;
            }
            const payload = {
                icon,
                abbreviation,
                category_name: name,
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
                    setFieldError(iconTrigger, iconError, errors.icon || "");
                    setFieldError(
                        abbreviationInput,
                        abbreviationError,
                        errors.abbreviation || "",
                    );
                    setFieldError(nameInput, nameError, errors.name || "");
                    setEditorFeedback(data.error || "The cuisine category could not be saved.");
                    form.querySelector('[aria-invalid="true"]')?.focus();
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
                    `${categoryDisplayLabel(item)} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}. Reassign or remove this cuisine category from those recipes before deleting it.`,
                    "warning",
                );
                deleteButton.focus();
                return;
            }
            if (!window.confirm(`Delete custom cuisine category "${categoryDisplayLabel(item)}"?`)) return;
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
            const displayLabel = categoryDisplayLabel(item);
            usageTitle.textContent = `Recipes using ${displayLabel}`;
            usageContext.textContent = `Review every recipe assigned to ${displayLabel}.`;
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

        iconTrigger.addEventListener("click", () => {
            if (iconMenu.hidden) {
                openIconPicker();
            } else {
                closeIconPicker({ focusTrigger: true });
            }
        });
        iconTrigger.addEventListener("keydown", event => {
            if (["ArrowDown", "ArrowUp"].includes(event.key)) {
                event.preventDefault();
                openIconPicker({ focusOption: true });
            } else if (event.key === "Escape" && !iconMenu.hidden) {
                event.preventDefault();
                closeIconPicker({ focusTrigger: true });
            }
        });
        iconSearch.addEventListener("input", renderIconOptions);
        iconSearch.addEventListener("keydown", event => {
            if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                const options = visibleIconOptions();
                const target = ["ArrowUp", "End"].includes(event.key)
                    ? options[options.length - 1]
                    : options[0];
                target?.focus({ preventScroll: true });
            } else if (event.key === "Enter") {
                const first = visibleIconOptions()[0];
                if (first) {
                    event.preventDefault();
                    chooseIconOption(first);
                }
            } else if (event.key === "Escape") {
                event.preventDefault();
                closeIconPicker({ focusTrigger: true });
            }
        });
        iconListbox.addEventListener("click", event => {
            chooseIconOption(event.target.closest("[data-cuisine-category-master-icon-option]"));
        });
        iconListbox.addEventListener("keydown", event => {
            const option = event.target.closest("[data-cuisine-category-master-icon-option]");
            if (option && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                moveIconOptionFocus(option, event.key);
            } else if (event.key === "Escape") {
                event.preventDefault();
                closeIconPicker({ focusTrigger: true });
            }
        });
        iconPicker.addEventListener("focusout", () => {
            // Pointer focus can temporarily leave the previous control before the
            // option click is delivered. Wait for that click to commit the manual
            // choice before deciding whether the picker actually lost focus.
            window.setTimeout(() => {
                if (!iconPicker.contains(document.activeElement)) closeIconPicker();
            }, 0);
        });
        abbreviationInput.addEventListener("input", suggestFlagFromAbbreviation);
        document.addEventListener("click", event => {
            if (!iconMenu.hidden && !event.target.closest("[data-cuisine-category-master-icon-picker]")) {
                closeIconPicker();
            }
        });
        window.addEventListener("resize", () => closeIconPicker());
        dialog.addEventListener("scroll", () => closeIconPicker(), { passive: true });

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

        populateFlagOptions();
        enhanceIconPicker();
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
