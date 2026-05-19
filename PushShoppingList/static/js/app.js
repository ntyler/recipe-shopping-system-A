function saveScroll() {
    localStorage.setItem("scrollY", window.scrollY);
}

let hiddenExtractJobId = null;
let lastRenderedExtractJobId = null;
let extractRefreshTimer = null;
let extractAutoCloseTimer = null;
let lastRenderedExtractProgress = null;
let currentExtractAbortController = null;
let currentExtractAbortControllers = [];
let cancelExtractRequested = false;
const recipeQuantitySaveTimers = new WeakMap();
const recipeQuantityNoticeTimers = new Map();
const recipeQuantitySaveDelayMs = 2000;

function restoreScroll() {
    const scrollY = localStorage.getItem("scrollY");

    if (scrollY !== null) {
        window.scrollTo(0, parseInt(scrollY));
        localStorage.removeItem("scrollY");
    }
}

function showExtractionOverlay() {
    const modal = document.getElementById("extractProgressModalBackdrop");

    if (modal) {
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
    }
}

function hideExtractProgressModal() {
    const modal = document.getElementById("extractProgressModalBackdrop");

    if (modal) {
        hiddenExtractJobId = lastRenderedExtractJobId;
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }

    const url = new URL(window.location.href);
    url.searchParams.delete("extract_job");
    window.history.replaceState({}, "", url.toString());
}

function hideExtractionOverlay() {
    hideExtractProgressModal();
}

function showProductsOverlay() {
    const modal = document.getElementById("productsOverlay");

    if (modal) {
        modal.style.display = "flex";
    }
}

function hideProductsOverlay() {
    const modal = document.getElementById("productsOverlay");

    if (modal) {
        modal.style.display = "none";
    }
}

function openRecipeMediaUpload() {
    const input = document.getElementById("recipeMediaUploadInput");

    if (input) {
        input.click();
    }
}

async function submitRecipeMediaUpload(input) {
    const form = document.getElementById("recipeMediaUploadForm");
    const status = document.getElementById("recipeMediaUploadStatus");

    if (!form || !input || !input.files || !input.files.length) {
        return;
    }

    const file = input.files[0];

    if (status) {
        status.textContent = `Loading ${file.name}...`;
    }

    showRecipeFileLoadingOverlay(file.name);
    await waitForNextPaint();

    const formData = new FormData(form);
    formData.set("ajax", "1");

    updateRecipeFileLoadingStep("upload", "running", "Uploading file");
    const readingTimer = setTimeout(() => {
        updateRecipeFileLoadingStep("upload", "done", "Uploaded");
        updateRecipeFileLoadingStep("read", "running", "Reading file contents");
        setRecipeFileLoadingSummary("Reading the recipe from the selected file...");
    }, 600);
    const extractTimer = setTimeout(() => {
        updateRecipeFileLoadingStep("read", "done", "Readable text found");
        updateRecipeFileLoadingStep("extract", "running", "Extracting recipe data");
        setRecipeFileLoadingSummary("Extracting ingredients, quantities, instructions, and sections...");
    }, 1600);

    try {
        const response = await fetch(form.action, {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });
        const data = await response.json();

        clearTimeout(readingTimer);
        clearTimeout(extractTimer);

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to load file.");
        }

        updateRecipeFileLoadingStep("upload", "done", "Uploaded");
        updateRecipeFileLoadingStep("read", "done", "Read");
        updateRecipeFileLoadingStep("extract", "done", `${(data.ingredients || []).length} ingredients found`);
        updateRecipeFileLoadingStep("save", "running", "Saving to shopping list");
        setRecipeFileLoadingSummary("Saving ingredients and refreshing the shopping list...");
        await waitForNextPaint();

        window.location.reload();
    } catch (err) {
        clearTimeout(readingTimer);
        clearTimeout(extractTimer);
        updateRecipeFileLoadingStep("extract", "failed", "Failed");
        updateRecipeFileLoadingStep("save", "failed", "Not saved");
        setRecipeFileLoadingSummary(err.message || "Unable to load file.");

        if (status) {
            status.textContent = err.message || "Unable to load file.";
        }
    } finally {
        input.value = "";
    }
}

