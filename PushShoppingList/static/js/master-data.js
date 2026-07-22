(function () {
    const POLL_INTERVAL_MS = 700;
    const REFRESH_DELAY_MS = 1200;
    const MASTER_DATA_THUMBNAIL_SIZE_STORAGE_KEY = "master-data-thumbnail-size";
    const MASTER_DATA_THUMBNAIL_DEFAULT_SIZE = 64;
    const MASTER_DATA_THUMBNAIL_MIN_SIZE = 32;
    const MASTER_DATA_THUMBNAIL_MAX_SIZE = 80;
    const MASTER_DATA_THUMBNAIL_STEP_SIZE = 8;
    const INGREDIENT_MASTER_DATA_VERSION_STORAGE_KEY = "ingredient-master-data-version";
    let activeJobId = "";
    let pollTimer = null;
    let activeImageJobId = "";
    let imagePollTimer = null;
    let imageRefreshTimer = null;
    let masterDataThumbnailSize = MASTER_DATA_THUMBNAIL_DEFAULT_SIZE;
    let masterDataThumbnailSizeEventsBound = false;
    let masterDataMergeSearchTimer = null;
    let masterDataMergeRequestId = 0;
    let masterDataMergeReturnFocus = null;
    let masterDataDuplicateReferenceRequestId = 0;
    let masterDataDuplicateReferenceReturnFocus = null;

    function text(value) {
        return String(value == null ? "" : value);
    }

    function stateLabel(value) {
        const labels = {
            starting: "Starting",
            running: "Running",
            complete: "Done",
            skipped: "Skipped",
            failed: "Failed",
            done: "Done",
        };
        return labels[value] || "Waiting";
    }

    function makeJobId(prefix) {
        const resolvedPrefix = prefix || "master-backfill";
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        return `${resolvedPrefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function progressPercent(progress) {
        const total = Number(progress && progress.recipes_total) || 0;
        const complete = Number(progress && progress.recipes_completed) || 0;
        if (!total) {
            return progress && ["complete", "skipped"].includes(progress.status) ? 100 : 6;
        }
        return Math.max(6, Math.min(100, Math.round((complete / total) * 100)));
    }

    function imageProgressPercent(progress) {
        const total = Number(progress && progress.total) || 0;
        const complete = Number(progress && progress.completed) || 0;
        if (!total) {
            return progress && progress.status === "complete" ? 100 : 6;
        }
        return Math.max(6, Math.min(100, Math.round((complete / total) * 100)));
    }

    function normalizeMasterDataThumbnailSize(value) {
        const parsed = Number.parseInt(value, 10);

        if (!Number.isFinite(parsed)) {
            return MASTER_DATA_THUMBNAIL_DEFAULT_SIZE;
        }

        const stepped = Math.round(parsed / MASTER_DATA_THUMBNAIL_STEP_SIZE) * MASTER_DATA_THUMBNAIL_STEP_SIZE;
        return Math.max(
            MASTER_DATA_THUMBNAIL_MIN_SIZE,
            Math.min(MASTER_DATA_THUMBNAIL_MAX_SIZE, stepped)
        );
    }

    function rememberedMasterDataThumbnailSize() {
        try {
            return normalizeMasterDataThumbnailSize(
                window.localStorage
                    ? window.localStorage.getItem(MASTER_DATA_THUMBNAIL_SIZE_STORAGE_KEY)
                    : ""
            );
        } catch (error) {
            console.warn("Unable to restore master-data thumbnail size.", error);
            return MASTER_DATA_THUMBNAIL_DEFAULT_SIZE;
        }
    }

    function updateMasterDataThumbnailSizeControls(size = masterDataThumbnailSize) {
        document.querySelectorAll("[data-master-thumbnail-size-value]").forEach((label) => {
            label.textContent = `${size}px`;
        });
        document.querySelectorAll("[data-master-thumbnail-size-decrease]").forEach((button) => {
            button.disabled = size <= MASTER_DATA_THUMBNAIL_MIN_SIZE;
        });
        document.querySelectorAll("[data-master-thumbnail-size-increase]").forEach((button) => {
            button.disabled = size >= MASTER_DATA_THUMBNAIL_MAX_SIZE;
        });
    }

    function updateReferenceImageSizes(size = masterDataThumbnailSize) {
        document.querySelectorAll(".master-data-reference-title-image[srcset]").forEach((image) => {
            image.sizes = `${size}px`;
        });
    }

    function applyMasterDataThumbnailSize(size, options = {}) {
        const normalizedSize = normalizeMasterDataThumbnailSize(size);
        masterDataThumbnailSize = normalizedSize;
        document.documentElement.style.setProperty("--master-data-thumbnail-size", `${normalizedSize}px`);
        document.documentElement.style.setProperty("--master-data-thumbnail-slot", `${normalizedSize + 2}px`);

        if (options.persist) {
            try {
                if (window.localStorage) {
                    window.localStorage.setItem(MASTER_DATA_THUMBNAIL_SIZE_STORAGE_KEY, String(normalizedSize));
                }
            } catch (error) {
                console.warn("Unable to remember master-data thumbnail size.", error);
            }
        }

        updateMasterDataThumbnailSizeControls(normalizedSize);
        updateReferenceImageSizes(normalizedSize);
        return normalizedSize;
    }

    function changeMasterDataThumbnailSize(direction) {
        const stepDirection = Number(direction) < 0 ? -1 : 1;
        applyMasterDataThumbnailSize(
            masterDataThumbnailSize + (stepDirection * MASTER_DATA_THUMBNAIL_STEP_SIZE),
            { persist: true }
        );
    }

    function resetMasterDataThumbnailSize() {
        applyMasterDataThumbnailSize(MASTER_DATA_THUMBNAIL_DEFAULT_SIZE, { persist: true });
    }

    function initMasterDataThumbnailSizeControls() {
        applyMasterDataThumbnailSize(rememberedMasterDataThumbnailSize());

        if (masterDataThumbnailSizeEventsBound) {
            return;
        }

        masterDataThumbnailSizeEventsBound = true;
        document.addEventListener("click", (event) => {
            const target = event.target && event.target.closest ? event.target : null;
            if (!target) {
                return;
            }

            if (target.closest("[data-master-thumbnail-size-decrease]")) {
                event.preventDefault();
                changeMasterDataThumbnailSize(-1);
            } else if (target.closest("[data-master-thumbnail-size-increase]")) {
                event.preventDefault();
                changeMasterDataThumbnailSize(1);
            } else if (target.closest("[data-master-thumbnail-size-reset]")) {
                event.preventDefault();
                resetMasterDataThumbnailSize();
            }
        });
    }

    function masterDataLightboxImageSelector() {
        return ".master-data-thumbnail[src], .master-data-reference-title-image[src]";
    }

    function ensureMasterDataImageLightbox() {
        let lightbox = document.getElementById("recipeImageLightbox");

        if (lightbox) {
            return lightbox;
        }

        lightbox = document.createElement("div");
        lightbox.id = "recipeImageLightbox";
        lightbox.className = "recipe-image-lightbox";
        lightbox.setAttribute("aria-hidden", "true");
        lightbox.innerHTML = `
            <div class="recipe-image-lightbox-content"
                 role="dialog"
                 aria-modal="true"
                 aria-label="Enlarged recipe image">
                <button type="button" class="recipe-image-lightbox-close">Close</button>
                <img id="recipeImageLightboxImage" alt="">
            </div>
        `;
        lightbox.addEventListener("click", (event) => {
            if (
                event.target === lightbox
                || event.target.classList.contains("recipe-image-lightbox-content")
            ) {
                closeMasterDataImageLightbox();
            }
        });
        const closeButton = lightbox.querySelector(".recipe-image-lightbox-close");
        if (closeButton) {
            closeButton.addEventListener("click", closeMasterDataImageLightbox);
        }
        document.body.appendChild(lightbox);

        return lightbox;
    }

    function openMasterDataImageLightbox(image) {
        if (!image || !(image.dataset.fullSrc || image.currentSrc || image.src)) {
            return;
        }

        const lightbox = ensureMasterDataImageLightbox();
        const lightboxImage = document.getElementById("recipeImageLightboxImage");

        if (!lightboxImage) {
            return;
        }

        lightboxImage.src = image.dataset.fullSrc || image.currentSrc || image.src;
        lightboxImage.alt = image.alt || "Recipe image";
        lightbox.classList.add("open");
        lightbox.setAttribute("aria-hidden", "false");
        document.body.classList.add("image-lightbox-open");

        const closeButton = lightbox.querySelector(".recipe-image-lightbox-close");
        if (closeButton) {
            closeButton.focus({ preventScroll: true });
        }
    }

    function closeMasterDataImageLightbox() {
        const lightbox = document.getElementById("recipeImageLightbox");
        const lightboxImage = document.getElementById("recipeImageLightboxImage");

        if (!lightbox) {
            return;
        }

        lightbox.classList.remove("open");
        lightbox.setAttribute("aria-hidden", "true");
        document.body.classList.remove("image-lightbox-open");

        if (lightboxImage) {
            lightboxImage.removeAttribute("src");
            lightboxImage.alt = "";
        }
    }

    function decorateMasterDataLightboxImages(root = document) {
        const scope = root && typeof root.querySelectorAll === "function" ? root : document;
        scope.querySelectorAll(masterDataLightboxImageSelector()).forEach((image) => {
            image.tabIndex = 0;
            image.setAttribute("role", "button");
            image.setAttribute("aria-label", `Enlarge ${image.alt || "recipe image"}`);
        });
    }

    function initMasterDataImageLightbox() {
        decorateMasterDataLightboxImages(document);
        document.addEventListener("click", (event) => {
            const image = event.target && event.target.closest
                ? event.target.closest(masterDataLightboxImageSelector())
                : null;
            if (!image) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            openMasterDataImageLightbox(image);
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeMasterDataImageLightbox();
                return;
            }

            const image = event.target && event.target.closest
                ? event.target.closest(masterDataLightboxImageSelector())
                : null;
            if (!image || (event.key !== "Enter" && event.key !== " ")) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            openMasterDataImageLightbox(image);
        });
    }

    function query(form, selector) {
        const root = form.closest(".master-data-page") || document;
        return root.querySelector(selector);
    }

    function filterFormFor(form) {
        const root = form.closest(".master-data-page") || document;
        return root.querySelector(".master-data-filter-form");
    }

    function setNamedFormValue(form, name, value) {
        let field = form.querySelector(`[name="${name}"]`);
        if (!field) {
            field = document.createElement("input");
            field.type = "hidden";
            field.name = name;
            form.appendChild(field);
        }
        field.value = value;
    }

    function filterRedirectUrl(filterForm) {
        const url = new URL(filterForm.getAttribute("action") || window.location.href, window.location.href);
        const formData = new FormData(filterForm);
        for (const [name, rawValue] of formData.entries()) {
            const value = text(rawValue).trim();
            if (value) {
                url.searchParams.set(name, value);
            } else {
                url.searchParams.delete(name);
            }
        }
        return `${url.pathname}${url.search}${url.hash}`;
    }

    function syncImageFormFromFilters(form) {
        const filterForm = filterFormFor(form);
        if (!filterForm || !window.FormData) {
            return;
        }

        const formData = new FormData(filterForm);
        const scope = text(formData.get("scope") || "mine").trim() || "mine";
        const userId = scope === "user" ? text(formData.get("user_id")).trim() : "";
        const search = text(formData.get("search")).trim();
        const redirectUrl = filterRedirectUrl(filterForm);

        setNamedFormValue(form, "scope", scope);
        setNamedFormValue(form, "user_id", userId);
        setNamedFormValue(form, "search", search);
        setNamedFormValue(form, "redirect_url", redirectUrl);
        form.dataset.imageRedirectUrl = redirectUrl;
    }

    function elementsFor(form) {
        const panel = query(form, "[data-master-backfill-progress]");
        return {
            panel,
            summary: panel && panel.querySelector("[data-master-backfill-summary]"),
            state: panel && panel.querySelector("[data-master-backfill-state]"),
            bar: panel && panel.querySelector("[data-master-backfill-bar]"),
            users: panel && panel.querySelector("[data-master-backfill-users]"),
            recipes: panel && panel.querySelector("[data-master-backfill-recipes]"),
            ingredients: panel && panel.querySelector("[data-master-backfill-ingredients]"),
            equipment: panel && panel.querySelector("[data-master-backfill-equipment]"),
            current: panel && panel.querySelector("[data-master-backfill-current]"),
            currentTitle: panel && panel.querySelector("[data-master-backfill-current-title]"),
            currentUrl: panel && panel.querySelector("[data-master-backfill-current-url]"),
            items: panel && panel.querySelector("[data-master-backfill-items]"),
        };
    }

    function imageElementsFor(form) {
        const panel = query(form, "[data-master-image-progress]");
        return {
            panel,
            summary: panel && panel.querySelector("[data-master-image-summary]"),
            state: panel && panel.querySelector("[data-master-image-state]"),
            bar: panel && panel.querySelector("[data-master-image-bar]"),
            total: panel && panel.querySelector("[data-master-image-total]"),
            complete: panel && panel.querySelector("[data-master-image-complete]"),
            generated: panel && panel.querySelector("[data-master-image-generated]"),
            failed: panel && panel.querySelector("[data-master-image-failed]"),
            current: panel && panel.querySelector("[data-master-image-current]"),
            currentTitle: panel && panel.querySelector("[data-master-image-current-title]"),
            currentMeta: panel && panel.querySelector("[data-master-image-current-meta]"),
            items: panel && panel.querySelector("[data-master-image-items]"),
        };
    }

    function setBusy(form, busy) {
        const submit = form.querySelector("[data-master-backfill-submit]");
        form.setAttribute("aria-busy", busy ? "true" : "false");
        Array.from(form.elements).forEach((element) => {
            element.disabled = busy;
        });
        if (submit) {
            submit.textContent = busy ? "Running..." : "Run Backfill";
        }
    }

    function setImageBusy(form, busy) {
        const submit = form.querySelector("[data-master-image-submit]");
        form.setAttribute("aria-busy", busy ? "true" : "false");
        Array.from(form.elements).forEach((element) => {
            element.disabled = busy;
        });
        if (submit) {
            submit.textContent = busy ? "Generating..." : "Generate Missing Images";
        }
    }

    function renderStarting(form) {
        const els = elementsFor(form);
        if (!els.panel) {
            return;
        }
        els.panel.hidden = false;
        els.panel.setAttribute("aria-busy", "true");
        if (els.summary) {
            els.summary.textContent = "Submitting backfill and preparing recipe list.";
        }
        if (els.state) {
            els.state.className = "master-data-backfill-state running";
            els.state.textContent = "Starting";
        }
        if (els.bar) {
            els.bar.style.width = "6%";
        }
        if (els.users) {
            els.users.textContent = "0 / 0";
        }
        if (els.recipes) {
            els.recipes.textContent = "0 / 0";
        }
        if (els.ingredients) {
            els.ingredients.textContent = "0";
        }
        if (els.equipment) {
            els.equipment.textContent = "0";
        }
        if (els.current) {
            els.current.hidden = true;
        }
        if (els.items) {
            els.items.replaceChildren();
        }
    }

    function renderProgressItem(item) {
        const row = document.createElement("li");
        row.className = "master-data-backfill-item";

        const main = document.createElement("div");
        main.className = "master-data-backfill-item-main";

        const title = document.createElement("div");
        title.className = "master-data-backfill-item-title";
        title.textContent = text(item.label || item.recipe_url || "Recipe");
        main.appendChild(title);

        const metaParts = [];
        if (item.user_id) {
            metaParts.push(`User: ${item.user_id}`);
        }
        if (item.recipe_url) {
            metaParts.push(item.recipe_url);
        }
        const ingredientCount = Number(item.ingredient_count) || 0;
        const equipmentCount = Number(item.equipment_count) || 0;
        if (ingredientCount || equipmentCount) {
            metaParts.push(`${ingredientCount} ingredient links, ${equipmentCount} equipment links`);
        }
        if (item.error) {
            metaParts.push(item.error);
        }
        const meta = document.createElement("div");
        meta.className = "master-data-backfill-item-meta";
        meta.textContent = metaParts.join(" | ");
        main.appendChild(meta);

        const state = document.createElement("span");
        const status = text(item.state || "waiting").toLowerCase();
        state.className = `master-data-backfill-item-state ${status}`;
        state.textContent = stateLabel(status);

        row.append(main, state);
        return row;
    }

    function renderImageProgressItem(item) {
        const row = document.createElement("li");
        row.className = "master-data-backfill-item";

        const main = document.createElement("div");
        main.className = "master-data-backfill-item-main";

        const title = document.createElement("div");
        title.className = "master-data-backfill-item-title";
        title.textContent = text(item.name || "Ingredient");
        main.appendChild(title);

        const metaParts = [];
        if (item.user_id) {
            metaParts.push(`User: ${item.user_id}`);
        }
        if (item.image_url) {
            metaParts.push(item.image_url);
        }
        if (item.error) {
            metaParts.push(item.error);
        }
        const meta = document.createElement("div");
        meta.className = "master-data-backfill-item-meta";
        meta.textContent = metaParts.join(" | ");
        main.appendChild(meta);

        const state = document.createElement("span");
        const status = text(item.state || "waiting").toLowerCase();
        state.className = `master-data-backfill-item-state ${status}`;
        state.textContent = stateLabel(status);

        row.append(main, state);
        return row;
    }

    function referenceRowForButton(button) {
        const rowId = button && button.getAttribute("aria-controls");
        return rowId ? document.getElementById(rowId) : null;
    }

    function panelForReferenceRow(row) {
        return row ? row.querySelector("[data-master-reference-panel]") : null;
    }

    function setReferenceLoading(panel) {
        if (!panel) {
            return;
        }
        panel.replaceChildren();
        const message = document.createElement("div");
        message.className = "master-data-reference-placeholder";
        message.textContent = "Loading recipe references...";
        panel.appendChild(message);
    }

    function setReferenceError(panel, message) {
        if (!panel) {
            return;
        }
        panel.replaceChildren();
        const error = document.createElement("div");
        error.className = "master-data-reference-error";
        error.textContent = message || "Recipe references could not be loaded.";
        panel.appendChild(error);
    }

    function referenceDetailText(reference) {
        const details = [];
        const amount = [reference.quantity, reference.unit].map(text).filter(Boolean).join(" ");
        if (amount) {
            details.push(amount);
        }
        if (reference.buy_as) {
            details.push(`Buy as: ${reference.buy_as}`);
        }
        if (reference.store_section) {
            details.push(reference.store_section);
        }
        if (reference.original_recipe_text) {
            details.push(reference.original_recipe_text);
        }
        if (reference.optional) {
            details.push("Optional");
        }
        return details.join(" | ");
    }

    function renderReferenceItem(reference) {
        const item = document.createElement("article");
        item.className = "master-data-reference-item";

        const main = document.createElement("div");
        main.className = "master-data-reference-main";

        const titleRow = document.createElement("div");
        titleRow.className = "master-data-reference-title-row";

        const recipeImageUrl = text(reference.recipe_image_url || "");
        if (recipeImageUrl) {
            titleRow.classList.add("has-title-image");
            const image = document.createElement("img");
            image.className = "master-data-reference-title-image";
            image.src = recipeImageUrl;
            image.dataset.fullSrc = text(reference.recipe_image_full_url || recipeImageUrl);
            image.alt = text(reference.recipe_image_alt || reference.recipe_title || "Recipe image");
            image.loading = "lazy";
            const srcset = text(reference.recipe_image_srcset || "");
            if (srcset) {
                image.srcset = srcset;
                image.sizes = `${masterDataThumbnailSize}px`;
            }
            titleRow.appendChild(image);
        }

        const copy = document.createElement("div");
        copy.className = "master-data-reference-copy";

        const title = document.createElement("strong");
        title.textContent = text(reference.recipe_title || reference.recipe_id || "Recipe");
        copy.appendChild(title);

        const detail = document.createElement("div");
        detail.className = "master-data-reference-detail";
        detail.textContent = referenceDetailText(reference) || text(reference.recipe_id || "");
        copy.appendChild(detail);

        const recipeId = text(reference.recipe_id || "");
        if (recipeId) {
            const code = document.createElement("code");
            code.textContent = recipeId;
            copy.appendChild(code);
        }

        titleRow.appendChild(copy);
        main.appendChild(titleRow);

        item.appendChild(main);

        if (reference.edit_url) {
            const link = document.createElement("a");
            link.className = "master-data-reference-link";
            link.href = reference.edit_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = "Open Recipe";
            item.appendChild(link);
        }

        return item;
    }

    function renderReferences(panel, data) {
        if (!panel) {
            return;
        }
        panel.replaceChildren();

        const references = Array.isArray(data && data.references) ? data.references : [];
        const total = Number(data && data.total) || references.length;

        const header = document.createElement("div");
        header.className = "master-data-reference-header";

        const title = document.createElement("strong");
        const recordName = text(data && data.record && data.record.name);
        title.textContent = `${recordName || "Record"} is used by ${total} recipe${total === 1 ? "" : "s"}`;
        header.appendChild(title);

        if (total > references.length) {
            const note = document.createElement("span");
            note.textContent = `Showing first ${references.length}.`;
            header.appendChild(note);
        }

        panel.appendChild(header);

        if (!references.length) {
            const empty = document.createElement("div");
            empty.className = "master-data-reference-placeholder";
            empty.textContent = "No recipe references were found for this record.";
            panel.appendChild(empty);
            return;
        }

        const list = document.createElement("div");
        list.className = "master-data-reference-list";
        references.forEach((reference) => {
            list.appendChild(renderReferenceItem(reference || {}));
        });
        panel.appendChild(list);
        decorateMasterDataLightboxImages(panel);
    }

    function closeOtherReferenceRows(activeButton) {
        document.querySelectorAll("[data-master-reference-toggle]").forEach((button) => {
            if (button === activeButton) {
                return;
            }
            button.setAttribute("aria-expanded", "false");
            const row = referenceRowForButton(button);
            if (row) {
                row.hidden = true;
            }
        });
    }

    async function toggleReferenceRow(button) {
        if (!button) {
            return;
        }

        const row = referenceRowForButton(button);
        const panel = panelForReferenceRow(row);
        if (!row || !panel) {
            return;
        }

        const isExpanded = button.getAttribute("aria-expanded") === "true";
        if (isExpanded) {
            button.setAttribute("aria-expanded", "false");
            row.hidden = true;
            return;
        }

        closeOtherReferenceRows(button);
        button.setAttribute("aria-expanded", "true");
        row.hidden = false;

        if (row.dataset.loaded === "true") {
            return;
        }

        const referenceUrl = button.dataset.referenceUrl;
        if (!referenceUrl || !window.fetch) {
            setReferenceError(panel, "Recipe references are not available in this browser.");
            return;
        }

        setReferenceLoading(panel);
        try {
            const response = await fetch(referenceUrl, {
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "fetch",
                },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                setReferenceError(panel, data.error || data.message || "Recipe references could not be loaded.");
                return;
            }
            renderReferences(panel, data);
            row.dataset.loaded = "true";
        } catch (error) {
            setReferenceError(panel, error && error.message ? error.message : "Recipe references could not be loaded.");
        }
    }

    function initMasterDataReferences() {
        document.addEventListener("click", (event) => {
            const target = event.target && event.target.closest ? event.target : null;
            const button = target ? target.closest("[data-master-reference-toggle]") : null;
            if (!button) {
                return;
            }
            event.preventDefault();
            toggleReferenceRow(button);
        });
    }

    function masterDataStoreSectionForms(root = document) {
        const scope = root && typeof root.querySelectorAll === "function" ? root : document;
        return Array.from(scope.querySelectorAll("[data-master-store-section-form]"));
    }

    function storeSectionSelectFor(form) {
        return form && form.elements ? form.elements.namedItem("store_section") : null;
    }

    function masterDataRecordFields(form) {
        return form && form.elements
            ? Array.from(form.elements).filter((field) => field.matches && field.matches("[data-master-record-field]"))
            : [];
    }

    function originalMasterRecordFieldValue(field) {
        return text(field && field.dataset ? field.dataset.originalValue : "").trim();
    }

    function currentMasterRecordFieldValue(field) {
        return text(field ? field.value : "").trim();
    }

    function originalStoreSectionValue(select) {
        return text(select && select.dataset ? select.dataset.originalStoreSection : "").trim();
    }

    function currentStoreSectionValue(select) {
        return text(select ? select.value : "").trim();
    }

    function storeSectionFormIsDirty(form) {
        return masterDataRecordFields(form).some((field) => (
            currentMasterRecordFieldValue(field) !== originalMasterRecordFieldValue(field)
        ));
    }

    function updateStoreSectionFormState(form) {
        const row = form && form.closest ? form.closest(".master-data-record-row") : null;
        const dirty = storeSectionFormIsDirty(form);
        form.classList.toggle("master-data-store-section-form-dirty", dirty);
        if (row) {
            row.classList.toggle("master-data-record-row-dirty", dirty);
            if (dirty) {
                row.classList.remove("master-data-record-row-saved");
            }
        }
        return dirty;
    }

    function changedStoreSectionForms() {
        return masterDataStoreSectionForms().filter((form) => updateStoreSectionFormState(form));
    }

    function storeSectionPanelElements() {
        const panel = document.querySelector("[data-master-store-section-panel]");
        return {
            panel,
            summary: panel && panel.querySelector("[data-master-store-section-summary]"),
            detail: panel && panel.querySelector("[data-master-store-section-detail]"),
            button: panel && panel.querySelector("[data-master-store-section-save]"),
        };
    }

    function setStoreSectionPanelMessage(summary, detail) {
        const els = storeSectionPanelElements();
        if (els.summary) {
            els.summary.textContent = summary;
        }
        if (els.detail) {
            els.detail.textContent = detail;
        }
    }

    function updateStoreSectionSavePanel() {
        const els = storeSectionPanelElements();
        if (!els.panel) {
            return;
        }

        const changedForms = changedStoreSectionForms();
        const count = changedForms.length;
        els.panel.classList.toggle("has-changes", count > 0);
        els.panel.classList.remove("has-error", "is-saving");
        els.panel.setAttribute("aria-busy", "false");

        if (els.button) {
            els.button.disabled = count === 0;
            els.button.textContent = count > 0
                ? `Save ${count} Change${count === 1 ? "" : "s"}`
                : "Save Changes";
        }

        if (count > 0) {
            setStoreSectionPanelMessage(
                `${count} unsaved ingredient change${count === 1 ? "" : "s"}`,
                "Save once after editing names, normalized names, or store sections on this page."
            );
        } else {
            setStoreSectionPanelMessage(
                "No ingredient changes",
                "Edit ingredient names, normalized names, or store sections, then save all pending changes here."
            );
        }
    }

    function setStoreSectionSaveBusy(busy) {
        const els = storeSectionPanelElements();
        if (els.panel) {
            els.panel.classList.toggle("is-saving", busy);
            els.panel.setAttribute("aria-busy", busy ? "true" : "false");
        }
        if (els.button) {
            const changedCount = changedStoreSectionForms().length;
            els.button.disabled = busy || changedCount === 0;
            els.button.textContent = busy
                ? "Saving..."
                : changedCount > 0
                    ? `Save ${changedCount} Change${changedCount === 1 ? "" : "s"}`
                    : "Save Changes";
        }
        masterDataStoreSectionForms().forEach((form) => {
            masterDataRecordFields(form).forEach((field) => {
                field.disabled = busy;
            });
        });
    }

    async function submitStoreSectionForm(form) {
        if (typeof form.reportValidity === "function" && !form.reportValidity()) {
            throw new Error("Complete the ingredient name and normalized name before saving.");
        }
        const response = await fetch(form.action, {
            method: form.method || "POST",
            body: new FormData(form),
            headers: {
                Accept: "application/json",
                "X-Requested-With": "fetch",
            },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok === false || data.success === false) {
            throw new Error(data.message || data.error || "Store section could not be saved.");
        }
        return data;
    }

    async function saveChangedStoreSections(event) {
        if (event) {
            event.preventDefault();
        }

        let forms = changedStoreSectionForms();
        if (!forms.length) {
            updateStoreSectionSavePanel();
            return;
        }

        if (!window.fetch || !window.FormData) {
            forms[0].submit();
            return;
        }

        const invalidForm = forms.find((form) => (
            typeof form.checkValidity === "function" && !form.checkValidity()
        ));
        if (invalidForm) {
            if (typeof invalidForm.reportValidity === "function") invalidForm.reportValidity();
            setStoreSectionPanelMessage(
                "Complete required ingredient fields",
                "Every changed record needs an ingredient name and normalized name."
            );
            return;
        }

        setStoreSectionSaveBusy(true);
        setStoreSectionPanelMessage(
            `Saving ${forms.length} ingredient change${forms.length === 1 ? "" : "s"}...`,
            "Please keep this page open while the updates finish."
        );

        let savedCount = 0;
        const failures = [];
        for (const form of forms) {
            const select = storeSectionSelectFor(form);
            const row = form.closest(".master-data-record-row");
            try {
                await submitStoreSectionForm(form);
                masterDataRecordFields(form).forEach((field) => {
                    field.dataset.originalValue = currentMasterRecordFieldValue(field);
                });
                if (select) select.dataset.originalStoreSection = currentStoreSectionValue(select);
                form.classList.remove("master-data-store-section-form-dirty");
                if (row) {
                    row.classList.remove("master-data-record-row-dirty", "master-data-record-row-error");
                    row.classList.add("master-data-record-row-saved");
                }
                savedCount += 1;
            } catch (error) {
                failures.push(error && error.message ? error.message : "Store section could not be saved.");
                if (row) {
                    row.classList.add("master-data-record-row-error");
                }
            }
        }

        setStoreSectionSaveBusy(false);

        const els = storeSectionPanelElements();
        if (failures.length) {
            if (els.panel) {
                els.panel.classList.add("has-error");
            }
            setStoreSectionPanelMessage(
                `${savedCount} saved, ${failures.length} failed`,
                failures[0]
            );
            return;
        }

        setStoreSectionPanelMessage(
            `${savedCount} ingredient change${savedCount === 1 ? "" : "s"} saved`,
            "Refreshing the table so groups and filters stay up to date."
        );

        window.setTimeout(() => {
            window.location.assign(window.location.href);
        }, 700);
    }

    function initMasterDataStoreSectionBatchSave() {
        const forms = masterDataStoreSectionForms();
        if (!forms.length) {
            return;
        }

        forms.forEach((form) => {
            const select = storeSectionSelectFor(form);
            if (select && !select.dataset.originalStoreSection) {
                select.dataset.originalStoreSection = currentStoreSectionValue(select);
            }
            masterDataRecordFields(form).forEach((field) => {
                if (!Object.prototype.hasOwnProperty.call(field.dataset, "originalValue")) {
                    field.dataset.originalValue = currentMasterRecordFieldValue(field);
                }
            });
            form.addEventListener("submit", saveChangedStoreSections);
            form.addEventListener("change", updateStoreSectionSavePanel);
            form.addEventListener("input", updateStoreSectionSavePanel);
            updateStoreSectionFormState(form);
        });

        const els = storeSectionPanelElements();
        if (els.button) {
            els.button.addEventListener("click", saveChangedStoreSections);
        }
        updateStoreSectionSavePanel();
    }

    function masterDataMergeElements() {
        const dialog = document.querySelector("[data-master-merge-dialog]");
        const form = dialog && dialog.querySelector("[data-master-merge-form]");
        return {
            dialog,
            form,
            search: dialog && dialog.querySelector("[data-master-merge-search]"),
            results: dialog && dialog.querySelector("[data-master-merge-results]"),
            targetId: form && form.querySelector("[data-master-merge-target-id]"),
            sourceName: dialog && dialog.querySelector("[data-master-merge-source-name]"),
            sourceNormalized: dialog && dialog.querySelector("[data-master-merge-source-normalized]"),
            sourceUsage: dialog && dialog.querySelector("[data-master-merge-source-usage]"),
            selection: dialog && dialog.querySelector("[data-master-merge-selection]"),
            targetName: dialog && dialog.querySelector("[data-master-merge-target-name]"),
            combinedUsage: dialog && dialog.querySelector("[data-master-merge-combined-usage]"),
            error: dialog && dialog.querySelector("[data-master-merge-error]"),
            submit: form && form.querySelector("[data-master-merge-submit]"),
        };
    }

    function masterDataMergeUsageLabel(count) {
        const usageCount = Math.max(0, Number(count) || 0);
        return `${usageCount} recipe reference${usageCount === 1 ? "" : "s"}`;
    }

    function setMasterDataMergeError(message = "") {
        const els = masterDataMergeElements();
        if (!els.error) {
            return;
        }
        els.error.textContent = text(message).trim();
        els.error.hidden = !els.error.textContent;
    }

    function setMasterDataMergeBusy(busy) {
        const els = masterDataMergeElements();
        if (els.dialog) {
            els.dialog.setAttribute("aria-busy", busy ? "true" : "false");
        }
        if (els.search) {
            els.search.disabled = busy;
        }
        if (els.submit) {
            els.submit.disabled = busy || !(els.targetId && els.targetId.value);
            els.submit.textContent = busy ? "Merging..." : "Merge ingredient";
        }
        if (els.results) {
            els.results.querySelectorAll("button").forEach((button) => {
                button.disabled = busy;
            });
        }
    }

    function resetMasterDataMergeSelection() {
        const els = masterDataMergeElements();
        if (els.targetId) els.targetId.value = "";
        if (els.targetName) els.targetName.textContent = "";
        if (els.combinedUsage) els.combinedUsage.textContent = "";
        if (els.selection) els.selection.hidden = true;
        if (els.submit) els.submit.disabled = true;
        if (els.results) {
            els.results.querySelectorAll("[role=\"option\"]").forEach((option) => {
                option.setAttribute("aria-selected", "false");
            });
        }
    }

    function chooseMasterDataMergeTarget(button) {
        const els = masterDataMergeElements();
        if (!button || !els.targetId) {
            return;
        }
        const targetId = text(button.dataset.ingredientId).trim();
        const targetName = text(button.dataset.ingredientName).trim();
        const targetUsage = Math.max(0, Number(button.dataset.usageCount) || 0);
        const sourceUsage = Math.max(0, Number(els.dialog && els.dialog.dataset.sourceUsageCount) || 0);
        els.targetId.value = targetId;
        if (els.targetName) els.targetName.textContent = targetName;
        if (els.combinedUsage) {
            els.combinedUsage.textContent = `${masterDataMergeUsageLabel(sourceUsage + targetUsage)} after merge`;
        }
        if (els.selection) els.selection.hidden = false;
        if (els.submit) els.submit.disabled = !targetId;
        if (els.results) {
            els.results.querySelectorAll("[role=\"option\"]").forEach((option) => {
                option.setAttribute("aria-selected", option === button ? "true" : "false");
            });
        }
        setMasterDataMergeError("");
    }

    function masterDataMergeOptionButton(ingredient) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "master-data-merge-option";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        button.dataset.ingredientId = text(ingredient.ingredient_id);
        button.dataset.ingredientName = text(ingredient.name);
        button.dataset.usageCount = text(ingredient.usage_count || 0);

        const media = document.createElement("span");
        media.className = "master-data-merge-option-media";
        if (ingredient.image_url) {
            const image = document.createElement("img");
            image.src = text(ingredient.image_url);
            image.alt = "";
            media.appendChild(image);
        } else {
            media.textContent = "—";
        }

        const copy = document.createElement("span");
        copy.className = "master-data-merge-option-copy";
        const name = document.createElement("strong");
        name.textContent = text(ingredient.name);
        const detail = document.createElement("span");
        const aliases = Array.isArray(ingredient.aliases) && ingredient.aliases.length
            ? ` · aliases: ${ingredient.aliases.join(", ")}`
            : "";
        detail.textContent = `${text(ingredient.normalized_name)} · ${text(ingredient.store_section)}${aliases}`;
        copy.append(name, detail);

        const usage = document.createElement("span");
        usage.className = "master-data-merge-option-usage";
        usage.textContent = masterDataMergeUsageLabel(ingredient.usage_count);
        button.append(media, copy, usage);
        button.addEventListener("click", () => chooseMasterDataMergeTarget(button));
        return button;
    }

    function renderMasterDataMergeOptions(ingredients, message = "") {
        const els = masterDataMergeElements();
        if (!els.results) {
            return;
        }
        els.results.replaceChildren();
        resetMasterDataMergeSelection();
        const rows = Array.isArray(ingredients) ? ingredients : [];
        if (!rows.length) {
            const empty = document.createElement("div");
            empty.className = "master-data-merge-empty";
            empty.textContent = message || "No other master ingredients match this search.";
            els.results.appendChild(empty);
            return;
        }
        rows.forEach((ingredient) => {
            els.results.appendChild(masterDataMergeOptionButton(ingredient));
        });
    }

    async function loadMasterDataMergeOptions(options = {}) {
        const els = masterDataMergeElements();
        const optionsUrl = text(els.dialog && els.dialog.dataset.mergeOptionsUrl).trim();
        if (!els.dialog || !els.search || !els.results || !optionsUrl) {
            return;
        }

        window.clearTimeout(masterDataMergeSearchTimer);
        const delay = options.immediate ? 0 : 180;
        masterDataMergeSearchTimer = window.setTimeout(async () => {
            const requestId = ++masterDataMergeRequestId;
            const queryValue = text(els.search.value).trim();
            renderMasterDataMergeOptions([], "Loading canonical ingredients...");
            setMasterDataMergeError("");
            try {
                const params = new URLSearchParams({ search: queryValue, limit: "20" });
                const response = await fetch(`${optionsUrl}?${params.toString()}`, {
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "fetch",
                    },
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.ok === false || data.success === false) {
                    throw new Error(data.error || "Canonical ingredients could not be loaded.");
                }
                if (requestId !== masterDataMergeRequestId || !els.dialog.open) {
                    return;
                }
                renderMasterDataMergeOptions(
                    data.ingredients,
                    queryValue
                        ? `No master ingredients match “${queryValue}”.`
                        : "No other master ingredients are available in this workspace."
                );
            } catch (error) {
                if (requestId === masterDataMergeRequestId) {
                    renderMasterDataMergeOptions([], "Canonical ingredients could not be loaded.");
                    setMasterDataMergeError(
                        error && error.message ? error.message : "Canonical ingredients could not be loaded."
                    );
                }
            }
        }, delay);
    }

    function closeMasterDataMergeDialog() {
        const els = masterDataMergeElements();
        window.clearTimeout(masterDataMergeSearchTimer);
        masterDataMergeRequestId += 1;
        if (els.dialog) {
            if (typeof els.dialog.close === "function" && els.dialog.open) {
                els.dialog.close();
            } else {
                els.dialog.removeAttribute("open");
            }
            els.dialog.removeAttribute("aria-busy");
            delete els.dialog.dataset.mergeOptionsUrl;
            delete els.dialog.dataset.sourceUsageCount;
        }
        if (els.form) els.form.action = "";
        if (els.search) els.search.value = "";
        if (els.results) els.results.replaceChildren();
        resetMasterDataMergeSelection();
        setMasterDataMergeError("");
        setMasterDataMergeBusy(false);
        if (masterDataMergeReturnFocus && masterDataMergeReturnFocus.isConnected) {
            masterDataMergeReturnFocus.focus({ preventScroll: true });
        }
        masterDataMergeReturnFocus = null;
    }

    function openMasterDataMergeDialog(button) {
        const els = masterDataMergeElements();
        if (!button || !els.dialog || !els.form || !els.search) {
            return;
        }
        if (changedStoreSectionForms().length) {
            setStoreSectionPanelMessage(
                "Save ingredient changes before merging",
                "Merging refreshes this page, so save the pending name or store-section edits first."
            );
            const panel = document.querySelector("[data-master-store-section-panel]");
            if (panel) panel.scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }

        masterDataMergeReturnFocus = button;
        els.form.action = text(button.dataset.mergeUrl);
        els.dialog.dataset.mergeOptionsUrl = text(button.dataset.mergeOptionsUrl);
        els.dialog.dataset.sourceUsageCount = text(button.dataset.sourceUsageCount || 0);
        if (els.sourceName) els.sourceName.textContent = text(button.dataset.sourceName);
        if (els.sourceNormalized) els.sourceNormalized.textContent = text(button.dataset.sourceNormalizedName);
        if (els.sourceUsage) {
            els.sourceUsage.textContent = masterDataMergeUsageLabel(button.dataset.sourceUsageCount);
        }
        els.search.value = "";
        resetMasterDataMergeSelection();
        setMasterDataMergeError("");
        setMasterDataMergeBusy(false);
        if (typeof els.dialog.showModal === "function") {
            els.dialog.showModal();
        } else {
            els.dialog.setAttribute("open", "");
        }
        els.search.focus({ preventScroll: true });
        void loadMasterDataMergeOptions({ immediate: true });
    }

    async function submitMasterDataMerge(event) {
        event.preventDefault();
        const els = masterDataMergeElements();
        if (!els.form || !els.targetId || !els.targetId.value) {
            setMasterDataMergeError("Choose the canonical ingredient first.");
            return;
        }
        setMasterDataMergeBusy(true);
        setMasterDataMergeError("");
        try {
            const response = await fetch(els.form.action, {
                method: els.form.method || "POST",
                body: new FormData(els.form),
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "fetch",
                },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false || data.success === false) {
                throw new Error(data.message || data.error || "Ingredient records could not be merged.");
            }
            if (els.selection) els.selection.classList.add("is-complete");
            if (els.combinedUsage) els.combinedUsage.textContent = data.message || "Ingredient merge complete.";
            try {
                if (window.localStorage) {
                    window.localStorage.setItem(
                        INGREDIENT_MASTER_DATA_VERSION_STORAGE_KEY,
                        String(Date.now())
                    );
                }
            } catch (storageError) {
                console.debug("Unable to notify other tabs about the ingredient merge.", storageError);
            }
            window.setTimeout(() => {
                window.location.assign(data.redirect_url || window.location.href);
            }, 650);
        } catch (error) {
            setMasterDataMergeBusy(false);
            setMasterDataMergeError(
                error && error.message ? error.message : "Ingredient records could not be merged."
            );
        }
    }

    function initMasterDataIngredientMerge() {
        const els = masterDataMergeElements();
        if (!els.dialog || !els.form) {
            return;
        }
        document.addEventListener("click", (event) => {
            const target = event.target && event.target.closest ? event.target : null;
            const openButton = target && target.closest("[data-master-merge-open]");
            const closeButton = target && target.closest("[data-master-merge-close]");
            if (openButton) {
                event.preventDefault();
                openMasterDataMergeDialog(openButton);
            } else if (closeButton) {
                event.preventDefault();
                closeMasterDataMergeDialog();
            }
        });
        if (els.search) {
            els.search.addEventListener("input", () => {
                void loadMasterDataMergeOptions();
            });
            els.search.addEventListener("keydown", (event) => {
                if (event.key === "ArrowDown" && els.results) {
                    const firstOption = els.results.querySelector("[role=\"option\"]");
                    if (firstOption) {
                        event.preventDefault();
                        firstOption.focus();
                    }
                }
            });
        }
        els.form.addEventListener("submit", submitMasterDataMerge);
        els.dialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            closeMasterDataMergeDialog();
        });
    }

    function masterDataDuplicateElements() {
        const panel = document.querySelector("[data-master-duplicate-review]");
        return {
            panel,
            scan: panel && panel.querySelector("[data-master-duplicate-scan]"),
            scanButtons: panel ? panel.querySelectorAll(
                "[data-master-duplicate-scan], [data-master-duplicate-toolbar-scan]"
            ) : [],
            status: panel && panel.querySelector("[data-master-duplicate-status]"),
            list: panel && panel.querySelector("[data-master-duplicate-list]"),
            toolbar: panel && panel.querySelector("[data-master-duplicate-toolbar]"),
            selectionCount: panel && panel.querySelector("[data-master-duplicate-selection-count]"),
            selectHighConfidence: panel && panel.querySelector("[data-master-duplicate-select-high-confidence]"),
            selectAll: panel && panel.querySelector("[data-master-duplicate-select-all]"),
            selectNone: panel && panel.querySelector("[data-master-duplicate-select-none]"),
            bulkActions: panel ? panel.querySelectorAll("[data-master-duplicate-bulk-action]") : [],
            reviewHistoryButtons: panel ? panel.querySelectorAll(
                "[data-master-duplicate-review-history], [data-master-duplicate-toolbar-review-history]"
            ) : [],
            undoMerge: panel && panel.querySelector("[data-master-duplicate-undo-merge]"),
            undoMergeButtons: panel ? panel.querySelectorAll(
                "[data-master-duplicate-undo-merge], [data-master-duplicate-toolbar-undo-merge]"
            ) : [],
            undoSummary: panel && panel.querySelector("[data-master-duplicate-undo-summary]"),
        };
    }

    function formatMasterDataDuplicateScanTime(value) {
        const date = new Date(text(value));
        if (Number.isNaN(date.getTime())) return "";
        return date.toLocaleString([], {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
        });
    }

    function masterDataDuplicateScanSuffix(scan) {
        const label = formatMasterDataDuplicateScanTime(scan && scan.scanned_at);
        return label ? ` Last scanned ${label}.` : "";
    }

    function updateMasterDataDuplicateScanState(scan) {
        const els = masterDataDuplicateElements();
        if (!els.panel || !scan || !scan.scanned_at) return;
        els.panel.dataset.lastScanAt = text(scan.scanned_at);
        if (els.panel.getAttribute("aria-busy") !== "true") {
            Array.from(els.scanButtons || []).forEach((button) => {
                button.textContent = "Rescan Potential Duplicates";
            });
        }
    }

    function setMasterDataDuplicateBusy(busy, message = "") {
        const els = masterDataDuplicateElements();
        if (!els.panel) return;
        els.panel.setAttribute("aria-busy", busy ? "true" : "false");
        Array.from(els.scanButtons || []).forEach((button) => {
            button.disabled = busy || els.panel.dataset.scope === "all";
            button.textContent = busy
                ? "Reviewing ingredient pairs..."
                : (els.panel.dataset.lastScanAt ? "Rescan Potential Duplicates" : "Find Potential Duplicates");
        });
        Array.from(els.undoMergeButtons || []).forEach((button) => {
            button.disabled = busy
                || els.panel.dataset.scope === "all"
                || button.dataset.undoAvailable !== "true";
        });
        Array.from(els.reviewHistoryButtons || []).forEach((button) => {
            button.disabled = busy || els.panel.dataset.scope === "all";
        });
        masterDataDuplicateCards().forEach((card) => {
            card.querySelectorAll("button").forEach((button) => {
                const blockedMerge = card.dataset.mergeBlocked === "true"
                    && button.dataset.masterDuplicateDecision === "merge";
                button.disabled = busy || blockedMerge;
            });
        });
        if (message && els.status) {
            els.status.textContent = message;
            els.status.classList.remove("is-error", "is-warning");
        }
        updateMasterDataDuplicateSelectionState();
    }

    function setMasterDataDuplicateStatus(message, kind = "") {
        const els = masterDataDuplicateElements();
        if (!els.status) return;
        els.status.textContent = message;
        els.status.classList.toggle("is-error", kind === "error");
        els.status.classList.toggle("is-warning", kind === "warning");
    }

    function setMasterDataDuplicateStatusWithUndo(message, reviewId) {
        const els = masterDataDuplicateElements();
        if (!els.status) return;
        setMasterDataDuplicateStatus(message);
        const undoButton = document.createElement("button");
        undoButton.type = "button";
        undoButton.className = "master-data-duplicate-status-undo";
        undoButton.dataset.masterDuplicateRestoreDecision = String(Number(reviewId) || 0);
        undoButton.textContent = "Undo";
        undoButton.addEventListener("click", () => {
            void restoreMasterDataDuplicateDecision(undoButton);
        });
        els.status.append(" ", undoButton);
    }

    function setMasterDataUndoMergeState(merge = null) {
        const els = masterDataDuplicateElements();
        if (!els.panel || !els.undoMerge) return;
        const available = Boolean(merge);
        const sourceName = available ? text(merge.source_name).trim() : "";
        const targetName = available ? text(merge.target_name).trim() : "";
        Array.from(els.undoMergeButtons || []).forEach((button) => {
            button.dataset.undoAvailable = available ? "true" : "false";
            button.dataset.sourceName = sourceName;
            button.dataset.targetName = targetName;
            button.disabled = !available
                || els.panel.dataset.scope === "all"
                || els.panel.getAttribute("aria-busy") === "true";
        });
        if (els.undoSummary) {
            els.undoSummary.textContent = available
                ? `Last merge: ${sourceName} into ${targetName}.`
                : "No merge is currently available to undo.";
        }
    }

    async function refreshMasterDataRecordResults() {
        const response = await fetch(window.location.href, {
            headers: { Accept: "text/html", "X-Requested-With": "fetch" },
        });
        if (!response.ok) {
            throw new Error("The ingredient table could not be refreshed.");
        }
        const html = await response.text();
        const nextDocument = new DOMParser().parseFromString(html, "text/html");
        const requiredSelectors = [
            "[data-master-results-header]",
            "[data-master-record-results]",
            "[data-master-pagination]",
        ];
        requiredSelectors.forEach((selector) => {
            const current = document.querySelector(selector);
            const incoming = nextDocument.querySelector(selector);
            if (!current || !incoming) {
                throw new Error("The updated ingredient table was incomplete.");
            }
            current.replaceWith(incoming);
        });

        const currentSavePanel = document.querySelector("[data-master-store-section-panel]");
        const incomingSavePanel = nextDocument.querySelector("[data-master-store-section-panel]");
        if (currentSavePanel && incomingSavePanel) {
            currentSavePanel.replaceWith(incomingSavePanel);
        } else if (currentSavePanel) {
            currentSavePanel.remove();
        } else if (incomingSavePanel) {
            const records = document.querySelector("[data-master-record-results]");
            if (records) records.before(incomingSavePanel);
        }

        decorateMasterDataLightboxImages();
        applyMasterDataThumbnailSize(masterDataThumbnailSize);
        initMasterDataStoreSectionBatchSave();
    }

    function broadcastIngredientMasterDataMerge(plural = false) {
        try {
            if (window.localStorage) {
                window.localStorage.setItem(INGREDIENT_MASTER_DATA_VERSION_STORAGE_KEY, String(Date.now()));
            }
        } catch (storageError) {
            console.debug(`Unable to notify other tabs about the ingredient merge${plural ? "s" : ""}.`, storageError);
        }
    }

    async function refreshAfterMasterDataDuplicateMerge(message, kind = "", merge = null) {
        broadcastIngredientMasterDataMerge();
        if (merge) setMasterDataUndoMergeState(merge);
        let recordsError = null;
        const [reviewsRefreshed] = await Promise.all([
            loadMasterDataDuplicateReviews(),
            refreshMasterDataRecordResults().catch((error) => {
                recordsError = error;
                console.warn("Unable to refresh ingredient master data in place.", error);
            }),
        ]);
        if (recordsError || !reviewsRefreshed) {
            setMasterDataDuplicateStatus(
                `${message} Some on-page data could not update; refresh whenever convenient.`,
                "warning"
            );
            return;
        }
        setMasterDataDuplicateStatus(message, kind);
    }

    function masterDataDuplicateRequestContext() {
        const els = masterDataDuplicateElements();
        return {
            scope: text(els.panel && els.panel.dataset.scope).trim(),
            user_id: text(els.panel && els.panel.dataset.userId).trim(),
        };
    }

    let activeMasterDataUndoPreview = null;
    const masterDataUndoCollapsedDateGroups = new Set();
    let masterDataUndoHistoryGroupsInitialized = false;

    function masterDataUndoPreviewElements() {
        const dialog = document.querySelector("[data-master-undo-dialog]");
        return {
            dialog,
            summary: dialog && dialog.querySelector("[data-master-undo-preview-summary]"),
            historyCount: dialog && dialog.querySelector("[data-master-undo-history-count]"),
            historyList: dialog && dialog.querySelector("[data-master-undo-history-list]"),
            status: dialog && dialog.querySelector("[data-master-undo-preview-status]"),
            preview: dialog && dialog.querySelector("[data-master-undo-preview]"),
            position: dialog && dialog.querySelector("[data-master-undo-preview-position]"),
            time: dialog && dialog.querySelector("[data-master-undo-preview-time]"),
            sourceName: dialog && dialog.querySelector('[data-master-undo-preview-name="source"]'),
            targetName: dialog && dialog.querySelector('[data-master-undo-preview-name="target"]'),
            sourceSection: dialog && dialog.querySelector('[data-master-undo-preview-section="source"]'),
            targetSection: dialog && dialog.querySelector('[data-master-undo-preview-section="target"]'),
            sourceAliases: dialog && dialog.querySelector('[data-master-undo-preview-aliases="source"]'),
            targetAliases: dialog && dialog.querySelector('[data-master-undo-preview-aliases="target"]'),
            sourceImage: dialog && dialog.querySelector('[data-master-undo-preview-image="source"]'),
            targetImage: dialog && dialog.querySelector('[data-master-undo-preview-image="target"]'),
            sourceImageFallback: dialog && dialog.querySelector('[data-master-undo-preview-image-fallback="source"]'),
            targetImageFallback: dialog && dialog.querySelector('[data-master-undo-preview-image-fallback="target"]'),
            impact: dialog && dialog.querySelector("[data-master-undo-preview-impact]"),
            referenceCount: dialog && dialog.querySelector("[data-master-undo-preview-reference-count]"),
            references: dialog && dialog.querySelector("[data-master-undo-preview-references]"),
            next: dialog && dialog.querySelector("[data-master-undo-preview-next]"),
            footer: dialog && dialog.querySelector("[data-master-undo-preview-footer]"),
            confirm: dialog && dialog.querySelector("[data-master-undo-preview-confirm]"),
            closeButtons: dialog ? dialog.querySelectorAll("[data-master-undo-preview-close]") : [],
        };
    }

    function setMasterDataUndoPreviewImage(image, fallback, record) {
        if (!image || !fallback) return;
        const imageUrl = text(record && record.image_url).trim();
        const name = text(record && record.name).trim() || "Ingredient";
        image.onerror = null;
        if (!imageUrl) {
            image.hidden = true;
            image.removeAttribute("src");
            image.alt = "";
            fallback.hidden = false;
            return;
        }
        image.src = imageUrl;
        image.alt = name;
        image.hidden = false;
        fallback.hidden = true;
        image.onerror = () => {
            image.hidden = true;
            fallback.hidden = false;
        };
    }

    function renderMasterDataUndoPreviewAliases(container, aliases) {
        if (!container) return;
        container.replaceChildren();
        const values = Array.isArray(aliases) ? aliases.filter(Boolean) : [];
        if (!values.length) {
            const empty = document.createElement("em");
            empty.textContent = "No saved aliases";
            container.appendChild(empty);
            return;
        }
        values.forEach((alias) => {
            const chip = document.createElement("span");
            chip.textContent = alias;
            container.appendChild(chip);
        });
    }

    function masterDataUndoPreviewFieldValue(change, value) {
        if (text(change && change.field) === "image_url") {
            return text(value).trim() ? "saved image" : "no image";
        }
        return text(value).trim() || "blank";
    }

    function appendMasterDataUndoPreviewImpact(list, message) {
        if (!list || !message) return;
        const item = document.createElement("li");
        item.textContent = message;
        list.appendChild(item);
    }

    function renderMasterDataUndoPreviewReferences(container, references, truncated) {
        if (!container) return;
        container.replaceChildren();
        const rows = Array.isArray(references) ? references : [];
        if (!rows.length) {
            const empty = document.createElement("div");
            empty.className = "master-data-undo-preview-reference";
            const label = document.createElement("strong");
            label.textContent = "No recipe references will move.";
            empty.appendChild(label);
            container.appendChild(empty);
            return;
        }
        rows.forEach((reference) => {
            const row = document.createElement("div");
            row.className = "master-data-undo-preview-reference";
            const title = document.createElement("strong");
            title.textContent = text(reference.recipe_title).trim() || "Recipe";
            const amount = document.createElement("span");
            amount.textContent = [reference.quantity, reference.unit, reference.size]
                .map((value) => text(value).trim())
                .filter(Boolean)
                .join(" ") || "Linked ingredient";
            row.append(title, amount);
            const detail = text(reference.original_recipe_text).trim()
                || text(reference.preparation).trim();
            if (detail) {
                const copy = document.createElement("small");
                copy.textContent = detail;
                row.appendChild(copy);
            }
            container.appendChild(row);
        });
        if (truncated) {
            const more = document.createElement("div");
            more.className = "master-data-undo-preview-reference";
            const label = document.createElement("strong");
            label.textContent = "Additional recipe references will also be restored.";
            more.appendChild(label);
            container.appendChild(more);
        }
    }

    function setMasterDataUndoPreviewError(message) {
        const els = masterDataUndoPreviewElements();
        if (els.status) {
            els.status.hidden = false;
            els.status.textContent = message;
            els.status.classList.add("is-error");
        }
        if (els.confirm) els.confirm.disabled = true;
    }

    function masterDataUndoHistoryDateInfo(value) {
        const date = new Date(text(value));
        if (Number.isNaN(date.getTime())) {
            return {
                key: "date-unavailable",
                label: "Date unavailable",
                time: "Time unavailable",
            };
        }
        const key = [
            date.getFullYear(),
            String(date.getMonth() + 1).padStart(2, "0"),
            String(date.getDate()).padStart(2, "0"),
        ].join("-");
        return {
            key,
            label: date.toLocaleDateString([], {
                year: "numeric",
                month: "long",
                day: "numeric",
            }),
            time: date.toLocaleTimeString([], {
                hour: "numeric",
                minute: "2-digit",
            }),
        };
    }

    function masterDataReviewHistoryElements() {
        const dialog = document.querySelector("[data-master-review-history-dialog]");
        return {
            dialog,
            status: dialog && dialog.querySelector("[data-master-review-history-status]"),
            list: dialog && dialog.querySelector("[data-master-review-history-list]"),
            closeButtons: dialog ? dialog.querySelectorAll("[data-master-review-history-close]") : [],
        };
    }

    function masterDataReviewHistoryUrl() {
        const duplicateEls = masterDataDuplicateElements();
        const url = new URL(
            text(duplicateEls.panel && duplicateEls.panel.dataset.reviewHistoryUrl),
            window.location.origin
        );
        const context = masterDataDuplicateRequestContext();
        if (context.scope) url.searchParams.set("scope", context.scope);
        if (context.user_id) url.searchParams.set("user_id", context.user_id);
        return url.toString();
    }

    function masterDataReviewHistoryItem(decision) {
        const article = document.createElement("article");
        article.className = "master-data-review-history-item";
        article.dataset.reviewId = String(Number(decision && decision.review_id) || 0);
        article.classList.toggle("is-blocked", decision && decision.can_restore === false);

        const copy = document.createElement("div");
        copy.className = "master-data-review-history-item-copy";
        const heading = document.createElement("div");
        heading.className = "master-data-review-history-item-heading";
        const names = document.createElement("strong");
        const leftName = text(decision && decision.left && decision.left.name).trim() || "Ingredient";
        const rightName = text(decision && decision.right && decision.right.name).trim() || "Ingredient";
        names.textContent = `${leftName} and ${rightName}`;
        const badge = document.createElement("span");
        const decisionType = text(decision && decision.decision).trim();
        badge.className = `master-data-review-history-badge is-${decisionType || "decision"}`;
        badge.textContent = text(decision && decision.decision_label).trim() || "Review decision";
        heading.append(names, badge);

        const detail = document.createElement("p");
        detail.textContent = decision && decision.can_restore === false
            ? text(decision.blocked_reason).trim()
            : "Restore this pair to Potential duplicate ingredients for another decision.";
        copy.append(heading, detail);

        const action = document.createElement("div");
        action.className = "master-data-review-history-item-action";
        const dateInfo = masterDataUndoHistoryDateInfo(decision && decision.decided_at);
        const time = document.createElement("time");
        time.dateTime = text(decision && decision.decided_at).trim();
        time.textContent = dateInfo.time;
        const restore = document.createElement("button");
        restore.type = "button";
        restore.dataset.masterReviewHistoryRestore = String(Number(decision && decision.review_id) || 0);
        restore.textContent = "Restore to review queue";
        restore.disabled = decision && decision.can_restore === false;
        restore.title = restore.disabled ? text(decision && decision.blocked_reason).trim() : "";
        action.append(time, restore);
        article.append(copy, action);
        return article;
    }

    function renderMasterDataReviewHistory(decisions) {
        const els = masterDataReviewHistoryElements();
        if (!els.list || !els.status) return;
        const items = Array.isArray(decisions) ? decisions : [];
        els.list.replaceChildren();
        if (!items.length) {
            els.status.hidden = false;
            els.status.classList.remove("is-error");
            els.status.textContent = "No Related variant or Not a duplicate decisions are currently restorable.";
            return;
        }

        const groups = new Map();
        items.forEach((decision) => {
            const dateInfo = masterDataUndoHistoryDateInfo(decision && decision.decided_at);
            if (!groups.has(dateInfo.key)) groups.set(dateInfo.key, { dateInfo, decisions: [] });
            groups.get(dateInfo.key).decisions.push(decision);
        });
        groups.forEach((group) => {
            const section = document.createElement("section");
            section.className = "master-data-review-history-date-group";
            const header = document.createElement("header");
            const title = document.createElement("h3");
            title.textContent = group.dateInfo.label;
            const count = document.createElement("span");
            count.textContent = `${group.decisions.length} decision${group.decisions.length === 1 ? "" : "s"}`;
            header.append(title, count);
            const list = document.createElement("div");
            list.append(...group.decisions.map(masterDataReviewHistoryItem));
            section.append(header, list);
            els.list.appendChild(section);
        });
        els.status.hidden = true;
        els.status.classList.remove("is-error");
    }

    async function loadMasterDataReviewHistory() {
        const els = masterDataReviewHistoryElements();
        if (!els.dialog || !els.list || !els.status) return false;
        els.status.hidden = false;
        els.status.classList.remove("is-error");
        els.status.textContent = "Loading review history...";
        els.list.replaceChildren();
        try {
            const response = await fetch(masterDataReviewHistoryUrl(), {
                headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "Review decision history could not be loaded.");
            }
            renderMasterDataReviewHistory(data.decisions);
            return true;
        } catch (error) {
            els.status.hidden = false;
            els.status.classList.add("is-error");
            els.status.textContent = error.message || "Review decision history could not be loaded.";
            return false;
        }
    }

    async function openMasterDataReviewHistory() {
        const els = masterDataReviewHistoryElements();
        if (!els.dialog) return;
        if (!els.dialog.open) els.dialog.showModal();
        await loadMasterDataReviewHistory();
    }

    function closeMasterDataReviewHistory() {
        const els = masterDataReviewHistoryElements();
        if (els.dialog && els.dialog.open) els.dialog.close();
    }

    async function restoreMasterDataDuplicateDecision(button) {
        const duplicateEls = masterDataDuplicateElements();
        const historyEls = masterDataReviewHistoryElements();
        const reviewId = Number(
            button && (
                button.dataset.masterReviewHistoryRestore
                || button.dataset.masterDuplicateRestoreDecision
            )
        ) || 0;
        if (!duplicateEls.panel || !reviewId || !duplicateEls.panel.dataset.restoreDecisionUrl) return;
        const defaultLabel = text(button.textContent).trim();
        button.disabled = true;
        button.textContent = "Restoring...";
        const requestUrl = text(duplicateEls.panel.dataset.restoreDecisionUrl)
            .replace("/0/restore", `/${reviewId}/restore`);
        try {
            const response = await fetch(requestUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify(masterDataDuplicateRequestContext()),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "The review decision could not be restored.");
            }
            await loadMasterDataDuplicateReviews();
            setMasterDataDuplicateStatus(data.message || "Review decision restored.");
            if (historyEls.dialog && historyEls.dialog.open) {
                await loadMasterDataReviewHistory();
            }
        } catch (error) {
            button.disabled = false;
            button.textContent = defaultLabel;
            if (historyEls.dialog && historyEls.dialog.open) {
                if (historyEls.status) {
                    historyEls.status.hidden = false;
                    historyEls.status.classList.add("is-error");
                    historyEls.status.textContent = error.message || "The review decision could not be restored.";
                }
            } else {
                setMasterDataDuplicateStatus(
                    error.message || "The review decision could not be restored.",
                    "error"
                );
            }
        }
    }

    function masterDataUndoHistoryItem(merge, selectedMergeId) {
        const mergeId = Number(merge && merge.merge_id) || 0;
        const newerCount = Math.max(0, Number(merge && merge.newer_undo_count) || 0);
        const referenceCount = Math.max(0, Number(merge && merge.restored_reference_count) || 0);
        const canUndoNow = Boolean(merge && merge.can_undo_now);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "master-data-undo-history-item";
        button.classList.toggle("is-blocked", !canUndoNow);
        button.dataset.masterUndoHistoryMergeId = String(mergeId);
        button.setAttribute("aria-current", mergeId === Number(selectedMergeId) ? "true" : "false");
        button.title = canUndoNow
            ? (newerCount ? "This merge is independent and can be undone out of order." : "This merge can be undone now.")
            : text(merge && merge.blocked_reason).trim();

        const header = document.createElement("span");
        header.className = "master-data-undo-history-item-header";
        const source = document.createElement("strong");
        source.textContent = text(merge && merge.source_name).trim() || "Ingredient";
        const badge = document.createElement("span");
        badge.className = "master-data-undo-history-item-badge";
        badge.textContent = canUndoNow
            ? (newerCount ? "Safe" : "Next")
            : "Blocked";
        badge.title = canUndoNow
            ? (newerCount ? "Safe independent out-of-order undo" : "Newest merge — undo next")
            : "This merge cannot currently be restored";
        header.append(source, badge);

        const target = document.createElement("span");
        target.className = "master-data-undo-history-item-target";
        target.textContent = `Merged into ${text(merge && merge.target_name).trim() || "ingredient"}`;

        const meta = document.createElement("span");
        meta.className = "master-data-undo-history-item-meta";
        const mergedAt = document.createElement("span");
        mergedAt.textContent = masterDataUndoHistoryDateInfo(merge && merge.merged_at).time;
        const references = document.createElement("span");
        references.textContent = `${referenceCount} recipe ref${referenceCount === 1 ? "" : "s"}`;
        meta.append(mergedAt, references);

        button.append(header, target, meta);
        button.addEventListener("click", () => {
            if (mergeId && mergeId !== Number(activeMasterDataUndoPreview && activeMasterDataUndoPreview.merge_id)) {
                void loadMasterDataUndoPreview(mergeId);
            }
        });
        return button;
    }

    function renderMasterDataUndoHistory(merges, selectedMergeId) {
        const els = masterDataUndoPreviewElements();
        const rows = Array.isArray(merges) ? merges : [];
        if (els.historyCount) els.historyCount.textContent = String(rows.length);
        if (!els.historyList) return;
        els.historyList.replaceChildren();
        const groups = [];
        const groupsByKey = new Map();
        rows.forEach((merge) => {
            const date = masterDataUndoHistoryDateInfo(merge && merge.merged_at);
            let group = groupsByKey.get(date.key);
            if (!group) {
                group = { ...date, merges: [] };
                groupsByKey.set(date.key, group);
                groups.push(group);
            }
            group.merges.push(merge);
        });

        const selectedGroup = groups.find((group) => group.merges.some(
            (merge) => Number(merge && merge.merge_id) === Number(selectedMergeId)
        ));
        if (!masterDataUndoHistoryGroupsInitialized) {
            masterDataUndoCollapsedDateGroups.clear();
            groups.slice(1).forEach((group) => masterDataUndoCollapsedDateGroups.add(group.key));
            masterDataUndoHistoryGroupsInitialized = true;
        }
        if (selectedGroup) masterDataUndoCollapsedDateGroups.delete(selectedGroup.key);

        groups.forEach((group) => {
            const dateGroup = document.createElement("details");
            dateGroup.className = "master-data-undo-history-date-group";
            dateGroup.dataset.undoHistoryDate = group.key;
            dateGroup.open = !masterDataUndoCollapsedDateGroups.has(group.key);

            const summary = document.createElement("summary");
            summary.className = "master-data-undo-history-date-summary";
            const label = document.createElement("strong");
            label.textContent = group.label;
            const count = document.createElement("span");
            count.textContent = String(group.merges.length);
            summary.append(label, count);

            const items = document.createElement("div");
            items.className = "master-data-undo-history-date-items";
            group.merges.forEach((merge) => {
                items.appendChild(masterDataUndoHistoryItem(merge, selectedMergeId));
            });
            dateGroup.append(summary, items);
            dateGroup.addEventListener("toggle", () => {
                if (dateGroup.open) {
                    masterDataUndoCollapsedDateGroups.delete(group.key);
                } else {
                    masterDataUndoCollapsedDateGroups.add(group.key);
                }
            });
            els.historyList.appendChild(dateGroup);
        });
    }

    function renderMasterDataUndoPreview(merge) {
        const els = masterDataUndoPreviewElements();
        if (!els.dialog || !merge) return;
        activeMasterDataUndoPreview = merge;
        const source = merge.source_restore || {};
        const target = merge.target_restore || {};
        const sourceName = text(source.name || merge.source_name).trim() || "Ingredient";
        const targetName = text(target.name || merge.target_name).trim() || "Ingredient";
        const referenceCount = Math.max(0, Number(merge.restored_reference_count) || 0);
        const newerCount = Math.max(0, Number(merge.newer_undo_count) || 0);
        const isNextUndo = merge.is_next_undo !== false && newerCount === 0;
        const canUndoNow = Boolean(merge.can_undo_now);
        const blockedReason = text(merge.blocked_reason).trim()
            || "This merge depends on newer changes and cannot be safely undone yet.";
        if (els.summary) {
            els.summary.textContent = canUndoNow
                ? `Restore ${sourceName} from its merge into ${targetName}.`
                : `Preview ${sourceName}; this restore is currently blocked.`;
        }
        if (els.position) {
            els.position.textContent = isNextUndo
                ? "Undo next • newest merge"
                : canUndoNow
                ? "Safe out-of-order undo"
                : "Blocked by newer changes";
        }
        if (els.time) {
            els.time.textContent = formatMasterDataDuplicateScanTime(merge.merged_at) || "Merge time unavailable";
        }
        if (els.sourceName) els.sourceName.textContent = sourceName;
        if (els.targetName) els.targetName.textContent = targetName;
        if (els.sourceSection) {
            els.sourceSection.textContent = `${text(source.store_section).trim() || "MISC"} store section`;
        }
        if (els.targetSection) {
            els.targetSection.textContent = `${text(target.store_section).trim() || "MISC"} store section after undo`;
        }
        setMasterDataUndoPreviewImage(els.sourceImage, els.sourceImageFallback, source);
        setMasterDataUndoPreviewImage(els.targetImage, els.targetImageFallback, target);
        renderMasterDataUndoPreviewAliases(els.sourceAliases, source.aliases);
        renderMasterDataUndoPreviewAliases(els.targetAliases, target.aliases);

        if (els.impact) {
            els.impact.replaceChildren();
            appendMasterDataUndoPreviewImpact(
                els.impact,
                `Restore ${sourceName} as its own ingredient master record.`
            );
            appendMasterDataUndoPreviewImpact(
                els.impact,
                referenceCount
                    ? `Move ${referenceCount} recipe reference${referenceCount === 1 ? "" : "s"} from ${targetName} back to ${sourceName}.`
                    : `No recipe references need to move back to ${sourceName}.`
            );
            const aliasCount = (Array.isArray(source.aliases) ? source.aliases.length : 0)
                + (Array.isArray(target.aliases) ? target.aliases.length : 0);
            appendMasterDataUndoPreviewImpact(
                els.impact,
                aliasCount
                    ? `Restore ${aliasCount} saved alias${aliasCount === 1 ? "" : "es"} across the two ingredients.`
                    : "Restore both ingredients without any saved aliases."
            );
            (Array.isArray(merge.target_changes) ? merge.target_changes : []).forEach((change) => {
                appendMasterDataUndoPreviewImpact(
                    els.impact,
                    `Reset ${targetName}'s ${text(change.label).toLowerCase()} from ${masterDataUndoPreviewFieldValue(change, change.current)} to ${masterDataUndoPreviewFieldValue(change, change.restored)}.`
                );
            });
        }
        if (els.referenceCount) {
            els.referenceCount.textContent = `${referenceCount} affected`;
        }
        renderMasterDataUndoPreviewReferences(
            els.references,
            merge.reference_previews,
            Boolean(merge.reference_preview_truncated)
        );
        const olderCount = Math.max(0, Number(merge.older_undo_count) || 0);
        if (els.next) {
            els.next.classList.toggle("is-blocked", !canUndoNow);
            els.next.textContent = !canUndoNow
                ? blockedReason
                : newerCount
                ? `This merge is independent. ${newerCount} newer merge${newerCount === 1 ? " will" : "s will"} remain after this undo.`
                : olderCount
                ? `${olderCount} older merge${olderCount === 1 ? "" : "s"} will remain available after this undo.`
                : "This is the oldest remaining merge in the undo history.";
        }
        if (els.footer) {
            els.footer.textContent = !canUndoNow
                ? "This merge is read-only until its restore checks pass."
                : isNextUndo
                ? "Undoing this merge will automatically advance the history stack."
                : "Safe out-of-order undo leaves unrelated newer merges available.";
        }
        if (els.status) {
            els.status.hidden = true;
            els.status.classList.remove("is-error");
        }
        if (els.preview) els.preview.hidden = false;
        if (els.confirm) {
            els.confirm.disabled = !canUndoNow;
            els.confirm.textContent = canUndoNow
                ? `Undo and restore ${sourceName}`
                : "Cannot safely undo yet";
        }
    }

    function closeMasterDataUndoPreview() {
        const els = masterDataUndoPreviewElements();
        activeMasterDataUndoPreview = null;
        if (els.dialog && els.dialog.open) els.dialog.close();
    }

    async function loadMasterDataUndoPreview(mergeId = 0) {
        const duplicateEls = masterDataDuplicateElements();
        const els = masterDataUndoPreviewElements();
        if (!duplicateEls.panel || !els.dialog) return false;
        activeMasterDataUndoPreview = null;
        if (els.preview) els.preview.hidden = true;
        if (els.summary) els.summary.textContent = "Loading merge restore details...";
        if (els.status) {
            els.status.hidden = false;
            els.status.textContent = "Loading undo details...";
            els.status.classList.remove("is-error");
        }
        if (els.confirm) {
            els.confirm.disabled = true;
            els.confirm.textContent = "Undo this merge";
        }
        try {
            const url = new URL(text(duplicateEls.panel.dataset.undoMergePreviewUrl), window.location.origin);
            const context = masterDataDuplicateRequestContext();
            if (context.scope) url.searchParams.set("scope", context.scope);
            if (context.user_id) url.searchParams.set("user_id", context.user_id);
            if (Number(mergeId) > 0) url.searchParams.set("merge_id", String(Number(mergeId)));
            const response = await fetch(url.toString(), {
                headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false || !data.merge) {
                throw new Error(data.error || "The latest ingredient merge could not be previewed.");
            }
            renderMasterDataUndoHistory(data.merges || data.merge.undoable_merges, data.merge.merge_id);
            renderMasterDataUndoPreview(data.merge);
            return true;
        } catch (error) {
            setMasterDataUndoPreviewError(
                error.message || "The latest ingredient merge could not be previewed."
            );
            return false;
        }
    }

    async function openMasterDataUndoPreview() {
        const duplicateEls = masterDataDuplicateElements();
        const els = masterDataUndoPreviewElements();
        if (!duplicateEls.panel || !els.dialog) return;
        if (changedStoreSectionForms().length) {
            setMasterDataDuplicateStatus("Save your pending ingredient edits before reviewing an undo.", "warning");
            return;
        }
        masterDataUndoCollapsedDateGroups.clear();
        masterDataUndoHistoryGroupsInitialized = false;
        if (els.historyList) els.historyList.replaceChildren();
        if (els.historyCount) els.historyCount.textContent = "0";
        if (!els.dialog.open) els.dialog.showModal();
        await loadMasterDataUndoPreview();
    }

    async function undoLastMasterDataIngredientMerge() {
        const els = masterDataDuplicateElements();
        const previewEls = masterDataUndoPreviewElements();
        const preview = activeMasterDataUndoPreview;
        if (
            !els.panel
            || !previewEls.dialog
            || !preview
            || !Number(preview.merge_id)
            || preview.can_undo_now === false
        ) return;
        if (changedStoreSectionForms().length) {
            setMasterDataUndoPreviewError("Save your pending ingredient edits before undoing a merge.");
            return;
        }

        setMasterDataDuplicateBusy(true, "Undoing the last ingredient merge...");
        if (previewEls.confirm) {
            previewEls.confirm.disabled = true;
            previewEls.confirm.textContent = "Restoring ingredient...";
        }
        try {
            const response = await fetch(text(els.panel.dataset.undoMergeUrl), {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    ...masterDataDuplicateRequestContext(),
                    merge_id: Number(preview.merge_id),
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "The last ingredient merge could not be undone.");
            }
            setMasterDataUndoMergeState(data.next_merge || null);
            activeMasterDataUndoPreview = null;
            if (previewEls.preview) previewEls.preview.hidden = true;
            if (previewEls.status) {
                previewEls.status.hidden = false;
                previewEls.status.textContent = "Merge undone. Loading the remaining history...";
                previewEls.status.classList.remove("is-error");
            }
            await refreshAfterMasterDataDuplicateMerge(
                data.message || "Ingredient merge undone."
            );
            if (data.next_merge) {
                await loadMasterDataUndoPreview();
            } else {
                closeMasterDataUndoPreview();
            }
        } catch (error) {
            activeMasterDataUndoPreview = null;
            setMasterDataUndoPreviewError(
                error.message || "The last ingredient merge could not be undone."
            );
            setMasterDataDuplicateStatus(
                error.message || "The last ingredient merge could not be undone.",
                "error"
            );
        } finally {
            setMasterDataDuplicateBusy(false);
        }
    }

    function duplicateClassificationLabel(classification) {
        return {
            duplicate: "Likely duplicate",
            related: "Related variant",
            different: "Likely different",
        }[text(classification).toLowerCase()] || "Needs review";
    }

    function duplicateUsageLabel(value) {
        const count = Math.max(0, Number(value) || 0);
        return `${count} recipe use${count === 1 ? "" : "s"}`;
    }

    function aiSecondOpinionVerdictLabel(opinion, panel) {
        const verdict = text(opinion && opinion.verdict).toLowerCase();
        if (verdict === "merge") {
            const targetId = Number(opinion && opinion.suggested_target_id) || 0;
            const targetName = targetId === Number(panel.dataset.leftIngredientId)
                ? panel.dataset.leftIngredientName
                : targetId === Number(panel.dataset.rightIngredientId)
                ? panel.dataset.rightIngredientName
                : "";
            return targetName ? `Merge into ${targetName}` : "Merge these records";
        }
        return {
            related: "Keep as related variants",
            not_duplicate: "Not a duplicate",
            insufficient_evidence: "More evidence needed",
        }[verdict] || "Review unavailable";
    }

    function renderMasterDataAiSecondOpinion(panel, opinion) {
        if (!panel) return;
        const result = opinion && typeof opinion === "object" ? opinion : {};
        const status = text(result.status || "not_generated").toLowerCase();
        panel.className = "master-data-ai-second-opinion";
        panel.dataset.opinionStatus = status;
        panel.removeAttribute("aria-busy");
        panel.replaceChildren();

        const header = document.createElement("header");
        const title = document.createElement("strong");
        title.textContent = "AI second opinion";
        const independence = document.createElement("small");
        independence.textContent = "Independent review";
        header.append(title, independence);
        panel.appendChild(header);

        if (status === "loading") {
            panel.classList.add("is-loading");
            panel.setAttribute("aria-busy", "true");
            const loading = document.createElement("p");
            loading.className = "master-data-ai-second-opinion-message";
            loading.textContent = "Analyzing names, aliases, store sections, and recipe context...";
            panel.appendChild(loading);
            return;
        }

        if (status !== "ready") {
            panel.classList.add(status === "stale" ? "is-stale" : "is-empty");
            const message = document.createElement("p");
            message.className = "master-data-ai-second-opinion-message";
            message.textContent = text(result.message)
                || "Generate a separate AI review that is not shown the queue recommendation.";
            const action = document.createElement("button");
            action.type = "button";
            action.dataset.masterDuplicateAiSecondOpinion = "1";
            action.dataset.reviewId = text(panel.dataset.reviewId);
            action.textContent = status === "unavailable"
                ? "Retry AI review"
                : status === "stale"
                ? "Refresh AI review"
                : "Get AI second opinion";
            panel.append(message, action);
            return;
        }

        const verdict = text(result.verdict).toLowerCase();
        panel.classList.add(`is-${verdict.replace(/[^a-z_]/g, "")}`);
        if (result.agreement) panel.classList.add(`is-${text(result.agreement).toLowerCase()}`);

        const recommendation = document.createElement("div");
        recommendation.className = "master-data-ai-second-opinion-recommendation";
        const verdictLabel = document.createElement("strong");
        verdictLabel.textContent = aiSecondOpinionVerdictLabel(result, panel);
        const confidence = document.createElement("span");
        confidence.textContent = `${Math.round((Number(result.confidence) || 0) * 100)}% confidence`;
        recommendation.append(verdictLabel, confidence);

        const agreement = document.createElement("p");
        agreement.className = "master-data-ai-second-opinion-agreement";
        agreement.textContent = text(result.agreement_label)
            || "Compare this opinion with the queue recommendation.";

        const evidence = Array.isArray(result.evidence) ? result.evidence.filter(Boolean).slice(0, 3) : [];
        if (evidence.length) {
            const evidenceList = document.createElement("ul");
            evidenceList.className = "master-data-ai-second-opinion-evidence";
            evidence.forEach((note) => {
                const item = document.createElement("li");
                item.textContent = text(note);
                evidenceList.appendChild(item);
            });
            panel.append(recommendation, agreement, evidenceList);
        } else {
            panel.append(recommendation, agreement);
        }

        const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean).slice(0, 2) : [];
        if (warnings.length) {
            const warning = document.createElement("div");
            warning.className = "master-data-ai-second-opinion-warning";
            warning.textContent = warnings.join(" ");
            panel.appendChild(warning);
        }

        const footer = document.createElement("footer");
        const advisory = document.createElement("small");
        advisory.textContent = "Advisory only — you make the final decision.";
        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.dataset.masterDuplicateAiSecondOpinion = "1";
        refresh.dataset.reviewId = text(panel.dataset.reviewId);
        refresh.textContent = "Refresh";
        footer.append(advisory, refresh);
        panel.appendChild(footer);
    }

    function masterDataAiSecondOpinionPanel(review) {
        const panel = document.createElement("aside");
        panel.className = "master-data-ai-second-opinion";
        panel.dataset.reviewId = text(review && review.review_id);
        panel.dataset.leftIngredientId = text(review && review.left && review.left.ingredient_id);
        panel.dataset.leftIngredientName = text(review && review.left && review.left.name);
        panel.dataset.rightIngredientId = text(review && review.right && review.right.ingredient_id);
        panel.dataset.rightIngredientName = text(review && review.right && review.right.name);
        panel.setAttribute("aria-label", "Independent AI second opinion");
        panel.setAttribute("aria-live", "polite");
        renderMasterDataAiSecondOpinion(panel, review && review.ai_second_opinion);
        return panel;
    }

    function masterDataDuplicateReferenceElements() {
        const dialog = document.querySelector("[data-master-duplicate-reference-dialog]");
        const column = (side) => {
            const element = dialog && dialog.querySelector(`[data-master-duplicate-reference-column="${side}"]`);
            return {
                element,
                pairName: dialog && dialog.querySelector(`[data-master-duplicate-reference-pair-name="${side}"]`),
                name: element && element.querySelector(`[data-master-duplicate-reference-name="${side}"]`),
                context: element && element.querySelector(`[data-master-duplicate-reference-context="${side}"]`),
                body: element && element.querySelector(`[data-master-duplicate-reference-body="${side}"]`),
                survivor: element && element.querySelector("[data-master-duplicate-reference-survivor]"),
            };
        };
        return {
            dialog,
            summary: dialog && dialog.querySelector("[data-master-duplicate-reference-summary]"),
            left: column("left"),
            right: column("right"),
            closeButtons: dialog ? dialog.querySelectorAll("[data-master-duplicate-reference-close]") : [],
        };
    }

    function masterDataDuplicateReferenceRecord(button, side) {
        const prefix = side === "right" ? "right" : "left";
        return {
            ingredientId: Number(button && button.dataset[`${prefix}IngredientId`]) || 0,
            name: text(button && button.dataset[`${prefix}IngredientName`]).trim() || "Ingredient",
            normalizedName: text(button && button.dataset[`${prefix}NormalizedName`]).trim(),
            storeSection: text(button && button.dataset[`${prefix}StoreSection`]).trim(),
            usageCount: Math.max(0, Number(button && button.dataset[`${prefix}UsageCount`]) || 0),
        };
    }

    function masterDataDuplicateReferenceUrl(ingredientId) {
        const els = masterDataDuplicateElements();
        const url = new URL(text(els.panel && els.panel.dataset.referenceUrl), window.location.origin);
        url.pathname = url.pathname.replace(/\/0\/references$/, `/${Number(ingredientId) || 0}/references`);
        const context = masterDataDuplicateRequestContext();
        if (context.scope) url.searchParams.set("scope", context.scope);
        if (context.user_id) url.searchParams.set("user_id", context.user_id);
        url.searchParams.set("limit", "500");
        return url.toString();
    }

    function renderMasterDataDuplicateReferenceColumn(column, data) {
        if (!column || !column.body) return;
        column.body.replaceChildren();
        const references = Array.isArray(data && data.references) ? data.references : [];
        const total = Number(data && data.total) || references.length;
        if (column.context) {
            const storeSection = text(data && data.record && data.record.store_section).trim();
            column.context.textContent = [storeSection, duplicateUsageLabel(total)].filter(Boolean).join(" · ");
        }
        if (!references.length) {
            const empty = document.createElement("div");
            empty.className = "master-data-reference-placeholder";
            empty.textContent = "No recipe references were found for this ingredient.";
            column.body.appendChild(empty);
            return;
        }
        if (total > references.length) {
            const note = document.createElement("div");
            note.className = "master-data-reference-placeholder";
            note.textContent = `Showing the first ${references.length} of ${total} recipes.`;
            column.body.appendChild(note);
        }
        const list = document.createElement("div");
        list.className = "master-data-reference-list";
        references.forEach((reference) => list.appendChild(renderReferenceItem(reference || {})));
        column.body.appendChild(list);
        decorateMasterDataLightboxImages(column.body);
    }

    async function loadMasterDataDuplicateReferenceColumn(column, record, requestId) {
        try {
            const response = await fetch(masterDataDuplicateReferenceUrl(record.ingredientId), {
                headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            });
            const data = await response.json().catch(() => ({}));
            if (requestId !== masterDataDuplicateReferenceRequestId) return;
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "Recipe references could not be loaded.");
            }
            renderMasterDataDuplicateReferenceColumn(column, data);
        } catch (error) {
            if (requestId !== masterDataDuplicateReferenceRequestId) return;
            setReferenceError(
                column.body,
                error && error.message ? error.message : "Recipe references could not be loaded."
            );
        }
    }

    function closeMasterDataDuplicateReferences() {
        const els = masterDataDuplicateReferenceElements();
        masterDataDuplicateReferenceRequestId += 1;
        if (els.dialog && els.dialog.open) {
            els.dialog.close();
        }
        [els.left, els.right].forEach((column) => {
            if (column && column.body) column.body.replaceChildren();
        });
        const returnFocus = masterDataDuplicateReferenceReturnFocus;
        masterDataDuplicateReferenceReturnFocus = null;
        if (returnFocus && returnFocus.isConnected) returnFocus.focus();
    }

    async function openMasterDataDuplicateReferences(button) {
        const els = masterDataDuplicateReferenceElements();
        const leftRecord = masterDataDuplicateReferenceRecord(button, "left");
        const rightRecord = masterDataDuplicateReferenceRecord(button, "right");
        if (!els.dialog || !leftRecord.ingredientId || !rightRecord.ingredientId) return;

        const suggestedTargetId = Number(button.dataset.suggestedTargetId) || 0;
        [[els.left, leftRecord], [els.right, rightRecord]].forEach(([column, record]) => {
            if (column.pairName) column.pairName.textContent = record.name;
            if (column.name) column.name.textContent = record.name;
            if (column.context) {
                column.context.textContent = [record.storeSection, duplicateUsageLabel(record.usageCount)]
                    .filter(Boolean)
                    .join(" · ");
            }
            if (column.element) {
                column.element.classList.toggle("is-suggested", record.ingredientId === suggestedTargetId);
            }
            if (column.survivor) column.survivor.hidden = record.ingredientId !== suggestedTargetId;
            setReferenceLoading(column.body);
        });
        if (els.summary) {
            const confidence = Math.round((Number(button.dataset.reviewConfidence) || 0) * 100);
            const classification = duplicateClassificationLabel(button.dataset.reviewClassification);
            const combinedUsage = leftRecord.usageCount + rightRecord.usageCount;
            els.summary.textContent = `${classification} · ${confidence}% confidence · ${duplicateUsageLabel(combinedUsage)} total`;
        }
        masterDataDuplicateReferenceReturnFocus = button;
        if (!els.dialog.open) {
            if (typeof els.dialog.showModal === "function") {
                els.dialog.showModal();
            } else {
                els.dialog.setAttribute("open", "");
            }
        }

        const requestId = ++masterDataDuplicateReferenceRequestId;
        await Promise.all([
            loadMasterDataDuplicateReferenceColumn(els.left, leftRecord, requestId),
            loadMasterDataDuplicateReferenceColumn(els.right, rightRecord, requestId),
        ]);
    }

    function masterDataDuplicateIngredient(record, suggestedTargetId, review) {
        const item = document.createElement("article");
        item.className = "master-data-duplicate-ingredient";
        item.dataset.ingredientId = text(record.ingredient_id);
        if (Number(record.ingredient_id) === Number(suggestedTargetId)) {
            item.classList.add("is-suggested");
        }

        const openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "master-data-duplicate-ingredient-open";
        openButton.dataset.masterDuplicateReferencesOpen = "1";
        ["left", "right"].forEach((side) => {
            const pairRecord = review && review[side] ? review[side] : {};
            openButton.dataset[`${side}IngredientId`] = text(pairRecord.ingredient_id);
            openButton.dataset[`${side}IngredientName`] = text(pairRecord.name);
            openButton.dataset[`${side}NormalizedName`] = text(pairRecord.normalized_name);
            openButton.dataset[`${side}StoreSection`] = text(pairRecord.store_section);
            openButton.dataset[`${side}UsageCount`] = text(pairRecord.usage_count);
        });
        openButton.dataset.suggestedTargetId = text(suggestedTargetId);
        openButton.dataset.reviewClassification = text(review && review.classification);
        openButton.dataset.reviewConfidence = text(review && review.confidence);
        openButton.setAttribute("aria-haspopup", "dialog");
        openButton.setAttribute("aria-controls", "masterDataIngredientReferencesDialog");
        openButton.setAttribute(
            "aria-label",
            `Compare recipes using ${text(review && review.left && review.left.name)} and ${text(review && review.right && review.right.name)}`
        );

        const media = document.createElement("span");
        media.className = "master-data-duplicate-media";
        if (record.image_url) {
            const image = document.createElement("img");
            image.src = text(record.image_url);
            image.alt = `${text(record.name)} ingredient`;
            media.appendChild(image);
        } else {
            media.textContent = "No image";
        }

        const copy = document.createElement("span");
        copy.className = "master-data-duplicate-ingredient-copy";
        const heading = document.createElement("span");
        heading.className = "master-data-duplicate-ingredient-heading";
        const name = document.createElement("strong");
        name.textContent = text(record.name);
        heading.appendChild(name);
        const recommended = document.createElement("span");
        recommended.dataset.masterDuplicateSuggestedSurvivor = "1";
        recommended.textContent = "Suggested survivor";
        recommended.hidden = Number(record.ingredient_id) !== Number(suggestedTargetId);
        heading.appendChild(recommended);
        const normalized = document.createElement("code");
        normalized.textContent = text(record.normalized_name);
        const detail = document.createElement("small");
        detail.textContent = `${text(record.store_section)} · ${duplicateUsageLabel(record.usage_count)}`;
        const viewRecipes = document.createElement("span");
        viewRecipes.className = "master-data-duplicate-view-references";
        viewRecipes.textContent = "Compare recipes";
        copy.append(heading, normalized, detail, viewRecipes);
        const aliases = Array.isArray(record.aliases) ? record.aliases.filter(Boolean) : [];
        if (aliases.length) {
            const aliasText = document.createElement("small");
            aliasText.textContent = `Aliases: ${aliases.join(", ")}`;
            copy.appendChild(aliasText);
        }
        openButton.append(media, copy);
        item.appendChild(openButton);
        return item;
    }

    function masterDataDuplicateAction(label, action, review, target = null, className = "") {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.dataset.masterDuplicateDecision = action;
        button.dataset.reviewId = text(review.review_id);
        if (target) {
            const source = Number(target.ingredient_id) === Number(review.left.ingredient_id)
                ? review.right
                : review.left;
            button.dataset.targetIngredientId = text(target.ingredient_id);
            button.dataset.targetName = text(target.name);
            button.dataset.sourceName = text(source.name);
        }
        if (className) button.className = className;
        return button;
    }

    function setMasterDataDuplicateSuggestedSurvivor(button) {
        const card = button && button.closest ? button.closest(".master-data-duplicate-card") : null;
        const targetId = Number(button && button.dataset.targetIngredientId) || 0;
        if (!card || !targetId) return;

        card.dataset.suggestedTargetId = text(targetId);
        card.dataset.suggestedTargetName = text(button.dataset.targetName);
        card.dataset.suggestedSourceName = text(button.dataset.sourceName);
        card.querySelectorAll(".master-data-duplicate-ingredient[data-ingredient-id]").forEach((ingredient) => {
            const isSuggested = Number(ingredient.dataset.ingredientId) === targetId;
            ingredient.classList.toggle("is-suggested", isSuggested);
            const label = ingredient.querySelector("[data-master-duplicate-suggested-survivor]");
            if (label) label.hidden = !isSuggested;
        });
        card.querySelectorAll("[data-master-duplicate-references-open]").forEach((referenceButton) => {
            referenceButton.dataset.suggestedTargetId = text(targetId);
        });
        card.querySelectorAll('[data-master-duplicate-decision="merge"]').forEach((mergeButton) => {
            const isSuggested = Number(mergeButton.dataset.targetIngredientId) === targetId;
            mergeButton.setAttribute("aria-pressed", isSuggested ? "true" : "false");
            if (card.dataset.classification === "duplicate") {
                mergeButton.classList.toggle("primary", isSuggested);
            }
        });
    }

    function masterDataDuplicateCard(review) {
        const card = document.createElement("article");
        card.className = `master-data-duplicate-card is-${text(review.classification).toLowerCase()}`;
        card.dataset.reviewId = text(review.review_id);
        card.dataset.classification = text(review.classification).toLowerCase();
        card.dataset.confidence = text(review.confidence || 0);
        card.dataset.suggestedTargetId = text(review.suggested_target_id || "");
        card.dataset.mergeBlocked = text(Boolean(review.merge_blocked));
        if (review.merge_blocked) card.classList.add("has-data-quality-warning");
        card.dataset.highConfidenceDuplicate = text(Boolean(
            !review.merge_blocked
            && review.classification === "duplicate"
            && Number(review.confidence) >= 0.98
            && review.signals
            && (review.signals.singular_exact || review.signals.alias_match)
        ));

        const header = document.createElement("header");
        const selection = document.createElement("label");
        selection.className = "master-data-duplicate-select";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.dataset.masterDuplicateSelect = "1";
        checkbox.setAttribute("aria-label", `Select ${text(review.left.name)} and ${text(review.right.name)}`);
        const selectionText = document.createElement("span");
        selectionText.textContent = "Select";
        selection.append(checkbox, selectionText);
        const classification = document.createElement("span");
        classification.className = "master-data-duplicate-classification";
        classification.textContent = duplicateClassificationLabel(review.classification);
        const confidence = document.createElement("strong");
        confidence.textContent = `${Math.round((Number(review.confidence) || 0) * 100)}% confidence`;
        const source = document.createElement("small");
        source.textContent = review.analysis_source === "ai" ? "AI review" : "Local similarity review";
        header.append(selection, classification, confidence, source);

        const comparison = document.createElement("div");
        comparison.className = "master-data-duplicate-comparison";
        comparison.append(
            masterDataDuplicateIngredient(review.left, review.suggested_target_id, review),
            masterDataDuplicateIngredient(review.right, review.suggested_target_id, review),
            masterDataAiSecondOpinionPanel(review)
        );

        const reason = document.createElement("p");
        reason.className = "master-data-duplicate-reason";
        reason.textContent = text(review.reason) || "These names have overlapping ingredient signals.";

        let dataQualityWarning = null;
        if (review.merge_blocked) {
            const issues = Array.isArray(review.data_quality_issues) ? review.data_quality_issues : [];
            const examples = issues
                .map((issue) => text(issue && issue.message).trim())
                .filter(Boolean)
                .slice(0, 3);
            dataQualityWarning = document.createElement("div");
            dataQualityWarning.className = "master-data-duplicate-quality-warning";
            dataQualityWarning.setAttribute("role", "status");
            const warningTitle = document.createElement("strong");
            warningTitle.textContent = "Needs data repair";
            const warningCopy = document.createElement("span");
            warningCopy.textContent = examples.length
                ? `${examples.join(" ")} Merge actions are disabled until these recipe references are repaired.`
                : "Suspicious recipe references must be repaired before this pair can be merged.";
            dataQualityWarning.append(warningTitle, warningCopy);
        }

        const signals = document.createElement("div");
        signals.className = "master-data-duplicate-signals";
        const signalLabels = [];
        if (review.signals && review.signals.singular_exact) signalLabels.push("singular/plural match");
        if (review.signals && review.signals.alias_match) signalLabels.push("alias match");
        if (review.signals && review.signals.token_subset) signalLabels.push("shared base name");
        if (review.signals && review.signals.same_store_section) signalLabels.push("same store section");
        signalLabels.forEach((label) => {
            const chip = document.createElement("span");
            chip.textContent = label;
            signals.appendChild(chip);
        });

        const actions = document.createElement("div");
        actions.className = "master-data-duplicate-actions";
        const suggested = Number(review.suggested_target_id) === Number(review.right.ingredient_id)
            ? review.right
            : review.left;
        const alternate = suggested === review.left ? review.right : review.left;
        card.dataset.suggestedTargetName = text(suggested.name);
        card.dataset.suggestedSourceName = text(alternate.name);
        const mergeSuggested = masterDataDuplicateAction(
            `Merge into ${suggested.name}`,
            "merge",
            review,
            suggested,
            review.classification === "duplicate" ? "primary" : ""
        );
        const mergeAlternate = masterDataDuplicateAction(`Merge into ${alternate.name}`, "merge", review, alternate);
        mergeSuggested.setAttribute("aria-pressed", "true");
        mergeAlternate.setAttribute("aria-pressed", "false");
        if (review.merge_blocked) {
            [mergeSuggested, mergeAlternate].forEach((mergeButton) => {
                mergeButton.disabled = true;
                mergeButton.title = "Repair the suspicious recipe references before merging this pair.";
            });
        }
        const related = masterDataDuplicateAction(
            "Related variant",
            "related",
            review,
            null,
            review.classification === "related" ? "primary" : ""
        );
        const notDuplicate = masterDataDuplicateAction(
            "Not a duplicate",
            "not_duplicate",
            review,
            null,
            review.classification === "different" ? "primary" : ""
        );
        actions.append(mergeSuggested, mergeAlternate, related, notDuplicate);
        card.append(header, comparison, reason);
        if (dataQualityWarning) card.appendChild(dataQualityWarning);
        if (signalLabels.length) card.appendChild(signals);
        card.appendChild(actions);
        return card;
    }

    function renderMasterDataDuplicateReviews(reviews) {
        const els = masterDataDuplicateElements();
        if (!els.list) return;
        els.list.replaceChildren();
        const rows = Array.isArray(reviews) ? reviews : [];
        if (els.toolbar) els.toolbar.hidden = !rows.length;
        if (!rows.length) {
            const empty = document.createElement("div");
            empty.className = "master-data-duplicate-empty";
            empty.textContent = "No unresolved duplicate suggestions.";
            els.list.appendChild(empty);
            updateMasterDataDuplicateSelectionState();
            return;
        }
        rows.forEach((review) => els.list.appendChild(masterDataDuplicateCard(review)));
        updateMasterDataDuplicateSelectionState();
    }

    function masterDataDuplicateCards() {
        const els = masterDataDuplicateElements();
        return els.list
            ? Array.from(els.list.querySelectorAll(".master-data-duplicate-card[data-review-id]"))
            : [];
    }

    function selectedMasterDataDuplicateCards() {
        return masterDataDuplicateCards().filter((card) => {
            const checkbox = card.querySelector("[data-master-duplicate-select]");
            return checkbox && checkbox.checked;
        });
    }

    function updateMasterDataDuplicateSelectionState() {
        const els = masterDataDuplicateElements();
        if (!els.panel) return;
        const cards = masterDataDuplicateCards();
        const selected = selectedMasterDataDuplicateCards();
        const busy = els.panel.getAttribute("aria-busy") === "true";
        cards.forEach((card) => {
            const checkbox = card.querySelector("[data-master-duplicate-select]");
            card.classList.toggle("is-selected", Boolean(checkbox && checkbox.checked));
            if (checkbox) checkbox.disabled = busy;
        });
        if (els.toolbar) els.toolbar.hidden = !cards.length;
        if (els.selectionCount) {
            els.selectionCount.textContent = `${selected.length} selected`;
        }
        if (els.selectHighConfidence) {
            const highConfidenceCount = cards.filter(
                (card) => card.dataset.highConfidenceDuplicate === "true"
            ).length;
            els.selectHighConfidence.textContent = highConfidenceCount
                ? `Select ${highConfidenceCount} high-confidence duplicate${highConfidenceCount === 1 ? "" : "s"}`
                : "No high-confidence duplicates";
        }
        [els.selectHighConfidence, els.selectAll, els.selectNone].forEach((button) => {
            if (button) button.disabled = busy || !cards.length;
        });
        Array.from(els.undoMergeButtons || []).forEach((button) => {
            button.disabled = busy
                || els.panel.dataset.scope === "all"
                || button.dataset.undoAvailable !== "true";
        });
        Array.from(els.reviewHistoryButtons || []).forEach((button) => {
            button.disabled = busy || els.panel.dataset.scope === "all";
        });
        Array.from(els.bulkActions || []).forEach((button) => {
            const action = text(button.dataset.masterDuplicateBulkAction).trim();
            const includesBlockedMerge = selected.some((card) => card.dataset.mergeBlocked === "true");
            const includesUnsafeMerge = selected.some((card) => card.dataset.highConfidenceDuplicate !== "true");
            button.disabled = busy || !selected.length || (action === "merge" && includesUnsafeMerge);
            if (action === "merge") {
                button.title = includesBlockedMerge
                    ? "Repair suspicious recipe references before bulk merging these pairs."
                    : includesUnsafeMerge
                    ? "Bulk merge is available only for ≥98% singular/plural or alias matches."
                    : "Merge each selected pair into its suggested survivor.";
            }
        });
    }

    function selectMasterDataDuplicateCards(mode) {
        const cards = masterDataDuplicateCards();
        cards.forEach((card) => {
            const checkbox = card.querySelector("[data-master-duplicate-select]");
            if (!checkbox) return;
            if (mode === "high-confidence") {
                checkbox.checked = card.dataset.highConfidenceDuplicate === "true";
            } else {
                checkbox.checked = mode === "all";
            }
        });
        updateMasterDataDuplicateSelectionState();
        const selectedCount = selectedMasterDataDuplicateCards().length;
        if (mode === "high-confidence") {
            setMasterDataDuplicateStatus(
                selectedCount
                    ? `Selected ${selectedCount} high-confidence singular/plural or alias match${selectedCount === 1 ? "" : "es"}.`
                    : "No high-confidence duplicates are currently available."
            );
        }
    }

    function masterDataDuplicateBulkDecisions(cards, action) {
        return cards.map((card) => ({
            review_id: Number(card.dataset.reviewId) || 0,
            action,
            target_ingredient_id: action === "merge"
                ? Number(card.dataset.suggestedTargetId) || null
                : null,
        }));
    }

    function setMasterDataDuplicateBulkBusy(busy, action = "") {
        const els = masterDataDuplicateElements();
        if (!els.panel) return;
        els.panel.setAttribute("aria-busy", busy ? "true" : "false");
        Array.from(els.scanButtons || []).forEach((button) => {
            button.disabled = busy || els.panel.dataset.scope === "all";
        });
        masterDataDuplicateCards().forEach((card) => {
            card.querySelectorAll("button").forEach((button) => {
                const blockedMerge = card.dataset.mergeBlocked === "true"
                    && button.dataset.masterDuplicateDecision === "merge";
                button.disabled = busy || blockedMerge;
            });
        });
        Array.from(els.bulkActions || []).forEach((button) => {
            if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent;
            const buttonAction = text(button.dataset.masterDuplicateBulkAction).trim();
            button.textContent = busy && buttonAction === action
                ? "Applying selected decisions..."
                : button.dataset.defaultLabel;
        });
        updateMasterDataDuplicateSelectionState();
    }

    async function applyMasterDataDuplicateBulkAction(button) {
        const els = masterDataDuplicateElements();
        const action = text(button.dataset.masterDuplicateBulkAction).trim();
        const selected = selectedMasterDataDuplicateCards();
        if (!els.panel || !selected.length || !action) return;
        if (action === "merge") {
            if (selected.some((card) => card.dataset.mergeBlocked === "true")) {
                setMasterDataDuplicateStatus(
                    "Repair suspicious recipe references before bulk merging these pairs.",
                    "warning"
                );
                return;
            }
            if (selected.some((card) => card.dataset.highConfidenceDuplicate !== "true")) {
                setMasterDataDuplicateStatus(
                    "Bulk merge is limited to ≥98% singular/plural or alias matches. Adjust the selection and try again.",
                    "warning"
                );
                return;
            }
            if (changedStoreSectionForms().length) {
                setMasterDataDuplicateStatus("Save your pending ingredient edits before merging records.", "warning");
                return;
            }
        }

        setMasterDataDuplicateBulkBusy(true, action);
        setMasterDataDuplicateStatus(`Applying ${selected.length} selected review decisions...`);
        try {
            const response = await fetch(text(els.panel.dataset.bulkDecisionUrl), {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    decisions: masterDataDuplicateBulkDecisions(selected, action),
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "Bulk review decisions could not be applied.");
            }
            if (Number(data.merged_count) > 0) {
                const mergedResults = Array.isArray(data.results)
                    ? data.results.filter((result) => result && result.ok && result.merge)
                    : [];
                const latestMerge = mergedResults.length
                    ? mergedResults[mergedResults.length - 1].merge
                    : null;
                await refreshAfterMasterDataDuplicateMerge(
                    data.message || "Bulk merge complete.",
                    Number(data.failed_count) > 0 ? "warning" : "",
                    latestMerge
                );
                return;
            }
            await loadMasterDataDuplicateReviews();
            setMasterDataDuplicateStatus(
                data.message || "Bulk review decisions saved.",
                Number(data.failed_count) > 0 ? "warning" : ""
            );
        } catch (error) {
            setMasterDataDuplicateStatus(error.message || "Bulk review decisions could not be applied.", "error");
        } finally {
            setMasterDataDuplicateBulkBusy(false);
        }
    }

    function duplicateReviewsUrl() {
        const els = masterDataDuplicateElements();
        const url = new URL(text(els.panel && els.panel.dataset.reviewsUrl), window.location.origin);
        const context = masterDataDuplicateRequestContext();
        if (context.scope) url.searchParams.set("scope", context.scope);
        if (context.user_id) url.searchParams.set("user_id", context.user_id);
        return url.toString();
    }

    async function loadMasterDataDuplicateReviews() {
        const els = masterDataDuplicateElements();
        if (!els.panel || !els.list || els.panel.dataset.scope === "all") return false;
        try {
            const response = await fetch(duplicateReviewsUrl(), {
                headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "Saved duplicate reviews could not be loaded.");
            }
            renderMasterDataDuplicateReviews(data.reviews);
            updateMasterDataDuplicateScanState(data.scan);
            setMasterDataDuplicateStatus(
                data.review_count
                    ? `${data.review_count} ingredient pair${data.review_count === 1 ? "" : "s"} waiting for your decision.${masterDataDuplicateScanSuffix(data.scan)}`
                    : `No unresolved suggestions. Run a scan whenever your ingredient master data changes.${masterDataDuplicateScanSuffix(data.scan)}`
            );
            return true;
        } catch (error) {
            renderMasterDataDuplicateReviews([]);
            setMasterDataDuplicateStatus(error.message || "Saved duplicate reviews could not be loaded.", "error");
            return false;
        }
    }

    async function scanMasterDataDuplicates() {
        const els = masterDataDuplicateElements();
        if (!els.panel || !els.scan || !els.panel.dataset.scanUrl) return;
        if (changedStoreSectionForms().length) {
            setMasterDataDuplicateStatus("Save your pending ingredient edits before running a duplicate scan.", "warning");
            return;
        }
        setMasterDataDuplicateBusy(
            true,
            "Checking likely pairs and asking AI to classify and independently explain them..."
        );
        try {
            const response = await fetch(els.panel.dataset.scanUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify(masterDataDuplicateRequestContext()),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "Potential duplicates could not be reviewed.");
            }
            renderMasterDataDuplicateReviews(data.reviews);
            updateMasterDataDuplicateScanState(data.scan);
            const baseMessage = data.review_count
                ? `Found ${data.review_count} pair${data.review_count === 1 ? "" : "s"} for your review.`
                : `Scanned ${data.scanned_count || 0} ingredients and found no unresolved pairs.`;
            setMasterDataDuplicateStatus(
                `${baseMessage}${masterDataDuplicateScanSuffix(data.scan)}${data.warning ? ` ${data.warning}` : ""}`,
                data.warning ? "warning" : ""
            );
        } catch (error) {
            setMasterDataDuplicateStatus(error.message || "Potential duplicates could not be reviewed.", "error");
        } finally {
            setMasterDataDuplicateBusy(false);
        }
    }

    async function generateMasterDataAiSecondOpinion(button) {
        const els = masterDataDuplicateElements();
        const panel = button && button.closest
            ? button.closest(".master-data-ai-second-opinion")
            : null;
        const reviewId = Number(button && button.dataset.reviewId) || 0;
        if (!els.panel || !panel || !reviewId || !els.panel.dataset.aiSecondOpinionUrl) return;

        const previousStatus = text(panel.dataset.opinionStatus).toLowerCase();
        renderMasterDataAiSecondOpinion(panel, { status: "loading" });
        const requestUrl = text(els.panel.dataset.aiSecondOpinionUrl)
            .replace("/0/ai-second-opinion", `/${reviewId}/ai-second-opinion`);
        try {
            const response = await fetch(requestUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({ force: previousStatus === "ready" || previousStatus === "stale" }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "AI second opinion could not be generated.");
            }
            renderMasterDataAiSecondOpinion(panel, data.ai_second_opinion);
        } catch (error) {
            const message = error && error.message
                ? error.message
                : "AI second opinion could not be generated.";
            renderMasterDataAiSecondOpinion(panel, { status: "unavailable", message });
            setMasterDataDuplicateStatus(message, "error");
        }
    }

    async function decideMasterDataDuplicate(button) {
        const els = masterDataDuplicateElements();
        const action = text(button.dataset.masterDuplicateDecision).trim();
        const reviewId = text(button.dataset.reviewId).trim();
        if (!els.panel || !action || !reviewId) return;
        if (action === "merge") {
            setMasterDataDuplicateSuggestedSurvivor(button);
            if (changedStoreSectionForms().length) {
                setMasterDataDuplicateStatus("Save your pending ingredient edits before merging records.", "warning");
                return;
            }
        }

        const card = button.closest(".master-data-duplicate-card");
        if (card) card.setAttribute("aria-busy", "true");
        if (card) card.querySelectorAll("button").forEach((actionButton) => { actionButton.disabled = true; });
        const decisionUrl = text(els.panel.dataset.decisionUrl).replace("/0/decision", `/${reviewId}/decision`);
        try {
            const response = await fetch(decisionUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    action,
                    target_ingredient_id: text(button.dataset.targetIngredientId).trim() || null,
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "That review decision could not be saved.");
            }
            if (action === "merge") {
                await refreshAfterMasterDataDuplicateMerge(
                    data.message || "Ingredient merge complete.",
                    "",
                    data.merge || null
                );
                return;
            }
            if (card) card.remove();
            const remaining = els.list.querySelectorAll(".master-data-duplicate-card[data-review-id]").length;
            if (!remaining) renderMasterDataDuplicateReviews([]);
            updateMasterDataDuplicateSelectionState();
            setMasterDataDuplicateStatusWithUndo(
                data.message || "Review decision saved.",
                reviewId
            );
        } catch (error) {
            if (card) card.removeAttribute("aria-busy");
            if (card) {
                card.querySelectorAll("button").forEach((actionButton) => {
                    const blockedMerge = card.dataset.mergeBlocked === "true"
                        && actionButton.dataset.masterDuplicateDecision === "merge";
                    actionButton.disabled = blockedMerge;
                });
            }
            setMasterDataDuplicateStatus(error.message || "That review decision could not be saved.", "error");
        }
    }

    function initMasterDataDuplicateReview() {
        const els = masterDataDuplicateElements();
        if (!els.panel) return;
        Array.from(els.scanButtons || []).forEach((button) => {
            button.addEventListener("click", scanMasterDataDuplicates);
        });
        Array.from(els.undoMergeButtons || []).forEach((button) => {
            button.addEventListener("click", () => void openMasterDataUndoPreview());
        });
        Array.from(els.reviewHistoryButtons || []).forEach((button) => {
            button.addEventListener("click", () => void openMasterDataReviewHistory());
        });
        if (els.selectHighConfidence) {
            els.selectHighConfidence.addEventListener("click", () => selectMasterDataDuplicateCards("high-confidence"));
        }
        if (els.selectAll) {
            els.selectAll.addEventListener("click", () => selectMasterDataDuplicateCards("all"));
        }
        if (els.selectNone) {
            els.selectNone.addEventListener("click", () => selectMasterDataDuplicateCards("none"));
        }
        Array.from(els.bulkActions || []).forEach((button) => {
            button.addEventListener("click", () => void applyMasterDataDuplicateBulkAction(button));
        });
        if (els.list) {
            els.list.addEventListener("click", (event) => {
                const aiSecondOpinionButton = event.target && event.target.closest
                    ? event.target.closest("[data-master-duplicate-ai-second-opinion]")
                    : null;
                if (aiSecondOpinionButton) {
                    event.preventDefault();
                    void generateMasterDataAiSecondOpinion(aiSecondOpinionButton);
                    return;
                }
                const referenceButton = event.target && event.target.closest
                    ? event.target.closest("[data-master-duplicate-references-open]")
                    : null;
                if (referenceButton) {
                    event.preventDefault();
                    void openMasterDataDuplicateReferences(referenceButton);
                    return;
                }
                const button = event.target && event.target.closest
                    ? event.target.closest("[data-master-duplicate-decision]")
                    : null;
                if (button) void decideMasterDataDuplicate(button);
            });
            els.list.addEventListener("change", (event) => {
                const checkbox = event.target && event.target.closest
                    ? event.target.closest("[data-master-duplicate-select]")
                    : null;
                if (checkbox) updateMasterDataDuplicateSelectionState();
            });
        }
        if (els.panel.dataset.scope === "all") {
            setMasterDataDuplicateStatus("Select one workspace to load or create duplicate suggestions.", "warning");
        } else {
            void loadMasterDataDuplicateReviews();
        }

        const referenceEls = masterDataDuplicateReferenceElements();
        Array.from(referenceEls.closeButtons || []).forEach((button) => {
            button.addEventListener("click", closeMasterDataDuplicateReferences);
        });
        if (referenceEls.dialog) {
            referenceEls.dialog.addEventListener("cancel", (event) => {
                event.preventDefault();
                closeMasterDataDuplicateReferences();
            });
            referenceEls.dialog.addEventListener("click", (event) => {
                if (event.target === referenceEls.dialog) closeMasterDataDuplicateReferences();
            });
        }

        const undoPreviewEls = masterDataUndoPreviewElements();
        Array.from(undoPreviewEls.closeButtons || []).forEach((button) => {
            button.addEventListener("click", closeMasterDataUndoPreview);
        });
        if (undoPreviewEls.confirm) {
            undoPreviewEls.confirm.addEventListener("click", () => {
                void undoLastMasterDataIngredientMerge();
            });
        }
        if (undoPreviewEls.dialog) {
            undoPreviewEls.dialog.addEventListener("cancel", (event) => {
                event.preventDefault();
                closeMasterDataUndoPreview();
            });
            undoPreviewEls.dialog.addEventListener("click", (event) => {
                if (event.target === undoPreviewEls.dialog) closeMasterDataUndoPreview();
            });
        }

        const reviewHistoryEls = masterDataReviewHistoryElements();
        Array.from(reviewHistoryEls.closeButtons || []).forEach((button) => {
            button.addEventListener("click", closeMasterDataReviewHistory);
        });
        if (reviewHistoryEls.list) {
            reviewHistoryEls.list.addEventListener("click", (event) => {
                const restoreButton = event.target && event.target.closest
                    ? event.target.closest("[data-master-review-history-restore]")
                    : null;
                if (restoreButton) void restoreMasterDataDuplicateDecision(restoreButton);
            });
        }
        if (reviewHistoryEls.dialog) {
            reviewHistoryEls.dialog.addEventListener("cancel", (event) => {
                event.preventDefault();
                closeMasterDataReviewHistory();
            });
            reviewHistoryEls.dialog.addEventListener("click", (event) => {
                if (event.target === reviewHistoryEls.dialog) closeMasterDataReviewHistory();
            });
        }
    }

    function renderProgress(form, progress) {
        const els = elementsFor(form);
        if (!els.panel || !progress) {
            return;
        }

        const status = text(progress.status || "running").toLowerCase();
        els.panel.hidden = false;
        els.panel.setAttribute("aria-busy", status === "running" || status === "starting" ? "true" : "false");

        if (els.summary) {
            els.summary.textContent = text(progress.summary || "Backfill is running.");
        }
        if (els.state) {
            els.state.className = `master-data-backfill-state ${status}`;
            els.state.textContent = stateLabel(status);
        }
        if (els.bar) {
            els.bar.style.width = `${progressPercent(progress)}%`;
        }
        if (els.users) {
            els.users.textContent = `${Number(progress.users_completed) || 0} / ${Number(progress.users_total) || 0}`;
        }
        if (els.recipes) {
            els.recipes.textContent = `${Number(progress.recipes_completed) || 0} / ${Number(progress.recipes_total) || 0}`;
        }
        if (els.ingredients) {
            els.ingredients.textContent = text(Number(progress.ingredient_rows) || 0);
        }
        if (els.equipment) {
            els.equipment.textContent = text(Number(progress.equipment_rows) || 0);
        }

        const items = Array.isArray(progress.items) ? progress.items : [];
        const currentItem = items.find((item) => item.key && item.key === progress.current_item_key)
            || [...items].reverse().find((item) => item.state === "running");
        if (els.current) {
            els.current.hidden = !currentItem || status === "complete" || status === "skipped";
        }
        if (currentItem) {
            if (els.currentTitle) {
                els.currentTitle.textContent = text(currentItem.label || "Recipe");
            }
            if (els.currentUrl) {
                els.currentUrl.textContent = text(currentItem.recipe_url || currentItem.user_id || "");
            }
        }

        if (els.items) {
            const visibleItems = [...items].reverse();
            els.items.replaceChildren(...visibleItems.map(renderProgressItem));
        }
    }

    function renderImageStarting(form) {
        const els = imageElementsFor(form);
        if (!els.panel) {
            return;
        }
        els.panel.hidden = false;
        els.panel.setAttribute("aria-busy", "true");
        if (els.summary) {
            els.summary.textContent = "Submitting image generation job.";
        }
        if (els.state) {
            els.state.className = "master-data-backfill-state running";
            els.state.textContent = "Starting";
        }
        if (els.bar) {
            els.bar.style.width = "6%";
        }
        if (els.total) {
            els.total.textContent = "0";
        }
        if (els.complete) {
            els.complete.textContent = "0";
        }
        if (els.generated) {
            els.generated.textContent = "0";
        }
        if (els.failed) {
            els.failed.textContent = "0";
        }
        if (els.current) {
            els.current.hidden = true;
        }
        if (els.items) {
            els.items.replaceChildren();
        }
    }

    function renderImageProgress(form, progress) {
        const els = imageElementsFor(form);
        if (!els.panel || !progress) {
            return;
        }

        const status = text(progress.status || "running").toLowerCase();
        els.panel.hidden = false;
        els.panel.setAttribute("aria-busy", progressIsActive(progress) ? "true" : "false");

        if (els.summary) {
            els.summary.textContent = text(progress.summary || "Image generation is running.");
        }
        if (els.state) {
            els.state.className = `master-data-backfill-state ${status}`;
            els.state.textContent = stateLabel(status);
        }
        if (els.bar) {
            els.bar.style.width = `${imageProgressPercent(progress)}%`;
        }
        if (els.total) {
            els.total.textContent = text(Number(progress.total) || 0);
        }
        if (els.complete) {
            els.complete.textContent = text(Number(progress.completed) || 0);
        }
        if (els.generated) {
            els.generated.textContent = text(Number(progress.generated) || 0);
        }
        if (els.failed) {
            els.failed.textContent = text(Number(progress.failed) || 0);
        }

        const currentName = text(progress.current_record_name || "");
        if (els.current) {
            els.current.hidden = !currentName || status === "complete" || status === "failed";
        }
        if (currentName) {
            if (els.currentTitle) {
                els.currentTitle.textContent = currentName;
            }
            if (els.currentMeta) {
                els.currentMeta.textContent = progress.current_record_id
                    ? `Record ${progress.current_record_id}`
                    : text(progress.user_id || "");
            }
        }

        if (els.items) {
            const items = Array.isArray(progress.items) ? progress.items : [];
            els.items.replaceChildren(...[...items].reverse().map(renderImageProgressItem));
        }
    }

    function renderError(form, message) {
        const els = elementsFor(form);
        if (!els.panel) {
            return;
        }
        els.panel.hidden = false;
        els.panel.setAttribute("aria-busy", "false");
        if (els.summary) {
            els.summary.textContent = message || "Backfill failed.";
        }
        if (els.state) {
            els.state.className = "master-data-backfill-state failed";
            els.state.textContent = "Failed";
        }
    }

    function renderImageError(form, message) {
        const els = imageElementsFor(form);
        if (!els.panel) {
            return;
        }
        els.panel.hidden = false;
        els.panel.setAttribute("aria-busy", "false");
        if (els.summary) {
            els.summary.textContent = message || "Image generation failed.";
        }
        if (els.state) {
            els.state.className = "master-data-backfill-state failed";
            els.state.textContent = "Failed";
        }
    }

    function progressIsActive(progress) {
        const status = text(progress && progress.status).toLowerCase();
        return status === "starting" || status === "running";
    }

    function schedulePoll(form, jobId, delay) {
        window.clearTimeout(pollTimer);
        pollTimer = window.setTimeout(() => pollProgress(form, jobId), delay);
    }

    function scheduleImagePoll(form, jobId, delay) {
        window.clearTimeout(imagePollTimer);
        imagePollTimer = window.setTimeout(() => pollImageProgress(form, jobId), delay);
    }

    async function pollProgress(form, jobId) {
        if (!jobId || jobId !== activeJobId) {
            return;
        }

        const statusUrl = form.dataset.backfillStatusUrl;
        if (!statusUrl) {
            return;
        }

        const url = new URL(statusUrl, window.location.href);
        url.searchParams.set("job_id", jobId);

        try {
            const response = await fetch(url.toString(), {
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "fetch",
                },
            });
            if (response.ok) {
                const data = await response.json();
                if (data.progress) {
                    renderProgress(form, data.progress);
                    if (progressIsActive(data.progress)) {
                        schedulePoll(form, jobId, POLL_INTERVAL_MS);
                    }
                    return;
                }
            }
        } catch (error) {
            // The submit request will surface the final failure if polling misses a beat.
        }

        if (jobId === activeJobId) {
            schedulePoll(form, jobId, POLL_INTERVAL_MS);
        }
    }

    async function pollImageProgress(form, jobId) {
        if (!jobId || jobId !== activeImageJobId) {
            return;
        }

        const statusUrl = form.dataset.imageStatusUrl;
        if (!statusUrl) {
            return;
        }

        const url = new URL(statusUrl, window.location.href);
        url.searchParams.set("job_id", jobId);

        try {
            const response = await fetch(url.toString(), {
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "fetch",
                },
            });
            if (response.ok) {
                const data = await response.json();
                if (data.progress) {
                    renderImageProgress(form, data.progress);
                    if (progressIsActive(data.progress)) {
                        scheduleImagePoll(form, jobId, POLL_INTERVAL_MS);
                    } else {
                        setImageBusy(form, false);
                        if (data.progress.status === "complete") {
                            window.clearTimeout(imageRefreshTimer);
                            imageRefreshTimer = window.setTimeout(() => {
                                window.location.assign(form.dataset.imageRedirectUrl || window.location.href);
                            }, REFRESH_DELAY_MS);
                        }
                    }
                    return;
                }
            }
        } catch (error) {
            // Keep polling; the submit response or next status check can surface final state.
        }

        if (jobId === activeImageJobId) {
            scheduleImagePoll(form, jobId, POLL_INTERVAL_MS);
        }
    }

    async function submitBackfill(event) {
        event.preventDefault();

        const form = event.currentTarget;
        if (form.getAttribute("aria-busy") === "true") {
            return;
        }

        const jobId = makeJobId();
        activeJobId = jobId;
        const formData = new FormData(form);
        formData.set("job_id", jobId);

        setBusy(form, true);
        renderStarting(form);
        schedulePoll(form, jobId, 250);

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "fetch",
                },
            });
            const data = await response.json().catch(() => ({}));
            if (jobId !== activeJobId) {
                return;
            }
            if (data.progress) {
                renderProgress(form, data.progress);
            }
            if (!response.ok || data.ok === false) {
                renderError(form, data.message || data.error || "Backfill failed.");
                setBusy(form, false);
                return;
            }
            window.clearTimeout(pollTimer);
            if (data.redirect_url) {
                window.setTimeout(() => {
                    window.location.assign(data.redirect_url);
                }, REFRESH_DELAY_MS);
            } else {
                setBusy(form, false);
            }
        } catch (error) {
            if (jobId === activeJobId) {
                renderError(form, error && error.message ? error.message : "Backfill failed.");
                setBusy(form, false);
            }
        }
    }

    async function submitImageGeneration(event) {
        event.preventDefault();

        const form = event.currentTarget;
        if (form.getAttribute("aria-busy") === "true") {
            return;
        }

        const jobId = makeJobId("master-images");
        activeImageJobId = jobId;
        syncImageFormFromFilters(form);
        const formData = new FormData(form);
        formData.set("job_id", jobId);

        setImageBusy(form, true);
        renderImageStarting(form);
        scheduleImagePoll(form, jobId, 250);

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "fetch",
                },
            });
            const data = await response.json().catch(() => ({}));
            if (jobId !== activeImageJobId) {
                return;
            }
            if (data.redirect_url) {
                form.dataset.imageRedirectUrl = data.redirect_url;
            }
            if (data.progress) {
                renderImageProgress(form, data.progress);
            }
            if (!response.ok || data.ok === false) {
                renderImageError(form, data.message || data.error || "Image generation failed.");
                setImageBusy(form, false);
                return;
            }
            if (data.progress && !progressIsActive(data.progress)) {
                window.clearTimeout(imagePollTimer);
                setImageBusy(form, false);
                if (data.progress.status === "complete") {
                    window.clearTimeout(imageRefreshTimer);
                    imageRefreshTimer = window.setTimeout(() => {
                        window.location.assign(form.dataset.imageRedirectUrl || window.location.href);
                    }, REFRESH_DELAY_MS);
                }
            }
        } catch (error) {
            if (jobId === activeImageJobId) {
                renderImageError(form, error && error.message ? error.message : "Image generation failed.");
                setImageBusy(form, false);
            }
        }
    }

    const MISC_REVIEW_STORE_SECTIONS = [
        "PRODUCE",
        "MEAT & SEAFOOD",
        "DAIRY & EGGS",
        "FROZEN",
        "DRY GOODS",
        "PASTA, RICE & GRAINS",
        "BAKING",
        "CANNED",
        "SAUCES & CONDIMENTS",
        "SNACKS",
        "BEVERAGES",
        "SPICES & SEASONINGS",
        "OILS & VINEGARS",
        "BAKERY",
        "DELI",
        "HOUSEHOLD",
        "PERSONAL CARE",
        "PET SUPPLIES",
        "MISC",
    ];

    function friendlyIngredientStoreSection(value) {
        const section = text(value).trim().toUpperCase();
        const labels = {
            "PRODUCE": "Produce",
            "MEAT & SEAFOOD": "Meat & Seafood",
            "DAIRY & EGGS": "Dairy",
            "FROZEN": "Frozen",
            "DRY GOODS": "Dry Goods",
            "PASTA, RICE & GRAINS": "Pasta, Rice & Grains",
            "BAKING": "Baking",
            "CANNED": "Canned Goods",
            "SAUCES & CONDIMENTS": "Sauces & Condiments",
            "SNACKS": "Snacks",
            "BEVERAGES": "Beverages",
            "SPICES & SEASONINGS": "Spices",
            "OILS & VINEGARS": "Oils & Vinegars",
            "BAKERY": "Bakery",
            "DELI": "Deli",
            "HOUSEHOLD": "Household",
            "PERSONAL CARE": "Personal Care",
            "PET SUPPLIES": "Pet Supplies",
            "MISC": "Misc",
        };
        return labels[section] || text(value).trim() || "Misc";
    }

    function miscReviewDisplayName(value) {
        const name = text(value).trim();
        return name ? `${name.charAt(0).toUpperCase()}${name.slice(1)}` : "Ingredient";
    }

    function miscReviewSectionPill(section, className = "is-proposed") {
        const pill = document.createElement("span");
        pill.className = `master-data-section-pill ${className}`;
        pill.textContent = friendlyIngredientStoreSection(section);
        return pill;
    }

    function miscReviewConfidence(value) {
        const confidence = Number(value);
        return Number.isFinite(confidence) ? `${Math.round(confidence * 100)}% confidence` : "";
    }

    function miscReviewDetails(parts) {
        const values = parts.filter(Boolean);
        if (!values.length) return null;
        const details = document.createElement("details");
        details.className = "master-data-misc-reclassification-details";
        const summary = document.createElement("summary");
        summary.textContent = "Classification details";
        const detailText = document.createElement("code");
        detailText.textContent = values.join(" · ");
        details.append(summary, detailText);
        return details;
    }

    function miscReviewRowsFromPreview(data) {
        const changes = Array.isArray(data && data.changes) ? data.changes : [];
        return changes.map((change) => ({
            ingredientId: Number(change.ingredient_id) || 0,
            ingredient: text(change.ingredient || change.normalized_name || "Ingredient"),
            normalizedName: text(change.normalized_name),
            form: text(change.form),
            deterministic: {
                storeSection: text(change.proposed_store_section || "MISC"),
                confidence: Number(change.store_section_confidence),
                reason: text(change.reason || "Matched a store-section classification rule."),
                rule: text(change.rule),
                source: text(change.store_section_source),
            },
            ai: null,
            decisionSection: text(change.proposed_store_section || "MISC"),
            decisionSource: "deterministic",
            requiresDecision: false,
        }));
    }

    function miscReviewDecisionSource(row, section) {
        if (row.deterministic && section === row.deterministic.storeSection) return "deterministic";
        if (row.ai && section === row.ai.storeSection) return "ai";
        return section === "MISC" ? "keep_misc" : "manual";
    }

    function miscReviewDecisionSelect(panel, row) {
        const wrap = document.createElement("div");
        wrap.className = "master-data-misc-review-cell master-data-misc-decision is-decision";
        const label = document.createElement("label");
        label.className = "master-data-misc-decision-control";
        const labelText = document.createElement("span");
        labelText.className = "sr-only";
        labelText.textContent = `Final store section for ${miscReviewDisplayName(row.ingredient)}`;
        const select = document.createElement("select");
        select.dataset.masterMiscDecision = String(row.ingredientId);
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = row.deterministic ? "Choose a final result" : "Skip for now";
        select.appendChild(placeholder);

        const sections = [];
        if (row.deterministic) sections.push(row.deterministic.storeSection);
        if (row.ai && row.ai.storeSection !== "MISC" && !sections.includes(row.ai.storeSection)) {
            sections.push(row.ai.storeSection);
        }
        sections.forEach((section) => {
            const option = document.createElement("option");
            option.value = section;
            const agrees = row.ai && row.deterministic && row.ai.storeSection === row.deterministic.storeSection;
            const sourceLabel = agrees
                ? "rules + AI"
                : row.deterministic && section === row.deterministic.storeSection
                    ? "rule-based"
                    : "AI opinion";
            option.textContent = `${friendlyIngredientStoreSection(section)} (${sourceLabel})`;
            select.appendChild(option);
        });
        const otherSections = MISC_REVIEW_STORE_SECTIONS.filter(
            (section) => section !== "MISC" && !sections.includes(section)
        );
        if (otherSections.length) {
            const group = document.createElement("optgroup");
            group.label = "Choose another section";
            otherSections.forEach((section) => {
                const option = document.createElement("option");
                option.value = section;
                option.textContent = friendlyIngredientStoreSection(section);
                group.appendChild(option);
            });
            select.appendChild(group);
        }
        const keep = document.createElement("option");
        keep.value = "MISC";
        keep.textContent = "Keep in Misc";
        select.appendChild(keep);
        select.value = row.decisionSection || "";
        select.addEventListener("change", () => {
            row.decisionSection = select.value;
            row.decisionSource = miscReviewDecisionSource(row, select.value);
            row.requiresDecision = false;
            renderMiscReclassificationRows(panel);
        });
        label.append(labelText, select);
        wrap.appendChild(label);
        if (row.requiresDecision && !row.decisionSection) {
            const warning = document.createElement("small");
            warning.textContent = "AI disagrees—choose the final section.";
            wrap.appendChild(warning);
        }
        return wrap;
    }

    function miscReviewIngredientCell(row) {
        const cell = document.createElement("div");
        cell.className = "master-data-misc-review-cell is-ingredient";
        const name = document.createElement("strong");
        name.textContent = miscReviewDisplayName(row.ingredient);
        const current = document.createElement("span");
        current.className = "master-data-misc-current-label";
        current.textContent = "Currently: Misc";
        cell.append(name, current);
        return cell;
    }

    function miscReviewDeterministicCell(row) {
        const cell = document.createElement("div");
        cell.className = "master-data-misc-review-cell is-classification";
        if (!row.deterministic) {
            const empty = document.createElement("span");
            empty.className = "master-data-misc-no-result";
            empty.textContent = "No confident rule match";
            cell.appendChild(empty);
            return cell;
        }
        const result = document.createElement("div");
        result.className = "master-data-misc-classification-result";
        result.appendChild(miscReviewSectionPill(row.deterministic.storeSection));
        const confidence = document.createElement("span");
        confidence.textContent = miscReviewConfidence(row.deterministic.confidence);
        result.appendChild(confidence);
        const reason = document.createElement("p");
        reason.textContent = row.deterministic.reason;
        cell.append(result, reason);
        const details = miscReviewDetails([
            row.deterministic.source ? `Source: ${row.deterministic.source.replaceAll("_", " ")}` : "",
            row.deterministic.rule ? `Rule: ${row.deterministic.rule}` : "",
        ]);
        if (details) cell.appendChild(details);
        return cell;
    }

    function miscReviewAiCell(panel, row) {
        const cell = document.createElement("div");
        cell.className = "master-data-misc-review-cell is-ai";
        if (!row.ai) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "master-data-misc-row-ai-button";
            button.textContent = "Ask AI";
            button.addEventListener("click", () => requestMiscAiSecondOpinions(panel, "all", [row.ingredientId], button));
            cell.appendChild(button);
            return cell;
        }
        const status = document.createElement("span");
        status.className = `master-data-misc-ai-status is-${row.ai.agreement}`;
        status.textContent = row.ai.agreement === "agree"
            ? "Agrees"
            : row.ai.agreement === "disagree"
                ? "Disagrees"
                : "AI suggestion";
        const result = document.createElement("div");
        result.className = "master-data-misc-classification-result";
        result.appendChild(miscReviewSectionPill(row.ai.storeSection, "is-ai"));
        const confidence = document.createElement("span");
        confidence.textContent = miscReviewConfidence(row.ai.confidence);
        result.appendChild(confidence);
        const reason = document.createElement("p");
        reason.textContent = row.ai.reason;
        cell.append(status, result, reason);
        const details = miscReviewDetails([
            row.ai.model ? `Model: ${row.ai.model}` : "",
            row.ai.generatedAt ? `Reviewed: ${row.ai.generatedAt}` : "",
        ]);
        if (details) cell.appendChild(details);
        return cell;
    }

    function renderMiscReclassificationRows(panel) {
        const list = panel.querySelector("[data-master-misc-reclassification-list]");
        const count = panel.querySelector("[data-master-misc-reclassification-count]");
        const empty = panel.querySelector("[data-master-misc-reclassification-empty]");
        const applyButton = panel.querySelector("[data-master-misc-reclassification-apply]");
        const acceptAiButton = panel.querySelector("[data-master-misc-ai-accept]");
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        const rows = Array.isArray(panel.miscReclassificationRows) ? panel.miscReclassificationRows : [];
        if (list) {
            list.replaceChildren();
            rows.forEach((row) => {
                const item = document.createElement("li");
                item.className = "master-data-misc-reclassification-item";
                if (row.ai && row.ai.agreement === "disagree") item.classList.add("has-disagreement");
                item.dataset.ingredientId = String(row.ingredientId);
                item.append(
                    miscReviewIngredientCell(row),
                    miscReviewDeterministicCell(row),
                    miscReviewAiCell(panel, row),
                    miscReviewDecisionSelect(panel, row)
                );
                list.appendChild(item);
            });
            list.hidden = !rows.length;
        }
        if (empty) empty.hidden = Boolean(rows.length);
        const selectedDecisions = rows.filter((row) => row.decisionSection);
        const unresolvedDecisions = rows.filter((row) => row.requiresDecision && !row.decisionSection);
        const unselectedAiSuggestions = rows.filter((row) => row.ai && !row.decisionSection);
        if (count) {
            const unresolvedLabel = panel.miscUnresolvedCount
                ? ` · ${panel.miscUnresolvedCount} without a rule match`
                : "";
            count.textContent = `${rows.length} review row${rows.length === 1 ? "" : "s"}${unresolvedLabel}`;
        }
        panel.dataset.miscPreviewReady = selectedDecisions.length && !unresolvedDecisions.length ? "true" : "false";
        if (applyButton) {
            applyButton.disabled = panel.dataset.miscPreviewReady !== "true";
            applyButton.textContent = selectedDecisions.length
                ? `Apply ${selectedDecisions.length} Decision${selectedDecisions.length === 1 ? "" : "s"}`
                : "Apply Changes";
        }
        if (acceptAiButton) {
            acceptAiButton.disabled = !unselectedAiSuggestions.length;
            acceptAiButton.textContent = unselectedAiSuggestions.length
                ? `Accept ${unselectedAiSuggestions.length} AI Suggestion${unselectedAiSuggestions.length === 1 ? "" : "s"}`
                : "AI Suggestions Selected";
        }
        if (summary && panel.dataset.miscApplied !== "true") {
            summary.textContent = unresolvedDecisions.length
                ? `${unresolvedDecisions.length} AI disagreement${unresolvedDecisions.length === 1 ? " requires" : "s require"} a final decision before applying.`
                : `${selectedDecisions.length} decision${selectedDecisions.length === 1 ? " is" : "s are"} selected. AI suggestions for unresolved ingredients are preselected and remain editable.`;
        }
    }

    function renderMiscReclassification(panel, data) {
        const previewPanel = panel.querySelector("[data-master-misc-reclassification-preview-panel]");
        const suggestedAiButton = panel.querySelector("[data-master-misc-ai-review-suggested]");
        const acceptAiButton = panel.querySelector("[data-master-misc-ai-accept]");
        const unresolvedAiButton = panel.querySelector("[data-master-misc-ai-review-unresolved]");
        panel.miscReclassificationRows = miscReviewRowsFromPreview(data);
        panel.miscUnresolvedCount = Number(data && data.unresolved_count) || 0;
        panel.dataset.miscApplied = data && data.applied ? "true" : "false";
        panel.classList.toggle("is-applied", Boolean(data && data.applied));
        if (previewPanel) previewPanel.hidden = false;
        if (suggestedAiButton) {
            suggestedAiButton.disabled = !panel.miscReclassificationRows.length;
            suggestedAiButton.textContent = "Get AI Second Opinions";
        }
        if (acceptAiButton) {
            acceptAiButton.disabled = true;
            acceptAiButton.textContent = "Accept AI Suggestions";
        }
        if (unresolvedAiButton) {
            unresolvedAiButton.disabled = !panel.miscUnresolvedCount;
            unresolvedAiButton.textContent = panel.miscUnresolvedCount
                ? `Review ${panel.miscUnresolvedCount} Unresolved with AI`
                : "No Unresolved Ingredients";
        }
        renderMiscReclassificationRows(panel);
    }

    function miscReviewDecisionPayload(panel) {
        return (panel.miscReclassificationRows || [])
            .filter((row) => row.decisionSection)
            .map((row) => {
                const opinion = row.decisionSource === "ai"
                    ? row.ai
                    : row.decisionSource === "deterministic"
                        ? row.deterministic
                        : null;
                return {
                    ingredient_id: row.ingredientId,
                    store_section: row.decisionSection,
                    decision_source: row.decisionSource,
                    confidence: opinion ? opinion.confidence : 1,
                    reason: opinion
                        ? opinion.reason
                        : row.decisionSection === "MISC"
                            ? "User confirmed that this ingredient should remain in Misc."
                            : "User selected the final store section during maintenance.",
                };
            });
    }

    function setMiscReviewBusy(panel, busy) {
        panel.setAttribute("aria-busy", busy ? "true" : "false");
        panel.querySelectorAll("button, select").forEach((control) => {
            control.disabled = Boolean(busy);
        });
    }

    function restoreMiscReviewControls(panel) {
        const previewButton = panel.querySelector("[data-master-misc-reclassification-preview]");
        const undoButton = panel.querySelector("[data-master-misc-reclassification-undo]");
        const suggestedAiButton = panel.querySelector("[data-master-misc-ai-review-suggested]");
        const acceptAiButton = panel.querySelector("[data-master-misc-ai-accept]");
        const unresolvedAiButton = panel.querySelector("[data-master-misc-ai-review-unresolved]");
        panel.setAttribute("aria-busy", "false");
        if (previewButton) previewButton.disabled = false;
        if (undoButton) undoButton.disabled = panel.dataset.undoAvailable !== "true";
        if (suggestedAiButton) {
            suggestedAiButton.disabled = !(panel.miscReclassificationRows || []).some((row) => row.deterministic);
        }
        if (acceptAiButton) {
            acceptAiButton.disabled = !(panel.miscReclassificationRows || []).some(
                (row) => row.ai && !row.decisionSection
            );
        }
        if (unresolvedAiButton) unresolvedAiButton.disabled = !panel.miscUnresolvedCount;
        renderMiscReclassificationRows(panel);
    }

    async function requestMiscReclassification(panel, apply) {
        const previewButton = panel.querySelector("[data-master-misc-reclassification-preview]");
        const applyButton = panel.querySelector("[data-master-misc-reclassification-apply]");
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        setMiscReviewBusy(panel, true);
        if (previewButton) previewButton.textContent = apply ? "Preview Changes" : "Previewing...";
        if (applyButton && apply) applyButton.textContent = "Applying...";
        if (summary) summary.textContent = apply ? "Applying reviewed decisions…" : "Reviewing unconfirmed Misc ingredients…";
        try {
            const response = await fetch(panel.dataset.reclassifyUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    apply,
                    ...(apply ? { decisions: miscReviewDecisionPayload(panel) } : {}),
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "Misc ingredient reclassification failed.");
            }
            if (data.applied) {
                panel.dataset.miscApplied = "true";
                panel.dataset.undoAvailable = data.undo_available ? "true" : panel.dataset.undoAvailable;
                if (data.batch_id) panel.dataset.undoBatchId = String(data.batch_id);
                panel.classList.add("is-applied");
                if (summary) summary.textContent = `Applied ${Number(data.changed_count) || 0} reviewed change${Number(data.changed_count) === 1 ? "" : "s"} to Ingredient Master Data.`;
                if (applyButton) {
                    applyButton.textContent = "Applied";
                    applyButton.disabled = true;
                }
                window.setTimeout(() => window.location.reload(), REFRESH_DELAY_MS);
            } else {
                renderMiscReclassification(panel, data);
            }
        } catch (error) {
            panel.dataset.miscPreviewReady = "false";
            if (summary) summary.textContent = error && error.message ? error.message : "Misc ingredient reclassification failed.";
        } finally {
            if (previewButton) {
                previewButton.textContent = "Preview Changes";
            }
            if (panel.dataset.miscApplied !== "true") restoreMiscReviewControls(panel);
        }
    }

    async function requestMiscReclassificationUndo(panel) {
        const undoButton = panel.querySelector("[data-master-misc-reclassification-undo]");
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        if (!undoButton || panel.dataset.undoAvailable !== "true") return;
        const originalLabel = undoButton.textContent;
        setMiscReviewBusy(panel, true);
        undoButton.textContent = "Undoing…";
        if (summary) summary.textContent = "Restoring the previous store-section assignments…";
        try {
            const response = await fetch(panel.dataset.undoUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    batch_id: Number(panel.dataset.undoBatchId) || 0,
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "The last store-section apply could not be undone.");
            }
            panel.dataset.miscUndoComplete = "true";
            panel.dataset.undoAvailable = data.undo_available ? "true" : "false";
            panel.dataset.undoBatchId = data.next_batch && data.next_batch.batch_id
                ? String(data.next_batch.batch_id)
                : "";
            undoButton.textContent = "Undone";
            undoButton.disabled = true;
            if (summary) summary.textContent = data.message || "The previous store-section assignments were restored.";
            window.setTimeout(() => window.location.reload(), REFRESH_DELAY_MS);
        } catch (error) {
            if (summary) {
                summary.textContent = error && error.message
                    ? error.message
                    : "The last store-section apply could not be undone.";
            }
            undoButton.textContent = originalLabel;
        } finally {
            if (panel.dataset.miscUndoComplete !== "true") restoreMiscReviewControls(panel);
        }
    }

    function acceptMiscAiSuggestions(panel) {
        let acceptedCount = 0;
        (panel.miscReclassificationRows || []).forEach((row) => {
            if (!row.ai || row.decisionSection) return;
            row.decisionSection = row.ai.storeSection;
            row.decisionSource = miscReviewDecisionSource(row, row.ai.storeSection);
            row.requiresDecision = false;
            acceptedCount += 1;
        });
        renderMiscReclassificationRows(panel);
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        if (summary && acceptedCount) {
            summary.textContent = `${acceptedCount} AI suggestion${acceptedCount === 1 ? "" : "s"} accepted as final decisions. Review them, then apply the changes.`;
        }
    }

    async function requestMiscAiSecondOpinions(panel, scope, ingredientIds, trigger) {
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        const originalLabel = trigger ? trigger.textContent : "";
        setMiscReviewBusy(panel, true);
        if (trigger) trigger.textContent = "Asking AI…";
        if (summary) summary.textContent = "Getting independent AI store-section opinions…";
        try {
            const response = await fetch(panel.dataset.aiSecondOpinionUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({ scope, ingredient_ids: ingredientIds || [] }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "AI second opinions are unavailable.");
            }
            const rows = panel.miscReclassificationRows || [];
            (Array.isArray(data.opinions) ? data.opinions : []).forEach((opinion) => {
                const ingredientId = Number(opinion.ingredient_id) || 0;
                let row = rows.find((candidate) => candidate.ingredientId === ingredientId);
                if (!row) {
                    row = {
                        ingredientId,
                        ingredient: text(opinion.ingredient || opinion.normalized_name || "Ingredient"),
                        normalizedName: text(opinion.normalized_name),
                        form: "",
                        deterministic: null,
                        ai: null,
                        decisionSection: "",
                        decisionSource: "",
                        requiresDecision: false,
                    };
                    rows.push(row);
                }
                if (!row) return;
                row.ai = {
                    storeSection: text(opinion.store_section),
                    confidence: Number(opinion.confidence),
                    reason: text(opinion.reason),
                    agreement: text(opinion.agreement || "suggestion"),
                    model: text(opinion.model),
                    generatedAt: text(opinion.generated_at),
                };
                if (row.deterministic && row.ai.storeSection !== row.deterministic.storeSection) {
                    row.decisionSection = "";
                    row.decisionSource = "";
                    row.requiresDecision = true;
                } else if (!row.deterministic) {
                    row.decisionSection = row.ai.storeSection;
                    row.decisionSource = miscReviewDecisionSource(row, row.ai.storeSection);
                    row.requiresDecision = false;
                }
            });
            panel.miscReclassificationRows = rows;
            renderMiscReclassificationRows(panel);
            if (summary && Number(data.missing_opinion_count)) {
                summary.textContent = `AI reviewed ${Number(data.opinion_count) || 0} ingredient${Number(data.opinion_count) === 1 ? "" : "s"}; ${Number(data.missing_opinion_count)} did not return a valid opinion.`;
            }
            if (trigger) {
                trigger.textContent = scope === "unresolved"
                    ? `AI Reviewed ${Number(data.opinion_count) || 0} Unresolved`
                    : "AI Opinions Added";
            }
        } catch (error) {
            if (summary) summary.textContent = error && error.message ? error.message : "AI second opinions are unavailable.";
            if (trigger) trigger.textContent = originalLabel;
        } finally {
            restoreMiscReviewControls(panel);
        }
    }

    function initMiscIngredientReclassification() {
        const panel = document.querySelector("[data-master-misc-reclassification]");
        if (!panel || !window.fetch) return;
        const previewButton = panel.querySelector("[data-master-misc-reclassification-preview]");
        const applyButton = panel.querySelector("[data-master-misc-reclassification-apply]");
        const undoButton = panel.querySelector("[data-master-misc-reclassification-undo]");
        const suggestedAiButton = panel.querySelector("[data-master-misc-ai-review-suggested]");
        const acceptAiButton = panel.querySelector("[data-master-misc-ai-accept]");
        const unresolvedAiButton = panel.querySelector("[data-master-misc-ai-review-unresolved]");
        if (previewButton) previewButton.addEventListener("click", () => requestMiscReclassification(panel, false));
        if (undoButton) undoButton.addEventListener("click", () => requestMiscReclassificationUndo(panel));
        if (applyButton) {
            applyButton.addEventListener("click", () => {
                if (panel.dataset.miscPreviewReady === "true") requestMiscReclassification(panel, true);
            });
        }
        if (suggestedAiButton) {
            suggestedAiButton.addEventListener("click", () => {
                const ingredientIds = (panel.miscReclassificationRows || [])
                    .filter((row) => row.deterministic)
                    .map((row) => row.ingredientId);
                requestMiscAiSecondOpinions(panel, "suggested", ingredientIds, suggestedAiButton);
            });
        }
        if (acceptAiButton) {
            acceptAiButton.addEventListener("click", () => acceptMiscAiSuggestions(panel));
        }
        if (unresolvedAiButton) {
            unresolvedAiButton.addEventListener("click", () => {
                requestMiscAiSecondOpinions(panel, "unresolved", [], unresolvedAiButton);
            });
        }
    }

    function initMasterDataPage() {
        initMasterDataReferences();
        initMasterDataThumbnailSizeControls();
        initMasterDataImageLightbox();
        initMasterDataStoreSectionBatchSave();
        initMasterDataIngredientMerge();
        initMasterDataDuplicateReview();
        initMiscIngredientReclassification();

        const form = document.querySelector("[data-master-backfill-form]");
        if (form && window.fetch && window.FormData) {
            form.addEventListener("submit", submitBackfill);
        }

        const imageForm = document.querySelector("[data-master-image-form]");
        if (imageForm && window.fetch && window.FormData) {
            imageForm.addEventListener("submit", submitImageGeneration);
        }
        if (!form && !imageForm) {
            return;
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initMasterDataPage);
    } else {
        initMasterDataPage();
    }
}());
