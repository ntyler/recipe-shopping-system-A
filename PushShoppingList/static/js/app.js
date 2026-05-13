function saveScroll() {
    localStorage.setItem("scrollY", window.scrollY);
}

let hiddenExtractJobId = null;
let lastRenderedExtractJobId = null;
let extractRefreshTimer = null;
let lastRenderedExtractProgress = null;
let currentExtractAbortController = null;
let cancelExtractRequested = false;

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
                    <span class="bulk-progress-text">
                        ${index + 1}. ${url}
                    </span>
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

    for (const [index, url] of urls.entries()) {
        if (cancelExtractRequested) {
            break;
        }

        const row = document.getElementById(`extract-url-${index}`);
        const text = row ? row.querySelector(".bulk-progress-text") : null;
        const reason = row ? row.querySelector(".bulk-skip-reason") : null;

        if (reason) {
            reason.textContent = "extracting - Running recipe extractor...";
        }

        if (text) {
            text.classList.add("active");
        }

        currentExtractAbortController = new AbortController();

        try {
            await fetch("/api/extract_recipe", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                signal: currentExtractAbortController.signal,
                body: JSON.stringify({
                    url: url,
                    urls: urls,
                    index: index,
                    job_id: jobId,
                }),
            });
        } catch (err) {
            if (!cancelExtractRequested) {
                throw err;
            }
        } finally {
            currentExtractAbortController = null;
        }
    }
}

async function cancelRecipeExtraction() {
    cancelExtractRequested = true;

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

        const text = document.createElement("span");
        text.className = "bulk-progress-text";

        if (item.state === "running") {
            text.classList.add("active");
        }

        if (item.state === "done") {
            text.classList.add("done");
        }

        if (item.state === "cancelled") {
            text.classList.add("cancelled");
        }

        text.textContent = `${index + 1}. ${item.url}`;

        const reason = document.createElement("div");
        reason.className = "bulk-skip-reason";
        reason.textContent = item.message || "waiting...";

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