function showRecipeFileLoadingOverlay(fileName) {
    let overlay = document.getElementById("recipeFileLoadingOverlay");

    if (!overlay) {
        overlay = document.createElement("div");
        overlay.id = "recipeFileLoadingOverlay";
        overlay.className = "recipe-qty-progress-backdrop recipe-file-loading-backdrop";
        overlay.setAttribute("aria-hidden", "true");
        overlay.innerHTML = `
            <div class="recipe-qty-progress-card" role="dialog" aria-modal="true" aria-labelledby="recipeFileLoadingTitle">
                <div class="recipe-qty-progress-header">
                    <h2 id="recipeFileLoadingTitle">Loading File</h2>
                    <button type="button" class="recipe-qty-progress-close" onclick="hideRecipeFileLoadingOverlay()">Hide</button>
                </div>
                <div id="recipeFileLoadingSummary" class="recipe-qty-progress-summary">Preparing file...</div>
                <div id="recipeFileLoadingList" class="recipe-qty-progress-list"></div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    const list = overlay.querySelector("#recipeFileLoadingList");
    const steps = [
        ["upload", "Upload", fileName],
        ["read", "Read File", "Detect text from photo, image, PDF, or document"],
        ["extract", "Extract Recipe", "Find ingredients, quantities, instructions, and recipe details"],
        ["save", "Save List", "Put ingredients where they belong"],
    ];

    list.innerHTML = steps.map(([key, name, detail]) => `
        <div class="recipe-qty-progress-row" data-file-step="${key}">
            <div class="recipe-qty-progress-main">
                <div class="recipe-qty-progress-name">${escapeHtml(name)}</div>
                <div class="recipe-qty-progress-qty">${escapeHtml(detail)}</div>
            </div>
            <div class="recipe-qty-progress-status waiting">Waiting</div>
        </div>
    `).join("");

    setRecipeFileLoadingSummary("Preparing to load the selected file...");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
}

function hideRecipeFileLoadingOverlay() {
    const overlay = document.getElementById("recipeFileLoadingOverlay");

    if (overlay) {
        overlay.classList.remove("open");
        overlay.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }
}

function updateRecipeFileLoadingStep(stepKey, state, message) {
    const row = document.querySelector(`[data-file-step="${stepKey}"]`);

    if (!row) {
        return;
    }

    const status = row.querySelector(".recipe-qty-progress-status");

    if (status) {
        status.className = `recipe-qty-progress-status ${state}`;
        status.textContent = message;
    }
}

function setRecipeFileLoadingSummary(message) {
    const summary = document.getElementById("recipeFileLoadingSummary");

    if (summary) {
        summary.textContent = message;
    }
}

function toggleCardCollapse(key) {
    const content = document.querySelector(`[data-collapse-content="${key}"]`);
    const icon = document.querySelector(`[data-collapse-icon="${key}"]`);
    const toggle = document.querySelector(`[data-collapse-toggle="${key}"]`);

    if (!content) {
        return;
    }

    const isCollapsed = content.classList.toggle("collapsed");
    localStorage.setItem(`card-collapse:${key}`, isCollapsed ? "collapsed" : "expanded");

    if (icon) {
        icon.textContent = isCollapsed ? "Show v" : "Hide ^";
    }

    if (toggle) {
        toggle.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    }
}

function cardCollapseDefaultIsCollapsed(content) {
    const mobileDefault = content.dataset.collapseMobileDefault;
    const defaultState = content.dataset.collapseDefault || "collapsed";

    if (mobileDefault && window.matchMedia && window.matchMedia("(max-width: 700px)").matches) {
        return mobileDefault === "collapsed";
    }

    return defaultState === "collapsed";
}

function toggleStorePanel(panelId) {
    const panel = document.getElementById(panelId);

    if (panel) {
        const isOpen = panel.classList.toggle("open");
        const openPanels = getOpenStorePanels();

        if (isOpen) {
            openPanels.add(panelId);
        } else {
            openPanels.delete(panelId);
        }

        saveOpenStorePanels(openPanels);
    }
}

function restoreCardCollapseState() {
    document.querySelectorAll("[data-collapse-content]").forEach(content => {
        const key = content.dataset.collapseContent;
        const icon = document.querySelector(`[data-collapse-icon="${key}"]`);
        const toggle = document.querySelector(`[data-collapse-toggle="${key}"]`);
        const savedState = localStorage.getItem(`card-collapse:${key}`);
        const shouldCollapse = savedState
            ? savedState === "collapsed"
            : cardCollapseDefaultIsCollapsed(content);

        content.classList.toggle("collapsed", shouldCollapse);

        if (icon) {
            icon.textContent = shouldCollapse ? "Show v" : "Hide ^";
        }

        if (toggle) {
            toggle.setAttribute("aria-expanded", shouldCollapse ? "false" : "true");
        }
    });
}

function getOpenStorePanels() {
    try {
        const savedPanels = JSON.parse(localStorage.getItem("store-open-panels") || "[]");
        return new Set(Array.isArray(savedPanels) ? savedPanels : []);
    } catch (err) {
        return new Set();
    }
}

function saveOpenStorePanels(openPanels) {
    localStorage.setItem("store-open-panels", JSON.stringify([...openPanels]));
}

function restoreOpenStorePanels() {
    const openPanels = getOpenStorePanels();
    const validOpenPanels = new Set();

    openPanels.forEach(panelId => {
        const panel = document.getElementById(panelId);

        if (panel) {
            panel.classList.add("open");
            validOpenPanels.add(panelId);
        }
    });

    saveOpenStorePanels(validOpenPanels);
}

function togglePasswordVisibility(inputId, button) {
    const input = document.getElementById(inputId);

    if (!input) {
        return;
    }

    const showing = input.type === "text";
    input.type = showing ? "password" : "text";

    if (button) {
        button.textContent = showing ? "Show" : "Hide";
    }
}

function showView(viewName) {
    const views = {
        section: document.getElementById("sectionView"),
        store: document.getElementById("storeView"),
        recipe: document.getElementById("recipeView"),
    };
    const buttons = {
        section: document.getElementById("sectionViewBtn"),
        store: document.getElementById("storeViewBtn"),
        recipe: document.getElementById("recipeViewBtn"),
    };

    Object.entries(views).forEach(([key, view]) => {
        if (view) {
            view.style.display = key === viewName ? "" : "none";
        }
    });

    Object.entries(buttons).forEach(([key, button]) => {
        if (button) {
            button.classList.toggle("active", key === viewName);
        }
    });

    localStorage.setItem("shopping-view", viewName);
    updateViewSwitcherStickyOffset();
}

function updateViewSwitcherStickyOffset() {
    const switcher = document.getElementById("viewSwitcherSticky");
    const height = switcher ? Math.ceil(switcher.getBoundingClientRect().height) : 0;

    document.documentElement.style.setProperty("--view-switcher-sticky-offset", `${height}px`);
}

function saveOpenStoreUrlsSetting() {
    saveToggleSetting("openStoreUrlsToggle", "open-store-urls", null);
}

function saveShowItemButtonsSetting() {
    saveToggleSetting("showItemButtonsToggle", "show-item-buttons", "hide-item-buttons", true);
}

function saveShowBestProductSetting() {
    saveToggleSetting("showBestProductToggle", "show-best-product", "hide-best-product", true);
}

function saveShowQtySetting() {
    saveToggleSetting("showQtyToggle", "show-qty", "hide-qty", true);
}

function saveHideCheckedItemsSetting() {
    saveToggleSetting("hideCheckedItemsToggle", "hide-checked-items", "hide-checked-items");
}

function saveCompactModeSetting() {
    saveToggleSetting("compactModeToggle", "compact-mode", "compact-mode");
}

function saveToggleSetting(inputId, storageKey, bodyClass, invertBodyClass = false) {
    const input = document.getElementById(inputId);

    if (!input) {
        return;
    }

    localStorage.setItem(storageKey, input.checked ? "1" : "0");

    if (bodyClass) {
        document.body.classList.toggle(
            bodyClass,
            invertBodyClass ? !input.checked : input.checked
        );
    }
}

function restoreViewBehaviorSettings() {
    restoreToggleSetting("openStoreUrlsToggle", "open-store-urls", true);
    restoreToggleSetting("showItemButtonsToggle", "show-item-buttons", true, "hide-item-buttons", true);
    restoreToggleSetting("showBestProductToggle", "show-best-product", true, "hide-best-product", true);
    restoreToggleSetting("showQtyToggle", "show-qty", true, "hide-qty", true);
    restoreToggleSetting("hideCheckedItemsToggle", "hide-checked-items", false, "hide-checked-items");
    restoreToggleSetting("compactModeToggle", "compact-mode", false, "compact-mode");
    showView(localStorage.getItem("shopping-view") || "section");
}

function restoreToggleSetting(inputId, storageKey, defaultChecked, bodyClass, invertBodyClass = false) {
    const input = document.getElementById(inputId);

    if (!input) {
        return;
    }

    const savedValue = localStorage.getItem(storageKey);
    input.checked = savedValue === null ? defaultChecked : savedValue === "1";

    if (bodyClass) {
        document.body.classList.toggle(
            bodyClass,
            invertBodyClass ? !input.checked : input.checked
        );
    }
}

function restoreItemCheckState() {
    document.querySelectorAll(".row[data-key]").forEach(row => {
        const checkbox = row.querySelector(".item-check");
        const itemText = row.querySelector(".item-text");

        if (!checkbox) {
            return;
        }

        const key = row.dataset.key;
        checkbox.checked = localStorage.getItem(`item-checked:${key}`) === "1";
        row.classList.toggle("row-checked", checkbox.checked);
        if (itemText) {
            itemText.classList.toggle("checked-item-text", checkbox.checked);
        }

        checkbox.addEventListener("change", () => {
            row.classList.toggle("row-checked", checkbox.checked);
            if (itemText) {
                itemText.classList.toggle("checked-item-text", checkbox.checked);
            }
            localStorage.setItem(`item-checked:${key}`, checkbox.checked ? "1" : "0");
        });
    });
}

function bindRecipeQuantityInputs() {
    document.querySelectorAll(".recipe-quantity-input").forEach(input => {
        if (input.dataset.quantityBound === "1") {
            return;
        }

        input.dataset.quantityBound = "1";
        input.dataset.lastSavedValue = input.value || "1";

        input.addEventListener("input", () => {
            normalizeRecipeQuantityInput(input);
        });

        input.addEventListener("change", () => {
            normalizeRecipeQuantityInput(input);
        });

        input.addEventListener("blur", () => {
            normalizeRecipeQuantityInput(input);
        });
    });

}

function bindRecipeNameInputs() {
    document.querySelectorAll(".recipe-name-input").forEach(input => {
        if (input.dataset.nameBound === "1") {
            return;
        }

        input.dataset.nameBound = "1";
        input.dataset.lastSavedValue = input.value || "";

        input.addEventListener("change", () => {
            saveRecipeName(input);
        });

        input.addEventListener("blur", () => {
            saveRecipeName(input);
        });

        input.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                input.blur();
            }
        });
    });
}

async function saveRecipeName(input) {
    const name = input.value.trim();

    if (input.dataset.lastSavedValue === name || input.dataset.savePending) {
        return;
    }

    input.dataset.savePending = "1";
    input.disabled = true;

    try {
        const response = await fetch("/api/recipe_name", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url: input.dataset.recipeUrl || "",
                name: name,
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to save recipe name.");
        }

        input.dataset.lastSavedValue = name;
        updateRecipeLogSummaryName(input.dataset.recipeUrl || "", data.name || name);
        input.classList.add("saved");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe name updated.");

        setTimeout(() => {
            input.classList.remove("saved");
        }, 700);
    } catch (err) {
        console.warn("Unable to save recipe name.", err);
        alert("Unable to save recipe name.");
    } finally {
        input.disabled = false;
        delete input.dataset.savePending;
    }
}

function updateRecipeLogSummaryName(recipeUrl, name) {
    if (!recipeUrl || !name) {
        return;
    }

    const selector = `.recipe-url-summary-name[data-recipe-url="${cssEscape(recipeUrl)}"]`;

    document.querySelectorAll(selector).forEach(link => {
        link.textContent = name;
    });
}

function normalizeRecipeQuantityInput(input) {
    input.value = Math.max(1, parseInt(input.value || "1", 10) || 1);
}

function queueRecipeQuantitySave(input, delayMs = recipeQuantitySaveDelayMs) {
    const existingTimer = recipeQuantitySaveTimers.get(input);

    if (existingTimer) {
        clearTimeout(existingTimer);
    }

    const timer = setTimeout(() => {
        saveRecipeQuantity(input);
        recipeQuantitySaveTimers.delete(input);
    }, delayMs);

    recipeQuantitySaveTimers.set(input, timer);
}

async function saveAllRecipeQuantities(button) {
    const inputs = [...document.querySelectorAll(".recipe-quantity-input")]
        .filter(input => {
            const nextQty = String(Math.max(1, parseInt(input.value || "1", 10) || 1));
            const savedQty = String(input.dataset.lastSavedValue || input.defaultValue || "1");

            return nextQty !== savedQty;
        });

    if (!inputs.length) {
        showRecipeQuantityUpdatedMessage("", "", "", "No recipe quantities changed.");
        return false;
    }

    const progressItems = buildRecipeQuantityProgressItems(inputs);
    showRecipeQuantityProgressOverlay(progressItems);

    if (button) {
        button.disabled = true;
        button.textContent = "Saving Qty...";
    }

    let failedCount = 0;

    try {
        for (const [index, input] of inputs.entries()) {
            updateRecipeQuantityProgressItem(index, "running", "Updating quantities with API...");

            try {
                await saveRecipeQuantity(input, {
                    force: true,
                    refresh: false,
                    message: false,
                    throwOnError: true,
                });
                updateRecipeQuantityProgressItem(index, "done", "Updated");
            } catch (err) {
                failedCount += 1;
                updateRecipeQuantityProgressItem(index, "failed", "Failed to update");
            }
        }

        setRecipeQuantityProgressSummary("Refreshing shopping list...");

        try {
            await refreshStoreMarkup();
            setRecipeQuantityProgressSummary(
                failedCount
                    ? `Finished with ${failedCount} failed update(s).`
                    : "All recipe quantities updated."
            );
        } catch (refreshErr) {
            console.warn("Unable to refresh recipe quantities in the background.", refreshErr);
            setRecipeQuantityProgressSummary("Quantities saved, but the page refresh failed.");
        }

        showRecipeQuantityUpdatedMessage(
            "",
            "",
            "",
            failedCount ? "Some recipe quantities failed." : "Recipe quantities updated."
        );
    } catch (err) {
        console.warn("Unable to save recipe quantities.", err);
        setRecipeQuantityProgressSummary("Unable to save recipe quantities.");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Save Qty";
        }
    }

    return false;
}

async function createNewRecipe(button) {
    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Creating...";
    }

    try {
        const response = await fetch("/api/create_recipe", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({}),
        });
        const data = await response.json();

        if (!response.ok || !data.ok || !data.url) {
            throw new Error((data && data.error) || "Unable to create recipe.");
        }

        await refreshStoreMarkup();
        showRecipeQuantityUpdatedMessage("", "", "", "New recipe created.");
        openRecipeEditor({ dataset: { recipeUrl: data.url } });
    } catch (err) {
        console.warn("Unable to create recipe.", err);
        alert("Unable to create recipe.");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Create New Recipe";
        }
    }

    return false;
}

function buildRecipeQuantityProgressItems(inputs) {
    return inputs.map(input => {
        const row = input.closest(".recipe-row");
        const left = row ? row.querySelector(".recipe-left") : null;
        const label = left
            ? left.textContent.trim().split(/\s+/).join(" ")
            : `Recipe ${input.dataset.recipeNumber || ""}`.trim();
        const previousQty = input.dataset.lastSavedValue || input.defaultValue || "1";
        const nextQty = String(Math.max(1, parseInt(input.value || "1", 10) || 1));

        return {
            label,
            previousQty,
            nextQty,
        };
    });
}

function showRecipeQuantityProgressOverlay(items) {
    let overlay = document.getElementById("recipeQtyProgressOverlay");

    if (!overlay) {
        overlay = document.createElement("div");
        overlay.id = "recipeQtyProgressOverlay";
        overlay.className = "recipe-qty-progress-backdrop";
        overlay.innerHTML = `
            <div class="recipe-qty-progress-card" role="dialog" aria-modal="true" aria-labelledby="recipeQtyProgressTitle">
                <div class="recipe-qty-progress-header">
                    <h2 id="recipeQtyProgressTitle">Updating Recipe Qty</h2>
                    <button type="button" class="recipe-qty-progress-close" onclick="hideRecipeQuantityProgressOverlay()">Hide</button>
                </div>
                <div id="recipeQtyProgressSummary" class="recipe-qty-progress-summary">Starting quantity updates...</div>
                <div id="recipeQtyProgressList" class="recipe-qty-progress-list"></div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    const list = overlay.querySelector("#recipeQtyProgressList");
    if (list) {
        list.innerHTML = items.map((item, index) => `
            <div class="recipe-qty-progress-row" data-progress-index="${index}">
                <div class="recipe-qty-progress-main">
                    <div class="recipe-qty-progress-name">${escapeHtml(item.label)}</div>
                    <div class="recipe-qty-progress-qty">Qty ${escapeHtml(item.previousQty)} -> ${escapeHtml(item.nextQty)}</div>
                </div>
                <div class="recipe-qty-progress-status waiting">Waiting</div>
            </div>
        `).join("");
    }

    setRecipeQuantityProgressSummary("Starting quantity updates...");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
}

function hideRecipeQuantityProgressOverlay() {
    const overlay = document.getElementById("recipeQtyProgressOverlay");

    if (overlay) {
        overlay.classList.remove("open");
        overlay.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }
}

function setRecipeQuantityProgressSummary(message) {
    const summary = document.getElementById("recipeQtyProgressSummary");

    if (summary) {
        summary.textContent = message;
    }
}

function updateRecipeQuantityProgressItem(index, state, message) {
    const row = document.querySelector(`.recipe-qty-progress-row[data-progress-index="${index}"]`);

    if (!row) {
        return;
    }

    const status = row.querySelector(".recipe-qty-progress-status");
    row.classList.remove("waiting", "running", "done", "failed");
    row.classList.add(state);

    if (status) {
        status.className = `recipe-qty-progress-status ${state}`;
        status.textContent = message;
    }
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value || "");
    return div.innerHTML;
}

function escapeAttribute(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
}

let recipeEditStoreSections = [];
let recipeEditFoodRules = { require: [], avoid: [] };
let recipeEditOriginalSnapshot = null;
let activeFoodReviewRow = null;
let activeFoodReviewAlternatives = [];

