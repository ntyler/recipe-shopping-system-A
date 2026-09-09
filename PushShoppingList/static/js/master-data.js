(function () {
    const POLL_INTERVAL_MS = 700;
    const REFRESH_DELAY_MS = 1200;
    const MASTER_DATA_THUMBNAIL_SIZE_STORAGE_KEY = "master-data-thumbnail-size";
    const MASTER_DATA_THUMBNAIL_DEFAULT_SIZE = 48;
    const MASTER_DATA_THUMBNAIL_MIN_SIZE = 32;
    const MASTER_DATA_THUMBNAIL_MAX_SIZE = 80;
    const MASTER_DATA_THUMBNAIL_STEP_SIZE = 8;
    const INGREDIENT_MASTER_DATA_VERSION_STORAGE_KEY = "ingredient-master-data-version";
    let activeJobId = "";
    let pollTimer = null;
    let activeImageJobId = "";
    let imagePollTimer = null;
    let imageRefreshTimer = null;
    let masterDataUsageReturnFocus = null;
    let restoreMasterDataUsageScroll = null;
    let masterDataUsageRequestId = 0;
    let masterDataThumbnailSize = MASTER_DATA_THUMBNAIL_DEFAULT_SIZE;
    let masterDataThumbnailSizeEventsBound = false;
    let masterDataMergeSearchTimer = null;
    let masterDataMergeRequestId = 0;
    let masterDataMergeReturnFocus = null;
    let masterDataDuplicateReferenceRequestId = 0;
    let masterDataDuplicateReferenceReturnFocus = null;
    let masterDataMiscReferenceReturnFocus = null;
    let activeMiscStoreSectionUndoPreview = null;
    let miscStoreSectionUndoReturnFocus = null;
    const miscStoreSectionUndoCollapsedDateGroups = new Set();
    let miscStoreSectionUndoHistoryGroupsInitialized = false;

    function text(value) {
        return String(value == null ? "" : value);
    }

    function canonicalMasterDataUrl(rawUrl, values = {}) {
        const url = new URL(rawUrl || window.location.href, window.location.href);

        Object.entries(values || {}).forEach(([name, rawValue]) => {
            const value = text(rawValue);
            if (value.trim()) {
                url.searchParams.set(name, value);
            } else {
                url.searchParams.delete(name);
            }
        });

        const nonBlankEntries = [...url.searchParams.entries()].filter(([, value]) => (
            text(value).trim()
        ));
        url.search = "";
        nonBlankEntries.forEach(([name, value]) => {
            url.searchParams.append(name, value);
        });

        const isEquipment = url.pathname === "/admin/master-data/equipment";
        const scope = isEquipment ? "mine" : text(url.searchParams.get("scope")).trim().toLowerCase();
        if (!scope || scope === "mine") {
            url.searchParams.delete("scope");
        }
        if (scope !== "user") {
            url.searchParams.delete("user_id");
        }
        if (text(url.searchParams.get("page")).trim() === "1") {
            url.searchParams.delete("page");
        }

        url.searchParams.delete("viewer_user_id");
        return url;
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
        return "[data-equipment-image-trigger], .master-data-thumbnail[src], .master-data-reference-title-image[src], [data-ingredient-master-row] .master-data-no-image";
    }

    function masterDataImageTrigger(event) {
        if (!event.target?.closest) return null;
        // Resolve the native Equipment button even when its image or empty span was clicked.
        return event.target.closest("[data-equipment-image-trigger]")
            || event.target.closest(masterDataLightboxImageSelector());
    }

    function ensureMasterDataImageLightbox() {
        let lightbox = document.getElementById("recipeImageLightbox");

        if (lightbox) {
            return lightbox;
        }

        lightbox = document.createElement("div");
        lightbox.id = "recipeImageLightbox";
        lightbox.className = "recipe-image-lightbox master-data-image-lightbox";
        lightbox.setAttribute("aria-hidden", "true");
        lightbox.innerHTML = `
            <div class="recipe-image-lightbox-content"
                 role="dialog"
                 aria-modal="true"
                 aria-label="Enlarged recipe image">
                <button type="button" class="recipe-image-lightbox-close">Close</button>
                <div class="recipe-image-lightbox-media">
                    <img id="recipeImageLightboxImage" alt="">
                    <div class="master-data-lightbox-empty" role="status" hidden>No image</div>
                    <div class="recipe-image-lightbox-actions" data-master-image-actions hidden>
                        <p data-master-image-status role="status" aria-live="polite"></p>
                        <div class="master-data-lightbox-buttons" role="group" aria-label="Image actions">
                            <button type="button" data-master-image-action="replace">Replace Image</button>
                            <button type="button" data-master-image-action="generate">Generate Image</button>
                            <button type="button" class="is-remove" data-master-image-action="remove">Remove Image</button>
                            <button type="button" data-master-image-retry hidden>Retry loading</button>
                        </div>
                    </div>
                </div>
                <input type="file" data-master-image-file accept="image/*" hidden>
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
        lightbox.querySelectorAll('[data-master-image-action]').forEach(button => {
            button.addEventListener('click', () => {
                if (button.disabled) return;
                const action = button.dataset.masterImageAction;
                if (lightbox.equipmentRow) {
                    if (action === 'replace') lightbox.querySelector('[data-master-image-file]').click();
                    else if (action === 'generate') void window.EquipmentRegistry.imageEditor.prepare(lightbox.equipmentRow);
                    else window.EquipmentRegistry.imageEditor.remove(lightbox.equipmentRow);
                    return;
                }
                if (lightbox.ingredientRow !== ingredientEditingRow) return;
                if (action === 'replace') document.querySelector('[data-ingredient-image-file]').click();
                else if (action === 'generate') void prepareIngredientImage();
                else removeIngredientImage();
            });
        });
        lightbox.querySelector('[data-master-image-file]').addEventListener('change', event => {
            const file = event.target.files[0];
            if (file && lightbox.equipmentRow) void window.EquipmentRegistry.imageEditor.prepare(lightbox.equipmentRow, file);
            event.target.value = '';
        });
        lightbox.querySelector('[data-master-image-retry]').addEventListener('click', () => {
            if (lightbox.ingredientRow === ingredientEditingRow) void loadIngredientEditor(ingredientEditingRow, ++ingredientEditorToken);
        });
        lightbox.querySelector('img').addEventListener('load', event => {
            const image = event.target;
            delete image.dataset.failedSrc;
            lightbox.querySelector('.recipe-image-lightbox-media').style.setProperty('--image-ratio', image.naturalWidth / image.naturalHeight);
            syncMasterDataLightboxImageState(lightbox);
        });
        lightbox.querySelector('img').addEventListener('error', event => {
            const image = event.target;
            image.dataset.failedSrc = image.getAttribute('src') || '';
            syncMasterDataLightboxImageState(lightbox);
        });
        document.body.appendChild(lightbox);

        return lightbox;
    }

    function openMasterDataImageLightbox(image) {
        if (!image) return;
        image = image.closest('[data-equipment-image-trigger]') || image;
        const row = image.closest('[data-ingredient-master-row]');
        const equipmentRow = image.closest('[data-equipment-master-row]');
        const media = image.matches('img') ? image : image.querySelector('img');
        const src = equipmentRow ? image.dataset.imageUrl || '' : media?.dataset.fullSrc || media?.currentSrc || media?.src || '';
        if (row && !editIngredientRow(row)) return;
        if (equipmentRow && !window.EquipmentRegistry.imageEditor.open(equipmentRow)) return;
        closeIngredientAliases({restoreFocus: false});
        const lightbox = ensureMasterDataImageLightbox();
        const lightboxImage = document.getElementById("recipeImageLightboxImage");

        if (!lightboxImage) {
            return;
        }

        const host = image.closest('dialog[open]') || document.body;
        if (lightbox.parentNode !== host) host.appendChild(lightbox);
        lightbox.returnFocus = image;
        lightbox.ingredientRow = row;
        lightbox.equipmentRow = equipmentRow;
        lightbox.querySelector('[role="dialog"]').setAttribute('aria-label', row || equipmentRow ? `Image for ${(row || equipmentRow).dataset.recordName}` : 'Enlarged recipe image');
        lightbox.querySelector('.recipe-image-lightbox-media').style.setProperty('--image-ratio', media?.naturalWidth && media?.naturalHeight ? media.naturalWidth / media.naturalHeight : 1);
        if (src) lightboxImage.src = src;
        else lightboxImage.removeAttribute('src');
        lightboxImage.alt = media?.alt || "Recipe image";
        syncMasterDataLightboxImageState(lightbox);
        lightbox.classList.add("open");
        lightbox.setAttribute("aria-hidden", "false");
        document.body.classList.add("image-lightbox-open");
        syncMasterDataImageLightbox();

        const closeButton = lightbox.querySelector(".recipe-image-lightbox-close");
        if (closeButton) {
            closeButton.focus({ preventScroll: true });
        }
    }

    function closeMasterDataImageLightbox() {
        const lightbox = document.getElementById("recipeImageLightbox");
        const lightboxImage = document.getElementById("recipeImageLightboxImage");

        if (!lightbox || !lightbox.classList.contains('open')) {
            return;
        }

        const trigger = lightbox.returnFocus;
        delete lightbox.returnFocus;
        delete lightbox.ingredientRow;
        delete lightbox.equipmentRow;
        lightbox.classList.remove("open");
        lightbox.setAttribute("aria-hidden", "true");
        document.body.classList.remove("image-lightbox-open");

        if (lightboxImage) {
            lightboxImage.removeAttribute("src");
            lightboxImage.alt = "";
            delete lightboxImage.dataset.failedSrc;
        }
        if (lightbox.parentNode !== document.body) document.body.appendChild(lightbox);
        if (trigger?.isConnected) trigger.focus({preventScroll: true});
    }

    function syncMasterDataLightboxImageState(lightbox) {
        const image = lightbox.querySelector('img');
        const src = image.getAttribute('src');
        const unavailable = Boolean(src && image.dataset.failedSrc === src);
        image.hidden = !src || unavailable;
        lightbox.querySelector('.recipe-image-lightbox-media').classList.toggle('has-image-placeholder', image.hidden);
        const placeholder = lightbox.querySelector('.master-data-lightbox-empty');
        placeholder.hidden = !image.hidden;
        placeholder.textContent = unavailable ? 'Image unavailable' : 'No image';
    }

    // Image actions share the row draft; previews never save by themselves.
    function syncMasterDataImageLightbox() {
        const lightbox = document.getElementById('recipeImageLightbox');
        if (!lightbox?.classList.contains('open')) return;
        const row = lightbox.ingredientRow;
        const equipment = lightbox.equipmentRow && window.EquipmentRegistry.imageEditor.state(lightbox.equipmentRow);
        const managing = Boolean(equipment || row && row === ingredientEditingRow);
        const toolbar = lightbox.querySelector('[data-master-image-actions]');
        toolbar.hidden = !managing;
        lightbox.classList.toggle('has-image-actions', managing);
        if (!managing) return;

        const draft = equipment || {
            url: ingredientImageUrl, name: ingredientRowValues(row).name,
            busy: ingredientMutationPending || ingredientEditorLoading || ingredientImagePending || !ingredientEditorContext,
            retry: !ingredientEditorControl('retry').hidden, retryDisabled: ingredientEditorControl('retry').disabled,
            feedback: Boolean(ingredientEditorLoading || ingredientImagePending || ingredientEditorErrors.image || !ingredientEditorControl('retry').hidden),
            status: ingredientEditorLoading ? 'Loading ingredient details…'
                : !ingredientEditorControl('retry').hidden ? ingredientEditorControl('feedback').textContent
                : ingredientEditorErrors.image || (ingredientImagePending ? ingredientImageStatus
                    : ingredientImageChange ? 'Unsaved image change · Save the row to keep it.' : 'Use the row’s Save to keep image changes.'),
        };
        const image = lightbox.querySelector('img');
        if (draft.url) {
            if (image.getAttribute('src') !== draft.url) image.src = draft.url;
        } else image.removeAttribute('src');
        image.alt = `${draft.name} image`;
        syncMasterDataLightboxImageState(lightbox);
        toolbar.querySelectorAll('[data-master-image-action]').forEach(button => {
            button.disabled = draft.busy || (button.dataset.masterImageAction === 'remove' && !draft.url);
        });
        const retry = toolbar.querySelector('[data-master-image-retry]');
        retry.hidden = !draft.retry;
        retry.disabled = Boolean(draft.retryDisabled);
        const status = toolbar.querySelector('[data-master-image-status]');
        toolbar.classList.toggle('has-image-feedback', draft.feedback);
        status.textContent = draft.status;
        toolbar.setAttribute('aria-busy', String(Boolean(draft.busy)));
        if (lightbox.contains(document.activeElement) && document.activeElement.disabled) {
            lightbox.querySelector('.recipe-image-lightbox-close').focus({preventScroll: true});
        }
    }

    function decorateMasterDataLightboxImages(root = document) {
        const scope = root && typeof root.querySelectorAll === "function" ? root : document;
        scope.querySelectorAll(masterDataLightboxImageSelector()).forEach((image) => {
            const trigger = image.closest('[data-equipment-image-trigger]');
            if (trigger) return; // The native button is the only Equipment thumbnail focus target.
            image.tabIndex = 0;
            image.setAttribute("role", "button");
            image.setAttribute("aria-label", image.matches('.master-data-no-image')
                ? `Manage image for ${image.closest('[data-ingredient-master-row]').dataset.recordName}`
                : `Enlarge ${image.alt || "recipe image"}`);
            image.setAttribute('aria-haspopup', 'dialog');
            image.setAttribute('aria-controls', 'recipeImageLightbox');
        });
    }

    function initMasterDataImageLightbox() {
        decorateMasterDataLightboxImages(document);
        document.addEventListener("click", (event) => {
            const image = masterDataImageTrigger(event);
            if (!image) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            openMasterDataImageLightbox(image);
        }, true); // Claim thumbnails before row click handlers can change or cancel the draft.
        document.addEventListener("keydown", (event) => {
            const lightbox = document.getElementById('recipeImageLightbox');
            if (lightbox?.classList.contains('open') && event.key === "Escape") {
                event.preventDefault();
                event.stopImmediatePropagation();
                closeMasterDataImageLightbox();
                return;
            }
            if (lightbox?.classList.contains('open') && event.key === 'Tab') {
                const controls = [...lightbox.querySelectorAll('button:not(:disabled)')].filter(control => control.getClientRects().length);
                const index = controls.indexOf(document.activeElement);
                if (index === -1 || (event.shiftKey ? index === 0 : index === controls.length - 1)) {
                    event.preventDefault();
                    controls[event.shiftKey ? controls.length - 1 : 0].focus({preventScroll: true});
                }
                event.stopImmediatePropagation();
                return;
            }

            const image = masterDataImageTrigger(event);
            if (!image || (event.key !== "Enter" && event.key !== " ")) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            openMasterDataImageLightbox(image);
        }, true);
        document.addEventListener('focusin', event => {
            const lightbox = document.getElementById('recipeImageLightbox');
            if (lightbox?.classList.contains('open') && !lightbox.contains(event.target)) {
                lightbox.querySelector('.recipe-image-lightbox-close').focus({preventScroll: true});
            }
        });
    }

    window.MasterDataImageLightbox = {sync: syncMasterDataImageLightbox};

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
        const values = {};
        const formData = new FormData(filterForm);
        for (const [name, rawValue] of formData.entries()) {
            values[name] = text(rawValue);
        }
        const url = canonicalMasterDataUrl(
            filterForm.getAttribute("action") || window.location.href,
            values
        );
        return `${url.pathname}${url.search}${url.hash}`;
    }

    function syncMasterDataTargetUserControl(filterForm) {
        if (!filterForm) return;
        const scope = filterForm.querySelector("[data-master-scope-filter]");
        const targetUser = filterForm.querySelector("[data-master-target-user-filter]");
        if (!scope || !targetUser) return;
        const selectingUser = text(scope.value).trim().toLowerCase() === "user";
        const targetUserField = filterForm.querySelector("[data-master-target-user-field]");
        const targetUserNote = filterForm.querySelector("[data-master-target-user-note]");
        targetUser.disabled = !selectingUser;
        targetUser.required = selectingUser;
        if (targetUserField) {
            targetUserField.hidden = !selectingUser;
        }
        if (targetUserNote) {
            targetUserNote.hidden = !selectingUser;
        }
    }

    function initMasterDataFilterForm() {
        const filterForm = document.querySelector(".master-data-filter-form");
        if (!filterForm) return;
        const scope = filterForm.querySelector("[data-master-scope-filter]");
        syncMasterDataTargetUserControl(filterForm);
        if (scope) {
            scope.addEventListener("change", () => syncMasterDataTargetUserControl(filterForm));
        }
        filterForm.addEventListener("submit", (event) => {
            event.preventDefault();
            window.location.assign(filterRedirectUrl(filterForm));
        });
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

        if (form.closest(".equipment-master-page")) {
            form.querySelectorAll('[name="scope"], [name="user_id"], [name="viewer_user_id"]').forEach(input => input.remove());
        } else {
            setNamedFormValue(form, "scope", scope);
            setNamedFormValue(form, "user_id", userId);
        }
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
        if (reference.ingredient_name && reference.matches_buy_as && !reference.matches_ingredient_name) {
            details.push(`Ingredient: ${reference.ingredient_name}`);
        }
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
        if (reference.preparation) {
            details.push(`Preparation: ${reference.preparation}`);
        }
        if (reference.notes) {
            details.push(`Notes: ${reference.notes}`);
        }
        if (reference.optional) {
            details.push("Optional");
        }
        return details.join(" | ");
    }

    function recipeUsageImagePlaceholder() {
        const placeholder = document.createElement("span");
        placeholder.className = "master-data-reference-title-image master-data-reference-title-placeholder";
        placeholder.textContent = "No image"; placeholder.setAttribute("aria-label", "No recipe image");
        return placeholder;
    }

    function groupRecipeUsageReferences(references) {
        const recipes = new Map();
        references.forEach(reference => {
            const key = JSON.stringify([reference.user_id || "", reference.recipe_id]);
            let recipe = recipes.get(key);
            if (!recipe) {
                recipe = {...reference, matches_ingredient_name: false, matches_buy_as: false, usage_details: []};
                recipes.set(key, recipe);
            }
            recipe.matches_ingredient_name ||= Boolean(reference.matches_ingredient_name);
            recipe.matches_buy_as ||= Boolean(reference.matches_buy_as);
            const detail = referenceDetailText(reference);
            if (detail && !recipe.usage_details.includes(detail)) recipe.usage_details.push(detail);
        });
        return [...recipes.values()];
    }

    function renderReferenceItem(reference, options = {}) {
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
            if (options.recipeUsage) image.addEventListener("error", () => image.replaceWith(recipeUsageImagePlaceholder()), {once: true});
            titleRow.appendChild(image);
        } else if (options.recipeUsage) {
            titleRow.classList.add("has-title-image");
            titleRow.appendChild(recipeUsageImagePlaceholder());
        }

        const copy = document.createElement("div");
        copy.className = "master-data-reference-copy";

        const title = document.createElement(reference.edit_url ? "a" : "strong");
        if (reference.edit_url) {
            title.className = "master-data-reference-title-link";
            title.href = reference.edit_url;
            title.target = "_blank";
            title.rel = "noopener noreferrer";
        }
        title.textContent = text(reference.recipe_title || (options.recipeUsage ? "Recipe" : reference.recipe_id) || "Recipe");
        copy.appendChild(title);

        if (reference.matches_ingredient_name || reference.matches_buy_as) {
            const matches = document.createElement("div");
            matches.className = "master-data-reference-matches";
            if (reference.matches_ingredient_name) {
                const nameMatch = document.createElement("span");
                nameMatch.className = "is-name";
                nameMatch.textContent = "Ingredient Name";
                matches.appendChild(nameMatch);
            }
            if (reference.matches_buy_as) {
                const buyAsMatch = document.createElement("span");
                buyAsMatch.className = "is-buy-as";
                buyAsMatch.textContent = "Buy As";
                matches.appendChild(buyAsMatch);
            }
            copy.appendChild(matches);
        }

        const detail = document.createElement("div");
        detail.className = "master-data-reference-detail";
        const details = options.recipeUsage ? reference.usage_details || [] : [referenceDetailText(reference) || text(reference.recipe_id || "")];
        details.forEach(value => { const line = document.createElement("div"); line.textContent = value; detail.appendChild(line); });
        copy.appendChild(detail);

        const recipeId = text(reference.recipe_id || "");
        if (recipeId && !options.recipeUsage) {
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

    function renderReferences(panel, data, options = {}) {
        if (!panel) {
            return;
        }
        panel.replaceChildren();

        const rawReferences = Array.isArray(data && data.references) ? data.references : [];
        const references = options.recipeUsage ? groupRecipeUsageReferences(rawReferences) : rawReferences;
        const total = Number(data && data.total) || references.length;
        const totalReferences = Number(data && data.total_reference_count) || references.length;
        const ingredientNameCount = Math.max(
            0,
            Number(data && data.ingredient_name_recipe_count) || 0,
        );
        const buyAsCount = Math.max(0, Number(data && data.buy_as_recipe_count) || 0);
        const hasIngredientBreakdown = text(data && data.record_type) === "ingredients";

        const header = document.createElement("div");
        header.className = "master-data-reference-header";

        const heading = document.createElement("div");
        heading.className = "master-data-reference-heading";
        const title = document.createElement("strong");
        const recordName = text(data && data.record && data.record.name);
        title.textContent = `${recordName || "Record"} is used by ${total} recipe${total === 1 ? "" : "s"}`;
        heading.appendChild(title);

        if (hasIngredientBreakdown) {
            const breakdown = document.createElement("div");
            breakdown.className = "master-data-reference-usage-breakdown";
            const nameUsage = document.createElement("span");
            nameUsage.textContent = `Ingredient Name ${ingredientNameCount}`;
            const buyAsUsage = document.createElement("span");
            buyAsUsage.textContent = `Buy As ${buyAsCount}`;
            const overlapNote = document.createElement("small");
            overlapNote.textContent = "Counts overlap when a recipe uses this record in both fields.";
            breakdown.append(nameUsage, buyAsUsage, overlapNote);
            heading.appendChild(breakdown);
        }
        header.appendChild(heading);

        if (totalReferences > references.length) {
            const note = document.createElement("span");
            note.textContent = `Showing first ${references.length} references.`;
            header.appendChild(note);
        }

        if (!options.hideHeader) {
            panel.appendChild(header);
        }

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
            list.appendChild(renderReferenceItem(reference || {}, options));
        });
        panel.appendChild(list);
        if (!options.recipeUsage) decorateMasterDataLightboxImages(panel);
    }

    function renderLoadedReferenceData(panel, data, options = {}) {
        if (typeof options.shouldRender === "function" && !options.shouldRender()) {
            return;
        }
        const renderer = typeof options.renderer === "function"
            ? options.renderer
            : renderReferences;
        renderer(panel, data, options);
    }

    async function loadReferenceData(button, panel, options = {}) {
        if (!button || !panel) return null;
        if (button.masterDataReferenceData) {
            renderLoadedReferenceData(panel, button.masterDataReferenceData, options);
            return button.masterDataReferenceData;
        }

        const referenceUrl = button.dataset.referenceUrl;
        if (!referenceUrl || !window.fetch) {
            if (typeof options.shouldRender !== "function" || options.shouldRender()) {
                setReferenceError(panel, "Recipe references are not available in this browser.");
            }
            return null;
        }

        setReferenceLoading(panel);
        try {
            const requestUrl = canonicalMasterDataUrl(referenceUrl, options.allReferences ? {limit: "500"} : {});
            let data;
            do {
                const response = await fetch(requestUrl.toString(), {
                    headers: {Accept: "application/json", "X-Requested-With": "fetch"},
                });
                const page = await response.json().catch(() => ({}));
                if (typeof options.shouldRender === "function" && !options.shouldRender()) return null;
                if (!response.ok || page.ok === false) throw new Error(page.error || page.message || "Recipe references could not be loaded.");
                data = data ? {...page, references: [...data.references, ...page.references]} : page;
                if (!options.allReferences || page.next_offset == null) break;
                const nextOffset = Number(page.next_offset);
                if (!Number.isFinite(nextOffset) || nextOffset <= Number(requestUrl.searchParams.get("offset") || 0)) throw new Error("The remaining recipe references could not be loaded.");
                requestUrl.searchParams.set("offset", String(nextOffset));
            } while (true);
            button.masterDataReferenceData = data;
            renderLoadedReferenceData(panel, data, options);
            return data;
        } catch (error) {
            if (typeof options.shouldRender !== "function" || options.shouldRender()) {
                setReferenceError(panel, error && error.message ? error.message : "Recipe references could not be loaded.");
            }
            return null;
        }
    }

    function masterDataUsageElements() {
        const dialog = document.querySelector("[data-master-usage-dialog]");
        return {
            dialog,
            title: dialog?.querySelector("[data-master-usage-title]"),
            summary: dialog?.querySelector("[data-master-usage-summary]"),
            results: dialog?.querySelector("[data-master-usage-results]"),
            closeButtons: dialog ? Array.from(dialog.querySelectorAll("[data-master-usage-close]")) : [],
        };
    }

    function lockRecipeUsageBackground(button) {
        const ancestors = new Set([document.documentElement, document.body]);
        for (let element = button.parentElement; element; element = element.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) ancestors.add(element);
        }
        const states = [...ancestors].map(element => {
            const computed = getComputedStyle(element);
            return {element, top: element.scrollTop, left: element.scrollLeft, padding: computed.paddingRight, width: element.clientWidth,
                styles: ["overflow", "padding-right"].map(key => [key, element.style.getPropertyValue(key), element.style.getPropertyPriority(key)])};
        });
        states.forEach(({element, padding, width}) => {
            element.style.setProperty("overflow", "hidden");
            const scrollbar = element.clientWidth - width;
            if (scrollbar > 0) element.style.setProperty("padding-right", `${parseFloat(padding) + scrollbar}px`);
        });
        const restorePositions = () => states.forEach(({element, top, left}) => { element.scrollTop = top; element.scrollLeft = left; });
        restorePositions();
        return (unlock = true) => {
            if (unlock) states.forEach(({element, styles}) => styles.forEach(([key, value, priority]) => {
                if (value) element.style.setProperty(key, value, priority); else element.style.removeProperty(key);
            }));
            restorePositions();
        };
    }

    function restoreMasterDataUsageFocus() {
        const returnFocus = masterDataUsageReturnFocus;
        masterDataUsageReturnFocus = null;
        restoreMasterDataUsageScroll?.(); restoreMasterDataUsageScroll = null;
        if (returnFocus) returnFocus.setAttribute("aria-expanded", "false");
        if (returnFocus?.isConnected) returnFocus.focus({preventScroll: true});
    }

    function closeMasterDataUsage() {
        const els = masterDataUsageElements();
        if (!els.dialog) return;
        masterDataUsageRequestId += 1;
        if (els.dialog.open) els.dialog.close();
        restoreMasterDataUsageFocus();
    }

    async function openMasterDataUsage(button) {
        const els = masterDataUsageElements();
        if (!button || !els.dialog || !els.results) return false;
        if (els.dialog.open) return true;
        masterDataUsageReturnFocus = button;
        button.setAttribute("aria-expanded", "true");
        const recordName = button.dataset.recordName || "this record";
        els.title.textContent = `Recipes using ${recordName}`;
        els.summary.textContent = ""; els.results.scrollTop = 0;
        els.results.setAttribute("aria-busy", "true"); setReferenceLoading(els.results);
        restoreMasterDataUsageScroll = lockRecipeUsageBackground(button);
        els.dialog.showModal();
        els.closeButtons[0].focus({preventScroll: true}); restoreMasterDataUsageScroll(false);
        const requestId = ++masterDataUsageRequestId;
        const shouldRender = () => requestId === masterDataUsageRequestId && els.dialog.open;
        const data = await loadReferenceData(button, els.results, {hideHeader: true, recipeUsage: true, allReferences: true, shouldRender});
        if (!shouldRender()) return true;
        els.results.setAttribute("aria-busy", "false");
        if (!data) return true;
        els.title.textContent = `Recipes using ${text(data.record?.name).trim() || recordName}`;
        const total = Math.max(0, Number(data.total) || 0);
        els.summary.textContent = `${total} distinct recipe${total === 1 ? "" : "s"}`;
        if (els.dialog.dataset.recordType === "ingredients") {
            const nameCount = Math.max(0, Number(data.ingredient_name_recipe_count) || 0);
            const buyAsCount = Math.max(0, Number(data.buy_as_recipe_count) || 0);
            els.summary.append(` · Ingredient Name ${nameCount} · Buy As ${buyAsCount}`);
            const note = document.createElement("small"); note.textContent = "A recipe using both fields is counted once in the total.";
            els.summary.append(note);
        } else {
            const referenceCount = Math.max(0, Number(data.total_reference_count) || 0);
            els.summary.append(` · ${referenceCount} matching equipment reference${referenceCount === 1 ? "" : "s"}`);
        }
        return true;
    }

    function trapRecipeUsageFocus(event) {
        if (event.key !== "Tab") return;
        const controls = [...event.currentTarget.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]')].filter(element => element.getClientRects().length);
        const first = controls[0], last = controls[controls.length - 1];
        if ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
            event.preventDefault(); (event.shiftKey ? last : first).focus({preventScroll: true});
        }
    }

    function initMasterDataReferences() {
        const usage = masterDataUsageElements();
        if (usage.dialog) {
            usage.closeButtons.forEach(button => button.addEventListener("click", closeMasterDataUsage));
            usage.dialog.addEventListener("cancel", event => { event.preventDefault(); closeMasterDataUsage(); });
            usage.dialog.addEventListener("click", event => { if (event.target === usage.dialog) closeMasterDataUsage(); });
            usage.dialog.addEventListener("close", () => { if (!usage.dialog.open) restoreMasterDataUsageFocus(); });
            usage.dialog.addEventListener("keydown", trapRecipeUsageFocus);
        }
        document.addEventListener("click", event => {
            const button = event.target.closest?.("[data-master-usage-button]");
            if (button) { event.preventDefault(); void openMasterDataUsage(button); }
        });
    }

    let ingredientEditingRow = null;
    let ingredientDeletingRow = null;
    let ingredientMutationPending = false;
    let ingredientEditorContext = null;
    let ingredientEditorLoading = false;
    let ingredientImagePending = false;
    let ingredientImageChange = null;
    let ingredientImageUrl = '';
    let ingredientEditorAliases = [];
    let ingredientEditorErrors = {};
    let ingredientEditorToken = 0;
    let ingredientSaving = false;
    let ingredientAliasAnchor = null;
    let ingredientImageStatus = '';
    let ingredientOrderOriginal = null;
    let ingredientOrderChange = null;

    function ingredientText(value) { return String(value || '').trim().replace(/\s+/g, ' '); }
    function ingredientKey(value) { return ingredientText(value).toLowerCase(); }
    function ingredientDraftSignature(values) {
        return JSON.stringify({...values, name: ingredientText(values.name), aliases: values.aliases.map(ingredientText).sort()});
    }
    function validateIngredientDraft(values, registry, recordId, sections) {
        const errors = {aliases: {}};
        const owners = new Map();
        registry.filter(record => String(record.id) !== String(recordId)).forEach(record => {
            [record.name, record.normalized_name, ...record.aliases].forEach(value => owners.set(ingredientKey(value), record.name));
        });
        const nameKey = ingredientKey(values.name);
        if (!nameKey) errors.name = 'Enter an ingredient name.';
        else if (ingredientText(values.name).length > 160) errors.name = 'Use an ingredient name of 160 characters or fewer.';
        else if (owners.has(nameKey)) errors.name = `“${ingredientText(values.name)}” already belongs to ${owners.get(nameKey)}. Use Merge duplicate to combine them.`;
        if (!sections.some(section => section.section_key === values.store_section)) errors.section = 'Choose a valid Store Section.';
        const seen = new Set();
        values.aliases.forEach((value, index) => {
            const alias = ingredientText(value), key = ingredientKey(alias);
            if (!key || alias.length > 160) errors.aliases[index] = 'Use an alias of 1–160 characters.';
            else if (index >= 100) errors.aliases[index] = 'Use at most 100 aliases.';
            else if (key === nameKey || key === ingredientKey(values.normalized_name)) errors.aliases[index] = 'The ingredient name does not need to be an alias.';
            else if (seen.has(key)) errors.aliases[index] = `“${alias}” is already in this ingredient.`;
            else if (owners.has(key)) errors.aliases[index] = `“${alias}” already belongs to ${owners.get(key)}.`;
            seen.add(key);
        });
        return errors;
    }

    function ingredientEditorControl(key) { return document.querySelector(`[data-ingredient-editor-${key}]`); }
    function ingredientRows() { return Array.from(document.querySelectorAll('[data-ingredient-master-row]')); }
    function ingredientAliases(row) { return Array.from(row.querySelectorAll('[data-ingredient-alias]'), chip => chip.dataset.ingredientAlias); }
    function ingredientRowValues(row) {
        if (row === ingredientEditingRow) {
            const name = ingredientText(row.querySelector('[data-ingredient-row-name]').value);
            return {
                name, normalized_name: name === row.ingredientOriginal.name ? row.ingredientOriginal.normalized_name : ingredientKey(name),
                store_section: row.querySelector('[data-ingredient-row-section]').value,
                aliases: [...ingredientEditorAliases].sort(), image_url: ingredientImageUrl,
            };
        }
        return {
            name: row.querySelector('[name="name"]').value,
            normalized_name: row.querySelector('[name="normalized_name"]').value,
            store_section: row.querySelector('[name="store_section"]').value,
            aliases: ingredientAliases(row).sort(), image_url: row.dataset.imageSrc || '',
        };
    }
    function ingredientRowIsDirty(row) {
        return Boolean(row && row === ingredientEditingRow && row.ingredientOriginal && (
            ingredientDraftSignature(ingredientRowValues(row)) !== ingredientDraftSignature(row.ingredientOriginal)
            || ingredientText(ingredientEditorControl('alias-input').value)
            || ingredientOrderChange
        ));
    }
    // Maintenance and merge workflows use the same unsaved-change guard.
    function changedStoreSectionForms() { return ingredientRows().filter(ingredientRowIsDirty).map(row => row.querySelector('form')); }
    function ingredientStatus(message, error = false, row = null) {
        if (row) {
            const restoreScroll = captureIngredientScroll(row);
            if (row === ingredientEditingRow) {
                const output = ingredientEditorControl('feedback');
                output.textContent = message; output.hidden = !message;
                output.dataset.status = error ? 'error' : 'success';
            }
            const status = row.querySelector('[data-ingredient-row-status]');
            status.textContent = message; status.classList.toggle('is-error', error);
            restoreScroll();
            return;
        }
        const status = document.querySelector('[data-ingredient-registry-status]');
        if (status) { status.textContent = message; status.classList.toggle('is-error', error); status.classList.toggle('sr-only', !error); }
    }
    function ingredientFieldError(key, message) {
        if (key === 'image') {
            if (message) ingredientEditorErrors.image = message; else delete ingredientEditorErrors.image;
            return;
        }
        const input = key === 'aliases' ? ingredientEditorControl('alias-input') : ingredientEditingRow?.querySelector(`[data-ingredient-row-${key}]`);
        const output = key === 'aliases' ? ingredientEditorControl('alias-error') : ingredientEditingRow?.querySelector(`[data-ingredient-row-${key}-error]`);
        if (input) {
            if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
        }
        if (output) { output.textContent = message || ''; output.hidden = !message; }
    }
    function ingredientValidation() {
        if (!ingredientEditingRow || !ingredientEditorContext) return {aliases: {}};
        const values = ingredientRowValues(ingredientEditingRow);
        const pending = ingredientText(ingredientEditorControl('alias-input').value);
        values.aliases = [...ingredientEditorAliases, ...(pending ? [pending] : [])];
        return validateIngredientDraft(values, ingredientEditorContext.registry, ingredientEditingRow.dataset.masterRecordId, ingredientEditorContext.sections);
    }
    function syncIngredientRowControls() {
        const restoreScroll = ingredientEditingRow ? captureIngredientScroll(ingredientEditingRow) : null;
        const form = document.getElementById('ingredientAliasManager');
        const busy = ingredientMutationPending || ingredientEditorLoading || ingredientImagePending;
        const dirty = ingredientRowIsDirty(ingredientEditingRow);
        const errors = ingredientValidation();
        const aliasMessage = ingredientEditorErrors.aliases || [...new Set(Object.values(errors.aliases))].join(' ');
        const nameError = ingredientEditorErrors.name || errors.name || '';
        const sectionError = ingredientEditorErrors.section || errors.section || '';
        const invalid = nameError || sectionError || aliasMessage || ingredientEditorErrors.image;
        if (form) {
            form.setAttribute('aria-busy', String(busy));
            form.classList.toggle('is-dirty', dirty);
            form.querySelectorAll('input, select, button').forEach(control => { control.disabled = busy || Boolean(ingredientEditingRow && !ingredientEditorContext); });
            ingredientEditorControl('close-aliases').disabled = false;
            ingredientEditorControl('retry').disabled = busy;
            ingredientFieldError('name', nameError);
            ingredientFieldError('section', sectionError);
            ingredientFieldError('aliases', aliasMessage);
            const name = ingredientEditingRow ? ingredientRowValues(ingredientEditingRow).name : '';
            ingredientEditorControl('title').textContent = name ? `Aliases for ${name}` : 'Ingredient aliases';
            const previewAliases = [...ingredientEditorAliases, ...(ingredientText(ingredientEditorControl('alias-input').value) ? [ingredientText(ingredientEditorControl('alias-input').value)] : [])].filter((_, index) => !errors.aliases[index]).slice(0, 2);
            const preview = name ? previewAliases.length ? `${previewAliases.map(alias => `“${alias}”`).join(' and ')} will normalize to “${name}”.` : `“${name}” is accepted as the canonical ingredient.` : '';
            if (ingredientEditorControl('alias-preview').textContent !== preview) ingredientEditorControl('alias-preview').textContent = preview;
            Array.from(ingredientEditorControl('alias-chips').children).forEach((chip, index) => {
                chip.classList.toggle('has-error', Boolean(errors.aliases[index])); chip.title = errors.aliases[index] || '';
            });
        }
        ingredientRows().forEach(row => {
            const editing = row === ingredientEditingRow;
            const confirmingDelete = row === ingredientDeletingRow;
            row.classList.toggle('is-editing', editing);
            row.classList.toggle('is-dirty', editing && dirty);
            row.classList.toggle('is-confirming-delete', confirmingDelete);
            row.querySelectorAll('button, input, select').forEach(control => { control.disabled = ingredientMutationPending; });
            const save = row.querySelector('[data-ingredient-row-save]');
            save.hidden = !editing || !dirty || confirmingDelete;
            save.disabled = !editing || busy || !ingredientEditorContext || !dirty || Boolean(invalid);
            save.textContent = ingredientSaving && editing ? 'Saving…' : 'Save';
            const cancel = row.querySelector('[data-ingredient-row-cancel]');
            cancel.hidden = !confirmingDelete && (!editing || !dirty);
            cancel.setAttribute('aria-label', confirmingDelete ? `Cancel deleting ${row.dataset.recordName}` : `Cancel changes to ${row.dataset.recordName}`);
            const remove = row.querySelector('[data-ingredient-row-delete]');
            if (remove) {
                remove.disabled = ingredientMutationPending || ingredientImagePending || dirty;
                remove.hidden = confirmingDelete || (editing && dirty);
            }
            const confirmDelete = row.querySelector('[data-ingredient-row-confirm-delete]');
            if (confirmDelete) {
                confirmDelete.hidden = !confirmingDelete;
                confirmDelete.disabled = ingredientMutationPending || ingredientImagePending || dirty;
                confirmDelete.textContent = confirmingDelete && ingredientMutationPending ? 'Deleting…' : 'Confirm delete';
            }
            row.querySelector('[data-ingredient-row-retry]').hidden = !editing || ingredientEditorControl('retry').hidden;
            const merge = row.querySelector('[data-master-merge-open]');
            merge.hidden = confirmingDelete || (editing && dirty && Boolean(invalid));
            merge.disabled = Boolean(merge.dataset.mergeBlockedReason) || ingredientMutationPending || ingredientImagePending || dirty;
            merge.title = merge.dataset.mergeBlockedReason || (dirty ? 'Save or cancel the current changes before merging.'
                : ingredientMutationPending || ingredientImagePending ? 'Wait for the current ingredient operation to finish.' : merge.dataset.mergeTitle);
            const blocked = ingredientMutationPending || row.dataset.orderEnabled !== 'true';
            const handle = row.querySelector('[data-ingredient-order-handle]');
            handle.disabled = false; handle.draggable = !blocked; handle.setAttribute('aria-disabled', String(blocked));
            row.querySelector('[data-ingredient-order-action="up"]').disabled = blocked || Number(row.dataset.sortOrder) === 0;
            row.querySelector('[data-ingredient-order-action="down"]').disabled = blocked || Number(row.dataset.sortOrder) >= Number(row.dataset.sectionCount) - 1;
            if (editing && ingredientEditorContext?.record.section_editable === false) row.querySelector('[data-ingredient-row-section]').disabled = true;
            syncRecipeIngredientStoreSectionControl(row.querySelector('[data-ingredient-row-section]'));
        });
        if (ingredientEditingRow) renderIngredientRowAliases(ingredientEditingRow, ingredientEditorAliases);
        if (ingredientAliasAnchor) window.MasterDataAliasEditor.positionPopover(form, ingredientAliasAnchor);
        syncMasterDataImageLightbox();
        restoreScroll?.();
    }
    function captureIngredientScroll(anchor) {
        const top = anchor.getBoundingClientRect().top;
        const scrollers = [];
        for (let element = anchor.parentElement; element; element = element.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) scrollers.push([element, element.scrollTop]);
        }
        scrollers.push([document.scrollingElement, document.scrollingElement.scrollTop]);
        return () => {
            scrollers.forEach(([element, position]) => { element.scrollTop = position; });
            if (anchor.isConnected && anchor.getClientRects().length) scrollers[0][0].scrollTop += anchor.getBoundingClientRect().top - top;
        };
    }

    function renderIngredientRowAliases(row, aliases) {
        const list = row.querySelector('[data-ingredient-alias-list]');
        if (JSON.stringify(ingredientAliases(row)) === JSON.stringify(aliases)) return;
        list.replaceChildren(...aliases.map(alias => {
            const chip = document.createElement('code'); chip.dataset.ingredientAlias = alias; chip.textContent = alias; chip.title = alias; return chip;
        }));
        if (!aliases.length) {
            const empty = document.createElement('span'); empty.className = 'unit-master-no-aliases';
            empty.dataset.ingredientAliasEmpty = ''; empty.textContent = 'No aliases'; list.append(empty);
        }
    }

    function openIngredientAliases(row, anchor) {
        if (!editIngredientRow(row)) return;
        closeIngredientAliases({restoreFocus: false});
        const form = document.getElementById('ingredientAliasManager');
        ingredientAliasAnchor = anchor;
        form.hidden = false; form.showPopover();
        anchor.setAttribute('aria-expanded', 'true'); syncIngredientRowControls();
        if (!ingredientEditorLoading) ingredientEditorControl('alias-input').focus({preventScroll: true});
    }
    function closeIngredientAliases({restoreFocus = true} = {}) {
        if (!ingredientAliasAnchor) return;
        const anchor = ingredientAliasAnchor, form = document.getElementById('ingredientAliasManager');
        ingredientAliasAnchor = null;
        if (form.matches(':popover-open')) form.hidePopover();
        form.hidden = true; form.removeAttribute('style');
        anchor.setAttribute('aria-expanded', 'false');
        if (restoreFocus && anchor.isConnected) anchor.focus({preventScroll: true});
    }
    function renderIngredientEditorAliases() {
        const container = ingredientEditorControl('alias-chips'); container.replaceChildren();
        ingredientEditorAliases.forEach((alias, index) => {
            const chip = document.createElement('span'); chip.className = 'unit-master-alias-chip';
            const text = document.createElement('span'); text.textContent = alias;
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
            remove.setAttribute('aria-label', `Remove alias ${alias}`);
            remove.addEventListener('click', () => {
                ingredientEditorAliases.splice(index, 1); delete ingredientEditorErrors.aliases;
                renderIngredientEditorAliases(); ingredientStatus('', false, ingredientEditingRow); syncIngredientRowControls();
                ingredientEditorControl('alias-input').focus({preventScroll: true});
            });
            chip.append(text, remove); container.append(chip);
        });
    }

    function focusIngredientImageAction(action) {
        const lightbox = document.getElementById('recipeImageLightbox');
        if (lightbox?.classList.contains('open') && lightbox.ingredientRow === ingredientEditingRow) {
            lightbox.querySelector(`[data-master-image-action="${action}"]`).focus({preventScroll: true});

        }
    }

    function fillIngredientEditor(values) {
        if (ingredientEditingRow) {
            ingredientEditingRow.querySelector('[data-ingredient-row-name]').value = values.name;
            ingredientEditingRow.querySelector('[data-ingredient-row-section]').value = values.store_section;
        }
        ingredientEditorAliases = [...values.aliases]; ingredientEditorControl('alias-input').value = '';
        ingredientImageUrl = values.image_url || ''; ingredientImageChange = null;
        document.querySelector('[data-ingredient-image-file]').value = '';
        ingredientImageStatus = '';
        renderIngredientEditorAliases(); syncMasterDataImageLightbox();
    }
    async function loadIngredientEditor(row, requestToken) {
        ingredientEditorLoading = true; ingredientEditorContext = null;
        ingredientEditorControl('retry').hidden = true; ingredientStatus('Loading ingredient details…', false, row); syncIngredientRowControls();
        try {
            const response = await fetch(row.dataset.editorUrl, {headers: {'X-Requested-With': 'fetch'}});
            const context = await response.json();
            if (requestToken !== ingredientEditorToken || row !== ingredientEditingRow) return;
            if (!response.ok || !context.ok) throw new Error(context.error || 'Ingredient details could not be loaded.');
            ingredientEditorContext = context;
            // Loading validation must not overwrite keystrokes entered while the request was in flight.
            const draft = ingredientRowValues(row), dirty = ingredientRowIsDirty(row);
            const pendingAlias = ingredientEditorControl('alias-input').value;
            const imageChange = ingredientImageChange;
            const record = context.record;
            row.ingredientOriginal = {name: record.name, normalized_name: record.normalized_name, store_section: record.store_section, aliases: record.aliases.slice().sort(), image_url: record.image_url};
            fillIngredientEditor(dirty ? draft : row.ingredientOriginal);
            ingredientEditorControl('alias-input').value = pendingAlias; ingredientImageChange = imageChange;
            ingredientStatus('', false, row);
        } catch (error) {
            if (requestToken !== ingredientEditorToken) return;
            ingredientStatus(error.message || 'Ingredient details could not be loaded.', true, row); ingredientEditorControl('retry').hidden = false;
        } finally {
            if (requestToken === ingredientEditorToken) {
                ingredientEditorLoading = false; syncIngredientRowControls();
                if (ingredientAliasAnchor && ingredientEditorContext) ingredientEditorControl('alias-input').focus({preventScroll: true});
            }
        }
    }
    function editIngredientRow(row) {
        if (ingredientMutationPending) return false;
        if (ingredientDeletingRow) cancelIngredientDeletion({restoreFocus: false});
        if (ingredientEditingRow === row) return true;
        const restoreScroll = captureIngredientScroll(row);
        if (ingredientEditingRow && !cancelIngredientRow(ingredientEditingRow, {restoreFocus: false})) return false;
        const values = ingredientRowValues(row); row.ingredientOriginal = values; ingredientEditingRow = row;
        ingredientEditorContext = null; ingredientEditorErrors = {};
        ingredientOrderOriginal = null; ingredientOrderChange = null;
        fillIngredientEditor(values);
        ingredientFieldError('image', '');
        void loadIngredientEditor(row, ++ingredientEditorToken);
        restoreScroll();
        return true;
    }
    function addIngredientAlias() {
        const input = ingredientEditorControl('alias-input'), value = ingredientText(input.value);
        if (!value) return true;
        if (ingredientValidation().aliases[ingredientEditorAliases.length]) { syncIngredientRowControls(); input.focus({preventScroll: true}); return false; }
        ingredientEditorAliases.push(value); input.value = ''; renderIngredientEditorAliases(); syncIngredientRowControls(); return true;
    }
    function cancelIngredientRow(row, {restoreFocus = true, discard = false} = {}) {
        if (!row) return true;
        if (ingredientMutationPending) return false;
        if (!discard && ingredientRowIsDirty(row) && !window.confirm('Discard unsaved changes to this ingredient?')) return false;
        const restoreScroll = captureIngredientScroll(row);
        ingredientEditorToken++; ingredientEditorLoading = false; ingredientImagePending = false; ingredientEditorErrors = {};
        fillIngredientEditor(row.ingredientOriginal); renderIngredientRowAliases(row, row.ingredientOriginal.aliases);
        ingredientFieldError('name', ''); ingredientFieldError('section', ''); ingredientStatus('', false, row);
        closeIngredientAliases({restoreFocus: false});
        if (ingredientOrderOriginal) placeIngredientRows(ingredientSectionRows(row), ingredientOrderOriginal);
        ingredientOrderOriginal = null; ingredientOrderChange = null;
        ingredientEditingRow = null; ingredientEditorContext = null; syncIngredientRowControls();
        // Keep keyboard focus in the table without reactivating a finished field.
        if (restoreFocus) row.focus({preventScroll: true});
        restoreScroll(); return true;
    }
    async function prepareIngredientImage(file = null) {
        if (!ingredientEditingRow || ingredientMutationPending || ingredientImagePending || ingredientEditorLoading) return;
        const row = ingredientEditingRow, requestToken = ++ingredientEditorToken;
        const lightbox = document.getElementById('recipeImageLightbox');
        const fromLightbox = lightbox?.classList.contains('open') && lightbox.ingredientRow === row;
        ingredientImagePending = true; delete ingredientEditorErrors.image; ingredientFieldError('image', '');
        ingredientImageStatus = file ? 'Preparing image preview…' : 'Generating an image preview…'; syncIngredientRowControls();
        try {
            let body, headers = {'X-Requested-With': 'fetch'};
            if (file) { body = new FormData(); body.append('image', file); }
            else { body = JSON.stringify({action: 'generate', name: ingredientRowValues(row).name}); headers['Content-Type'] = 'application/json'; }
            const response = await fetch(row.dataset.imageUrl, {method: 'POST', headers, body});
            const result = await response.json(); if (requestToken !== ingredientEditorToken) return;
            if (!response.ok || !result.ok) throw new Error(result.error || 'Image preview could not be prepared.');
            ingredientImageChange = {action: 'replace', token: result.token}; ingredientImageUrl = result.image_url;
            syncMasterDataImageLightbox(); ingredientStatus('', false, row);
        } catch (error) { if (requestToken === ingredientEditorToken) ingredientFieldError('image', error.message || 'Image preview could not be prepared.'); }
        finally {
            if (requestToken === ingredientEditorToken) {
                ingredientImagePending = false; document.querySelector('[data-ingredient-image-file]').value = '';
                ingredientImageStatus = '';
                syncIngredientRowControls();
                if (!fromLightbox || (lightbox.classList.contains('open') && lightbox.ingredientRow === row)) {
                    focusIngredientImageAction(file ? 'replace' : 'generate');
                }
            }
        }
    }
    function removeIngredientImage() {
        if (!window.confirm('Remove this ingredient image? The change stays pending until you save.')) return;
        ingredientImageUrl = ''; ingredientImageChange = ingredientEditingRow.ingredientOriginal.image_url ? {action: 'remove'} : null;
        ingredientFieldError('image', '');
        syncIngredientRowControls(); focusIngredientImageAction('replace');
    }
    async function saveIngredientRow(row) {
        if (!row || row !== ingredientEditingRow || row.querySelector('[data-ingredient-row-save]').disabled) return;
        if (!addIngredientAlias()) return;
        const form = document.getElementById('ingredientAliasManager'), restoreScroll = captureIngredientScroll(row);
        const values = ingredientRowValues(row), payload = {...values, redirect_url: window.location.href};
        delete payload.image_url; if (ingredientImageChange) payload.image = ingredientImageChange;
        if (ingredientOrderChange) payload.order = ingredientOrderChange;
        ingredientMutationPending = true; ingredientSaving = true; row.classList.add('is-saving');
        ingredientStatus('Saving changes…', false, row); syncIngredientRowControls();
        let saved = false;
        try {
            const response = await fetch(row.querySelector('form').action, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'}, body: JSON.stringify(payload)});
            const result = await response.json();
            if (!response.ok || !result.ok) {
                ingredientEditorErrors = result.result?.errors || {}; if (ingredientEditorErrors.image) ingredientFieldError('image', ingredientEditorErrors.image);
                throw new Error(result.message || result.error || 'The ingredient could not be saved.');
            }
            saved = true; const record = result.result;
            row.ingredientOriginal = {name: record.name, normalized_name: record.normalized_name, store_section: record.store_section, aliases: record.aliases.slice().sort(), image_url: record.image_url};
            // Keep the saved values authoritative even if the follow-up table request fails.
            for (const key of ['name', 'normalized_name', 'store_section']) row.querySelector(`[name="${key}"]`).value = record[key];
            row.dataset.recordName = record.name; row.dataset.imageSrc = record.image_url;
            row.dataset.storeSection = record.store_section; row.dataset.sortOrder = String(record.sort_order);
            renderIngredientRowAliases(row, record.aliases);
            const oldImage = row.querySelector('.master-data-thumbnail, [data-master-image-empty]');
            const image = document.createElement(record.image_url ? 'img' : 'button');
            if (record.image_url) {
                image.className = 'master-data-thumbnail'; image.src = record.image_url;
                image.dataset.fullSrc = record.image_url; image.alt = `${record.name} image`;
            } else {
                image.type = 'button'; image.className = 'master-data-no-image'; image.dataset.masterImageEmpty = ''; image.textContent = 'No image';
            }
            oldImage.replaceWith(image); decorateMasterDataLightboxImages(row);
            ingredientEditorErrors = {}; fillIngredientEditor(row.ingredientOriginal);
            closeIngredientAliases({restoreFocus: false}); ingredientEditingRow = null; ingredientEditorContext = null;
            ingredientOrderOriginal = null; ingredientOrderChange = null;
            await refreshMasterDataRecordResults();
            ingredientStatus(`${record.name} saved.`);
        } catch (error) {
            if (saved) ingredientRows().forEach(item => { item.dataset.orderEnabled = 'false'; });
            ingredientStatus(saved ? 'Saved. The table could not refresh; reload the page to see the updated group.' : error.message || 'The ingredient could not be saved.', true, ingredientEditingRow);
        } finally {
            ingredientMutationPending = false; ingredientSaving = false; row.classList.remove('is-saving');
            syncIngredientRowControls();
            if (saved) {
                const focusTarget = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${row.dataset.masterRecordId}"]`)
                    || document.querySelector('.master-data-filter-form [name="search"]');
                focusTarget?.focus({preventScroll: true}); restoreScroll();
            } else (row.querySelector('[aria-invalid="true"]') || form.querySelector('[aria-invalid="true"]'))?.focus({preventScroll: true});
        }
    }
    function cancelIngredientDeletion({restoreFocus = true} = {}) {
        if (!ingredientDeletingRow || ingredientMutationPending) return;
        const row = ingredientDeletingRow;
        ingredientDeletingRow = null;
        ingredientStatus('', false, row);
        syncIngredientRowControls();
        if (restoreFocus) row.querySelector('[data-ingredient-row-delete]')?.focus({preventScroll: true});
    }
    function confirmIngredientDeletion(row) {
        const button = row?.querySelector('[data-ingredient-row-delete]');
        if (!button || button.disabled || ingredientMutationPending || ingredientRowIsDirty(ingredientEditingRow)) return;
        if (ingredientEditingRow) cancelIngredientRow(ingredientEditingRow, {restoreFocus: false});
        cancelIngredientDeletion({restoreFocus: false});
        ingredientDeletingRow = row;
        ingredientStatus('', false, row);
        syncIngredientRowControls();
        row.querySelector('[data-ingredient-row-cancel]').focus({preventScroll: true});
    }
    async function deleteIngredientRow(row) {
        const button = row?.querySelector('[data-ingredient-row-confirm-delete]');
        const remove = row?.querySelector('[data-ingredient-row-delete]');
        if (row !== ingredientDeletingRow || !button || !remove || button.disabled || ingredientMutationPending || ingredientRowIsDirty(ingredientEditingRow)) return;
        const name = row.dataset.recordName;
        const nextRowId = ingredientRows().find(item => item !== row)?.dataset.masterRecordId;
        ingredientMutationPending = true;
        syncIngredientRowControls();
        let deleted = false;
        try {
            const response = await fetch(remove.dataset.deleteUrl, {
                method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
                body: JSON.stringify({confirm: true, redirect_url: window.location.href}),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                if (result.result?.can_delete === false) {
                    remove.remove(); button.remove(); ingredientDeletingRow = null;
                }
                throw new Error(result.result?.delete_blocked_reason || result.message || result.error || 'The ingredient could not be deleted.');
            }
            deleted = true;
            ingredientDeletingRow = null;
            row.remove();
            await refreshMasterDataRecordResults();
            ingredientStatus(`${name} deleted.`);
        } catch (error) {
            if (deleted) ingredientRows().forEach(item => { item.dataset.orderEnabled = 'false'; });
            ingredientStatus(deleted ? 'Deleted. The table could not refresh; reload the page to see the updated group.' : error.message || 'The ingredient could not be deleted.', true, deleted ? null : row);
        } finally {
            ingredientMutationPending = false;
            syncIngredientRowControls();
            const target = deleted
                ? document.querySelector(`[data-ingredient-master-row][data-master-record-id="${nextRowId}"]`) || document.querySelector('.master-data-filter-form [name="search"]')
                : button.isConnected ? button : row;
            target?.focus({preventScroll: true});
        }
    }
    function ingredientSectionRows(row) {
        return ingredientRows().filter(other => other.dataset.userId === row.dataset.userId && other.dataset.storeSection === row.dataset.storeSection);
    }

    function placeIngredientRows(previous, ordered) {
        const anchor = document.createComment('ingredient order');
        previous[0].before(anchor);
        ordered.forEach((row, index) => {
            anchor.before(row);
            row.dataset.sortOrder = String(index);
            const number = row.querySelector('[data-ingredient-order-number]');
            number.textContent = String(index + 1);
            number.setAttribute('aria-label', `Position ${index + 1}`);
        });
        anchor.remove();
    }

    function moveIngredientRow(row, targetIndex, trigger) {
        if (ingredientMutationPending || row.dataset.orderEnabled !== 'true' || !editIngredientRow(row)) return;
        const previous = ingredientSectionRows(row);
        const current = previous.indexOf(row);
        const target = Math.max(0, Math.min(previous.length - 1, targetIndex));
        if (current === target) return;
        const restoreScroll = captureIngredientScroll(row);
        if (!ingredientOrderOriginal) ingredientOrderOriginal = [...previous];
        const ordered = [...previous];
        ordered.splice(target, 0, ordered.splice(current, 1)[0]);
        ingredientOrderChange = ordered.every((item, index) => item === ingredientOrderOriginal[index]) ? null : {
            position: target + 1, expected_ids: ingredientOrderOriginal.map(item => Number(item.dataset.masterRecordId)),
        };
        placeIngredientRows(previous, ordered);
        ingredientStatus('', false, row); syncIngredientRowControls();
        (trigger?.disabled ? row.querySelector('[data-ingredient-order-handle]') : trigger)?.focus({preventScroll: true});
        restoreScroll();
    }
    function initIngredientStoreSectionPicker(row) {
        const select = row.querySelector('[data-ingredient-row-section]');
        if (select.dataset.storeSectionControlBound === 'true') return;
        select.dataset.storeSectionControlBound = 'true';
        select.dataset.storeSectionAllowCustom = 'false';
        const wrapper = select.closest('.ingredient-section-summary');
        wrapper.classList.add('recipe-edit-store-section-label', 'master-data-store-section-picker');
        wrapper.querySelector('.recipe-edit-store-section-icon')?.remove();
        const trigger = createRecipeIngredientStoreSectionTrigger(select);
        trigger.classList.add('ingredient-row-section', 'master-data-store-section-trigger');
        trigger.setAttribute('aria-label', select.getAttribute('aria-label'));
        trigger.setAttribute('aria-describedby', select.getAttribute('aria-describedby'));
        // Capture the original section before the shared menu changes the select.
        const beginEditing = event => {
            if (!editIngredientRow(row)) { event.preventDefault(); event.stopImmediatePropagation(); }
        };
        trigger.addEventListener('click', beginEditing, true);
        trigger.addEventListener('keydown', event => {
            if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key) || recipeEditListboxTypeaheadKey(event)) beginEditing(event);
        }, true);
        select.hidden = true;
        wrapper.insertBefore(trigger, select);
    }

    function initIngredientRegistry() {
        const root = document.querySelector('.ingredient-master-page'); if (!root) return;
        ingredientRows().forEach(row => {
            initIngredientStoreSectionPicker(row);
            if (row.ingredientOriginal) return;
            row.ingredientOriginal = ingredientRowValues(row);
            const merge = row.querySelector('[data-master-merge-open]');
            merge.dataset.mergeTitle = merge.title;
        });
        syncIngredientRowControls();
        if (root.dataset.ingredientRegistryBound) return;
        root.dataset.ingredientRegistryBound = 'true';
        const form = document.getElementById('ingredientAliasManager');
        form.addEventListener('input', () => {
            delete ingredientEditorErrors.aliases;
            ingredientStatus('', false, ingredientEditingRow); syncIngredientRowControls();
        });
        ingredientEditorControl('alias-add').addEventListener('click', () => { addIngredientAlias(); ingredientEditorControl('alias-input').focus({preventScroll: true}); });
        ingredientEditorControl('close-aliases').addEventListener('click', () => { closeIngredientAliases(); syncIngredientRowControls(); });
        ingredientEditorControl('retry').addEventListener('click', () => loadIngredientEditor(ingredientEditingRow, ++ingredientEditorToken));
        document.querySelector('[data-ingredient-image-file]').addEventListener('change', event => { if (event.target.files[0]) void prepareIngredientImage(event.target.files[0]); });
        root.addEventListener('focusin', event => {
            if (event.target.matches('[data-ingredient-row-name]') && !editIngredientRow(event.target.closest('[data-ingredient-master-row]'))) {
                ingredientEditingRow?.querySelector('[data-ingredient-row-name]').focus({preventScroll: true});
            }
        });
        form.addEventListener('keydown', event => {
            if (event.target === ingredientEditorControl('alias-input') && ['Enter', ','].includes(event.key)) { event.preventDefault(); addIngredientAlias(); }
            else if (event.key === 'Escape') {
                event.preventDefault();
                if (ingredientAliasAnchor) { closeIngredientAliases(); syncIngredientRowControls(); }
                else cancelIngredientRow(ingredientEditingRow, {discard: true});
            }
        });
        const updateInlineValue = event => {
            const control = event.target;
            if (!control.matches('[data-ingredient-row-name], [data-ingredient-row-section]')) return;
            const row = control.closest('[data-ingredient-master-row]'), value = control.value;
            if (!editIngredientRow(row)) { control.value = row.ingredientOriginal[control.matches('[data-ingredient-row-name]') ? 'name' : 'store_section']; return; }
            control.value = value;
            const key = control.matches('[data-ingredient-row-name]') ? 'name' : 'section';
            delete ingredientEditorErrors[key];
            ingredientStatus('', false, row); syncIngredientRowControls();
        };
        root.addEventListener('input', updateInlineValue);
        root.addEventListener('change', updateInlineValue);
        document.addEventListener('pointerdown', event => {
            if (ingredientAliasAnchor && !form.contains(event.target) && !ingredientAliasAnchor.contains(event.target)) {
                closeIngredientAliases({restoreFocus: false}); syncIngredientRowControls();
            }
        });
        const positionAliases = () => {
            if (ingredientAliasAnchor) window.MasterDataAliasEditor.positionPopover(form, ingredientAliasAnchor);
        };
        window.addEventListener('resize', positionAliases);
        document.addEventListener('scroll', positionAliases, true);
        root.addEventListener('submit', event => {
            if (event.target.matches('.master-data-filter-form') && ingredientRowIsDirty(ingredientEditingRow)) {
                if (!cancelIngredientRow(ingredientEditingRow, {restoreFocus: false})) event.preventDefault();
            }
        });
        root.addEventListener('click', event => {
            const button = event.target.closest('button'), row = button?.closest('[data-ingredient-master-row]'); if (!row) return;
            if (button.matches('[data-ingredient-row-alias]')) openIngredientAliases(row, button);
            else if (button.matches('[data-ingredient-row-save]')) { event.preventDefault(); void saveIngredientRow(row); }
            else if (button.matches('[data-ingredient-row-cancel]')) {
                if (row === ingredientDeletingRow) cancelIngredientDeletion();
                else cancelIngredientRow(row, {discard: true});
            }
            else if (button.matches('[data-ingredient-row-delete]')) confirmIngredientDeletion(row);
            else if (button.matches('[data-ingredient-row-confirm-delete]')) void deleteIngredientRow(row);
            else if (button.matches('[data-ingredient-row-retry]')) void loadIngredientEditor(row, ++ingredientEditorToken);
            else if (button.matches('[data-ingredient-order-action]')) void moveIngredientRow(row, ingredientSectionRows(row).indexOf(row) + (button.dataset.ingredientOrderAction === 'up' ? -1 : 1), button);
            else if (button.matches('[data-master-merge-open]')) {
                cancelIngredientDeletion({restoreFocus: false});
                if (ingredientEditingRow && !ingredientRowIsDirty(ingredientEditingRow)) cancelIngredientRow(ingredientEditingRow, {restoreFocus: false});
            }
        });
        root.addEventListener('keydown', event => {
            if (event.defaultPrevented) return;
            const row = event.target.closest('[data-ingredient-master-row]'); if (!row) return;
            if (event.key === 'Escape' && row === ingredientDeletingRow) {
                event.preventDefault(); cancelIngredientDeletion(); return;
            }
            if (event.key === 'Escape' && row === ingredientEditingRow) {
                event.preventDefault(); cancelIngredientRow(row, {discard: true}); return;
            }
            if (event.key === 'Enter' && event.target.matches('[data-ingredient-row-name]')) {
                event.preventDefault(); void saveIngredientRow(row); return;
            }
            if (event.target.matches('[data-ingredient-order-handle]') && ['ArrowUp','ArrowDown','Home','End'].includes(event.key)) {
                event.preventDefault(); const rows = ingredientSectionRows(row);
                const target = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 : rows.indexOf(row) + (event.key === 'ArrowUp' ? -1 : 1);
                void moveIngredientRow(row, target, event.target);
            }
        });
        let dragged = null, dropTarget = null, dropAfter = false;
        const clearDrag = () => { ingredientRows().forEach(row => row.classList.remove('is-row-dragging','is-row-drop-before','is-row-drop-after')); dropTarget = null; };
        root.addEventListener('dragstart', event => {
            const handle = event.target.closest('[data-ingredient-order-handle]');
            if (!handle || handle.getAttribute('aria-disabled') === 'true') { event.preventDefault(); return; }
            dragged = handle.closest('[data-ingredient-master-row]'); dragged.classList.add('is-row-dragging');
            event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', dragged.dataset.masterRecordId);
        });
        root.addEventListener('dragover', event => {
            if (!dragged) return;
            event.preventDefault(); clearDrag();
            const target = event.target.closest('[data-ingredient-master-row]');
            if (ingredientMutationPending || !target || target === dragged || target.dataset.userId !== dragged.dataset.userId || target.dataset.storeSection !== dragged.dataset.storeSection) { event.dataTransfer.dropEffect = 'none'; return; }
            dropTarget = target; const rect = target.getBoundingClientRect(); dropAfter = event.clientY > rect.top + rect.height / 2;
            dragged.classList.add('is-row-dragging'); target.classList.add(dropAfter ? 'is-row-drop-after' : 'is-row-drop-before'); event.dataTransfer.dropEffect = 'move';
        });
        root.addEventListener('drop', event => {
            if (!dragged) return; event.preventDefault();
            if (dropTarget) {
                const rows = ingredientSectionRows(dragged); let target = rows.indexOf(dropTarget) + (dropAfter ? 1 : 0);
                if (rows.indexOf(dragged) < target) target--;
                void moveIngredientRow(dragged, target, dragged.querySelector('[data-ingredient-order-handle]'));
            }
            clearDrag(); dragged = null;
        });
        root.addEventListener('dragend', () => { clearDrag(); dragged = null; });
        window.addEventListener('beforeunload', event => {
            if (ingredientRowIsDirty(ingredientEditingRow) || ingredientMutationPending) { event.preventDefault(); event.returnValue = ''; }
        });
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

    function masterDataMergeRecordLabel(plural = false) {
        return document.querySelector('[data-master-merge-dialog]')?.dataset.recordType === 'equipment'
            ? 'equipment' : plural ? 'ingredients' : 'ingredient';
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
            els.submit.textContent = busy ? "Merging..." : `Merge ${masterDataMergeRecordLabel()}`;
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
        const sourceReferences = Number(els.dialog?.dataset.sourceReferenceCount);
        if (!Number.isInteger(sourceReferences) || sourceReferences < 0) return;
        els.targetId.value = targetId;
        if (els.targetName) els.targetName.textContent = targetName;
        if (els.combinedUsage) {
            els.combinedUsage.textContent = `${masterDataMergeUsageLabel(sourceReferences)} affected. The selected canonical ${masterDataMergeRecordLabel()} will be kept.`;
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
        button.dataset.ingredientId = text(ingredient.ingredient_id || ingredient.equipment_id || ingredient.id);
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
        detail.textContent = `${text(ingredient.normalized_name)} · ${text(ingredient.store_section || ingredient.equipment_section)}${aliases}`;
        copy.append(name, detail);

        const usage = document.createElement("span");
        usage.className = "master-data-merge-option-usage";
        const recipeCount = Math.max(0, Number(ingredient.usage_count) || 0);
        usage.textContent = `${recipeCount} recipe${recipeCount === 1 ? '' : 's'}`;
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
            empty.textContent = message || `No other master ${masterDataMergeRecordLabel(true)} match this search.`;
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
            renderMasterDataMergeOptions([], `Loading canonical ${masterDataMergeRecordLabel(true)}...`);
            setMasterDataMergeError("");
            try {
                const requestUrl = canonicalMasterDataUrl(optionsUrl, {
                    search: queryValue,
                    limit: "20",
                    ...(els.dialog.dataset.recordType === 'equipment' && els.dialog.dataset.preferredTargetId
                        ? {target_equipment_id: els.dialog.dataset.preferredTargetId} : {}),
                });
                const response = await fetch(requestUrl.toString(), {
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "fetch",
                    },
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.ok === false || data.success === false) {
                    throw new Error(data.error || `Canonical ${masterDataMergeRecordLabel(true)} could not be loaded.`);
                }
                if (requestId !== masterDataMergeRequestId || !els.dialog.open) {
                    return;
                }
                const referenceCount = data.source?.reference_count;
                if (!Number.isInteger(referenceCount) || referenceCount < 0) {
                    throw new Error(`Recipe references could not be counted. Try loading the canonical ${masterDataMergeRecordLabel(true)} again.`);
                }
                els.dialog.dataset.sourceReferenceCount = String(referenceCount);
                if (els.sourceUsage) els.sourceUsage.textContent = `${masterDataMergeUsageLabel(referenceCount)} affected`;
                if (els.targetId.value && els.combinedUsage) {
                    els.combinedUsage.textContent = `${masterDataMergeUsageLabel(referenceCount)} affected. The selected canonical ${masterDataMergeRecordLabel()} will be kept.`;
                }
                renderMasterDataMergeOptions(
                    data.ingredients || data.equipment,
                    queryValue
                        ? `No master ${masterDataMergeRecordLabel(true)} match “${queryValue}”.`
                        : `No other master ${masterDataMergeRecordLabel(true)} are available in this workspace.`
                );
                const preferredId = els.dialog.dataset.preferredTargetId;
                if (preferredId) {
                    const target = [...els.results.querySelectorAll('[role="option"]')]
                        .find(option => option.dataset.ingredientId === preferredId);
                    if (target) chooseMasterDataMergeTarget(target);
                    else setMasterDataMergeError('The conflicting equipment is no longer available in these results. Reload the equipment list to check its current owner.');
                    delete els.dialog.dataset.preferredTargetId;
                }
            } catch (error) {
                if (requestId === masterDataMergeRequestId) {
                    renderMasterDataMergeOptions([], `Canonical ${masterDataMergeRecordLabel(true)} could not be loaded.`);
                    setMasterDataMergeError(
                        error && error.message ? error.message : `Canonical ${masterDataMergeRecordLabel(true)} could not be loaded.`
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
            delete els.dialog.dataset.sourceReferenceCount;
            delete els.dialog.dataset.preferredTargetId;
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

    function openMasterDataMergeDialog(button, options = {}) {
        const els = masterDataMergeElements();
        if (!button || button.disabled || !els.dialog || !els.form || !els.search) {
            return;
        }
        if (ingredientMutationPending || ingredientRowIsDirty(ingredientEditingRow)) {
            ingredientStatus('Save or cancel the current ingredient before merging.', true, ingredientEditingRow);
            return;
        }
        if (window.EquipmentRegistry?.hasPendingWork()) return;

        masterDataMergeReturnFocus = button;
        els.form.action = text(button.dataset.mergeUrl);
        els.dialog.dataset.mergeOptionsUrl = text(button.dataset.mergeOptionsUrl);
        els.dialog.dataset.sourceUsageCount = text(button.dataset.sourceUsageCount || 0);
        delete els.dialog.dataset.sourceReferenceCount;
        if (els.sourceName) els.sourceName.textContent = text(button.dataset.sourceName);
        if (els.sourceNormalized) els.sourceNormalized.textContent = text(button.dataset.sourceNormalizedName);
        if (els.sourceUsage) {
            els.sourceUsage.textContent = 'Counting affected recipe references…';
        }
        els.search.value = text(options.targetName);
        if (options.targetId) els.dialog.dataset.preferredTargetId = text(options.targetId);
        else delete els.dialog.dataset.preferredTargetId;
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

    window.MasterDataMerge = {open: openMasterDataMergeDialog};

    async function submitMasterDataMerge(event) {
        event.preventDefault();
        const els = masterDataMergeElements();
        if (!els.form || !els.targetId || !els.targetId.value) {
            setMasterDataMergeError(`Choose the canonical ${masterDataMergeRecordLabel()} first.`);
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
                throw new Error(data.message || data.error || `The ${masterDataMergeRecordLabel()} records could not be merged.`);
            }
            if (els.selection) els.selection.classList.add("is-complete");
            if (els.combinedUsage) els.combinedUsage.textContent = data.message || 'Merge complete.';
            try {
                if (window.localStorage && masterDataMergeRecordLabel() === 'ingredient') {
                    window.localStorage.setItem(
                        INGREDIENT_MASTER_DATA_VERSION_STORAGE_KEY,
                        String(Date.now())
                    );
                }
            } catch (storageError) {
                console.debug("Unable to notify other tabs about the ingredient merge.", storageError);
            }
            window.setTimeout(() => {
                window.location.assign(
                    canonicalMasterDataUrl(data.redirect_url || window.location.href).toString()
                );
            }, 650);
        } catch (error) {
            setMasterDataMergeBusy(false);
            setMasterDataMergeError(
                error && error.message ? error.message : `The ${masterDataMergeRecordLabel()} records could not be merged.`
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
        const response = await fetch(canonicalMasterDataUrl(window.location.href).toString(), {
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
        const editingId = ingredientEditingRow?.dataset.masterRecordId;
        const activeRow = ingredientEditingRow;
        const replacements = requiredSelectors.map((selector) => {
            const current = document.querySelector(selector);
            const incoming = nextDocument.querySelector(selector);
            if (!current || !incoming) {
                throw new Error("The updated ingredient table was incomplete.");
            }
            return [current, incoming];
        });
        if (editingId) closeIngredientAliases({restoreFocus: false});
        replacements.forEach(([current, incoming]) => current.replaceWith(incoming));

        if (editingId) {
            ingredientEditingRow = document.querySelector(`[data-ingredient-master-row][data-master-record-id="${editingId}"]`);
            if (ingredientEditingRow) {
                ingredientEditingRow.replaceWith(activeRow);
                ingredientEditingRow = activeRow;
                if (ingredientOrderOriginal) {
                    const currentRows = ingredientSectionRows(activeRow);
                    ingredientOrderOriginal = ingredientOrderOriginal.map(old => currentRows.find(row => row.dataset.masterRecordId === old.dataset.masterRecordId)).filter(Boolean);
                    const ordered = [...ingredientOrderOriginal];
                    if (ingredientOrderChange) ordered.splice(ingredientOrderChange.position - 1, 0, ordered.splice(ordered.indexOf(activeRow), 1)[0]);
                    placeIngredientRows(currentRows, ordered);
                }
            } else {
                ingredientEditorContext = null;
                ingredientOrderOriginal = null; ingredientOrderChange = null;
            }
        }
        decorateMasterDataLightboxImages();
        applyMasterDataThumbnailSize(masterDataThumbnailSize);
        initIngredientRegistry();
        window.EquipmentRegistry?.sync();
    }

    // Equipment uses the same refreshed fragments and image decoration as Ingredient.
    window.MasterDataRegistryRefresh = refreshMasterDataRecordResults;

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
        const context = masterDataDuplicateRequestContext();
        return canonicalMasterDataUrl(
            text(duplicateEls.panel && duplicateEls.panel.dataset.reviewHistoryUrl),
            context
        ).toString();
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
            const context = masterDataDuplicateRequestContext();
            const url = canonicalMasterDataUrl(
                text(duplicateEls.panel.dataset.undoMergePreviewUrl),
                {
                    ...context,
                    merge_id: Number(mergeId) > 0 ? String(Number(mergeId)) : "",
                }
            );
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
        const url = canonicalMasterDataUrl(text(els.panel && els.panel.dataset.referenceUrl));
        url.pathname = url.pathname.replace(/\/0\/references$/, `/${Number(ingredientId) || 0}/references`);
        const context = masterDataDuplicateRequestContext();
        return canonicalMasterDataUrl(url, { ...context, limit: "500" }).toString();
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
        const context = masterDataDuplicateRequestContext();
        return canonicalMasterDataUrl(
            text(els.panel && els.panel.dataset.reviewsUrl),
            context
        ).toString();
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
                    : `No unresolved suggestions. Run a scan whenever your Ingredient records change.${masterDataDuplicateScanSuffix(data.scan)}`
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

        const url = canonicalMasterDataUrl(statusUrl, { job_id: jobId });

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

        const url = canonicalMasterDataUrl(statusUrl, { job_id: jobId });

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
                                window.location.assign(
                                    canonicalMasterDataUrl(
                                        form.dataset.imageRedirectUrl || window.location.href
                                    ).toString()
                                );
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
                    window.location.assign(canonicalMasterDataUrl(data.redirect_url).toString());
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
                        window.location.assign(
                            canonicalMasterDataUrl(
                                form.dataset.imageRedirectUrl || window.location.href
                            ).toString()
                        );
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
            imageUrl: text(change.image_url),
            form: text(change.form),
            referencesLoading: false,
            referencesData: null,
            referencesError: "",
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
            wasUnresolved: false,
            applying: false,
            applyError: "",
        }));
    }

    function miscReviewDecisionSource(row, section) {
        if (row.deterministic && section === row.deterministic.storeSection) return "deterministic";
        if (row.ai && section === row.ai.storeSection) return "ai";
        return section === "MISC" ? "keep_misc" : "manual";
    }

    function miscReviewDecisionForRow(row) {
        if (!row || !row.decisionSection) return null;
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
            row.applyError = "";
            renderMiscReclassificationRows(panel);
        });
        label.append(labelText, select);
        const controls = document.createElement("div");
        controls.className = "master-data-misc-decision-actions";
        const applyRowButton = document.createElement("button");
        applyRowButton.type = "button";
        applyRowButton.className = "master-data-misc-row-apply-button";
        applyRowButton.dataset.masterMiscRowApply = String(row.ingredientId);
        applyRowButton.textContent = row.applying ? "Applying..." : "Apply Row";
        applyRowButton.disabled = Boolean(row.applying || row.requiresDecision || !row.decisionSection);
        applyRowButton.setAttribute(
            "aria-label",
            `Apply store-section decision for ${miscReviewDisplayName(row.ingredient)}`
        );
        applyRowButton.addEventListener("click", () => requestMiscRowReclassification(panel, row));
        controls.append(label, applyRowButton);
        wrap.appendChild(controls);
        if (row.requiresDecision && !row.decisionSection) {
            const warning = document.createElement("small");
            warning.textContent = "AI disagrees—choose the final section.";
            wrap.appendChild(warning);
        }
        if (row.applyError) {
            const error = document.createElement("small");
            error.className = "master-data-misc-row-apply-error";
            error.setAttribute("role", "alert");
            error.textContent = row.applyError;
            wrap.appendChild(error);
        }
        return wrap;
    }

    function miscReviewMissingImage() {
        const missing = document.createElement("span");
        missing.className = "master-data-no-image master-data-misc-no-image";
        missing.textContent = "No image";
        return missing;
    }

    function miscReviewIngredientImage(row) {
        const imageUrl = text(row.imageUrl).trim();
        if (!imageUrl) return miscReviewMissingImage();
        const image = document.createElement("img");
        image.className = "master-data-thumbnail master-data-misc-thumbnail";
        image.src = imageUrl;
        image.dataset.fullSrc = imageUrl;
        image.alt = `${miscReviewDisplayName(row.ingredient)} image`;
        image.loading = "lazy";
        image.decoding = "async";
        image.tabIndex = 0;
        image.setAttribute("role", "button");
        image.setAttribute("aria-label", `Enlarge ${image.alt}`);
        image.addEventListener("error", () => image.replaceWith(miscReviewMissingImage()), { once: true });
        return image;
    }

    function miscReviewReferenceUrl(panel, ingredientId) {
        const rawUrl = text(panel && panel.dataset.referenceUrl).trim();
        if (!rawUrl) return "";
        try {
            const url = canonicalMasterDataUrl(rawUrl);
            url.pathname = url.pathname.replace(/\/0\/references$/, `/${Number(ingredientId) || 0}/references`);
            const scope = text(panel.dataset.scope).trim();
            const userId = text(panel.dataset.userId).trim();
            return canonicalMasterDataUrl(url, {
                scope,
                user_id: userId,
                limit: "500",
            }).toString();
        } catch (error) {
            return "";
        }
    }

    function miscReviewReferenceElements() {
        const dialog = document.querySelector("[data-master-misc-reference-dialog]");
        return {
            dialog,
            title: dialog && dialog.querySelector("[data-master-misc-reference-title]"),
            context: dialog && dialog.querySelector("[data-master-misc-reference-context]"),
            image: dialog && dialog.querySelector("[data-master-misc-reference-image]"),
            imageFallback: dialog && dialog.querySelector("[data-master-misc-reference-image-fallback]"),
            body: dialog && dialog.querySelector("[data-master-misc-reference-body]"),
            closeButtons: dialog ? dialog.querySelectorAll("[data-master-misc-reference-close]") : [],
        };
    }

    function setMiscReviewReferenceIdentity(els, row) {
        const ingredientName = miscReviewDisplayName(row.ingredient);
        if (els.title) els.title.textContent = `Recipes using ${ingredientName}`;
        if (els.context) els.context.textContent = "Loading connected recipes…";
        const imageUrl = text(row.imageUrl).trim();
        if (els.image) {
            els.image.hidden = !imageUrl;
            if (imageUrl) {
                els.image.src = imageUrl;
                els.image.alt = `${ingredientName} image`;
            } else {
                els.image.removeAttribute("src");
                els.image.alt = "";
            }
        }
        if (els.imageFallback) els.imageFallback.hidden = Boolean(imageUrl);
    }

    function renderMiscReviewReferenceDialog(els, row) {
        if (!els.body) return;
        if (row.referencesLoading) {
            setReferenceLoading(els.body);
            return;
        }
        if (row.referencesError) {
            setReferenceError(els.body, row.referencesError);
            if (els.context) els.context.textContent = "Connected recipes could not be loaded.";
            return;
        }
        if (row.referencesData) {
            renderReferences(els.body, row.referencesData);
            const references = Array.isArray(row.referencesData.references)
                ? row.referencesData.references
                : [];
            const total = Number(row.referencesData.total) || references.length;
            if (els.context) {
                els.context.textContent = `${total} connected recipe${total === 1 ? "" : "s"}. Recipe links open in a new tab.`;
            }
        }
    }

    function closeMiscReviewReferences() {
        const els = miscReviewReferenceElements();
        if (els.dialog && els.dialog.open) els.dialog.close();
    }

    async function openMiscReviewReferences(panel, row, trigger) {
        const els = miscReviewReferenceElements();
        if (!els.dialog || !els.body) return;
        masterDataMiscReferenceReturnFocus = trigger || null;
        setMiscReviewReferenceIdentity(els, row);
        if (!els.dialog.open) els.dialog.showModal();

        if (row.referencesData || row.referencesLoading) {
            renderMiscReviewReferenceDialog(els, row);
            return;
        }

        const referenceUrl = miscReviewReferenceUrl(panel, row.ingredientId);
        if (!referenceUrl || !window.fetch) {
            row.referencesError = "Recipe references are not available in this browser.";
            renderMiscReviewReferenceDialog(els, row);
            return;
        }

        row.referencesError = "";
        row.referencesLoading = true;
        renderMiscReviewReferenceDialog(els, row);
        try {
            const response = await fetch(referenceUrl, {
                headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || data.message || "Recipe references could not be loaded.");
            }
            row.referencesData = data;
        } catch (error) {
            row.referencesError = error && error.message
                ? error.message
                : "Recipe references could not be loaded.";
        } finally {
            row.referencesLoading = false;
            if (els.dialog.open) renderMiscReviewReferenceDialog(els, row);
        }
    }

    function miscReviewIngredientCell(panel, row) {
        const cell = document.createElement("div");
        cell.className = "master-data-misc-review-cell is-ingredient";
        const copy = document.createElement("div");
        copy.className = "master-data-misc-ingredient-copy";
        const name = document.createElement("button");
        name.type = "button";
        name.className = "master-data-misc-ingredient-name";
        name.setAttribute("aria-haspopup", "dialog");
        name.setAttribute("aria-controls", "masterDataMiscReferencesDialog");
        name.setAttribute("aria-label", `Show recipes referencing ${miscReviewDisplayName(row.ingredient)}`);
        const nameText = document.createElement("span");
        nameText.textContent = miscReviewDisplayName(row.ingredient);
        const indicator = document.createElement("span");
        indicator.className = "master-data-misc-ingredient-indicator";
        indicator.setAttribute("aria-hidden", "true");
        indicator.textContent = "↗";
        name.append(nameText, indicator);
        name.addEventListener("click", () => openMiscReviewReferences(panel, row, name));
        const current = document.createElement("span");
        current.className = "master-data-misc-current-label";
        current.textContent = "Currently: Misc";
        copy.append(name, current);
        cell.append(miscReviewIngredientImage(row), copy);
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
                    miscReviewIngredientCell(panel, row),
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
            .map(miscReviewDecisionForRow)
            .filter(Boolean);
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

    async function requestMiscRowReclassification(panel, row) {
        const decision = miscReviewDecisionForRow(row);
        if (!decision || row.requiresDecision || row.applying) return;
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        const undoButton = panel.querySelector("[data-master-misc-reclassification-undo]");
        const ingredientName = miscReviewDisplayName(row.ingredient);
        let finalMessage = "";
        row.applying = true;
        row.applyError = "";
        renderMiscReclassificationRows(panel);
        setMiscReviewBusy(panel, true);
        if (summary) summary.textContent = `Applying the decision for ${ingredientName}…`;
        try {
            const response = await fetch(panel.dataset.reclassifyUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({ apply: true, decisions: [decision] }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || `The decision for ${ingredientName} could not be applied.`);
            }
            if (!data.applied || Number(data.changed_count) < 1) {
                throw new Error(`${ingredientName} is no longer eligible for reclassification. Preview the list again.`);
            }
            row.applying = false;
            panel.miscReclassificationRows = (panel.miscReclassificationRows || []).filter(
                (candidate) => candidate.ingredientId !== row.ingredientId
            );
            if (row.wasUnresolved && panel.miscUnresolvedCount > 0) {
                panel.miscUnresolvedCount -= 1;
            }
            panel.dataset.undoAvailable = data.undo_available ? "true" : panel.dataset.undoAvailable;
            if (data.batch_id) panel.dataset.undoBatchId = String(data.batch_id);
            if (undoButton && data.undo_available) {
                undoButton.disabled = false;
                undoButton.textContent = `Review Undo (${Number(data.changed_count) || 1})`;
            }
            finalMessage = `Applied ${ingredientName} to ${friendlyIngredientStoreSection(decision.store_section)}. The other review rows were not changed.`;
        } catch (error) {
            row.applying = false;
            row.applyError = error && error.message
                ? error.message
                : `The decision for ${ingredientName} could not be applied.`;
            finalMessage = row.applyError;
        } finally {
            restoreMiscReviewControls(panel);
            if (summary) summary.textContent = finalMessage;
        }
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
                if (summary) summary.textContent = `Applied ${Number(data.changed_count) || 0} reviewed change${Number(data.changed_count) === 1 ? "" : "s"} to Ingredient.`;
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

    function miscStoreSectionUndoElements() {
        const dialog = document.querySelector("[data-master-store-section-undo-dialog]");
        return {
            dialog,
            summary: dialog && dialog.querySelector("[data-master-store-section-undo-summary]"),
            historyCount: dialog && dialog.querySelector("[data-master-store-section-undo-history-count]"),
            historyList: dialog && dialog.querySelector("[data-master-store-section-undo-history-list]"),
            status: dialog && dialog.querySelector("[data-master-store-section-undo-status]"),
            preview: dialog && dialog.querySelector("[data-master-store-section-undo-preview]"),
            position: dialog && dialog.querySelector("[data-master-store-section-undo-position]"),
            time: dialog && dialog.querySelector("[data-master-store-section-undo-time]"),
            restoredMontage: dialog && dialog.querySelector("[data-master-store-section-undo-restored-montage]"),
            restoredTitle: dialog && dialog.querySelector("[data-master-store-section-undo-restored-title]"),
            restoredSummary: dialog && dialog.querySelector("[data-master-store-section-undo-restored-summary]"),
            restoredSections: dialog && dialog.querySelector("[data-master-store-section-undo-restored-sections]"),
            currentMontage: dialog && dialog.querySelector("[data-master-store-section-undo-current-montage]"),
            currentTitle: dialog && dialog.querySelector("[data-master-store-section-undo-current-title]"),
            currentSummary: dialog && dialog.querySelector("[data-master-store-section-undo-current-summary]"),
            currentSections: dialog && dialog.querySelector("[data-master-store-section-undo-current-sections]"),
            recipeCount: dialog && dialog.querySelector("[data-master-store-section-undo-recipe-count]"),
            recipes: dialog && dialog.querySelector("[data-master-store-section-undo-recipes]"),
            listCount: dialog && dialog.querySelector("[data-master-store-section-undo-list-count]"),
            changeList: dialog && dialog.querySelector("[data-master-store-section-undo-change-list]"),
            impact: dialog && dialog.querySelector("[data-master-store-section-undo-impact]"),
            next: dialog && dialog.querySelector("[data-master-store-section-undo-next]"),
            footer: dialog && dialog.querySelector("[data-master-store-section-undo-footer]"),
            confirm: dialog && dialog.querySelector("[data-master-store-section-undo-confirm]"),
            closeButtons: dialog ? dialog.querySelectorAll("[data-master-store-section-undo-close]") : [],
        };
    }

    function setMiscStoreSectionUndoError(message) {
        const els = miscStoreSectionUndoElements();
        if (els.status) {
            els.status.hidden = false;
            els.status.classList.add("is-error");
            els.status.textContent = message;
        }
        if (els.preview) els.preview.hidden = true;
        if (els.confirm) els.confirm.disabled = true;
    }

    function miscStoreSectionUndoHistoryKey(item) {
        return `${Number(item && item.batch_id) || 0}:${Number(item && item.ingredient_id) || 0}`;
    }

    function miscStoreSectionUndoHistoryItem(panel, item, selectedItemKey) {
        const batchId = Number(item && item.batch_id) || 0;
        const ingredientId = Number(item && item.ingredient_id) || 0;
        const referenceCount = Math.max(0, Number(item && item.recipe_reference_count) || 0);
        const newerCount = Math.max(0, Number(item && item.newer_undo_count) || 0);
        const canUndoNow = Boolean(item && item.can_undo_now);
        const itemKey = miscStoreSectionUndoHistoryKey(item);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "master-data-undo-history-item master-data-store-section-undo-history-item";
        button.classList.toggle("is-blocked", !canUndoNow);
        button.dataset.masterStoreSectionUndoHistoryItemId = itemKey;
        button.setAttribute("aria-current", itemKey === selectedItemKey ? "true" : "false");
        button.title = canUndoNow
            ? (newerCount
                ? "This decision can be safely restored out of order."
                : "This store-section decision can be restored now.")
            : text(item && item.blocked_reason).trim();

        const header = document.createElement("span");
        header.className = "master-data-undo-history-item-header";
        const name = document.createElement("strong");
        name.textContent = miscReviewDisplayName(item && item.ingredient);
        const badge = document.createElement("span");
        badge.className = "master-data-undo-history-item-badge";
        badge.textContent = canUndoNow ? (newerCount ? "Safe" : "Next") : "Blocked";
        header.append(name, badge);

        const label = document.createElement("span");
        label.className = "master-data-undo-history-item-target";
        const appliedSection = friendlyIngredientStoreSection(
            item && item.applied_store_section
        );
        const restoredSection = friendlyIngredientStoreSection(
            item && item.restored_store_section
        );
        label.textContent = `${appliedSection} \u2192 restore ${restoredSection}`;

        const meta = document.createElement("span");
        meta.className = "master-data-undo-history-item-meta";
        const time = document.createElement("span");
        time.textContent = masterDataUndoHistoryDateInfo(item && item.applied_at).time;
        const references = document.createElement("span");
        references.textContent = `${referenceCount} recipe ref${referenceCount === 1 ? "" : "s"}`;
        meta.append(time, references);
        button.append(header, label, meta);
        button.addEventListener("click", () => {
            const activeKey = miscStoreSectionUndoHistoryKey(activeMiscStoreSectionUndoPreview);
            if (batchId && ingredientId && itemKey !== activeKey) {
                void loadMiscStoreSectionUndoPreview(panel, batchId, ingredientId);
            }
        });
        return button;
    }

    function renderMiscStoreSectionUndoHistory(panel, items, selectedItemKey) {
        const els = miscStoreSectionUndoElements();
        const rows = Array.isArray(items) ? items : [];
        if (els.historyCount) els.historyCount.textContent = String(rows.length);
        if (!els.historyList) return;
        els.historyList.replaceChildren();

        const groups = [];
        const groupsByKey = new Map();
        rows.forEach((item) => {
            const date = masterDataUndoHistoryDateInfo(item && item.applied_at);
            let group = groupsByKey.get(date.key);
            if (!group) {
                group = { ...date, items: [] };
                groupsByKey.set(date.key, group);
                groups.push(group);
            }
            group.items.push(item);
        });

        const selectedGroup = groups.find((group) => group.items.some(
            (item) => miscStoreSectionUndoHistoryKey(item) === selectedItemKey
        ));
        if (!miscStoreSectionUndoHistoryGroupsInitialized) {
            miscStoreSectionUndoCollapsedDateGroups.clear();
            groups.slice(1).forEach((group) => {
                miscStoreSectionUndoCollapsedDateGroups.add(group.key);
            });
            miscStoreSectionUndoHistoryGroupsInitialized = true;
        }
        if (selectedGroup) {
            miscStoreSectionUndoCollapsedDateGroups.delete(selectedGroup.key);
        }

        groups.forEach((group) => {
            const dateGroup = document.createElement("details");
            dateGroup.className = "master-data-undo-history-date-group";
            dateGroup.dataset.undoHistoryDate = group.key;
            dateGroup.open = !miscStoreSectionUndoCollapsedDateGroups.has(group.key);

            const summary = document.createElement("summary");
            summary.className = "master-data-undo-history-date-summary";
            const label = document.createElement("strong");
            label.textContent = group.label;
            const count = document.createElement("span");
            count.textContent = String(group.items.length);
            summary.append(label, count);

            const dateItems = document.createElement("div");
            dateItems.className = "master-data-undo-history-date-items";
            group.items.forEach((item) => {
                dateItems.appendChild(
                    miscStoreSectionUndoHistoryItem(panel, item, selectedItemKey)
                );
            });
            dateGroup.append(summary, dateItems);
            dateGroup.addEventListener("toggle", () => {
                if (dateGroup.open) {
                    miscStoreSectionUndoCollapsedDateGroups.delete(group.key);
                } else {
                    miscStoreSectionUndoCollapsedDateGroups.add(group.key);
                }
            });
            els.historyList.appendChild(dateGroup);
        });
    }

    function miscStoreSectionUndoImage(change) {
        const wrap = document.createElement("span");
        wrap.className = "master-data-store-section-undo-image";
        const imageUrl = text(change && change.image_url).trim();
        if (!imageUrl) {
            wrap.textContent = "↶";
            wrap.setAttribute("aria-hidden", "true");
            return wrap;
        }
        const image = document.createElement("img");
        image.src = imageUrl;
        image.alt = `${miscReviewDisplayName(change && change.ingredient)} image`;
        image.loading = "lazy";
        image.addEventListener("error", () => {
            wrap.replaceChildren();
            wrap.textContent = "↶";
            wrap.setAttribute("aria-hidden", "true");
        }, { once: true });
        wrap.appendChild(image);
        return wrap;
    }

    function renderMiscStoreSectionUndoChanges(container, changes) {
        if (!container) return;
        container.replaceChildren();
        const rows = Array.isArray(changes) ? changes : [];
        rows.forEach((change) => {
            const row = document.createElement("article");
            row.className = "master-data-store-section-undo-change";
            const identity = document.createElement("div");
            identity.className = "master-data-store-section-undo-identity";
            const copy = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = miscReviewDisplayName(change && change.ingredient);
            const references = document.createElement("span");
            const referenceCount = Math.max(0, Number(change && change.recipe_reference_count) || 0);
            references.textContent = `${referenceCount} linked recipe ingredient${referenceCount === 1 ? "" : "s"}`;
            copy.append(name, references);
            identity.append(miscStoreSectionUndoImage(change), copy);

            const transition = document.createElement("div");
            transition.className = "master-data-store-section-undo-transition";
            const applied = document.createElement("div");
            const appliedLabel = document.createElement("span");
            appliedLabel.textContent = "Applied";
            applied.append(
                appliedLabel,
                miscReviewSectionPill(change && change.applied_store_section, "is-current")
            );
            const arrow = document.createElement("span");
            arrow.className = "master-data-store-section-undo-arrow";
            arrow.textContent = "→";
            arrow.setAttribute("aria-hidden", "true");
            const restored = document.createElement("div");
            const restoredLabel = document.createElement("span");
            restoredLabel.textContent = "Restore";
            restored.append(
                restoredLabel,
                miscReviewSectionPill(change && change.restored_store_section, "is-restored")
            );
            transition.append(applied, arrow, restored);
            row.append(identity, transition);
            container.appendChild(row);
        });
    }

    function miscStoreSectionUndoDistribution(changes, field) {
        const counts = new Map();
        (Array.isArray(changes) ? changes : []).forEach((change) => {
            const section = friendlyIngredientStoreSection(change && change[field]) || "Misc";
            counts.set(section, (counts.get(section) || 0) + 1);
        });
        return Array.from(counts.entries())
            .map(([section, count]) => ({ section, count }))
            .sort((left, right) => right.count - left.count || left.section.localeCompare(right.section));
    }

    function renderMiscStoreSectionUndoDistribution(container, distribution) {
        if (!container) return;
        container.replaceChildren();
        const rows = Array.isArray(distribution) ? distribution : [];
        const visible = rows.slice(0, 4);
        visible.forEach((entry) => {
            const chip = document.createElement("span");
            const label = document.createElement("strong");
            label.textContent = entry.section;
            const count = document.createElement("small");
            count.textContent = String(entry.count);
            chip.append(label, count);
            container.appendChild(chip);
        });
        if (rows.length > visible.length) {
            const more = document.createElement("span");
            more.className = "is-more";
            more.textContent = `+${rows.length - visible.length} sections`;
            container.appendChild(more);
        }
    }

    function renderMiscStoreSectionUndoMontage(container, changes) {
        if (!container) return;
        container.replaceChildren();
        const rows = Array.isArray(changes) ? changes : [];
        const images = rows
            .filter((change) => text(change && change.image_url).trim())
            .slice(0, 3);
        images.forEach((change) => {
            const frame = document.createElement("span");
            const image = document.createElement("img");
            image.src = text(change.image_url).trim();
            image.alt = "";
            image.loading = "lazy";
            image.addEventListener("error", () => frame.remove(), { once: true });
            frame.appendChild(image);
            container.appendChild(frame);
        });
        if (!images.length) {
            const fallback = document.createElement("span");
            fallback.className = "is-fallback";
            fallback.textContent = "↶";
            fallback.setAttribute("aria-hidden", "true");
            container.appendChild(fallback);
        }
        const remaining = Math.max(0, rows.length - images.length);
        if (remaining) {
            const more = document.createElement("strong");
            more.textContent = `+${remaining}`;
            more.setAttribute("aria-label", `${remaining} additional ingredients`);
            container.appendChild(more);
        }
    }

    function renderMiscStoreSectionUndoRecipes(els, preview) {
        const references = Array.isArray(preview && preview.recipe_references)
            ? preview.recipe_references
            : [];
        const affectedCount = Math.max(
            references.length,
            Number(preview && preview.affected_recipe_count) || 0
        );
        if (els.recipeCount) {
            els.recipeCount.textContent = `${affectedCount} affected`;
        }
        if (!references.length && els.recipes) {
            els.recipes.replaceChildren();
            const empty = document.createElement("div");
            empty.className = "master-data-undo-preview-reference";
            const label = document.createElement("strong");
            label.textContent = "No linked recipes need restoration.";
            empty.appendChild(label);
            els.recipes.appendChild(empty);
            return;
        }
        const visible = references.slice(0, 6).map((reference) => {
            const ingredientCount = Math.max(0, Number(reference.ingredient_reference_count) || 0);
            const ingredients = Array.isArray(reference.ingredients) ? reference.ingredients : [];
            return {
                recipe_title: reference.recipe_title,
                quantity: String(ingredientCount),
                unit: `ingredient${ingredientCount === 1 ? "" : "s"}`,
                original_recipe_text: ingredients.slice(0, 4).join(", "),
            };
        });
        renderMasterDataUndoPreviewReferences(
            els.recipes,
            visible,
            references.length > visible.length
        );
    }

    function renderMiscStoreSectionUndoComparison(els, preview) {
        const changes = Array.isArray(preview && preview.changes) ? preview.changes : [];
        const changeCount = changes.length;
        const restoredDistribution = miscStoreSectionUndoDistribution(
            changes,
            "restored_store_section"
        );
        const currentDistribution = miscStoreSectionUndoDistribution(
            changes,
            "applied_store_section"
        );
        renderMiscStoreSectionUndoMontage(els.restoredMontage, changes);
        renderMiscStoreSectionUndoMontage(els.currentMontage, changes);
        renderMiscStoreSectionUndoDistribution(els.restoredSections, restoredDistribution);
        renderMiscStoreSectionUndoDistribution(els.currentSections, currentDistribution);
        if (els.restoredTitle) {
            els.restoredTitle.textContent = `${changeCount} previous assignment${changeCount === 1 ? "" : "s"}`;
        }
        if (els.currentTitle) {
            els.currentTitle.textContent = `${changeCount} current assignment${changeCount === 1 ? "" : "s"}`;
        }
        if (els.restoredSummary) {
            els.restoredSummary.textContent = `Restore ${restoredDistribution.length} prior store section${restoredDistribution.length === 1 ? "" : "s"}.`;
        }
        if (els.currentSummary) {
            els.currentSummary.textContent = `Keep classifications across ${currentDistribution.length} store section${currentDistribution.length === 1 ? "" : "s"}.`;
        }
    }

    function renderMiscStoreSectionUndoPreview(panel, preview, items) {
        const els = miscStoreSectionUndoElements();
        if (!els.dialog || !preview) return;
        activeMiscStoreSectionUndoPreview = preview;
        const changeCount = Math.max(0, Number(preview.change_count) || 0);
        const referenceCount = Math.max(0, Number(preview.recipe_reference_count) || 0);
        const newerCount = Math.max(
            0,
            Number(preview.newer_undo_item_count ?? preview.newer_undo_count) || 0
        );
        const otherCount = Math.max(0, Number(preview.other_undo_count) || 0);
        const canUndoNow = Boolean(preview.can_undo_now);
        const isNextUndo = Boolean(preview.is_next_undo) && newerCount === 0;
        const selectedChange = Array.isArray(preview.changes) ? preview.changes[0] : null;
        const ingredientName = miscReviewDisplayName(
            selectedChange && selectedChange.ingredient
        );
        if (els.summary) {
            els.summary.textContent = `Restore ${ingredientName} to its previous store-section assignment.`;
        }
        if (els.position) {
            els.position.textContent = canUndoNow
                ? (isNextUndo
                    ? "Undo next \u2022 newest decision"
                    : "Safe out-of-order undo")
                : `Blocked by ${newerCount} newer decision${newerCount === 1 ? "" : "s"}`;
        }
        if (els.time) {
            els.time.textContent = formatMasterDataDuplicateScanTime(preview.applied_at)
                || "Apply time unavailable";
        }
        if (els.listCount) {
            els.listCount.textContent = `${changeCount} change${changeCount === 1 ? "" : "s"}`;
        }
        renderMiscStoreSectionUndoComparison(els, preview);
        renderMiscStoreSectionUndoRecipes(els, preview);
        renderMiscStoreSectionUndoChanges(els.changeList, preview.changes);
        if (els.impact) {
            els.impact.replaceChildren();
            appendMasterDataUndoPreviewImpact(
                els.impact,
                `Restore ${changeCount} Ingredient store-section assignment${changeCount === 1 ? "" : "s"}.`
            );
            appendMasterDataUndoPreviewImpact(
                els.impact,
                referenceCount
                    ? `Restore ${referenceCount} linked recipe ingredient assignment${referenceCount === 1 ? "" : "s"}.`
                    : "No linked recipe ingredient assignments need to be restored."
            );
            appendMasterDataUndoPreviewImpact(
                els.impact,
                "Restore the prior source, confidence, confirmation state, classifier version, and rule metadata."
            );
        }
        if (els.next) {
            els.next.classList.toggle("is-blocked", !canUndoNow);
            els.next.textContent = !canUndoNow
                ? text(preview.blocked_reason).trim() || "Undo newer store-section decisions first."
                : otherCount
                ? `${otherCount} other store-section decision${otherCount === 1 ? "" : "s"} will remain available after this undo.`
                : "This is the last remaining store-section decision in the undo history.";
        }
        if (els.footer) {
            els.footer.textContent = canUndoNow
                ? "Undoing this decision will automatically advance the store-section history stack."
                : "This decision is read-only until newer decisions have been undone.";
        }
        if (els.status) {
            els.status.hidden = true;
            els.status.classList.remove("is-error");
        }
        if (els.preview) els.preview.hidden = false;
        if (els.confirm) {
            els.confirm.disabled = !canUndoNow;
            els.confirm.textContent = canUndoNow
                ? `Undo and restore ${ingredientName}`
                : "Cannot undo this decision yet";
        }
        renderMiscStoreSectionUndoHistory(
            panel,
            items || preview.history_items,
            miscStoreSectionUndoHistoryKey(preview)
        );
    }

    async function loadMiscStoreSectionUndoPreview(panel, batchId = 0, ingredientId = 0) {
        const els = miscStoreSectionUndoElements();
        if (!panel || !els.dialog || !panel.dataset.undoPreviewUrl) return false;
        activeMiscStoreSectionUndoPreview = null;
        if (els.preview) els.preview.hidden = true;
        if (els.summary) els.summary.textContent = "Loading store-section restore details...";
        if (els.status) {
            els.status.hidden = false;
            els.status.classList.remove("is-error");
            els.status.textContent = "Loading undo details...";
        }
        if (els.confirm) {
            els.confirm.disabled = true;
            els.confirm.textContent = "Undo this decision";
        }
        try {
            const url = canonicalMasterDataUrl(panel.dataset.undoPreviewUrl, {
                batch_id: Number(batchId) > 0 ? String(Number(batchId)) : "",
                ingredient_id: Number(ingredientId) > 0 ? String(Number(ingredientId)) : "",
            });
            const response = await fetch(url.toString(), {
                headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false || !data.preview) {
                throw new Error(data.error || "The latest store-section decision could not be previewed.");
            }
            renderMiscStoreSectionUndoPreview(panel, data.preview, data.items);
            return true;
        } catch (error) {
            setMiscStoreSectionUndoError(
                error && error.message
                    ? error.message
                    : "The latest store-section decision could not be previewed."
            );
            return false;
        }
    }

    async function openMiscStoreSectionUndoPreview(panel, trigger) {
        const els = miscStoreSectionUndoElements();
        if (!panel || !els.dialog || panel.dataset.undoAvailable !== "true") return;
        if (changedStoreSectionForms().length) {
            const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
            if (summary) summary.textContent = "Save pending ingredient edits before reviewing an undo.";
            return;
        }
        miscStoreSectionUndoReturnFocus = trigger || null;
        miscStoreSectionUndoCollapsedDateGroups.clear();
        miscStoreSectionUndoHistoryGroupsInitialized = false;
        if (els.historyList) els.historyList.replaceChildren();
        if (els.historyCount) els.historyCount.textContent = "0";
        if (!els.dialog.open) els.dialog.showModal();
        await loadMiscStoreSectionUndoPreview(panel);
    }

    function closeMiscStoreSectionUndoPreview() {
        const els = miscStoreSectionUndoElements();
        activeMiscStoreSectionUndoPreview = null;
        if (els.dialog && els.dialog.open) els.dialog.close();
    }

    async function requestMiscReclassificationUndo(panel) {
        const undoButton = panel.querySelector("[data-master-misc-reclassification-undo]");
        const summary = panel.querySelector("[data-master-misc-reclassification-summary]");
        const els = miscStoreSectionUndoElements();
        const preview = activeMiscStoreSectionUndoPreview;
        if (
            !undoButton
            || !els.dialog
            || !els.confirm
            || panel.dataset.undoAvailable !== "true"
            || !preview
            || !preview.can_undo_now
        ) return;
        const originalLabel = undoButton.textContent;
        const originalConfirmLabel = els.confirm.textContent;
        setMiscReviewBusy(panel, true);
        undoButton.textContent = "Restoring...";
        els.confirm.disabled = true;
        els.confirm.textContent = "Restoring...";
        if (els.status) {
            els.status.hidden = false;
            els.status.classList.remove("is-error");
            els.status.textContent = "Restoring the previous store-section assignments...";
        }
        if (summary) summary.textContent = "Restoring the previous store-section assignments...";
        try {
            const response = await fetch(panel.dataset.undoUrl, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    batch_id: Number(preview.batch_id) || 0,
                    ingredient_id: Number(preview.ingredient_id) || 0,
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || "The store-section decision could not be undone.");
            }
            panel.dataset.miscUndoComplete = "true";
            panel.dataset.undoAvailable = data.undo_available ? "true" : "false";
            panel.dataset.undoBatchId = data.next_batch && data.next_batch.batch_id
                ? String(data.next_batch.batch_id)
                : "";
            undoButton.textContent = "Restored";
            undoButton.disabled = true;
            els.confirm.textContent = "Restored";
            if (els.status) {
                els.status.hidden = false;
                els.status.textContent = data.message || "The previous store-section assignments were restored.";
            }
            if (summary) summary.textContent = data.message || "The previous store-section assignments were restored.";
            window.setTimeout(() => window.location.reload(), REFRESH_DELAY_MS);
        } catch (error) {
            const errorMessage = error && error.message
                ? error.message
                : "The store-section decision could not be undone.";
            if (summary) {
                summary.textContent = errorMessage;
            }
            if (els.status) {
                els.status.hidden = false;
                els.status.classList.add("is-error");
                els.status.textContent = errorMessage;
            }
            if (els.preview) els.preview.hidden = false;
            undoButton.textContent = originalLabel;
            els.confirm.textContent = originalConfirmLabel;
            els.confirm.disabled = !preview.can_undo_now;
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
                        imageUrl: text(opinion.image_url),
                        form: "",
                        referencesLoading: false,
                        referencesData: null,
                        referencesError: "",
                        deterministic: null,
                        ai: null,
                        decisionSection: "",
                        decisionSource: "",
                        requiresDecision: false,
                        wasUnresolved: true,
                        applying: false,
                        applyError: "",
                    };
                    rows.push(row);
                }
                if (!row) return;
                if (!row.imageUrl) row.imageUrl = text(opinion.image_url);
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

    function initMiscReviewReferenceDialog() {
        const els = miscReviewReferenceElements();
        if (!els.dialog) return;
        els.closeButtons.forEach((button) => {
            button.addEventListener("click", closeMiscReviewReferences);
        });
        els.dialog.addEventListener("click", (event) => {
            if (event.target === els.dialog) closeMiscReviewReferences();
        });
        els.dialog.addEventListener("close", () => {
            if (els.body) els.body.replaceChildren();
            const returnFocus = masterDataMiscReferenceReturnFocus;
            masterDataMiscReferenceReturnFocus = null;
            if (returnFocus && returnFocus.isConnected) returnFocus.focus();
        });
        if (els.image) {
            els.image.addEventListener("error", () => {
                els.image.hidden = true;
                if (els.imageFallback) els.imageFallback.hidden = false;
            });
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
        if (undoButton) {
            undoButton.addEventListener("click", () => openMiscStoreSectionUndoPreview(panel, undoButton));
        }
        const undoEls = miscStoreSectionUndoElements();
        if (undoEls.dialog) {
            undoEls.closeButtons.forEach((button) => {
                button.addEventListener("click", closeMiscStoreSectionUndoPreview);
            });
            if (undoEls.confirm) {
                undoEls.confirm.addEventListener("click", () => requestMiscReclassificationUndo(panel));
            }
            undoEls.dialog.addEventListener("cancel", (event) => {
                event.preventDefault();
                closeMiscStoreSectionUndoPreview();
            });
            undoEls.dialog.addEventListener("click", (event) => {
                if (event.target === undoEls.dialog) closeMiscStoreSectionUndoPreview();
            });
            undoEls.dialog.addEventListener("close", () => {
                activeMiscStoreSectionUndoPreview = null;
                const returnFocus = miscStoreSectionUndoReturnFocus;
                miscStoreSectionUndoReturnFocus = null;
                if (returnFocus && returnFocus.isConnected) returnFocus.focus();
            });
        }
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

    function initMasterDataMaintenance() {
        const maintenance = document.querySelector("[data-master-maintenance]");
        if (!maintenance) return;

        const pagination = document.querySelector("[data-master-pagination]");
        if (pagination && pagination.parentElement === maintenance.parentElement) {
            pagination.insertAdjacentElement("afterend", maintenance);
        }
        maintenance.open = false;
    }

    function initMasterDataPage() {
        initMasterDataFilterForm();
        initMasterDataMaintenance();
        initMasterDataReferences();
        initMasterDataThumbnailSizeControls();
        initMasterDataImageLightbox();
        initIngredientRegistry();
        initMasterDataIngredientMerge();
        initMasterDataDuplicateReview();
        initMiscReviewReferenceDialog();
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
