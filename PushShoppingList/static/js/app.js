function saveScroll() {
    localStorage.setItem("scrollY", window.scrollY);
}

let hiddenExtractJobId = null;
let lastRenderedExtractJobId = null;
let extractRefreshTimer = null;
let lastRenderedExtractProgress = null;
let currentExtractAbortController = null;
let currentExtractAbortControllers = [];
let cancelExtractRequested = false;
const recipeQuantitySaveTimers = new WeakMap();
const recipeQuantityNoticeTimers = new Map();
let recipeQuantityStepButtonsBound = false;
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

function toggleCardCollapse(key) {
    const content = document.querySelector(`[data-collapse-content="${key}"]`);
    const icon = document.querySelector(`[data-collapse-icon="${key}"]`);

    if (!content) {
        return;
    }

    const isCollapsed = content.classList.toggle("collapsed");
    localStorage.setItem(`card-collapse:${key}`, isCollapsed ? "collapsed" : "expanded");

    if (icon) {
        icon.textContent = isCollapsed ? "Show v" : "Hide ^";
    }
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
        const savedState = localStorage.getItem(`card-collapse:${key}`);
        const shouldCollapse = savedState !== "expanded";

        content.classList.toggle("collapsed", shouldCollapse);

        if (icon) {
            icon.textContent = shouldCollapse ? "Show v" : "Hide ^";
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
            queueRecipeQuantitySave(input, recipeQuantitySaveDelayMs);
        });

        input.addEventListener("change", () => {
            saveRecipeQuantity(input);
        });

        input.addEventListener("blur", () => {
            saveRecipeQuantity(input);
        });
    });

    if (recipeQuantityStepButtonsBound) {
        return;
    }

    recipeQuantityStepButtonsBound = true;

    document.addEventListener("click", event => {
        const button = event.target.closest(".recipe-quantity-step");

        if (!button) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        const control = button.closest(".recipe-quantity-control");
        const input = control ? control.querySelector(".recipe-quantity-input") : null;

        if (!input) {
            return;
        }

        const step = parseInt(button.dataset.step || "0", 10);
        const currentValue = parseInt(input.value || "1", 10) || 1;
        input.value = Math.max(1, currentValue + step);
        queueRecipeQuantitySave(input, recipeQuantitySaveDelayMs);
    });
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

async function saveRecipeQuantity(input) {
    const queuedSave = recipeQuantitySaveTimers.get(input);

    if (queuedSave) {
        clearTimeout(queuedSave);
        recipeQuantitySaveTimers.delete(input);
    }

    const url = input.dataset.recipeUrl || "";
    const quantity = Math.max(1, parseInt(input.value || "1", 10) || 1);
    input.value = quantity;

    if (input.dataset.lastSavedValue === String(quantity) && !input.dataset.savePending) {
        return;
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

        try {
            await refreshStoreMarkup();
        } catch (refreshErr) {
            console.warn("Unable to refresh recipe quantities in the background.", refreshErr);
        }

        showRecipeQuantityUpdatedMessage(url, quantity, input.dataset.recipeNumber || "");

        setTimeout(() => {
            input.classList.remove("saved");
        }, 700);
    } catch (err) {
        console.warn("Unable to save recipe quantity.", err);
    } finally {
        setRecipeQuantityControlSaving(input, false);
        delete input.dataset.savePending;
    }
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

function showRecipeQuantityUpdatedMessage(recipeUrl, quantity, recipeNumber = "") {
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
    notice.textContent = `${recipeLabel}Qty updated to ${quantity}.`;
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

    const summary = document.getElementById("homeAddressSummary");
    const saveButton = form.querySelector('button[name="action"][value="save"]');
    const formData = new FormData(form);
    formData.set("ajax", "1");

    if (summary) {
        summary.textContent = buildAddressSummaryFromForm(form);
    }

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

        if (summary) {
            summary.textContent = data.home_address.full_address || "";
        }
    } catch (err) {
        console.warn("Unable to save address in the background.", err);
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
        }
    }

    return false;
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
    replaceSectionFromPage(nextPage, "#sectionView");
    replaceSectionFromPage(nextPage, "#storeView");
    replaceSectionFromPage(nextPage, "#recipeView");
    restoreCardCollapseState();
    restoreOpenStorePanels();
    restoreViewBehaviorSettings();
    restoreItemCheckState();
    bindRecipeQuantityInputs();
    bindStoreButtons();
    bindSectionHeaderToggles();
    bindRecipeDetailToggles();
    bindRecipeTaskChecks();
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
    const stateInput = form.querySelector('[name="address_state"]');
    const zipInput = form.querySelector('[name="address_zip"]');

    const street = streetInput ? streetInput.value.trim() : "";
    const apartment = apartmentInput ? apartmentInput.value.trim() : "";
    const city = cityInput ? cityInput.value.trim() : "";
    const state = stateInput ? stateInput.value.trim() : "";
    const zip = zipInput ? zipInput.value.trim() : "";

    const streetLine = [street, apartment].filter(Boolean).join(" ");
    const cityStateZip = [state, zip].filter(Boolean).join(" ");
    const cityLine = [city, cityStateZip].filter(Boolean).join(", ");

    return [streetLine, cityLine].filter(Boolean).join(", ");
}

document.addEventListener("DOMContentLoaded", function () {
    restoreScroll();
    restoreCardCollapseState();
    restoreOpenStorePanels();
    restoreViewBehaviorSettings();
    restoreItemCheckState();
    bindRecipeQuantityInputs();
    bindStoreButtons();
    bindSectionHeaderToggles();
    bindRecipeDetailToggles();
    bindRecipeTaskChecks();
    startExtractionProgressPolling();
});

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