async function openRecipeEditor(button, options = {}) {
    const url = button ? button.dataset.recipeUrl || "" : "";
    const modal = document.getElementById("recipeEditModal");
    const shouldScrollToFoodReview = options === true || Boolean(options.scrollToFoodReview);

    if (!url || !modal) {
        return;
    }

    setRecipeEditStatus("Loading recipe...");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    try {
        const response = await fetch(`/api/recipe?url=${encodeURIComponent(url)}`, {
            cache: "no-store",
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to load recipe.");
        }

        recipeEditStoreSections = data.store_sections || [];
        recipeEditFoodRules = data.food_rules || { require: [], avoid: [] };
        populateRecipeEditor(data.recipe, url);
        requestAnimationFrame(updateRecipeEditStickyOffsets);
        setRecipeEditStatus("");
        if (shouldScrollToFoodReview) {
            await waitForNextPaint();
            scrollRecipeEditorToFoodReview();
        }
    } catch (err) {
        console.warn("Unable to open recipe editor.", err);
        setRecipeEditStatus("Unable to load recipe.", true);
    }
}

function closeRecipeEditor() {
    const modal = document.getElementById("recipeEditModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }
}

function populateRecipeEditor(recipe, originalUrl) {
    recipeEditOriginalSnapshot = normalizeRecipeEditorSnapshot({
        display_name: recipe.display_name || "",
        recipe_title: recipe.recipe_title || "",
        source_url: recipe.source_url || originalUrl,
        quantity: recipe.quantity || "1",
        servings: recipe.servings || "",
        ingredients: recipe.ingredients || [],
        equipment: recipe.equipment || [],
        instructions: recipe.instructions || [],
        nutrition: recipe.nutrition || [],
    });

    setValue("recipeEditOriginalUrl", originalUrl);
    setValue("recipeEditDisplayName", recipe.display_name || "");
    setValue("recipeEditTitleInput", recipe.recipe_title || "");
    setValue("recipeEditSourceUrl", recipe.source_url || originalUrl);
    setValue("recipeEditQuantity", recipe.quantity || "1");
    setValue("recipeEditServings", recipe.servings || "");

    const ingredientWrap = document.getElementById("recipeEditIngredients");
    const equipmentWrap = document.getElementById("recipeEditEquipment");
    const instructionWrap = document.getElementById("recipeEditInstructions");
    const nutritionWrap = document.getElementById("recipeEditNutrition");

    if (ingredientWrap) {
        ingredientWrap.innerHTML = "";
        (recipe.ingredients || []).forEach(item => addRecipeIngredientRow(item));
        if (!recipe.ingredients || !recipe.ingredients.length) {
            addRecipeIngredientRow();
        }
    }

    if (equipmentWrap) {
        equipmentWrap.innerHTML = recipeEquipmentHeaderHtml();
        (recipe.equipment || []).forEach(item => addRecipeEquipmentRow(item));
        if (!recipe.equipment || !recipe.equipment.length) {
            addRecipeEquipmentRow();
        }
    }

    if (instructionWrap) {
        instructionWrap.innerHTML = recipeInstructionsHeaderHtml();
        (recipe.instructions || []).forEach((item, index) => addRecipeInstructionRow(item, index + 1));
        if (!recipe.instructions || !recipe.instructions.length) {
            addRecipeInstructionRow();
        }
    }

    if (nutritionWrap) {
        nutritionWrap.innerHTML = recipeNutritionHeaderHtml();
        (recipe.nutrition || []).forEach(item => addRecipeNutritionRow(item));
        if (!recipe.nutrition || !recipe.nutrition.length) {
            addRecipeNutritionRow();
        }
    }

    updateRecipeEditStickyOffsets();
}

function updateRecipeEditStickyOffsets() {
    document.querySelectorAll(".recipe-edit-equipment-section, .recipe-edit-instructions-section, .recipe-edit-nutrition-section")
        .forEach(section => {
            const sectionHeader = section.querySelector(".recipe-edit-section-header");

            if (!sectionHeader) {
                return;
            }

            const stickyTop = parseFloat(getComputedStyle(sectionHeader).top) || 0;
            const tableTop = stickyTop + sectionHeader.offsetHeight;
            section.style.setProperty("--recipe-edit-table-sticky-top", `${Math.ceil(tableTop)}px`);
        });
}

function setValue(id, value) {
    const element = document.getElementById(id);

    if (element) {
        element.value = value;
    }
}

function setRecipeEditStatus(message, isError = false) {
    const status = document.getElementById("recipeEditStatus");

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("visible", Boolean(message));
    status.classList.toggle("error", Boolean(isError));
}

function scrollRecipeEditorToFoodReview() {
    const marker = document.querySelector("#recipeEditIngredients .recipe-edit-food-warning:not([hidden])");

    if (!marker) {
        return false;
    }

    const row = marker.closest(".recipe-edit-ingredient-row") || marker;
    document.querySelectorAll(".recipe-edit-review-target").forEach(element => {
        element.classList.remove("recipe-edit-review-target");
    });
    row.classList.add("recipe-edit-review-target");
    row.scrollIntoView({
        behavior: "smooth",
        block: "center",
        inline: "nearest",
    });

    const ingredientInput = row.querySelector('[data-field="ingredient"]');
    if (ingredientInput) {
        setTimeout(() => {
            try {
                ingredientInput.focus({ preventScroll: true });
            } catch (err) {
                ingredientInput.focus();
            }
        }, 250);
    }

    setTimeout(() => row.classList.remove("recipe-edit-review-target"), 2400);
    return true;
}

async function openFoodReviewAlternatives(marker) {
    const row = marker ? marker.closest(".recipe-edit-ingredient-row") : null;

    if (!row) {
        return false;
    }

    activeFoodReviewRow = row;
    activeFoodReviewAlternatives = [];
    showFoodReviewAlternativesModal();
    renderFoodReviewAlternativesLoading(row);

    try {
        const response = await fetch("/api/food_review_alternatives", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(foodReviewPayloadFromRow(row)),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to load alternatives.");
        }

        activeFoodReviewAlternatives = data.alternatives || [];
        renderFoodReviewAlternatives(data);
    } catch (err) {
        console.warn("Unable to load food review alternatives.", err);
        renderFoodReviewAlternativesError(err.message || "Unable to load alternatives.");
    }

    return false;
}

function openFoodReviewAlternativesFromKey(event, marker) {
    if (!event || (event.key !== "Enter" && event.key !== " ")) {
        return;
    }

    event.preventDefault();
    openFoodReviewAlternatives(marker);
}

function foodReviewPayloadFromRow(row) {
    const payload = fieldValuesFromRow(row);
    const marker = row.querySelector(".recipe-edit-food-warning");

    if (marker && marker.dataset.blockedBy) {
        try {
            payload.blocked_by = JSON.parse(marker.dataset.blockedBy);
        } catch (err) {
            payload.blocked_by = [];
        }
    }

    return payload;
}

function showFoodReviewAlternativesModal() {
    let modal = document.getElementById("foodReviewAlternativesModal");

    if (!modal) {
        modal = document.createElement("div");
        modal.id = "foodReviewAlternativesModal";
        modal.className = "food-review-alt-backdrop";
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = `
            <div class="food-review-alt-dialog" role="dialog" aria-modal="true" aria-labelledby="foodReviewAltTitle">
                <div class="food-review-alt-header">
                    <div>
                        <h2 id="foodReviewAltTitle">Food Review Alternatives</h2>
                        <div id="foodReviewAltSubtitle" class="food-review-alt-subtitle"></div>
                    </div>
                    <button type="button" class="food-review-alt-close" onclick="closeFoodReviewAlternatives()">Close</button>
                </div>
                <div id="foodReviewAltContent" class="food-review-alt-content"></div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
}

function closeFoodReviewAlternatives() {
    const modal = document.getElementById("foodReviewAlternativesModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }
}

function renderFoodReviewAlternativesLoading(row) {
    const subtitle = document.getElementById("foodReviewAltSubtitle");
    const content = document.getElementById("foodReviewAltContent");
    const payload = foodReviewPayloadFromRow(row);

    if (subtitle) {
        subtitle.textContent = payload.ingredient || payload.original_text || "Ingredient";
    }

    if (content) {
        content.innerHTML = `
            <div class="food-review-alt-state">
                Asking ChatGPT for practical swaps...
            </div>
        `;
    }
}

function renderFoodReviewAlternatives(data) {
    const subtitle = document.getElementById("foodReviewAltSubtitle");
    const content = document.getElementById("foodReviewAltContent");
    const review = data.review || {};
    const alternatives = data.alternatives || [];

    if (subtitle) {
        const issues = (review.blocked_by || []).join("; ");
        subtitle.textContent = issues
            ? `${review.ingredient || review.original_text || "Ingredient"} - ${issues}`
            : (review.ingredient || review.original_text || "Ingredient");
    }

    if (!content) {
        return;
    }

    if (!alternatives.length) {
        content.innerHTML = `
            <div class="food-review-alt-state">
                No alternatives came back for this ingredient.
            </div>
        `;
        return;
    }

    content.innerHTML = alternatives.map((item, index) => `
        <div class="food-review-alt-card">
            <div class="food-review-alt-card-main">
                <div class="food-review-alt-name">${escapeHtml(item.ingredient)}</div>
                <div class="food-review-alt-meta">${escapeHtml(formatFoodReviewAmount(item))}</div>
                <div class="food-review-alt-reason">${escapeHtml(item.reason || "Suggested as a recipe-compatible replacement.")}</div>
                ${item.adjustment ? `<div class="food-review-alt-adjustment">${escapeHtml(item.adjustment)}</div>` : ""}
            </div>
            <div class="food-review-alt-card-actions">
                <span class="food-review-alt-confidence ${escapeAttribute(item.confidence || "medium")}">${escapeHtml(item.confidence || "medium")}</span>
                <button type="button" onclick="applyFoodReviewAlternative(${index})">Use</button>
            </div>
        </div>
    `).join("");
}

function renderFoodReviewAlternativesError(message) {
    const subtitle = document.getElementById("foodReviewAltSubtitle");
    const content = document.getElementById("foodReviewAltContent");

    if (subtitle) {
        subtitle.textContent = "Could not load alternatives";
    }

    if (content) {
        content.innerHTML = `
            <div class="food-review-alt-state error">
                ${escapeHtml(message)}
            </div>
        `;
    }
}

function formatFoodReviewAmount(item) {
    const amount = `${item.quantity || ""} ${item.unit || ""}`.trim();
    return amount || "Amount depends on recipe taste and texture.";
}

function applyFoodReviewAlternative(index) {
    const alternative = activeFoodReviewAlternatives[index];
    const row = activeFoodReviewRow;

    if (!alternative || !row) {
        return;
    }

    setRowFieldValue(row, "ingredient", alternative.ingredient || "");
    setRowFieldValue(row, "quantity", alternative.quantity || "");
    setRowFieldValue(row, "unit", alternative.unit || "");
    setRowFieldValue(
        row,
        "original_text",
        `${alternative.quantity || ""} ${alternative.unit || ""} ${alternative.ingredient || ""}`.trim()
    );
    updateRecipeIngredientFoodRuleWarning(row);
    markRecipeIngredientReviewed(row);
    closeFoodReviewAlternatives();
    showRecipeQuantityUpdatedMessage("", "", "", "Alternative filled in. Save Recipe to keep it.");
}

function markRecipeIngredientReviewed(row) {
    const marker = row ? row.querySelector(".recipe-edit-food-warning") : null;

    if (!row || !marker) {
        return;
    }

    row.dataset.foodReviewState = "reviewed";
    marker.hidden = false;
    marker.textContent = "Reviewed";
    marker.title = "Reviewed with a ChatGPT alternative.";
    marker.dataset.blockedBy = "[]";
    marker.tabIndex = 0;
    marker.classList.add("reviewed");
}

function setRowFieldValue(row, field, value) {
    const input = row.querySelector(`[data-field="${field}"]`);

    if (input) {
        input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
    }
}

function addRecipeIngredientRow(item = {}) {
    const wrap = document.getElementById("recipeEditIngredients");

    if (!wrap) {
        return;
    }

    const row = document.createElement("div");
    row.className = "recipe-edit-ingredient-row";
    row.innerHTML = `
        <label>
            <span class="recipe-edit-food-warning food-rule-marker"
                  role="button"
                  tabindex="0"
                  onclick="openFoodReviewAlternatives(this)"
                  onkeydown="openFoodReviewAlternativesFromKey(event, this)"
                  hidden>Food Review</span>
            <span>Ingredient</span>
            <input type="text" data-field="ingredient" value="${escapeAttribute(item.ingredient || "")}">
        </label>
        <label>
            <span>Qty</span>
            <input type="text" data-field="quantity" value="${escapeAttribute(item.quantity || "")}">
        </label>
        <label>
            <span>Unit</span>
            <input type="text" data-field="unit" value="${escapeAttribute(item.unit || "")}">
        </label>
        <label>
            <span>Original Text</span>
            <input type="text" data-field="original_text" value="${escapeAttribute(item.original_text || "")}">
        </label>
        <label>
            <span>Preparation</span>
            <input type="text" data-field="preparation" value="${escapeAttribute(item.preparation || "")}">
        </label>
        <label>
            <span>Section</span>
            <input type="text" data-field="section" value="${escapeAttribute(item.section || "")}">
        </label>
        <label>
            <span>Store Section</span>
            <select data-field="store_section">${recipeStoreSectionOptions(item.store_section || "")}</select>
        </label>
        <label class="recipe-edit-check-label">
            <span>Optional</span>
            <input type="checkbox" data-field="optional" ${item.optional ? "checked" : ""}>
        </label>
        <button type="button" class="recipe-edit-remove-row" aria-label="Remove ingredient" onclick="removeRecipeEditRow(this)">X</button>
    `;
    wrap.appendChild(row);
    bindRecipeIngredientFoodRuleWarning(row);
    updateRecipeIngredientFoodRuleWarning(row);
}

function bindRecipeIngredientFoodRuleWarning(row) {
    row.querySelectorAll('[data-field="ingredient"], [data-field="original_text"], [data-field="preparation"]').forEach(input => {
        input.addEventListener("input", () => updateRecipeIngredientFoodRuleWarning(row));
    });
}

function updateRecipeIngredientFoodRuleWarning(row) {
    const marker = row.querySelector(".recipe-edit-food-warning");

    if (!marker) {
        return;
    }

    const ingredientInput = row.querySelector('[data-field="ingredient"]');
    const originalTextInput = row.querySelector('[data-field="original_text"]');
    const preparationInput = row.querySelector('[data-field="preparation"]');
    const text = [
        ingredientInput ? ingredientInput.value : "",
        originalTextInput ? originalTextInput.value : "",
        preparationInput ? preparationInput.value : "",
    ].join(" ").toLowerCase();
    const blockedBy = recipeFoodRuleIssues(text);
    const isReviewed = row.dataset.foodReviewState === "reviewed";

    marker.classList.toggle("reviewed", blockedBy.length === 0 && isReviewed);

    if (blockedBy.length) {
        marker.hidden = false;
        marker.textContent = "Food Review";
        marker.title = `Food rule review: ${blockedBy.join("; ")}`;
        marker.dataset.blockedBy = JSON.stringify(blockedBy);
        marker.tabIndex = 0;
        return;
    }

    if (isReviewed) {
        marker.hidden = false;
        marker.textContent = "Reviewed";
        marker.title = "Reviewed with a ChatGPT alternative.";
        marker.dataset.blockedBy = "[]";
        marker.tabIndex = 0;
        return;
    }

    marker.hidden = true;
    marker.textContent = "Food Review";
    marker.title = "";
    marker.dataset.blockedBy = JSON.stringify(blockedBy);
    marker.tabIndex = -1;
}

function recipeFoodRuleIssues(text) {
    const rules = recipeEditFoodRules && Array.isArray(recipeEditFoodRules.avoid)
        ? recipeEditFoodRules.avoid
        : [];

    return rules
        .filter(rule => {
            const terms = Array.isArray(rule.terms) ? rule.terms : [];
            return terms.some(term => recipeFoodRuleTermMatches(text, term));
        })
        .map(rule => rule.label)
        .filter(Boolean);
}

function recipeFoodRuleTermMatches(text, term) {
    const value = String(term || "").trim().toLowerCase();

    if (!value) {
        return false;
    }

    if (/^[a-z0-9]+$/.test(value)) {
        return new RegExp(`\\b${escapeRegExp(value)}\\b`).test(text);
    }

    return text.includes(value);
}

function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function recipeStoreSectionOptions(selected) {
    const selectedValue = String(selected || "").toUpperCase();
    const sections = recipeEditStoreSections.length ? recipeEditStoreSections : ["MISC"];

    return sections.map(section => {
        const value = String(section || "");
        const isSelected = value.toUpperCase() === selectedValue ? " selected" : "";
        return `<option value="${escapeAttribute(value)}"${isSelected}>${escapeHtml(value)}</option>`;
    }).join("");
}

function addRecipeEquipmentRow(value = "") {
    const wrap = document.getElementById("recipeEditEquipment");

    if (!wrap) {
        return;
    }

    const row = document.createElement("div");
    row.className = "recipe-edit-text-row recipe-edit-equipment-row";
    row.innerHTML = `
        <label>
            <span class="sr-only">Equipment</span>
            <input type="text" data-field="text" value="${escapeAttribute(value || "")}">
        </label>
        <button type="button" class="recipe-edit-remove-row" aria-label="Remove equipment" onclick="removeRecipeEditRow(this)">X</button>
    `;
    wrap.appendChild(row);
}

function recipeEquipmentHeaderHtml() {
    return `
        <div class="recipe-edit-equipment-header" aria-hidden="true">
            <span>Equipment</span>
            <span></span>
        </div>
    `;
}

function addRecipeInstructionRow(value = "", stepNumber = null) {
    const wrap = document.getElementById("recipeEditInstructions");

    if (!wrap) {
        return;
    }

    const instruction = typeof value === "object" && value !== null
        ? (value.instruction || value.text || "")
        : value;
    const sourceStepNumber = typeof value === "object" && value !== null
        ? (value.step_number || value.stepNumber || stepNumber)
        : stepNumber;
    const nextStepNumber = sourceStepNumber || nextRecipeInstructionNumber();
    const row = document.createElement("div");
    row.className = "recipe-edit-text-row recipe-edit-instruction-row";
    row.innerHTML = `
        <label class="recipe-edit-step-number">
            <span class="sr-only">Step #</span>
            <input type="number" min="1" step="0.1" data-field="step_number" value="${escapeAttribute(nextStepNumber)}">
        </label>
        <label class="recipe-edit-step-text">
            <span class="sr-only">Instructions</span>
            <textarea data-field="text" rows="3">${escapeHtml(instruction || "")}</textarea>
        </label>
        <button type="button" class="recipe-edit-remove-row" aria-label="Remove step" onclick="removeRecipeEditRow(this)">X</button>
    `;
    wrap.appendChild(row);
}

function recipeInstructionsHeaderHtml() {
    return `
        <div class="recipe-edit-instructions-header" aria-hidden="true">
            <span>Step #</span>
            <span>Instructions</span>
            <span></span>
        </div>
    `;
}

function nextRecipeInstructionNumber() {
    const stepNumbers = [...document.querySelectorAll("#recipeEditInstructions [data-field='step_number']")]
        .map(input => parseFloat(input.value || "0") || 0);

    return Math.max(0, ...stepNumbers) + 1;
}

function addRecipeNutritionRow(item = {}) {
    const wrap = document.getElementById("recipeEditNutrition");

    if (!wrap) {
        return;
    }

    const row = document.createElement("div");
    row.className = "recipe-edit-nutrition-row";
    row.innerHTML = `
        <label>
            <input type="text" data-field="key" aria-label="Nutrition label" value="${escapeAttribute(item.key || "")}">
        </label>
        <label>
            <input type="text" data-field="value" aria-label="Nutrition value" value="${escapeAttribute(item.value || "")}">
        </label>
        <button type="button" class="recipe-edit-remove-row" aria-label="Remove nutrition" onclick="removeRecipeEditRow(this)">X</button>
    `;
    wrap.appendChild(row);
}

function recipeNutritionHeaderHtml() {
    return `
        <div class="recipe-edit-nutrition-header" aria-hidden="true">
            <span>Label</span>
            <span>Value</span>
            <span></span>
        </div>
    `;
}

function removeRecipeEditRow(button) {
    const row = button ? button.closest(".recipe-edit-ingredient-row, .recipe-edit-text-row, .recipe-edit-nutrition-row") : null;

    if (row) {
        row.remove();
    }
}

async function saveRecipeEditor(event) {
    if (event) {
        event.preventDefault();
    }

    const form = document.getElementById("recipeEditForm");
    const saveButton = form ? form.querySelector(".recipe-edit-save") : null;

    if (!form) {
        return false;
    }

    if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "Saving...";
    }

    setRecipeEditStatus("Saving recipe...");

    try {
        const payload = collectRecipeEditorPayload();
        const progressItems = buildRecipeSaveProgressItems(payload.recipe);
        showRecipeSaveProgressOverlay(progressItems);
        updateRecipeSaveProgressItem(0, "running", "Saving...");

        const response = await fetch("/api/recipe", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to save recipe.");
        }

        updateRecipeSaveProgressItem(0, "done", "Saved");
        updateRecipeSaveProgressItem(1, "done", "Updated");
        updateRecipeSaveProgressItem(2, "running", "Refreshing...");
        await refreshStoreMarkup();
        if (data.recipe) {
            populateRecipeEditor(data.recipe, data.recipe.source_url || payload.recipe.source_url || payload.original_url);
        }
        updateRecipeSaveProgressItem(2, "done", "Refreshed");
        setRecipeSaveProgressSummary("Recipe saved and page values refreshed.");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe updated.");
    } catch (err) {
        console.warn("Unable to save recipe.", err);
        setRecipeEditStatus("Unable to save recipe.", true);
        setRecipeSaveProgressSummary("Unable to save recipe.");
        updateRecipeSaveProgressFailed();
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = "Save Recipe";
        }
    }

    return false;
}

function normalizeRecipeEditorSnapshot(recipe) {
    return {
        display_name: String(recipe.display_name || "").trim(),
        recipe_title: String(recipe.recipe_title || "").trim(),
        source_url: String(recipe.source_url || "").trim(),
        quantity: String(Math.max(1, parseInt(recipe.quantity || "1", 10) || 1)),
        servings: String(recipe.servings || "").trim(),
        ingredients: (recipe.ingredients || []).map(item => ({
            ingredient: String(item.ingredient || "").trim(),
            quantity: String(item.quantity || "").trim(),
            unit: String(item.unit || "").trim(),
            original_text: String(item.original_text || "").trim(),
            preparation: String(item.preparation || "").trim(),
            section: String(item.section || "").trim(),
            store_section: String(item.store_section || "").trim(),
            optional: Boolean(item.optional),
        })),
        equipment: (recipe.equipment || []).map(value => String(value || "").trim()).filter(Boolean),
        instructions: (recipe.instructions || [])
            .map((value, index) => normalizeRecipeInstructionSnapshot(value, index))
            .filter(item => item.instruction),
        nutrition: (recipe.nutrition || []).map(item => ({
            key: String(item.key || "").trim(),
            value: String(item.value || "").trim(),
        })),
    };
}

function buildRecipeSaveProgressItems(recipe) {
    const next = normalizeRecipeEditorSnapshot(recipe);
    const previous = recipeEditOriginalSnapshot || normalizeRecipeEditorSnapshot({});
    const detailLines = [];

    [
        ["Display name", "display_name"],
        ["Recipe title", "recipe_title"],
        ["Source URL", "source_url"],
        ["Quantity", "quantity"],
        ["Servings", "servings"],
    ].forEach(([label, key]) => {
        if (previous[key] !== next[key]) {
            detailLines.push(`${label}: ${previous[key] || "(blank)"} -> ${next[key] || "(blank)"}`);
        }
    });

    const ingredientLines = changedRecipeIngredientLines(previous.ingredients, next.ingredients);
    if (ingredientLines.length) {
        detailLines.push(...ingredientLines);
    } else if (previous.ingredients.length !== next.ingredients.length) {
        detailLines.push(`Ingredients: ${previous.ingredients.length} -> ${next.ingredients.length}`);
    }

    [
        ["Equipment", previous.equipment.length, next.equipment.length],
        ["Instructions", previous.instructions.length, next.instructions.length],
        ["Nutrition", previous.nutrition.length, next.nutrition.length],
    ].forEach(([label, beforeCount, afterCount]) => {
        if (beforeCount !== afterCount) {
            detailLines.push(`${label}: ${beforeCount} -> ${afterCount}`);
        }
    });

    return [
        {
            label: "Recipe file and saved values",
            detail: detailLines.length ? detailLines.slice(0, 8).join("; ") : "Saving current recipe values.",
        },
        {
            label: "Source Recipe Qty values",
            detail: "Recalculating ingredient quantities from the saved recipe numbers.",
        },
        {
            label: "Visible page sections",
            detail: "Refreshing Items, Store View, and Recipe View with updated source values.",
        },
    ];
}

function normalizeRecipeInstructionSnapshot(value, index = 0) {
    if (typeof value === "object" && value !== null) {
        return {
            step_number: String(value.step_number || value.stepNumber || index + 1).trim(),
            instruction: String(value.instruction || value.text || "").trim(),
        };
    }

    return {
        step_number: String(index + 1),
        instruction: String(value || "").trim(),
    };
}

function changedRecipeIngredientLines(previousIngredients, nextIngredients) {
    const lines = [];
    const previousByName = new Map(previousIngredients.map(item => [normalizeFoodKey(item.ingredient), item]));

    nextIngredients.forEach((item, index) => {
        const name = item.ingredient || `Ingredient ${index + 1}`;
        const previous = previousByName.get(normalizeFoodKey(item.ingredient));

        if (!previous) {
            lines.push(`Added ${name}: ${formatRecipeIngredientAmount(item) || "(no qty)"}`);
            return;
        }

        const amountChanged = previous.quantity !== item.quantity || previous.unit !== item.unit;
        const sectionChanged = previous.store_section !== item.store_section;
        const detailsChanged = [
            "original_text",
            "preparation",
            "section",
            "optional",
        ].some(key => previous[key] !== item[key]);

        if (amountChanged) {
            lines.push(`${name}: ${formatRecipeIngredientAmount(previous) || "(blank)"} -> ${formatRecipeIngredientAmount(item) || "(blank)"}`);
        } else if (sectionChanged) {
            lines.push(`${name} store section: ${previous.store_section || "(blank)"} -> ${item.store_section || "(blank)"}`);
        } else if (detailsChanged) {
            lines.push(`${name}: ingredient details updated`);
        }
    });

    const nextNames = new Set(nextIngredients.map(item => normalizeFoodKey(item.ingredient)));
    previousIngredients.forEach(item => {
        if (!nextNames.has(normalizeFoodKey(item.ingredient))) {
            lines.push(`Removed ${item.ingredient || "ingredient"}`);
        }
    });

    return lines;
}

function formatRecipeIngredientAmount(item) {
    return `${item.quantity || ""} ${item.unit || ""}`.trim();
}

function showRecipeSaveProgressOverlay(items) {
    let overlay = document.getElementById("recipeSaveProgressOverlay");

    if (!overlay) {
        overlay = document.createElement("div");
        overlay.id = "recipeSaveProgressOverlay";
        overlay.className = "recipe-qty-progress-backdrop recipe-save-progress-backdrop";
        overlay.innerHTML = `
            <div class="recipe-qty-progress-card" role="dialog" aria-modal="true" aria-labelledby="recipeSaveProgressTitle">
                <div class="recipe-qty-progress-header">
                    <h2 id="recipeSaveProgressTitle">Saving Recipe</h2>
                    <button type="button" class="recipe-qty-progress-close" onclick="hideRecipeSaveProgressOverlay()">Hide</button>
                </div>
                <div id="recipeSaveProgressSummary" class="recipe-qty-progress-summary">Starting recipe save...</div>
                <div id="recipeSaveProgressList" class="recipe-qty-progress-list"></div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    const list = overlay.querySelector("#recipeSaveProgressList");
    if (list) {
        list.innerHTML = items.map((item, index) => `
            <div class="recipe-qty-progress-row" data-recipe-save-progress-index="${index}">
                <div class="recipe-qty-progress-main">
                    <div class="recipe-qty-progress-name">${escapeHtml(item.label)}</div>
                    <div class="recipe-qty-progress-qty">${escapeHtml(item.detail)}</div>
                </div>
                <div class="recipe-qty-progress-status waiting">Waiting</div>
            </div>
        `).join("");
    }

    setRecipeSaveProgressSummary("Starting recipe save...");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
}

function hideRecipeSaveProgressOverlay() {
    const overlay = document.getElementById("recipeSaveProgressOverlay");

    if (overlay) {
        overlay.classList.remove("open");
        overlay.setAttribute("aria-hidden", "true");
    }
}

function setRecipeSaveProgressSummary(message) {
    const summary = document.getElementById("recipeSaveProgressSummary");

    if (summary) {
        summary.textContent = message;
    }
}

function updateRecipeSaveProgressItem(index, state, message) {
    const row = document.querySelector(`.recipe-qty-progress-row[data-recipe-save-progress-index="${index}"]`);

    if (!row) {
        return;
    }

    const status = row.querySelector(".recipe-qty-progress-status");
    row.classList.remove("waiting", "running", "done", "failed");
    row.classList.add(state);

    if (status) {
        status.className = `recipe-qty-progress-status ${state}`;
        status.textContent = message;
    }
}

function updateRecipeSaveProgressFailed() {
    const rows = document.querySelectorAll("#recipeSaveProgressList .recipe-qty-progress-row");
    const runningRow = [...rows].find(row => row.classList.contains("running"));
    const targetRow = runningRow || [...rows].find(row => row.classList.contains("waiting"));

    if (!targetRow) {
        return;
    }

    const index = targetRow.dataset.recipeSaveProgressIndex;
    updateRecipeSaveProgressItem(index, "failed", "Failed");
}

function collectRecipeEditorPayload() {
    const originalUrl = document.getElementById("recipeEditOriginalUrl").value || "";
    const quantity = Math.max(1, parseInt(document.getElementById("recipeEditQuantity").value || "1", 10) || 1);

    return {
        original_url: originalUrl,
        recipe: {
            display_name: document.getElementById("recipeEditDisplayName").value.trim(),
            recipe_title: document.getElementById("recipeEditTitleInput").value.trim(),
            source_url: document.getElementById("recipeEditSourceUrl").value.trim(),
            quantity,
            servings: document.getElementById("recipeEditServings").value.trim(),
            ingredients: collectRecipeIngredientRows(),
            equipment: collectRecipeTextRows("#recipeEditEquipment .recipe-edit-text-row"),
            instructions: collectRecipeInstructionRows(),
            nutrition: collectRecipeNutritionRows(),
        },
    };
}

function collectRecipeIngredientRows() {
    return [...document.querySelectorAll("#recipeEditIngredients .recipe-edit-ingredient-row")]
        .map(row => fieldValuesFromRow(row))
        .filter(item => item.ingredient || item.original_text);
}

function collectRecipeNutritionRows() {
    return [...document.querySelectorAll("#recipeEditNutrition .recipe-edit-nutrition-row")]
        .map(row => fieldValuesFromRow(row))
        .filter(item => item.key || item.value);
}

function collectRecipeInstructionRows() {
    return [...document.querySelectorAll("#recipeEditInstructions .recipe-edit-instruction-row")]
        .map((row, index) => {
            const textInput = row.querySelector('[data-field="text"]');
            const stepInput = row.querySelector('[data-field="step_number"]');
            const stepNumber = Math.max(1, parseFloat(stepInput ? stepInput.value : "") || index + 1);

            return {
                text: textInput ? textInput.value.trim() : "",
                stepNumber,
                originalIndex: index,
            };
        })
        .filter(item => item.text)
        .sort((a, b) => (a.stepNumber - b.stepNumber) || (a.originalIndex - b.originalIndex))
        .map(item => ({
            step_number: item.stepNumber,
            instruction: item.text,
        }));
}

function collectRecipeTextRows(selector) {
    return [...document.querySelectorAll(selector)]
        .map(row => {
            const input = row.querySelector('[data-field="text"]');
            return input ? input.value.trim() : "";
        })
        .filter(Boolean);
}

function fieldValuesFromRow(row) {
    const item = {};

    row.querySelectorAll("[data-field]").forEach(input => {
        item[input.dataset.field] = input.type === "checkbox" ? input.checked : input.value.trim();
    });

    return item;
}

async function saveRecipeQuantity(input, options = {}) {
    const queuedSave = recipeQuantitySaveTimers.get(input);

    if (queuedSave) {
        clearTimeout(queuedSave);
        recipeQuantitySaveTimers.delete(input);
    }

    const url = input.dataset.recipeUrl || "";
    const quantity = Math.max(1, parseInt(input.value || "1", 10) || 1);
    input.value = quantity;

    if (!options.force && input.dataset.lastSavedValue === String(quantity) && !input.dataset.savePending) {
        return { skipped: true };
    }

    input.dataset.savePending = "1";
    setRecipeQuantityControlSaving(input, true);

    try {
        const response = await fetch("/api/recipe_quantity", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url: url,
                quantity: quantity,
            }),
        });

        if (!response.ok) {
            throw new Error("Unable to save recipe quantity.");
        }

        const data = await response.json();
        input.dataset.lastSavedValue = String(quantity);
        input.classList.add("saved");
        updateRecipeQuantityDisplays(url, quantity, data);

        if (options.refresh !== false) {
            try {
                await refreshStoreMarkup();
            } catch (refreshErr) {
                console.warn("Unable to refresh recipe quantities in the background.", refreshErr);
            }
        }

        if (options.message !== false) {
            showRecipeQuantityUpdatedMessage(url, quantity, input.dataset.recipeNumber || "");
        }

        setTimeout(() => {
            input.classList.remove("saved");
        }, 700);
        return data;
    } catch (err) {
        console.warn("Unable to save recipe quantity.", err);
        if (options.throwOnError) {
            throw err;
        }
    } finally {
        setRecipeQuantityControlSaving(input, false);
        delete input.dataset.savePending;
    }

    return null;
}

