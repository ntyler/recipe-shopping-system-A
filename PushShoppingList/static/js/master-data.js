(function () {
    const POLL_INTERVAL_MS = 700;
    const REFRESH_DELAY_MS = 1200;
    const MASTER_DATA_THUMBNAIL_SIZE_STORAGE_KEY = "master-data-thumbnail-size";
    const MASTER_DATA_THUMBNAIL_DEFAULT_SIZE = 64;
    const MASTER_DATA_THUMBNAIL_MIN_SIZE = 32;
    const MASTER_DATA_THUMBNAIL_MAX_SIZE = 80;
    const MASTER_DATA_THUMBNAIL_STEP_SIZE = 8;
    let activeJobId = "";
    let pollTimer = null;
    let activeImageJobId = "";
    let imagePollTimer = null;
    let imageRefreshTimer = null;
    let masterDataThumbnailSize = MASTER_DATA_THUMBNAIL_DEFAULT_SIZE;
    let masterDataThumbnailSizeEventsBound = false;

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

    function initMasterDataPage() {
        initMasterDataReferences();
        initMasterDataThumbnailSizeControls();
        initMasterDataImageLightbox();
        initMasterDataStoreSectionBatchSave();

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
