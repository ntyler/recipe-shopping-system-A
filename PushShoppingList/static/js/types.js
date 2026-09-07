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
        let orderPending = false;
        let mutationRequests = 0;
        let draggedRow = null;
        let rowDropTarget = null;
        let rowDropAfter = false;
        const drafts = new Map();
        const phoneLayout = window.matchMedia('(max-width: 600px)');
        const expandedTypeIds = new Set();

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
            const mutation = options.method && options.method !== "GET";
            if (mutation) {
                mutationRequests += 1;
                updateRowOrderControls();
            }
            try {
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
            } finally {
                if (mutation) {
                    mutationRequests -= 1;
                    updateRowOrderControls();
                }
            }
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

        const syncDisclosure = (row, draft) => {
            const id = row.dataset.typeId;
            let summary = row.querySelector('[data-type-master-row-summary]');
            let toggle = row.querySelector('[data-type-master-row-toggle]');
            if (!summary) {
                summary = document.createElement('button');
                summary.type = 'button';
                summary.className = 'type-master-name-display';
                summary.dataset.typeMasterRowSummary = '';
                row.append(summary);
            }
            if (!toggle) {
                toggle = document.createElement('button');
                toggle.type = 'button';
                toggle.className = 'type-master-details-toggle';
                toggle.dataset.typeMasterRowToggle = '';
                toggle.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"></path></svg>';
                row.append(toggle);
            }
            const actions = row.querySelector('.type-master-row-actions');
            if (!actions.querySelector('[data-type-master-row-cancel]')) {
                const cancel = document.createElement('button');
                cancel.type = 'button';
                cancel.className = 'type-master-row-cancel';
                cancel.dataset.typeMasterRowCancel = '';
                cancel.textContent = 'Cancel';
                actions.insertBefore(cancel, actions.querySelector('[data-type-master-row-delete]'));
            }
            actions.querySelector('[data-type-master-row-cancel]').disabled = draft.saving || draft.deleting;
            const details = ['.type-master-row-name-field', '.unit-master-source-badge', '.type-master-row-actions'].map((selector, index) => {
                const cell = row.querySelector(selector);
                cell.id = `typeDetails-${id}-${index}`;
                return cell.id;
            }).join(' ');
            const expanded = expandedTypeIds.has(id);
            const name = cleanText(draft.name) || draft.originalName;
            row.classList.toggle('is-mobile-expanded', expanded);
            summary.textContent = name;
            for (const control of [summary, toggle]) {
                control.setAttribute('aria-expanded', String(expanded));
                control.setAttribute('aria-controls', details);
                control.setAttribute('aria-label', `${expanded ? 'Hide' : 'Show'} details for ${name}${draftIsDirty(draft) ? ', unsaved changes' : ''}`);
            }
        };

        const syncRowState = row => {
            const item = typeById(row?.dataset.typeId);
            if (!item) return;
            const draft = ensureDraft(item);
            const controls = rowControls(row);
            const message = draft.errors.name || draft.feedback || "";
            const dirty = draftIsDirty(draft);
            if (phoneLayout.matches && message) expandedTypeIds.add(String(item.id));
            syncDisclosure(row, draft);
            row.classList.toggle("is-dirty", dirty);
            row.classList.toggle("is-saving", draft.saving);
            row.classList.toggle("has-error", Boolean(message));
            row.setAttribute("aria-busy", String(orderPending || draft.saving || draft.deleting));
            controls.name.setAttribute("aria-invalid", String(Boolean(message)));
            controls.name.classList.toggle("is-dirty", dirty);
            controls.name.disabled = draft.saving || draft.deleting;
            controls.save.disabled = orderPending || !dirty || draft.saving || draft.deleting;
            controls.save.textContent = draft.saving ? "Saving…" : "Save";
            if (controls.delete) {
                controls.delete.disabled = orderPending || draft.saving || draft.deleting;
                controls.delete.textContent = draft.deleting ? "Deleting…" : "Delete";
            }
            controls.error.textContent = message;
            controls.error.hidden = !message;
        };

        const setRowExpanded = (row, expanded) => {
            if (expanded) expandedTypeIds.add(row.dataset.typeId);
            else expandedTypeIds.delete(row.dataset.typeId);
            syncRowState(row);
        };

        const cancelTypeRow = row => {
            const item = typeById(row?.dataset.typeId);
            if (!item || ensureDraft(item).saving || ensureDraft(item).deleting) return;
            drafts.delete(String(item.id));
            rowControls(row).name.value = ensureDraft(item).name;
            syncRowState(row);
            applySearch();
        };

        const createOrderCell = (item, position) => {
            const label = item.name;
            const cell = document.createElement("div");
            cell.className = "store-section-master-order-cell type-master-order-cell";
            cell.setAttribute("role", "cell");
            cell.setAttribute("aria-colindex", "1");
            cell.dataset.mobileLabel = "Order";

            const order = document.createElement("div");
            order.className = "store-section-master-order";

            const handle = document.createElement("button");
            handle.type = "button";
            handle.className = "store-section-master-drag-handle";
            handle.dataset.typeMasterDragHandle = "";
            handle.setAttribute("aria-label", `Drag ${label} to reorder`);
            handle.title = "Drag to reorder Types";
            handle.setAttribute("aria-describedby", "typeMasterOrderHelp");
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
            up.dataset.typeMasterOrderAction = "up";
            up.setAttribute("aria-label", `Move ${label} up`);
            up.innerHTML = [
                '<svg viewBox="0 0 24 24" aria-hidden="true">',
                '<path d="M12 19V5"></path>',
                '<path d="m6 11 6-6 6 6"></path>',
                "</svg>",
            ].join("");

            const number = document.createElement("span");
            number.className = "store-section-master-order-step";
            number.dataset.typeMasterOrderNumber = "";
            number.textContent = String(position);
            number.setAttribute("aria-label", `Step ${position}`);

            const down = document.createElement("button");
            down.type = "button";
            down.value = "move_down";
            down.dataset.typeMasterOrderAction = "down";
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

            row.append(createOrderCell(item, index + 1), nameField, createUsageCell(item), sourceBadge, action, error);
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
            updateRowOrderControls();
        };

        const renderRegistry = () => {
            const liveIds = new Set(registry.types.map(item => String(item.id)));
            Array.from(drafts.keys()).forEach(id => {
                if (!liveIds.has(id)) drafts.delete(id);
            });
            expandedTypeIds.forEach(id => { if (!liveIds.has(id)) expandedTypeIds.delete(id); });
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

        const typeRows = () => Array.from(rows.querySelectorAll("[data-type-master-row]"));
        const reorderIsFiltered = () => Boolean(cleanText(search.value));
        const reorderIsBlocked = () => orderPending || mutationRequests > 0 || reorderIsFiltered();

        const updateRowOrderControls = () => {
            const currentRows = typeRows();
            const blocked = reorderIsBlocked();
            currentRows.forEach((row, index) => {
                const number = row.querySelector("[data-type-master-order-number]");
                number.textContent = String(index + 1);
                number.setAttribute("aria-label", `Step ${index + 1}`);
                row.querySelectorAll("[data-type-master-order-action]").forEach(button => {
                    const up = button.dataset.typeMasterOrderAction === "up";
                    button.disabled = blocked || (up ? index === 0 : index === currentRows.length - 1);
                    button.title = reorderIsFiltered()
                        ? "Clear the filters before reordering."
                        : `Move this Type ${up ? "up" : "down"} from position ${index + 1}`;
                });
                const handle = row.querySelector("[data-type-master-drag-handle]");
                handle.draggable = !blocked;
                handle.setAttribute("aria-disabled", String(blocked));
                handle.title = reorderIsFiltered()
                    ? "Clear the filters before reordering."
                    : "Drag to reorder Types";
            });
            const next = root.querySelector("[data-type-master-create-order-number]");
            next.textContent = String(currentRows.length + 1);
            next.setAttribute("aria-label", `Step ${currentRows.length + 1}`);
        };

        const setOrderPending = pending => {
            orderPending = pending;
            typeRows().forEach(syncRowState);
            addButtons.forEach(button => { button.disabled = pending; });
            createSubmit.disabled = pending;
            importButton.disabled = pending;
            updateRowOrderControls();
        };

        const acceptPersistedOrder = nextRegistry => {
            const currentRows = typeRows();
            const byId = new Map(currentRows.map(row => [row.dataset.typeId, row]));
            const nextTypes = nextRegistry.types;
            if (nextTypes.length !== byId.size || nextTypes.some(item => !byId.has(String(item.id)))) {
                updateRegistry(nextRegistry);
                return;
            }
            // Move existing nodes so an order response never discards name drafts.
            nextTypes.forEach(item => rows.append(byId.get(String(item.id))));
            registry = { types: nextTypes };
            source.textContent = JSON.stringify(registry);
            renderStats();
            applySearch();
        };

        const moveRowTo = async (row, targetIndex, submitter) => {
            if (reorderIsBlocked()) return;
            const previousRows = typeRows();
            const currentIndex = previousRows.indexOf(row);
            if (currentIndex < 0 || targetIndex < 0 || targetIndex >= previousRows.length || currentIndex === targetIndex) return;
            const typeId = row.dataset.typeId;
            const label = typeById(typeId).name;
            setOrderPending(true);
            previousRows[targetIndex].insertAdjacentElement(targetIndex < currentIndex ? "beforebegin" : "afterend", row);
            updateRowOrderControls();
            try {
                const url = root.dataset.updateUrlTemplate.replace("__TYPE_ID__", encodeURIComponent(typeId));
                const { response, data } = await requestJson(url, {
                    method: "PATCH",
                    body: JSON.stringify({ action: "move_to", position: targetIndex + 1 }),
                });
                if (!response.ok || data.ok === false || !Array.isArray(data.registry?.types)) {
                    throw new Error(data.error || "The new Type order could not be saved.");
                }
                acceptPersistedOrder(data.registry);
                setStatus(`${label} moved to position ${data.position}.`);
            } catch (error) {
                rows.append(...previousRows);
                applySearch();
                setStatus(error.message || "The new Type order could not be saved. Try again.", "error");
            } finally {
                setOrderPending(false);
                const movedRow = typeRows().find(item => item.dataset.typeId === typeId);
                const focusTarget = submitter?.isConnected && !submitter.disabled
                    ? submitter
                    : movedRow?.querySelector("[data-type-master-drag-handle]");
                focusTarget?.focus({ preventScroll: true });
            }
        };

        const clearRowDropState = () => {
            typeRows().forEach(row => row.classList.remove("is-row-drop-before", "is-row-drop-after", "is-row-dragging"));
            rowDropTarget = null;
            rowDropAfter = false;
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
            if (orderPending) return;
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
            if (orderPending) return;
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
            if (orderPending) return;
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
            const handle = event.target.closest("[data-type-master-drag-handle]");
            if (handle && ["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                const row = handle.closest("[data-type-master-row]");
                const currentRows = typeRows();
                const index = currentRows.indexOf(row);
                const target = event.key === "Home" ? 0 : event.key === "End" ? currentRows.length - 1
                    : index + (event.key === "ArrowUp" ? -1 : 1);
                moveRowTo(row, target, handle);
                return;
            }
            if (!event.target.matches("[data-type-master-row-name]")) return;
            const row = event.target.closest("[data-type-master-row]");
            if (event.key === "Enter") {
                event.preventDefault();
                saveTypeRow(row);
            } else if (event.key === "Escape") {
                cancelTypeRow(row);
            }
        });
        root.addEventListener("click", event => {
            const row = event.target.closest('[data-type-master-row]');
            if (phoneLayout.matches && row && (event.target.closest('[data-type-master-row-summary], [data-type-master-row-toggle]') || event.target === row)) {
                setRowExpanded(row, !row.classList.contains('is-mobile-expanded'));
                return;
            }
            if (event.target.closest('[data-type-master-row-cancel]')) {
                cancelTypeRow(row);
                setRowExpanded(row, false);
                row.querySelector('[data-type-master-row-toggle]').focus({preventScroll: true});
                return;
            }
            const orderAction = event.target.closest("[data-type-master-order-action]");
            if (orderAction) {
                const row = orderAction.closest("[data-type-master-row]");
                const direction = orderAction.dataset.typeMasterOrderAction === "up" ? -1 : 1;
                moveRowTo(row, typeRows().indexOf(row) + direction, orderAction);
                return;
            }
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

        // Phone dragging shares the existing persisted-order operation with desktop.
        let touchOrder = null, touchOrderFrame = 0;
        const updateTouchOrder = () => {
            if (!touchOrder?.moving) return;
            const {row, x, y, scroller} = touchOrder;
            const top = scroller.getBoundingClientRect().top;
            const bottom = Math.min(scroller.getBoundingClientRect().bottom, window.innerHeight - bottomViewportInset());
            if (y < top + 48) scroller.scrollTop -= 12;
            else if (y > bottom - 48) scroller.scrollTop += 12;
            clearRowDropState();
            row.classList.add('is-row-dragging');
            const target = document.elementFromPoint(x, y)?.closest('[data-type-master-row]');
            if (target && target !== row && rows.contains(target)) {
                const bounds = target.getBoundingClientRect();
                rowDropTarget = target;
                rowDropAfter = y > bounds.top + bounds.height / 2;
                target.classList.add(rowDropAfter ? 'is-row-drop-after' : 'is-row-drop-before');
            }
            touchOrderFrame = requestAnimationFrame(updateTouchOrder);
        };
        rows.addEventListener('pointerdown', event => {
            const handle = event.target.closest('[data-type-master-drag-handle]');
            if (!phoneLayout.matches || event.pointerType !== 'touch' || !event.isPrimary || !handle || reorderIsBlocked()) return;
            event.preventDefault();
            const row = handle.closest('[data-type-master-row]');
            const scroller = root.closest('.app-content') || document.scrollingElement;
            touchOrder = {row, handle, scroller, id: event.pointerId, startY: event.clientY, x: event.clientX, y: event.clientY, moving: false};
            handle.setPointerCapture(event.pointerId);
        });
        rows.addEventListener('pointermove', event => {
            if (!touchOrder || event.pointerId !== touchOrder.id) return;
            touchOrder.x = event.clientX;
            touchOrder.y = event.clientY;
            if (!touchOrder.moving && Math.abs(event.clientY - touchOrder.startY) > 8) {
                touchOrder.moving = true;
                updateTouchOrder();
            }
        });
        const finishTouchOrder = event => {
            if (!touchOrder || event.pointerId !== touchOrder.id) return;
            const {row, handle, moving} = touchOrder;
            touchOrder = null;
            cancelAnimationFrame(touchOrderFrame);
            if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
            const currentRows = typeRows();
            let target = rowDropTarget ? currentRows.indexOf(rowDropTarget) + (rowDropAfter ? 1 : 0) : -1;
            if (currentRows.indexOf(row) < target) target -= 1;
            clearRowDropState();
            if (moving && event.type === 'pointerup' && target >= 0) moveRowTo(row, target, handle);
        };
        rows.addEventListener('pointerup', finishTouchOrder);
        rows.addEventListener('pointercancel', finishTouchOrder);
        rows.addEventListener('lostpointercapture', finishTouchOrder);

        rows.addEventListener("dragstart", event => {
            const handle = event.target.closest("[data-type-master-drag-handle]");
            if (!handle || touchOrder || reorderIsBlocked()) {
                event.preventDefault();
                return;
            }
            draggedRow = handle.closest("[data-type-master-row]");
            draggedRow.classList.add("is-row-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", draggedRow.dataset.typeId);
        });
        rows.addEventListener("dragover", event => {
            if (!draggedRow) return;
            event.preventDefault();
            if (reorderIsBlocked()) {
                clearRowDropState();
                event.dataTransfer.dropEffect = "none";
                return;
            }
            const target = event.target.closest("[data-type-master-row]");
            clearRowDropState();
            if (!target || target === draggedRow || !rows.contains(target)) return;
            event.dataTransfer.dropEffect = "move";
            draggedRow.classList.add("is-row-dragging");
            const rect = target.getBoundingClientRect();
            rowDropAfter = event.clientY > rect.top + rect.height / 2;
            rowDropTarget = target;
            target.classList.add(rowDropAfter ? "is-row-drop-after" : "is-row-drop-before");
        });
        rows.addEventListener("drop", event => {
            if (!draggedRow) return;
            event.preventDefault();
            if (!rowDropTarget || reorderIsBlocked()) return;
            const moving = draggedRow;
            const currentRows = typeRows();
            const from = currentRows.indexOf(moving);
            let target = currentRows.indexOf(rowDropTarget) + (rowDropAfter ? 1 : 0);
            if (from < target) target -= 1;
            clearRowDropState();
            draggedRow = null;
            moveRowTo(moving, target, moving.querySelector("[data-type-master-drag-handle]"));
        });
        rows.addEventListener("dragend", () => {
            clearRowDropState();
            draggedRow = null;
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

        // Keep the server-rendered controls in place through initialization.
        rows.querySelectorAll("[data-type-master-row]").forEach(syncRowState);
        renderStats();
        applySearch();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initTypeMasterPage, { once: true });
    } else {
        initTypeMasterPage();
    }
})();