function setRecipeQuantityControlSaving(input, isSaving) {
    const control = input.closest(".recipe-quantity-control");

    if (!control) {
        input.disabled = isSaving;
        return;
    }

    control.classList.toggle("saving", isSaving);
    control.querySelectorAll("button, input").forEach(element => {
        element.disabled = isSaving;
    });
}

function updateRecipeQuantityDisplays(recipeUrl, multiplier, apiData = null) {
    document.querySelectorAll(`.recipe-servings-scaled[data-recipe-url="${cssEscape(recipeUrl)}"]`).forEach(element => {
        const baseServings = element.dataset.baseServings || "";
        const scaledServings = (apiData && apiData.servings) || scaleServingsForDisplay(baseServings, multiplier);
        element.textContent = multiplier > 1 && scaledServings ? ` -> ${scaledServings}` : "";
    });

    document.querySelectorAll(`.recipe-ingredient-scaled-quantity[data-recipe-url="${cssEscape(recipeUrl)}"]`).forEach(element => {
        const ingredientName = element.dataset.ingredientName || "";
        const apiIngredient = findScaledIngredient(apiData, ingredientName);
        const baseQuantity = element.dataset.baseQuantity || "";
        const unit = element.dataset.unit || "";
        const baseDisplay = `${baseQuantity} ${unit}`.trim();

        if (apiIngredient && apiIngredient.display) {
            element.textContent = multiplier > 1 ? apiIngredient.display : baseDisplay;
            return;
        }

        const scaledQuantity = scaleQuantityForDisplay(baseQuantity, multiplier);

        if (scaledQuantity) {
            element.textContent = multiplier > 1 ? `${scaledQuantity} ${unit}`.trim() : baseDisplay;
        }
    });
}

