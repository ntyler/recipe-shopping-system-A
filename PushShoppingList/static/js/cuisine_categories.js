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
        const rowDrafts = new Map();
        let usageReturnFocus = null;
        let usageRequestToken = 0;
        let activeIconTarget = null;
        let createIconChoiceExplicit = false;
        let suggestedIconToken = "";
        let createValidationErrors = {};
        let createValidationFeedback = "";

        const source = document.getElementById("cuisineCategoryConfig");
        const status = root.querySelector("[data-cuisine-category-master-status]");
        const search = root.querySelector("[data-cuisine-category-master-search]");
        const iconFilter = root.querySelector("[data-cuisine-category-master-icon-filter]");
        const rows = root.querySelector("[data-cuisine-category-master-rows]");
        const countLabel = root.querySelector("[data-cuisine-category-master-count-label]");
        const totalCount = root.querySelector("[data-cuisine-category-master-total-count]");
        const searchEmpty = root.querySelector("[data-cuisine-category-master-search-empty]");
        const createForm = root.querySelector("[data-cuisine-category-master-create-form]");
        const createNameInput = root.querySelector("[data-cuisine-category-master-create-name]");
        const createAbbreviationInput = root.querySelector(
            "[data-cuisine-category-master-create-abbreviation]",
        );
        const createIconInput = root.querySelector("[data-cuisine-category-master-create-icon]");
        const createIconTrigger = root.querySelector(
            "[data-cuisine-category-master-create-icon-trigger]",
        );
        const createError = root.querySelector("[data-cuisine-category-master-create-error]");
        const createSubmit = root.querySelector("[data-cuisine-category-master-create-submit]");
        const iconPicker = root.querySelector("[data-cuisine-category-master-icon-picker]");
        const iconInput = root.querySelector("[data-cuisine-category-master-icon]");
        const iconMenu = root.querySelector("[data-cuisine-category-master-icon-menu]");
        const iconSearch = root.querySelector("[data-cuisine-category-master-icon-search]");
        const iconListbox = root.querySelector("[data-cuisine-category-master-icon-listbox]");
        const iconEmpty = root.querySelector("[data-cuisine-category-master-icon-empty]");
        const importPanel = root.querySelector("[data-cuisine-category-master-import]");
        const importButton = root.querySelector("[data-cuisine-category-master-import-button]");
        const usageDialog = root.querySelector("[data-cuisine-category-master-usage-dialog]");
        const usageTitle = root.querySelector("[data-cuisine-category-master-usage-title]");
        const usageContext = root.querySelector("[data-cuisine-category-master-usage-context]");
        const usageSummary = root.querySelector("[data-cuisine-category-master-usage-summary]");
        const usageResults = root.querySelector("[data-cuisine-category-master-usage-results]");
        const addShortcuts = Array.from(
            root.querySelectorAll("[data-cuisine-category-master-add-shortcut]"),
        );

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

        const setAriaInvalid = (input, invalid) => {
            if (!input) return;
            if (invalid) input.setAttribute("aria-invalid", "true");
            else input.removeAttribute("aria-invalid");
        };

        const normalizeAbbreviation = value => cleanText(value).toUpperCase();

        const categorySnapshot = item => ({
            icon: cleanText(item?.icon),
            abbreviation: normalizeAbbreviation(item?.abbreviation),
            name: categoryName(item),
        });

        const normalizedDraft = draft => ({
            icon: cleanText(draft?.icon),
            abbreviation: normalizeAbbreviation(draft?.abbreviation),
            name: cleanText(draft?.name),
        });

        const valuesMatch = (left, right) => (
            left.icon === right.icon
            && left.abbreviation === right.abbreviation
            && left.name === right.name
        );

        const freshRowDraft = item => {
            const baseline = categorySnapshot(item);
            return {
                ...baseline,
                baseline,
                errors: {},
                feedback: "",
                saving: false,
                deleting: false,
                wasDirty: false,
            };
        };

        const ensureRowDraft = item => {
            const categoryId = String(item.id);
            if (!rowDrafts.has(categoryId)) {
                rowDrafts.set(categoryId, freshRowDraft(item));
            }
            return rowDrafts.get(categoryId);
        };

        const draftIsDirty = draft => !valuesMatch(
            normalizedDraft(draft),
            normalizedDraft(draft.baseline),
        );

        const validateValues = (values, item = null) => {
            const normalized = normalizedDraft(values);
            const errors = {};
            if (!normalized.name) {
                errors.name = "Enter a cuisine category name.";
            } else if (normalized.name.length > 60) {
                errors.name = "Use 60 characters or fewer.";
            } else if (/[,;\r\n]/.test(normalized.name)) {
                errors.name = "Cuisine category names cannot contain commas, semicolons, or line breaks.";
            } else if (!categoryKey(normalized.name)) {
                errors.name = "Enter a cuisine category name containing letters or numbers.";
            } else if (item?.seeded && normalized.name !== categoryName(item)) {
                errors.name = "Built-in cuisine category names cannot be changed.";
            } else if (registry.categories.some(category => (
                String(category.id) !== String(item?.id || "")
                && categoryKey(categoryName(category)) === categoryKey(normalized.name)
            ))) {
                errors.name = "A cuisine category with that name already exists.";
            }

            if (normalized.abbreviation && normalized.abbreviation.length < 2) {
                errors.abbreviation = "Use at least 2 characters.";
            } else if (normalized.abbreviation.length > 8) {
                errors.abbreviation = "Use 8 characters or fewer.";
            } else if (
                normalized.abbreviation
                && !/^[A-Z0-9]+$/.test(normalized.abbreviation)
            ) {
                errors.abbreviation = "Use letters and numbers only.";
            } else if (normalized.abbreviation && registry.categories.some(category => (
                String(category.id) !== String(item?.id || "")
                && normalizeAbbreviation(category.abbreviation) === normalized.abbreviation
            ))) {
                errors.abbreviation = "A cuisine category with that abbreviation already exists.";
            }
            return errors;
        };

        const errorMessage = (errors, fallback = "") => {
            const messages = [...new Set([
                errors?.icon,
                errors?.abbreviation,
                errors?.name,
                fallback,
            ].filter(Boolean))];
            return messages.join(" ");
        };

        const setCreateErrors = (errors = {}, fallback = "") => {
            createValidationErrors = { ...errors };
            createValidationFeedback = fallback;
            const message = errorMessage(createValidationErrors, createValidationFeedback);
            setAriaInvalid(createNameInput, Boolean(createValidationErrors.name));
            setAriaInvalid(
                createAbbreviationInput,
                Boolean(createValidationErrors.abbreviation),
            );
            setAriaInvalid(createIconTrigger, Boolean(createValidationErrors.icon));
            createError.textContent = message;
            createError.hidden = !message;
            createForm.classList.toggle("has-error", Boolean(message));
        };

        const clearCreateFieldError = field => {
            const nextErrors = { ...createValidationErrors };
            delete nextErrors[field];
            setCreateErrors(nextErrors);
        };

        const rowControls = row => ({
            icon: row.querySelector("[data-cuisine-category-master-row-icon-trigger]"),
            abbreviation: row.querySelector(
                "[data-cuisine-category-master-row-abbreviation]",
            ),
            name: row.querySelector("[data-cuisine-category-master-row-name]"),
            save: row.querySelector("[data-cuisine-category-master-row-save]"),
            delete: row.querySelector("[data-cuisine-category-master-row-delete]"),
            error: row.querySelector("[data-cuisine-category-master-row-error]"),
        });

        const setRowErrors = (row, errors = {}, fallback = "") => {
            const controls = rowControls(row);
            const message = errorMessage(errors, fallback);
            setAriaInvalid(controls.icon, Boolean(errors.icon));
            setAriaInvalid(controls.abbreviation, Boolean(errors.abbreviation));
            setAriaInvalid(controls.name, Boolean(errors.name));
            controls.error.textContent = message;
            controls.error.hidden = !message;
            row.classList.toggle("has-error", Boolean(message));
        };

        const syncIconTrigger = (trigger, value, contextLabel = "this cuisine category") => {
            if (!trigger) return;
            const token = cleanText(value);
            const item = renderIconVisual(
                trigger.querySelector(".cuisine-category-icon-visual"),
                token,
            );
            const label = trigger.querySelector(
                "[data-cuisine-category-master-icon-label], "
                + "[data-cuisine-category-master-row-icon-label]",
            );
            if (label) label.textContent = item.label;
            trigger.dataset.iconValue = token;
            trigger.title = item.label;
            trigger.setAttribute("aria-label", `Choose icon for ${contextLabel}`);
        };

        const syncRowState = row => {
            const item = categoryById(row.dataset.categoryId);
            if (!item) return;
            const draft = ensureRowDraft(item);
            const controls = rowControls(row);
            const normalized = normalizedDraft(draft);
            const validationErrors = validateValues(normalized, item);
            const errors = { ...draft.errors, ...validationErrors };
            const dirty = draftIsDirty(draft);
            const pending = Boolean(draft.saving || draft.deleting);
            const dirtyChanged = dirty !== draft.wasDirty;
            row.classList.toggle("is-dirty", dirty);
            row.classList.toggle("is-saving", pending);
            row.dataset.dirty = String(dirty);
            row.setAttribute("aria-busy", String(pending));
            controls.icon.disabled = pending;
            controls.abbreviation.disabled = pending;
            controls.name.disabled = pending;
            controls.save.disabled = !dirty || Boolean(Object.keys(errors).length) || pending;
            controls.save.textContent = draft.saving ? "Saving…" : "Save";
            controls.delete?.toggleAttribute("disabled", pending);
            if (controls.delete) controls.delete.textContent = draft.deleting ? "Deleting…" : "Delete";
            draft.wasDirty = dirty;
            if (dirtyChanged) {
                setStatus(
                    dirty
                        ? `${categoryDisplayLabel(item)} has unsaved changes.`
                        : `Changes to ${categoryDisplayLabel(item)} were reverted.`,
                    "info",
                );
            }
            row.dataset.cuisineCategoryMasterSearchValue = [
                normalized.icon,
                iconDescriptor(normalized.icon).label,
                normalized.abbreviation,
                normalized.name,
            ].filter(Boolean).join(" ");
            row.dataset.cuisineCategoryMasterIconValue = normalized.icon;
            setRowErrors(row, errors, draft.feedback);
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
            const draft = ensureRowDraft(item);
            const displayLabel = categoryDisplayLabel(item);
            const errorId = `cuisineCategoryRowError-${String(item.id).replace(/[^a-zA-Z0-9_-]/g, "")}`;
            const row = document.createElement("div");
            row.className = "unit-master-row";
            row.setAttribute("role", "row");
            row.dataset.cuisineCategoryMasterRow = "";
            row.dataset.categoryId = item.id;
            row.dataset.cuisineCategoryMasterIconValue = cleanText(item.icon);
            const iconField = document.createElement("div");
            iconField.className = "cuisine-category-master-row-icon-field";
            iconField.setAttribute("role", "cell");
            iconField.dataset.mobileLabel = "Icon";
            const icon = document.createElement("button");
            icon.type = "button";
            icon.className = "cuisine-category-master-icon-trigger cuisine-category-master-row-icon-trigger";
            icon.setAttribute("role", "combobox");
            icon.setAttribute("aria-haspopup", "listbox");
            icon.setAttribute("aria-expanded", "false");
            icon.setAttribute("aria-controls", "cuisineCategoryIconListbox");
            icon.setAttribute("aria-describedby", errorId);
            icon.dataset.cuisineCategoryMasterRowIconTrigger = "";
            const iconPreview = document.createElement("span");
            iconPreview.className = "cuisine-category-icon-visual";
            iconPreview.dataset.cuisineCategoryMasterRowIconPreview = "";
            iconPreview.setAttribute("aria-hidden", "true");
            const iconLabel = document.createElement("span");
            iconLabel.className = "sr-only";
            iconLabel.dataset.cuisineCategoryMasterRowIconLabel = "";
            const iconChevron = document.createElement("span");
            iconChevron.className = "cuisine-category-master-icon-chevron";
            iconChevron.setAttribute("aria-hidden", "true");
            iconChevron.textContent = "⌄";
            icon.append(iconPreview, iconLabel, iconChevron);
            syncIconTrigger(icon, draft.icon, displayLabel);
            iconField.appendChild(icon);

            const abbreviationField = document.createElement("label");
            abbreviationField.className = "cuisine-category-master-row-abbreviation-field";
            abbreviationField.setAttribute("role", "cell");
            abbreviationField.dataset.mobileLabel = "Abbreviation";
            const abbreviationLabel = document.createElement("span");
            abbreviationLabel.className = "sr-only";
            abbreviationLabel.textContent = `Abbreviation for ${displayLabel}`;
            const abbreviation = document.createElement("input");
            abbreviation.type = "text";
            abbreviation.className = "cuisine-category-master-abbreviation";
            abbreviation.maxLength = 8;
            abbreviation.value = draft.abbreviation;
            abbreviation.autocomplete = "off";
            abbreviation.spellcheck = false;
            abbreviation.dataset.cuisineCategoryMasterRowAbbreviation = "";
            abbreviation.setAttribute("aria-describedby", errorId);
            abbreviationField.append(abbreviationLabel, abbreviation);

            const nameField = document.createElement("label");
            nameField.className = "cuisine-category-master-row-name-field";
            nameField.setAttribute("role", "cell");
            nameField.dataset.mobileLabel = "Cuisine Category Name";
            const nameLabel = document.createElement("span");
            nameLabel.className = "sr-only";
            nameLabel.textContent = item.seeded
                ? `Cuisine category name for ${displayLabel}; built-in names cannot be changed`
                : `Cuisine category name for ${displayLabel}`;
            const name = document.createElement("input");
            name.type = "text";
            name.className = "cuisine-category-master-name";
            name.maxLength = 60;
            name.value = draft.name;
            name.autocomplete = "off";
            name.required = true;
            name.readOnly = Boolean(item.seeded);
            name.dataset.cuisineCategoryMasterRowName = "";
            name.setAttribute("aria-describedby", errorId);
            if (item.seeded) {
                name.setAttribute("aria-readonly", "true");
                name.title = "Built-in cuisine category names cannot be changed.";
            }
            nameField.append(nameLabel, name);

            const identity = document.createElement("div");
            identity.className = "cuisine-category-master-identity";
            identity.setAttribute("role", "presentation");
            identity.append(iconField, abbreviationField, nameField);

            const sourceBadge = document.createElement("span");
            sourceBadge.className = `unit-master-source-badge${item.custom ? " user-created" : ""}`;
            sourceBadge.setAttribute("role", "cell");
            sourceBadge.textContent = item.custom ? "User-created" : "Built-in";

            const save = document.createElement("button");
            save.type = "button";
            save.className = "unit-master-edit-button";
            save.dataset.cuisineCategoryMasterRowSave = "";
            save.dataset.categoryId = item.id;
            save.textContent = draft.saving ? "Saving…" : "Save";
            save.setAttribute("aria-label", `Save ${displayLabel}`);

            const actionCell = document.createElement("span");
            actionCell.className = "unit-master-action-cell cuisine-category-master-row-actions";
            actionCell.setAttribute("role", "cell");
            actionCell.dataset.mobileLabel = "Action";
            actionCell.appendChild(save);
            if (item.custom) {
                const deleteButton = document.createElement("button");
                deleteButton.type = "button";
                deleteButton.className = "danger cuisine-category-master-row-delete";
                deleteButton.dataset.cuisineCategoryMasterRowDelete = "";
                deleteButton.dataset.categoryId = item.id;
                deleteButton.textContent = "Delete";
                deleteButton.setAttribute("aria-label", `Delete ${displayLabel}`);
                actionCell.appendChild(deleteButton);
            }

            const rowError = document.createElement("div");
            rowError.id = errorId;
            rowError.className = "unit-master-field-error cuisine-category-master-row-error";
            rowError.dataset.cuisineCategoryMasterRowError = "";
            rowError.setAttribute("role", "alert");
            rowError.hidden = true;

            row.append(
                identity,
                createUsageCell(item),
                sourceBadge,
                actionCell,
                rowError,
            );
            syncRowState(row);
            return row;
        };

        const renderStats = () => {
            if (totalCount) totalCount.textContent = String(registry.categories.length);
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
            const selectedIcon = cleanText(iconFilter?.value);
            let visible = 0;
            root.querySelectorAll("[data-cuisine-category-master-row]").forEach(row => {
                const searchValue = cleanText(
                    row.dataset.cuisineCategoryMasterSearchValue,
                );
                const matchesSearch = (
                    !rawQuery
                    || searchValue.toLocaleLowerCase().includes(rawQuery)
                    || (
                        Boolean(semanticQuery)
                        && categoryKey(searchValue).includes(semanticQuery)
                    )
                );
                const rowIcon = cleanText(row.dataset.cuisineCategoryMasterIconValue);
                const matchesIcon = (
                    !selectedIcon
                    || (selectedIcon === "__none__" ? !rowIcon : rowIcon === selectedIcon)
                );
                const matches = matchesSearch && matchesIcon;
                row.hidden = !matches;
                if (matches) visible += 1;
            });
            countLabel.textContent = (
                `Showing ${visible} of ${registry.categories.length} Cuisine Categories.`
            );
            searchEmpty.hidden = visible > 0;
        };

        const renderRegistry = () => {
            rows.replaceChildren(...registry.categories.map(createCategoryRow));
            renderStats();
            syncIconFilterOptions();
            applySearch();
        };

        const reconcileRowDrafts = (nextCategories, resetCategoryIds = []) => {
            const resetIds = new Set(resetCategoryIds.map(String));
            const nextIds = new Set(nextCategories.map(item => String(item.id)));
            Array.from(rowDrafts.keys()).forEach(categoryId => {
                if (!nextIds.has(categoryId)) rowDrafts.delete(categoryId);
            });
            nextCategories.forEach(item => {
                const categoryId = String(item.id);
                const existing = rowDrafts.get(categoryId);
                if (!existing || resetIds.has(categoryId)) {
                    rowDrafts.set(categoryId, freshRowDraft(item));
                    return;
                }
                existing.baseline = categorySnapshot(item);
            });
        };

        const updateRegistry = (nextRegistry, options = {}) => {
            registry = {
                ...(nextRegistry || {}),
                categories: Array.isArray(nextRegistry?.categories)
                    ? nextRegistry.categories
                    : [],
            };
            reconcileRowDrafts(registry.categories, options.resetCategoryIds || []);
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

        const syncIconFilterOptions = () => {
            if (!iconFilter) return;
            const previousValue = iconFilter.value;
            const allOption = document.createElement("option");
            allOption.value = "";
            allOption.textContent = "All icons";
            const nextOptions = [allOption];
            if (registry.categories.some(item => !cleanText(item.icon))) {
                const noneOption = document.createElement("option");
                noneOption.value = "__none__";
                noneOption.textContent = "No icon";
                nextOptions.push(noneOption);
            }
            const usedIcons = Array.from(new Set(
                registry.categories.map(item => cleanText(item.icon)).filter(Boolean),
            )).sort((left, right) => (
                iconDescriptor(left).label.localeCompare(iconDescriptor(right).label)
            ));
            usedIcons.forEach(token => {
                const option = document.createElement("option");
                option.value = token;
                option.textContent = iconDescriptor(token).label;
                nextOptions.push(option);
            });
            iconFilter.replaceChildren(...nextOptions);
            iconFilter.value = nextOptions.some(option => option.value === previousValue)
                ? previousValue
                : "";
        };

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

        const activeIconValue = () => {
            if (activeIconTarget?.kind === "create") return createIconInput.value;
            if (activeIconTarget?.kind === "row") {
                const item = categoryById(activeIconTarget.categoryId);
                return item ? ensureRowDraft(item).icon : "";
            }
            return "";
        };

        const createIconOption = record => {
            const selectedValue = activeIconValue();
            const option = document.createElement("button");
            option.type = "button";
            option.className = "cuisine-category-master-icon-option";
            option.dataset.cuisineCategoryMasterIconOption = record.token;
            option.setAttribute("role", "option");
            option.setAttribute("aria-selected", String(record.token === selectedValue));
            option.tabIndex = -1;
            option.classList.toggle("is-selected", record.token === selectedValue);

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
                && activeIconTarget?.kind === "create"
                && record.token === suggestedIconToken
                && !createIconChoiceExplicit
                ? "Suggested"
                : record.token === selectedValue ? "✓" : "";
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

        const setCreateIconSelection = (value, options = {}) => {
            const token = iconVisuals?.normalizeToken(value) || cleanText(value);
            createIconInput.value = token;
            if (options.explicit) {
                createIconChoiceExplicit = true;
                suggestedIconToken = "";
            }
            syncIconTrigger(createIconTrigger, token, "the new cuisine category");
            if (options.clearError) clearCreateFieldError("icon");
            if (activeIconTarget?.kind === "create") renderIconOptions();
        };

        const setActiveIconSelection = (value, options = {}) => {
            const token = ensureLegacyIconOption(value);
            iconInput.value = token;
            if (activeIconTarget?.kind === "create") {
                setCreateIconSelection(token, { ...options, clearError: true });
                return;
            }
            if (activeIconTarget?.kind === "row") {
                const item = categoryById(activeIconTarget.categoryId);
                const row = root.querySelector(
                    `[data-cuisine-category-master-row][data-category-id="${CSS.escape(String(activeIconTarget.categoryId))}"]`,
                );
                if (!item || !row) return;
                const draft = ensureRowDraft(item);
                draft.icon = token;
                delete draft.errors.icon;
                draft.feedback = "";
                syncIconTrigger(rowControls(row).icon, token, normalizedDraft(draft).name);
                syncRowState(row);
                renderIconOptions();
            }
        };

        const positionIconMenu = () => {
            const trigger = activeIconTarget?.trigger;
            if (iconMenu.hidden || !trigger?.isConnected) return;
            const rect = trigger.getBoundingClientRect();
            const gutter = 10;
            const width = Math.min(
                Math.max(300, rect.width),
                Math.max(240, window.innerWidth - gutter * 2),
            );
            const left = Math.max(gutter, Math.min(rect.left, window.innerWidth - width - gutter));
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
            const trigger = activeIconTarget?.trigger;
            iconMenu.hidden = true;
            iconPicker.classList.remove("is-open");
            trigger?.classList.remove("is-open");
            trigger?.setAttribute("aria-expanded", "false");
            ["width", "max-height", "left", "top", "bottom"].forEach(
                property => iconMenu.style.removeProperty(property),
            );
            iconSearch.value = "";
            activeIconTarget = null;
            if (options.focusTrigger && trigger?.isConnected) {
                trigger.focus({ preventScroll: true });
            }
        };

        const openIconPicker = (target, options = {}) => {
            if (!target?.trigger) return;
            if (activeIconTarget?.trigger && activeIconTarget.trigger !== target.trigger) {
                closeIconPicker();
            }
            activeIconTarget = target;
            iconInput.value = ensureLegacyIconOption(activeIconValue());
            iconSearch.value = "";
            renderIconOptions();
            iconMenu.hidden = false;
            iconPicker.classList.add("is-open");
            target.trigger.classList.add("is-open");
            target.trigger.setAttribute("aria-expanded", "true");
            positionIconMenu();
            const selected = iconListbox.querySelector('[role="option"][aria-selected="true"]');
            selected?.scrollIntoView({ block: "nearest" });
            if (options.focusOption) {
                (selected || visibleIconOptions()[0])?.focus({ preventScroll: true });
            } else {
                iconSearch.focus({ preventScroll: true });
            }
        };

        const chooseIconOption = option => {
            if (!option || !activeIconTarget) return;
            setActiveIconSelection(option.dataset.cuisineCategoryMasterIconOption, {
                explicit: true,
            });
            closeIconPicker({ focusTrigger: true });
        };

        const focusIconOption = option => {
            if (!option) return;
            option.focus({ preventScroll: true });
            option.scrollIntoView({ block: "nearest", inline: "nearest" });
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
            focusIconOption(options[nextIndex]);
        };

        const suggestFlagFromCreateAbbreviation = () => {
            if (createIconChoiceExplicit) return;
            const code = cleanText(createAbbreviationInput.value).toLowerCase();
            const supportedCodes = new Set(iconVisuals?.supportedFlagCodes || []);
            const token = /^[a-z]{2}$/.test(code) && supportedCodes.has(code)
                ? `flag:${code}`
                : "";
            suggestedIconToken = token;
            setCreateIconSelection(token, { clearError: true });
        };

        const enhanceIconPicker = () => {
            iconInput.tabIndex = -1;
            iconInput.setAttribute("aria-hidden", "true");
            iconPicker.classList.add("is-enhanced");
            setCreateIconSelection(createIconInput.value);
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

        const focusFirstInvalid = (container, fallback = null) => {
            const target = container.querySelector('[aria-invalid="true"]') || fallback;
            target?.focus({ preventScroll: true });
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
            const panelRect = createForm.getBoundingClientRect();
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
            const visibleBottom = viewportHeight - bottomViewportInset();
            const content = root.closest("#appContent") || root.closest(".app-content");
            const contentRect = content?.getBoundingClientRect();
            const visibleTop = Math.max(0, contentRect?.top || 0);
            const clippedBottom = Math.min(visibleBottom, contentRect?.bottom || visibleBottom);
            return panelRect.top >= visibleTop && panelRect.bottom <= clippedBottom;
        };

        const setCreatePanelExpanded = (expanded, options = {}) => {
            createForm.hidden = !expanded;
            addShortcuts.forEach(button => {
                button.setAttribute("aria-expanded", String(expanded));
            });
            if (!expanded) {
                createForm.style.scrollMarginBottom = "";
                closeIconPicker();
                return;
            }
            createNameInput.focus({ preventScroll: true });
            const bottomInset = bottomViewportInset();
            createForm.style.scrollMarginBottom = bottomInset
                ? `${Math.ceil(bottomInset)}px`
                : "";
            if (!createPanelIsFullyVisible()) {
                createForm.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
            if (options.announce !== false) {
                setStatus("Add Cuisine Category form focused.", "info");
            }
        };

        const resetCreateDraft = () => {
            createForm.reset();
            createIconChoiceExplicit = false;
            suggestedIconToken = "";
            setCreateIconSelection("");
            setCreateErrors();
        };

        const cancelCreate = () => {
            if (createForm.classList.contains("is-saving")) return;
            resetCreateDraft();
            setCreatePanelExpanded(false, { announce: false });
            addShortcuts.at(-1)?.focus({ preventScroll: true });
            setStatus("New Cuisine Category discarded.", "info");
        };

        const setCreateSaving = saving => {
            createForm.classList.toggle("is-saving", saving);
            createForm.setAttribute("aria-busy", String(saving));
            createNameInput.disabled = saving;
            createAbbreviationInput.disabled = saving;
            createIconInput.disabled = saving;
            createIconTrigger.disabled = saving;
            createSubmit.disabled = saving;
            createSubmit.textContent = saving ? "Saving…" : "Save";
            if (saving) setStatus("Adding cuisine category…", "info");
        };

        const saveNewCategory = async event => {
            event.preventDefault();
            const values = normalizedDraft({
                icon: createIconInput.value,
                abbreviation: createAbbreviationInput.value,
                name: createNameInput.value,
            });
            createNameInput.value = values.name;
            createAbbreviationInput.value = values.abbreviation;
            const errors = validateValues(values);
            setCreateErrors(errors);
            if (Object.keys(errors).length) {
                focusFirstInvalid(createForm, createNameInput);
                return;
            }
            closeIconPicker();
            setCreateSaving(true);
            try {
                const { response, data } = await requestJson(root.dataset.createUrl, {
                    method: "POST",
                    body: JSON.stringify({
                        icon: values.icon,
                        abbreviation: values.abbreviation,
                        category_name: values.name,
                    }),
                });
                if (!response.ok || data.ok === false) {
                    const failureMessage = data.error || "The cuisine category could not be added.";
                    setCreateSaving(false);
                    setCreateErrors(
                        data.errors || {},
                        failureMessage,
                    );
                    setStatus(failureMessage, "error");
                    focusFirstInvalid(createForm, createNameInput);
                    return;
                }
                updateRegistry(data.registry);
                resetCreateDraft();
                setCreatePanelExpanded(false, { announce: false });
                addShortcuts.at(-1)?.focus({ preventScroll: true });
                setStatus(data.message || "Cuisine category added.");
            } catch (error) {
                const failureMessage = "The cuisine category could not be added. Try again.";
                setCreateSaving(false);
                setCreateErrors({}, failureMessage);
                setStatus(failureMessage, "error");
                createNameInput.focus({ preventScroll: true });
                console.error("Unable to add cuisine category.", error);
            } finally {
                setCreateSaving(false);
            }
        };

        const captureRowDraft = (row, changedField = "") => {
            const item = categoryById(row.dataset.categoryId);
            if (!item) return null;
            const draft = ensureRowDraft(item);
            const controls = rowControls(row);
            draft.icon = controls.icon.dataset.iconValue || "";
            draft.abbreviation = controls.abbreviation.value;
            draft.name = item.seeded ? categoryName(item) : controls.name.value;
            if (changedField) {
                delete draft.errors[changedField];
                draft.feedback = "";
            }
            syncRowState(row);
            return draft;
        };

        const saveCategoryRow = async row => {
            const item = categoryById(row?.dataset.categoryId);
            if (!item) return;
            if (ensureRowDraft(item).deleting) return;
            const draft = captureRowDraft(row);
            const values = normalizedDraft(draft);
            const errors = validateValues(values, item);
            draft.errors = errors;
            draft.feedback = "";
            syncRowState(row);
            if (Object.keys(errors).length) {
                focusFirstInvalid(row, rowControls(row).abbreviation);
                return;
            }
            if (!draftIsDirty(draft) || draft.saving) return;
            draft.saving = true;
            setStatus(`Saving ${categoryDisplayLabel(item)}…`, "info");
            syncRowState(row);
            closeIconPicker();
            let saved = false;
            try {
                const url = root.dataset.updateUrlTemplate.replace(
                    "__CATEGORY_ID__",
                    encodeURIComponent(item.id),
                );
                const { response, data } = await requestJson(url, {
                    method: "PATCH",
                    body: JSON.stringify({
                        icon: values.icon,
                        abbreviation: values.abbreviation,
                        category_name: item.seeded ? categoryName(item) : values.name,
                    }),
                });
                if (!response.ok || data.ok === false) {
                    const failureMessage = data.error || "The cuisine category could not be saved.";
                    draft.saving = false;
                    draft.errors = data.errors || {};
                    draft.feedback = failureMessage;
                    syncRowState(row);
                    setStatus(failureMessage, "error");
                    focusFirstInvalid(row, rowControls(row).abbreviation);
                    return;
                }
                saved = true;
                draft.saving = false;
                updateRegistry(data.registry, { resetCategoryIds: [item.id] });
                setStatus(data.message || "Cuisine category saved.");
            } catch (error) {
                const failureMessage = "The cuisine category could not be saved. Try again.";
                draft.saving = false;
                draft.feedback = failureMessage;
                syncRowState(row);
                setStatus(failureMessage, "error");
                rowControls(row).abbreviation.focus({ preventScroll: true });
                console.error("Unable to save cuisine category.", error);
            } finally {
                if (!saved) {
                    draft.saving = false;
                    syncRowState(row);
                }
            }
        };

        const deleteCategoryRow = async row => {
            const item = categoryById(row?.dataset.categoryId);
            if (!item?.custom) return;
            const draft = ensureRowDraft(item);
            if (draft.saving || draft.deleting) return;
            const controls = rowControls(row);
            if (Number(item.recipe_count) > 0) {
                draft.errors = {};
                draft.feedback = `${categoryDisplayLabel(item)} is used by ${item.recipe_count} recipe${Number(item.recipe_count) === 1 ? "" : "s"}. Reassign or remove this cuisine category from those recipes before deleting it.`;
                syncRowState(row);
                controls.delete.focus({ preventScroll: true });
                return;
            }
            if (!window.confirm(`Delete custom cuisine category "${categoryDisplayLabel(item)}"?`)) {
                return;
            }
            draft.errors = {};
            draft.feedback = "";
            draft.deleting = true;
            setStatus(`Deleting ${categoryDisplayLabel(item)}…`, "info");
            syncRowState(row);
            if (activeIconTarget?.categoryId === String(item.id)) closeIconPicker();
            try {
                const url = root.dataset.updateUrlTemplate.replace(
                    "__CATEGORY_ID__",
                    encodeURIComponent(item.id),
                );
                const { response, data } = await requestJson(url, { method: "DELETE" });
                if (!response.ok || data.ok === false) {
                    const failureMessage = data.error || "The cuisine category could not be deleted.";
                    draft.deleting = false;
                    draft.errors = data.errors || {};
                    draft.feedback = failureMessage;
                    syncRowState(row);
                    setStatus(failureMessage, "error");
                    controls.delete.focus({ preventScroll: true });
                    return;
                }
                updateRegistry(data.registry);
                setStatus(data.message || "Cuisine category deleted.");
                addShortcuts.at(-1)?.focus({ preventScroll: true });
            } catch (error) {
                const failureMessage = "The cuisine category could not be deleted. Try again.";
                draft.deleting = false;
                draft.errors = {};
                draft.feedback = failureMessage;
                syncRowState(row);
                setStatus(failureMessage, "error");
                controls.delete.focus({ preventScroll: true });
                console.error("Unable to delete cuisine category.", error);
            } finally {
                if (row.isConnected && draft.deleting) {
                    draft.deleting = false;
                    syncRowState(row);
                }
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

        iconSearch.addEventListener("input", renderIconOptions);
        iconSearch.addEventListener("keydown", event => {
            if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                const options = visibleIconOptions();
                const target = ["ArrowUp", "End"].includes(event.key)
                    ? options[options.length - 1]
                    : options[0];
                focusIconOption(target);
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
                if (
                    !iconPicker.contains(document.activeElement)
                    && document.activeElement !== activeIconTarget?.trigger
                ) closeIconPicker();
            }, 0);
        });
        addShortcuts.forEach(button => {
            button.addEventListener("click", event => {
                event.preventDefault();
                setCreatePanelExpanded(true);
            });
        });
        root.querySelectorAll("[data-cuisine-category-master-create-cancel]").forEach(
            button => button.addEventListener("click", event => {
                event.preventDefault();
                cancelCreate();
            }),
        );
        createForm.addEventListener("submit", saveNewCategory);
        createAbbreviationInput.addEventListener("input", () => {
            clearCreateFieldError("abbreviation");
            suggestFlagFromCreateAbbreviation();
        });
        createNameInput.addEventListener("input", () => clearCreateFieldError("name"));

        root.addEventListener("input", event => {
            const row = event.target.closest("[data-cuisine-category-master-row]");
            if (!row) return;
            if (event.target.matches("[data-cuisine-category-master-row-abbreviation]")) {
                captureRowDraft(row, "abbreviation");
            } else if (event.target.matches("[data-cuisine-category-master-row-name]")) {
                captureRowDraft(row, "name");
            }
        });
        root.addEventListener("focusout", event => {
            if (!event.target.matches("[data-cuisine-category-master-row-abbreviation]")) return;
            event.target.value = normalizeAbbreviation(event.target.value);
            const row = event.target.closest("[data-cuisine-category-master-row]");
            if (row) captureRowDraft(row, "abbreviation");
        });

        const pickerTargetForTrigger = trigger => {
            if (trigger.matches("[data-cuisine-category-master-create-icon-trigger]")) {
                return { kind: "create", trigger };
            }
            const row = trigger.closest("[data-cuisine-category-master-row]");
            return row ? {
                kind: "row",
                categoryId: String(row.dataset.categoryId),
                trigger,
            } : null;
        };

        root.addEventListener("keydown", event => {
            const trigger = event.target.closest(
                "[data-cuisine-category-master-create-icon-trigger], "
                + "[data-cuisine-category-master-row-icon-trigger]",
            );
            if (!trigger) return;
            if (["ArrowDown", "ArrowUp"].includes(event.key)) {
                event.preventDefault();
                openIconPicker(pickerTargetForTrigger(trigger), { focusOption: true });
            } else if (event.key === "Escape" && !iconMenu.hidden) {
                event.preventDefault();
                closeIconPicker({ focusTrigger: true });
            }
        });

        document.addEventListener("click", event => {
            const trigger = event.target.closest(
                "[data-cuisine-category-master-create-icon-trigger], "
                + "[data-cuisine-category-master-row-icon-trigger]",
            );
            if (
                !iconMenu.hidden
                && !event.target.closest("[data-cuisine-category-master-icon-picker]")
                && !trigger
            ) {
                closeIconPicker();
            }
        });
        window.addEventListener("resize", () => closeIconPicker());
        document.addEventListener("scroll", event => {
            if (event.target instanceof Node && iconPicker.contains(event.target)) return;
            closeIconPicker();
        }, {
            capture: true,
            passive: true,
        });

        root.addEventListener("click", event => {
            const iconTrigger = event.target.closest(
                "[data-cuisine-category-master-create-icon-trigger], "
                + "[data-cuisine-category-master-row-icon-trigger]",
            );
            if (iconTrigger) {
                if (!iconMenu.hidden && activeIconTarget?.trigger === iconTrigger) {
                    closeIconPicker({ focusTrigger: true });
                } else {
                    openIconPicker(pickerTargetForTrigger(iconTrigger));
                }
                return;
            }
            const save = event.target.closest("[data-cuisine-category-master-row-save]");
            if (save) {
                saveCategoryRow(save.closest("[data-cuisine-category-master-row]"));
                return;
            }
            const deleteButton = event.target.closest("[data-cuisine-category-master-row-delete]");
            if (deleteButton) {
                deleteCategoryRow(deleteButton.closest("[data-cuisine-category-master-row]"));
                return;
            }
            const usage = event.target.closest("[data-cuisine-category-master-usage-button]");
            if (usage) {
                openUsage(categoryById(usage.dataset.categoryId), usage);
            }
        });
        search.addEventListener("input", applySearch);
        iconFilter?.addEventListener("change", applySearch);
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