function showRecipeQuantityUpdatedMessage(recipeUrl, quantity, recipeNumber = "", message = "") {
    let notice = document.getElementById("recipeQuantityUpdateOverlay");

    if (!notice) {
        notice = document.createElement("div");
        notice.id = "recipeQuantityUpdateOverlay";
        notice.className = "recipe-quantity-update-overlay";
        notice.setAttribute("aria-live", "polite");
        document.body.appendChild(notice);
    }

    const existingTimer = recipeQuantityNoticeTimers.get("global");

    if (existingTimer) {
        clearTimeout(existingTimer.fade);
        clearTimeout(existingTimer.clear);
    }

    const recipeLabel = recipeNumber ? `Recipe ${recipeNumber} ` : "";
    notice.textContent = message || `${recipeLabel}Qty updated to ${quantity}.`;
    notice.classList.remove("fading");
    notice.classList.add("visible");

    const fade = setTimeout(() => {
        notice.classList.add("fading");
        notice.classList.remove("visible");
    }, 1400);

    const clear = setTimeout(() => {
        notice.textContent = "";
        notice.classList.remove("fading");
        recipeQuantityNoticeTimers.delete("global");
    }, 2200);

    recipeQuantityNoticeTimers.set("global", { fade, clear });
}

function openItemQtyEditor(button) {
    const modal = document.getElementById("itemQtyModal");
    const keyInput = document.getElementById("itemQtyKeyInput");
    const manualInput = document.getElementById("itemQtyManualInput");
    const nameDisplay = document.getElementById("itemQtyName");
    const titleNameDisplay = document.getElementById("itemQtyTitleName");
    const currentDisplay = document.getElementById("itemQtyCurrent");
    const sourcesDisplay = document.getElementById("itemQtySources");

    if (!modal || !keyInput || !manualInput || !nameDisplay || !currentDisplay) {
        return;
    }

    const itemName = button.dataset.itemName || "";
    const currentQty = button.dataset.currentQty || "";
    const manualQty = button.dataset.manualQty || "";

    keyInput.value = button.dataset.itemKey || "";
    manualInput.value = manualQty;
    nameDisplay.textContent = itemName;
    if (titleNameDisplay) {
        titleNameDisplay.textContent = itemName ? itemName : "";
    }
    currentDisplay.textContent = currentQty || "No recipe quantity found.";
    currentDisplay.classList.toggle("muted", !currentQty);
    renderItemQtySources(sourcesDisplay, button.dataset.recipeQtySources, button.dataset.itemKey || "");

    modal.style.display = "flex";
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    setTimeout(() => manualInput.focus(), 0);
}

function renderItemQtySources(container, sourcesJson, itemKey = "") {
    if (!container) {
        return;
    }

    let sources = [];

    try {
        sources = JSON.parse(sourcesJson || "[]");
    } catch (err) {
        sources = [];
    }

    sources = sources.filter(source => source && (source.quantity || source.ingredient || source.url));
    container.replaceChildren();
    container.hidden = sources.length === 0;

    if (!sources.length) {
        return;
    }

    const header = document.createElement("div");
    header.className = "item-qty-source-header";
    ["Recipe", "Default qty", "Unit", "Recipe Qty"].forEach(text => {
        const cell = document.createElement("span");
        cell.textContent = text;
        header.appendChild(cell);
    });
    container.appendChild(header);

    sources.forEach(source => {
        const row = document.createElement("div");
        row.className = "item-qty-source-row";

        const label = document.createElement("span");
        label.className = "item-qty-source-label";
        label.textContent = source.label || "Recipe qty";

        const defaultQuantity = document.createElement("div");
        defaultQuantity.className = "item-qty-source-default";
        const defaultQuantityValue = source.default_quantity_value || source.default_quantity || source.quantity || "";
        const defaultQuantityInput = document.createElement("input");
        defaultQuantityInput.className = "item-qty-source-default-input";
        defaultQuantityInput.type = "text";
        defaultQuantityInput.value = defaultQuantityValue;
        defaultQuantityInput.placeholder = "qty";
        defaultQuantityInput.dataset.recipeUrl = source.url || "";
        defaultQuantityInput.dataset.ingredientName = source.ingredient || "";
        defaultQuantityInput.dataset.itemKey = itemKey;
        defaultQuantityInput.setAttribute("aria-label", `${source.label || "Recipe"} default quantity`);

        const defaultUnitInput = document.createElement("input");
        defaultUnitInput.className = "item-qty-source-unit-input";
        defaultUnitInput.type = "text";
        defaultUnitInput.value = source.default_unit || "";
        defaultUnitInput.placeholder = "unit";
        defaultUnitInput.dataset.recipeUrl = source.url || "";
        defaultUnitInput.dataset.ingredientName = source.ingredient || "";
        defaultUnitInput.dataset.itemKey = itemKey;
        defaultUnitInput.setAttribute("aria-label", `${source.label || "Recipe"} default unit`);

        [defaultQuantityInput, defaultUnitInput].forEach(input => {
            input.addEventListener("change", () => {
                saveItemModalDefaultQuantity(defaultQuantityInput, defaultUnitInput);
            });

            input.addEventListener("keydown", event => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    saveItemModalDefaultQuantity(defaultQuantityInput, defaultUnitInput);
                }
            });
        });

        defaultQuantity.append(defaultQuantityInput, defaultUnitInput);

        const quantityInput = document.createElement("input");
        quantityInput.className = "item-qty-source-value recipe-quantity-input";
        quantityInput.type = "number";
        quantityInput.min = "1";
        quantityInput.step = "1";
        quantityInput.value = source.recipe_quantity || 1;
        quantityInput.placeholder = "1";
        quantityInput.dataset.recipeUrl = source.url || "";
        quantityInput.dataset.recipeNumber = source.recipe_number || "";
        quantityInput.dataset.lastSavedValue = String(source.recipe_quantity || 1);
        quantityInput.dataset.itemKey = itemKey;
        quantityInput.title = source.quantity ? `Ingredient qty: ${source.quantity}` : "";

        quantityInput.addEventListener("change", () => {
            saveItemModalRecipeQuantity(quantityInput);
        });

        quantityInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                saveItemModalRecipeQuantity(quantityInput);
            }
        });

        row.append(label, defaultQuantity, quantityInput);
        container.appendChild(row);
    });
}

async function saveItemModalDefaultQuantity(quantityInput, unitInput) {
    const url = quantityInput.dataset.recipeUrl || unitInput.dataset.recipeUrl || "";
    const ingredient = quantityInput.dataset.ingredientName || unitInput.dataset.ingredientName || "";
    const itemKey = quantityInput.dataset.itemKey || unitInput.dataset.itemKey || "";

    quantityInput.disabled = true;
    unitInput.disabled = true;

    try {
        const response = await fetch("/api/recipe_ingredient_quantity", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url: url,
                ingredient: ingredient,
                quantity: quantityInput.value.trim(),
                unit: unitInput.value.trim(),
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to save recipe ingredient quantity.");
        }

        await refreshStoreMarkup();
        syncOpenItemQtyEditor(itemKey);
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe ingredient qty updated.");
    } catch (err) {
        console.warn("Unable to save recipe ingredient quantity.", err);
        alert("Unable to save recipe ingredient quantity.");
    } finally {
        quantityInput.disabled = false;
        unitInput.disabled = false;
    }
}

async function saveItemModalRecipeQuantity(input) {
    let data = null;

    try {
        normalizeRecipeQuantityInput(input);
        data = await saveRecipeQuantity(input, { throwOnError: true });
    } catch (err) {
        console.warn("Unable to save recipe quantity from item modal.", err);
        alert("Unable to save recipe quantity.");
        return;
    }

    if (data) {
        syncOpenItemQtyEditor(input.dataset.itemKey || "");
    }
}

function syncOpenItemQtyEditor(itemKey) {
    if (!itemKey) {
        return;
    }

    const modal = document.getElementById("itemQtyModal");

    if (!modal || modal.getAttribute("aria-hidden") === "true") {
        return;
    }

    const sourceButton = document.querySelector(`.edit-qty-btn[data-item-key="${cssEscape(itemKey)}"]`);
    const currentDisplay = document.getElementById("itemQtyCurrent");
    const sourcesDisplay = document.getElementById("itemQtySources");

    if (!sourceButton || !currentDisplay) {
        return;
    }

    const currentQty = sourceButton.dataset.currentQty || "";
    currentDisplay.textContent = currentQty || "No recipe quantity found.";
    currentDisplay.classList.toggle("muted", !currentQty);
    renderItemQtySources(sourcesDisplay, sourceButton.dataset.recipeQtySources, itemKey);
}

function closeItemQtyEditor() {
    const modal = document.getElementById("itemQtyModal");

    if (modal) {
        modal.style.display = "none";
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }
}

async function clearItemQtyOverride() {
    const manualInput = document.getElementById("itemQtyManualInput");

    if (manualInput) {
        manualInput.value = "";
    }

    await saveItemQtyOverride();
}

async function saveItemQtyOverride(event) {
    if (event) {
        event.preventDefault();
    }

    const form = document.getElementById("itemQtyForm");

    if (!form) {
        return false;
    }

    const saveButton = form.querySelector(".item-qty-save-btn");
    const formData = new FormData(form);
    formData.set("ajax", "1");

    if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "Saving...";
    }

    try {
        const response = await fetch("/save_item_qty", {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error("Unable to save item quantity.");
        }

        closeItemQtyEditor();
        await refreshStoreMarkup();
        showRecipeQuantityUpdatedMessage("", "", "", "Item quantity updated.");
    } catch (err) {
        console.warn("Unable to save item quantity.", err);
        alert("Unable to save item quantity.");
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = "Save Qty";
        }
    }

    return false;
}

function findScaledIngredient(apiData, ingredientName) {
    if (!apiData || !apiData.ingredients) {
        return null;
    }

    const exact = apiData.ingredients[ingredientName];

    if (exact) {
        return exact;
    }

    const targetKey = normalizeFoodKey(ingredientName);
    const matchedName = Object.keys(apiData.ingredients).find(name => {
        return normalizeFoodKey(name) === targetKey;
    });

    return matchedName ? apiData.ingredients[matchedName] : null;
}

function normalizeFoodKey(value) {
    return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function scaleServingsForDisplay(servings, multiplier) {
    const value = String(servings || "").trim();

    if (!value || multiplier === 1) {
        return value;
    }

    return value.replace(/\d+(?:\.\d+)?/, match => {
        const scaled = Number(match) * multiplier;
        return Number.isInteger(scaled) ? String(scaled) : String(scaled);
    });
}

function scaleQuantityForDisplay(quantity, multiplier) {
    const value = String(quantity || "").trim();

    if (!value || multiplier === 1) {
        return value;
    }

    const rangeMatch = value.match(/^(.+?)\s*(-|to)\s*(.+)$/);
    if (rangeMatch) {
        const separator = rangeMatch[2] === "to" ? " to " : "-";
        return `${scaleQuantityPart(rangeMatch[1], multiplier)}${separator}${scaleQuantityPart(rangeMatch[3], multiplier)}`;
    }

    return scaleQuantityPart(value, multiplier);
}

function scaleQuantityPart(value, multiplier) {
    const fraction = parseQuantityFraction(value);

    if (!fraction) {
        return value;
    }

    return formatQuantityFraction({
        numerator: fraction.numerator * multiplier,
        denominator: fraction.denominator,
    });
}

function parseQuantityFraction(value) {
    const text = String(value || "").trim();
    let match = text.match(/^(\d+)\s+(\d+)\/(\d+)$/);

    if (match) {
        const whole = parseInt(match[1], 10);
        const numerator = parseInt(match[2], 10);
        const denominator = parseInt(match[3], 10);
        return {
            numerator: whole * denominator + numerator,
            denominator: denominator,
        };
    }

    match = text.match(/^(\d+)\/(\d+)$/);
    if (match) {
        return {
            numerator: parseInt(match[1], 10),
            denominator: parseInt(match[2], 10),
        };
    }

    match = text.match(/^\d+(?:\.\d+)?$/);
    if (match) {
        const numberValue = Number(text);
        const denominator = text.includes(".") ? 1000 : 1;
        return reduceFraction({
            numerator: Math.round(numberValue * denominator),
            denominator: denominator,
        });
    }

    return null;
}

function formatQuantityFraction(fraction) {
    const reduced = reduceFraction(fraction);

    if (reduced.denominator === 1) {
        return String(reduced.numerator);
    }

    const whole = Math.floor(reduced.numerator / reduced.denominator);
    const remainder = reduced.numerator % reduced.denominator;

    if (whole) {
        return `${whole} ${remainder}/${reduced.denominator}`;
    }

    return `${remainder}/${reduced.denominator}`;
}

function reduceFraction(fraction) {
    const divisor = gcd(Math.abs(fraction.numerator), Math.abs(fraction.denominator));

    return {
        numerator: fraction.numerator / divisor,
        denominator: fraction.denominator / divisor,
    };
}

function gcd(a, b) {
    while (b) {
        const next = a % b;
        a = b;
        b = next;
    }

    return a || 1;
}

function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
    }

    return String(value).replace(/"/g, '\\"');
}

function bindStoreButtons() {
    document.querySelectorAll(".store-btn").forEach(button => {
        button.addEventListener("click", async () => {
            const row = button.closest(".row");
            const itemKey = button.dataset.itemKey || (row ? row.dataset.key : "");
            const storeKey = button.dataset.store || "";
            const wasActive = button.classList.contains("active");

            if (row) {
                row.querySelectorAll(".store-btn").forEach(rowButton => {
                    rowButton.classList.remove("active");
                });
            }

            if (!wasActive) {
                button.classList.add("active");
            }

            if (itemKey) {
                await saveItemStoreSelection(itemKey, wasActive ? "" : storeKey);
            }

            if (localStorage.getItem("open-store-urls") === "0") {
                return;
            }

            const itemText = row ? row.querySelector(".item-text") : null;
            const searchBaseUrl = button.dataset.storeUrl || "";
            const ingredient = itemText ? itemText.textContent.trim() : "";

            if (searchBaseUrl && ingredient) {
                window.open(`${searchBaseUrl}${encodeURIComponent(ingredient)}`, "_blank", "noopener");
            }
        });
    });
}

async function saveItemStoreSelection(itemKey, storeKey) {
    const formData = new FormData();
    formData.set("item_key", itemKey);
    formData.set("store_key", storeKey);
    formData.set("ajax", "1");

    try {
        const response = await fetch("/save_item_store", {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });

        if (!response.ok) {
            throw new Error("Unable to save item store.");
        }

        await refreshStoreMarkup();
    } catch (err) {
        console.warn("Unable to save the selected store.", err);
    }
}

function bindSectionHeaderToggles() {
    document.querySelectorAll("#sectionView .collapsible-header, #storeView .collapsible-header, #recipeView .collapsible-header").forEach(header => {
        const title = header.querySelector(".header-title");
        const collapseKey = header.dataset.collapseKey || (title ? normalizeSectionKey(title.textContent) : "");
        const icon = header.querySelector(".header-toggle-icon");
        const isCollapsed = localStorage.getItem(`section-collapsed:${collapseKey}`) === "1";

        setSectionCollapsed(header, icon, isCollapsed);

        header.addEventListener("click", () => {
            const shouldCollapse = !(icon && icon.textContent.trim().toLowerCase().startsWith("show"));
            setSectionCollapsed(header, icon, shouldCollapse);
            localStorage.setItem(`section-collapsed:${collapseKey}`, shouldCollapse ? "1" : "0");
        });
    });
}

function setSectionCollapsed(header, icon, collapsed) {
    const scope = header.dataset.collapseScope || "section";
    let sibling = header.nextElementSibling;

    while (sibling) {
        if (scope === "section" && sibling.classList.contains("section-header-row")) {
            break;
        }

        if (scope === "store" && sibling.classList.contains("store-header-row")) {
            break;
        }

        if (
            scope === "store-section" &&
            (sibling.classList.contains("store-section-header") || sibling.classList.contains("store-header-row"))
        ) {
            break;
        }

        if (
            scope === "recipe-section" &&
            (sibling.classList.contains("store-section-header") || sibling.classList.contains("recipe-view-card"))
        ) {
            break;
        }

        sibling.classList.toggle("collapsed-by-header", collapsed);
        sibling = sibling.nextElementSibling;
    }

    if (icon) {
        icon.textContent = collapsed ? "Show v" : "Hide ^";
    }
}

function bindRecipeDetailToggles() {
    document.querySelectorAll(".detail-toggle").forEach(button => {
        const key = button.dataset.detailKey;
        const content = document.querySelector(`[data-detail-content="${cssEscape(key)}"]`);
        const icon = button.querySelector(".detail-toggle-icon");

        if (!content) {
            return;
        }

        const collapsed = localStorage.getItem(`detail-collapsed:${key}`) !== "0";
        content.classList.toggle("collapsed", collapsed);
        if (icon) {
            icon.textContent = collapsed ? "Show v" : "Hide ^";
        }

        button.addEventListener("click", () => {
            const isCollapsed = content.classList.toggle("collapsed");
            localStorage.setItem(`detail-collapsed:${key}`, isCollapsed ? "1" : "0");
            if (icon) {
                icon.textContent = isCollapsed ? "Show v" : "Hide ^";
            }
        });
    });

    document.querySelectorAll(".nutrition-toggle").forEach(button => {
        const key = button.dataset.nutritionKey;
        const content = document.querySelector(`[data-nutrition-content="${cssEscape(key)}"]`);
        const icon = button.querySelector(".nutrition-toggle-icon");

        if (!content) {
            return;
        }

        const collapsed = localStorage.getItem(`nutrition-collapsed:${key}`) !== "0";
        content.classList.toggle("collapsed", collapsed);
        if (icon) {
            icon.textContent = collapsed ? "Show v" : "Hide ^";
        }

        button.addEventListener("click", () => {
            const isCollapsed = content.classList.toggle("collapsed");
            localStorage.setItem(`nutrition-collapsed:${key}`, isCollapsed ? "1" : "0");
            if (icon) {
                icon.textContent = isCollapsed ? "Show v" : "Hide ^";
            }
        });
    });
}

function bindRecipeTaskChecks() {
    document.querySelectorAll(".recipe-task-check").forEach(checkbox => {
        const key = checkbox.dataset.taskKey;
        const taskRow = checkbox.closest(".recipe-task-row");
        const text = taskRow ? taskRow.querySelector(".recipe-task-text") : null;

        checkbox.checked = localStorage.getItem(`recipe-task-checked:${key}`) === "1";
        if (text) {
            text.classList.toggle("checked-item-text", checkbox.checked);
        }

        checkbox.addEventListener("change", () => {
            localStorage.setItem(`recipe-task-checked:${key}`, checkbox.checked ? "1" : "0");
            if (text) {
                text.classList.toggle("checked-item-text", checkbox.checked);
            }
        });
    });
}

function cssEscape(value) {
    if (window.CSS && CSS.escape) {
        return CSS.escape(value);
    }

    return String(value || "").replace(/"/g, '\\"');
}

function normalizeSectionKey(text) {
    return String(text || "")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, "-");
}

function resetItemChecks(event) {
    event.preventDefault();

    document.querySelectorAll(".row[data-key]").forEach(row => {
        const checkbox = row.querySelector(".item-check");

        if (!checkbox) {
            return;
        }

        checkbox.checked = false;
        row.classList.remove("row-checked");
        const itemText = row.querySelector(".item-text");
        if (itemText) {
            itemText.classList.remove("checked-item-text");
        }
        localStorage.removeItem(`item-checked:${row.dataset.key}`);
    });

    return false;
}

async function resetStores(event) {
    event.preventDefault();

    const form = event.currentTarget;

    try {
        await submitStoreForm(form);
        await refreshStoreMarkup();
    } catch (err) {
        console.warn("Unable to reset stores in the background.", err);
    }

    return false;
}

async function saveHomeAddress(event) {
    const form = event.currentTarget;
    const submitter = event.submitter || document.activeElement;
    const action = submitter ? submitter.value : "";

    if (action === "run_find_nearest") {
        saveScroll();
        return true;
    }

    event.preventDefault();

    try {
        await saveHomeAddressForm(form);
    } catch (err) {
        // saveHomeAddressForm already logs this; keep the normal save path non-disruptive.
    }

    return false;
}

async function saveHomeAddressForm(form) {
    const saveButton = form.querySelector('button[name="action"][value="save"]');
    const formData = new FormData(form);
    formData.set("ajax", "1");

    updateHomeAddressSummaries(buildAddressSummaryFromForm(form));

    if (saveButton) {
        saveButton.disabled = true;
    }

    try {
        const response = await fetch(form.action, {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });
        const contentType = response.headers.get("content-type") || "";

        if (!contentType.includes("application/json")) {
            if (!response.ok) {
                throw new Error("Unable to save address.");
            }

            return false;
        }

        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(data.error || "Unable to save address.");
        }

        updateHomeAddressSummaries(data.home_address.full_address || "");
        return data;
    } catch (err) {
        console.warn("Unable to save address in the background.", err);
        throw err;
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
        }
    }
}

function updateHomeAddressSummaries(address) {
    const text = address || "";
    const summary = document.getElementById("homeAddressSummary");
    const collapsedSummary = document.getElementById("homeAddressCollapsedSummary");

    if (summary) {
        summary.textContent = text;
    }

    if (collapsedSummary) {
        collapsedSummary.textContent = text || "No home address saved.";
    }
}

async function useDeviceLocationForHomeAddress(button) {
    const form = document.getElementById("homeAddressForm");

    if (!form) {
        return;
    }

    if (!locationOriginCanUseDeviceLocation()) {
        showRecipeQuantityUpdatedMessage("", "", "", "Device GPS needs HTTPS or localhost.");
        return;
    }

    if (!navigator.geolocation) {
        showRecipeQuantityUpdatedMessage("", "", "", "This browser cannot use device location.");
        return;
    }

    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Finding location...";
    }

    try {
        const position = await getCurrentDevicePosition();

        if (button) {
            button.textContent = "Looking up address...";
        }

        const response = await fetch("/api/reverse_geocode", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to look up address for this location.");
        }

        fillHomeAddressForm(form, data.address || {});
        updateHomeAddressSummaries(buildAddressSummaryFromForm(form));
        showRecipeQuantityUpdatedMessage("", "", "", "Location found. Save Address to keep it.");
    } catch (err) {
        console.warn("Unable to use device location.", err);
        showRecipeQuantityUpdatedMessage("", "", "", friendlyGeolocationError(err));
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Use My Location";
        }
    }
}

function locationOriginCanUseDeviceLocation() {
    return Boolean(
        window.isSecureContext
        || window.location.hostname === "localhost"
        || window.location.hostname === "127.0.0.1"
    );
}

function friendlyGeolocationError(err) {
    if (err && err.code === 1) {
        return "Device location permission was denied or blocked.";
    }

    if (err && err.code === 2) {
        return "The browser could not determine this device location.";
    }

    if (err && err.code === 3) {
        return "Device location timed out. Try again.";
    }

    return (err && err.message) || "Unable to use device location.";
}

function getCurrentDevicePosition() {
    return new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 60000,
        });
    });
}

function fillHomeAddressForm(form, address) {
    setHomeAddressField(form, "address_street", address.street);
    setHomeAddressField(form, "address_city", address.city);
    setHomeAddressField(form, "address_county", address.county);
    setHomeAddressField(form, "address_state", address.state);
    setHomeAddressField(form, "address_zip", address.zip);
    setHomeAddressField(form, "address_country", address.country);

    if (address.apartment) {
        setHomeAddressField(form, "address_apartment", address.apartment);
    }
}

function setHomeAddressField(form, name, value) {
    const input = form.querySelector(`[name="${name}"]`);

    if (input && value !== undefined && value !== null) {
        input.value = value;
    }
}

async function saveStoreOptions(event) {
    event.preventDefault();

    const form = event.currentTarget;
    await saveStoreOptionsForm(form);
    return false;
}

async function saveStoreToggle(toggle) {
    const form = document.getElementById("store-options-form");

    if (!form) {
        return false;
    }

    await saveStoreOptionsForm(form);

    return false;
}

async function saveStoreOptionsForm(form) {
    try {
        await submitStoreForm(form);
        await refreshStoreMarkup();
    } catch (err) {
        console.warn("Unable to save store options in the background.", err);
    }
}

async function addStore(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const submitButton = form.querySelector('button[type="submit"]');

    if (submitButton) {
        submitButton.disabled = true;
    }

    try {
        await submitStoreForm(form);
        await refreshStoreMarkup();
    } catch (err) {
        console.warn("Unable to add store in the background.", err);
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
        }
    }

    return false;
}

async function deleteStore(event, message) {
    event.preventDefault();

    if (!confirm(message)) {
        return false;
    }

    const form = event.currentTarget;
    const submitButton = form.querySelector('button[type="submit"]');

    if (submitButton) {
        submitButton.disabled = true;
    }

    try {
        await submitStoreForm(form);
        await refreshStoreMarkup();
    } catch (err) {
        console.warn("Unable to delete store in the background.", err);

        if (submitButton) {
            submitButton.disabled = false;
        }
    }

    return false;
}

async function submitStoreForm(form) {
    const formData = new FormData(form);
    formData.set("ajax", "1");

    const response = await fetch(form.action, {
        method: "POST",
        headers: {
            "X-Requested-With": "fetch",
        },
        body: formData,
    });

    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
        ? await response.json()
        : null;

    if (!response.ok || (data && !data.ok)) {
        throw new Error((data && data.error) || "Store update failed.");
    }
}

async function refreshStoreMarkup() {
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const response = await fetch(window.location.href, {
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error("Unable to refresh store markup.");
    }

    const html = await response.text();
    const nextPage = new DOMParser().parseFromString(html, "text/html");
    replaceSectionFromPage(nextPage, "#storeOptionsSection");
    replaceSectionFromPage(nextPage, "#currentRecipeUrlLogCard");
    replaceSectionFromPage(nextPage, "#sectionView");
    replaceSectionFromPage(nextPage, "#storeView");
    replaceSectionFromPage(nextPage, "#recipeView");
    restoreCardCollapseState();
    restoreOpenStorePanels();
    restoreViewBehaviorSettings();
    restoreItemCheckState();
    bindRecipeQuantityInputs();
    bindRecipeNameInputs();
    bindStoreButtons();
    bindSectionHeaderToggles();
    bindRecipeDetailToggles();
    bindRecipeTaskChecks();
    updateViewSwitcherStickyOffset();
    window.scrollTo(scrollX, scrollY);
}

function replaceSectionFromPage(nextPage, selector) {
    const currentSection = document.querySelector(selector);
    const nextSection = nextPage.querySelector(selector);

    if (currentSection && nextSection) {
        currentSection.replaceWith(nextSection);
    }
}

function buildAddressSummaryFromForm(form) {
    const streetInput = form.querySelector('[name="address_street"]');
    const apartmentInput = form.querySelector('[name="address_apartment"]');
    const cityInput = form.querySelector('[name="address_city"]');
    const countyInput = form.querySelector('[name="address_county"]');
    const stateInput = form.querySelector('[name="address_state"]');
    const zipInput = form.querySelector('[name="address_zip"]');
    const countryInput = form.querySelector('[name="address_country"]');

    const street = streetInput ? streetInput.value.trim() : "";
    const apartment = apartmentInput ? apartmentInput.value.trim() : "";
    const city = cityInput ? cityInput.value.trim() : "";
    const county = countyInput ? countyInput.value.trim() : "";
    const state = stateInput ? stateInput.value.trim() : "";
    const zip = zipInput ? zipInput.value.trim() : "";
    const country = countryInput ? countryInput.value.trim() : "";

    const streetLine = [street, apartment].filter(Boolean).join(" ");
    const cityStateZip = [state, zip].filter(Boolean).join(" ");
    const cityLine = [city, county, cityStateZip].filter(Boolean).join(", ");

    return [streetLine, cityLine, country].filter(Boolean).join(", ");
}

document.addEventListener("DOMContentLoaded", function () {
    restoreScroll();
    restoreCardCollapseState();
    restoreOpenStorePanels();
    restoreViewBehaviorSettings();
    restoreItemCheckState();
    bindRecipeQuantityInputs();
    bindRecipeNameInputs();
    bindStoreButtons();
    bindSectionHeaderToggles();
    bindRecipeDetailToggles();
    bindRecipeTaskChecks();
    updateRecipeEditStickyOffsets();
    updateViewSwitcherStickyOffset();
    startExtractionProgressPolling();
});

window.addEventListener("resize", updateRecipeEditStickyOffsets);
window.addEventListener("resize", updateViewSwitcherStickyOffset);

async function startRecipeExtraction(event) {
    event.preventDefault();

    const textarea = document.getElementById("recipeUrlsTextarea");
    const urls = textarea.value
        .split(/\r?\n/)
        .map(x => x.trim())
        .filter(Boolean);

    if (!urls.length) {
        alert("Paste at least one recipe URL.");
        return;
    }

    await startRecipeExtractionUrls(urls);
}

async function startRecipeExtractionUrls(urls) {
    showExtractionOverlay();
    const jobId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    hiddenExtractJobId = null;
    lastRenderedExtractJobId = jobId;
    lastRenderedExtractProgress = null;
    cancelExtractRequested = false;

    const list = document.getElementById("extractUrlList");
    const status = document.getElementById("extractStatusText");
    const summary = document.getElementById("extractSummary");
    const bar = document.getElementById("extractProgressBar");

    list.innerHTML = "";
    updateExtractionActionButtons({
        active: true,
        status: "running",
        urls: urls.map(url => ({ url: url, state: "waiting" })),
    });

    urls.forEach((url, index) => {
        const row = document.createElement("div");
        row.className = "bulk-progress-item";
        row.id = `extract-url-${index}`;

        row.innerHTML = `
            <input type="checkbox" class="bulk-progress-check" disabled>
            <div class="bulk-progress-main">
                <div class="bulk-progress-title-line">
                    <span class="bulk-progress-text">${index + 1}. </span>
                    <a class="bulk-progress-text extract-url-progress-link"
                       href="${url}"
                       target="_blank"
                       rel="noopener noreferrer">${url}</a>
                </div>
                <div class="bulk-skip-reason">
                    waiting...
                </div>
            </div>
        `;

        list.appendChild(row);
    });

    await waitForNextPaint();

    status.textContent = `Downloading ${urls.length} recipe${urls.length === 1 ? "" : "s"}...`;
    summary.textContent = "Fetching recipe pages and extracting ingredients.";
    if (bar) {
        bar.style.width = "10%";
    }

    await fetch("/api/start_extract_progress", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            urls: urls,
            job_id: jobId,
        }),
    });

    currentExtractAbortControllers = [];

    const extractionRequests = urls.map((url, index) => {
        const row = document.getElementById(`extract-url-${index}`);
        const text = row ? row.querySelector(".extract-url-progress-link") : null;
        const reason = row ? row.querySelector(".bulk-skip-reason") : null;

        if (reason) {
            reason.textContent = "extracting - Running recipe extractor...";
        }

        if (text) {
            text.classList.add("active");
        }

        const controller = new AbortController();
        currentExtractAbortControllers.push(controller);
        currentExtractAbortController = controller;

        return fetch("/api/extract_recipe", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            signal: controller.signal,
            body: JSON.stringify({
                url: url,
                urls: urls,
                index: index,
                job_id: jobId,
            }),
        }).catch(err => {
            if (!cancelExtractRequested) {
                throw err;
            }
        });
    });

    try {
        await Promise.allSettled(extractionRequests);
    } finally {
        currentExtractAbortController = null;
        currentExtractAbortControllers = [];
    }
}

async function cancelRecipeExtraction() {
    cancelExtractRequested = true;

    currentExtractAbortControllers.forEach(controller => {
        controller.abort();
    });
    currentExtractAbortControllers = [];

    if (currentExtractAbortController) {
        currentExtractAbortController.abort();
        currentExtractAbortController = null;
    }

    if (!lastRenderedExtractJobId) {
        return;
    }

    try {
        await fetch("/api/cancel_extract", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                job_id: lastRenderedExtractJobId,
            }),
        });
        await pollExtractionProgress();
    } catch (err) {
        // Cancel is best-effort; polling will catch the final state.
    }
}

async function redoMissingRecipeExtraction() {
    const progress = lastRenderedExtractProgress;

    if (!progress || progress.active) {
        return;
    }

    const missingUrls = (progress.urls || [])
        .filter(item => item.state !== "done")
        .map(item => item.url)
        .filter(Boolean);

    if (!missingUrls.length) {
        return;
    }

    await startRecipeExtractionUrls(missingUrls);
}

function waitForNextPaint() {
    return new Promise(resolve => {
        requestAnimationFrame(() => {
            requestAnimationFrame(resolve);
        });
    });
}

function startExtractionProgressPolling() {
    pollExtractionProgress();
    setInterval(pollExtractionProgress, 2000);
}

async function pollExtractionProgress() {
    try {
        const response = await fetch("/api/extract_progress", {
            cache: "no-store",
        });

        if (!response.ok) {
            return;
        }

        const progress = await response.json();
        renderExtractionProgress(progress);
    } catch (err) {
        // Progress polling is best-effort; extraction still runs through the form request.
    }
}

function renderExtractionProgress(progress) {
    if (!progress || !progress.job_id) {
        return;
    }

    lastRenderedExtractJobId = progress.job_id;
    lastRenderedExtractProgress = progress;

    if (progress.active && hiddenExtractJobId !== progress.job_id) {
        showExtractionOverlay();
    }

    const list = document.getElementById("extractUrlList");
    const status = document.getElementById("extractStatusText");
    const summary = document.getElementById("extractSummary");
    const bar = document.getElementById("extractProgressBar");

    if (!list || !status || !summary || !bar) {
        return;
    }

    status.textContent = progressStatusText(progress);
    summary.textContent = progress.summary || "Fetching recipe pages and extracting ingredients.";
    bar.style.width = `${Math.max(0, Math.min(100, progress.percent || 0))}%`;
    updateExtractionActionButtons(progress);

    list.innerHTML = "";

    (progress.urls || []).forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "bulk-progress-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "bulk-progress-check";
        checkbox.disabled = true;
        checkbox.checked = item.state === "done";

        const main = document.createElement("div");
        main.className = "bulk-progress-main";

        const titleLine = document.createElement("div");
        titleLine.className = "bulk-progress-title-line";

        const prefix = document.createElement("span");
        prefix.className = "bulk-progress-text";
        prefix.textContent = `${index + 1}. `;

        const text = document.createElement("a");
        text.className = "bulk-progress-text";
        text.classList.add("extract-url-progress-link");
        text.href = item.url;
        text.target = "_blank";
        text.rel = "noopener noreferrer";

        if (item.state === "running") {
            text.classList.add("active");
        }

        if (item.state === "done") {
            text.classList.add("done");
        }

        if (item.state === "cancelled") {
            text.classList.add("cancelled");
        }

        text.textContent = item.url;

        const reason = document.createElement("div");
        reason.className = "bulk-skip-reason";
        reason.textContent = item.message || "waiting...";

        titleLine.appendChild(prefix);
        titleLine.appendChild(text);
        main.appendChild(titleLine);
        main.appendChild(reason);
        row.appendChild(checkbox);
        row.appendChild(main);
        list.appendChild(row);
    });

    if (!progress.active && progress.status === "complete") {
        scheduleExtractionAutoClose(progress.job_id);
        scheduleExtractionRefresh(progress.job_id);
    }
}

function progressStatusText(progress) {
    if (!progress.active && progress.status === "complete") {
        return "Extraction complete.";
    }

    if (!progress.active && progress.status === "failed") {
        return "Extraction finished with errors.";
    }

    if (!progress.active && progress.status === "cancelled") {
        return "Extraction cancelled.";
    }

    const total = progress.total || 0;

    if (!total) {
        return "Starting...";
    }

    const completed = (progress.urls || []).filter(item => {
        return item.state === "done" || item.state === "failed" || item.state === "cancelled";
    }).length;

    return `Downloading recipes ${completed} of ${total} complete...`;
}

function updateExtractionActionButtons(progress) {
    const cancelBtn = document.getElementById("cancelExtractBtn");
    const redoBtn = document.getElementById("redoMissingExtractBtn");

    if (cancelBtn) {
        cancelBtn.style.display = progress && progress.active ? "inline-flex" : "none";
        cancelBtn.disabled = !progress || !progress.active;
    }

    if (redoBtn) {
        const hasMissing = Boolean(
            progress &&
            !progress.active &&
            (progress.urls || []).some(item => item.state !== "done")
        );

        redoBtn.style.display = hasMissing ? "inline-flex" : "none";
        redoBtn.disabled = !hasMissing;
    }
}

function scheduleExtractionRefresh(jobId) {
    if (!jobId || localStorage.getItem(`extract_refreshed_${jobId}`)) {
        return;
    }

    localStorage.setItem(`extract_refreshed_${jobId}`, "1");

    if (extractRefreshTimer) {
        clearTimeout(extractRefreshTimer);
    }

    extractRefreshTimer = setTimeout(() => {
        window.location.href = "/";
    }, 1200);
}

function scheduleExtractionAutoClose(jobId) {
    if (!jobId || localStorage.getItem(`extract_closed_${jobId}`)) {
        return;
    }

    localStorage.setItem(`extract_closed_${jobId}`, "1");

    if (extractAutoCloseTimer) {
        clearTimeout(extractAutoCloseTimer);
    }

    extractAutoCloseTimer = setTimeout(() => {
        hideExtractProgressModal();
    }, 700);
}
