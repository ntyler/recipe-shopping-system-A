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
let productProgressTimer = null;
let activeProductJobId = null;
let activeProductPromptChoice = null;
let activeTestGrabAldiButton = null;
let testGrabAldiRunning = false;
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
        document.body.classList.add("modal-open");
    }
}

function hideProductsOverlay() {
    const modal = document.getElementById("productsOverlay");

    if (modal) {
        modal.style.display = "none";
        document.body.classList.remove("modal-open");
    }
}

function setProductsOverlayState(status, summary = "", percent = 0, rows = []) {
    const statusElement = document.getElementById("productsStatusText");
    const summaryElement = document.getElementById("productsSummary");
    const bar = document.getElementById("productsProgressBar");
    const list = document.getElementById("productsList");

    if (statusElement) {
        statusElement.textContent = status || "";
    }

    if (summaryElement) {
        summaryElement.textContent = summary || "";
    }

    if (bar) {
        bar.style.width = `${Math.max(0, Math.min(100, percent || 0))}%`;
    }

    if (list) {
        list.innerHTML = rows.map(renderProductProgressRow).join("");
    }
}

function renderProductProgressRow(row, index) {
    const selected = row.selected_product || null;
    const isTestGrab = Boolean(row.test_grab);
    const skip = (row.skip_reasons || [])[0] || "";
    const productUrl = selected && selected.product_url && selected.product_url !== selected.search_url
        ? selected.product_url
        : "";
    const selectedName = selected ? (selected.product_name || "Unnamed product") : "No product selected";
    const requestedQuantity = selected ? (selected.requested_quantity || row.quantity || "") : (row.quantity || "");
    const rowSearchUrl = productSearchUrlForRow(row, selected);
    const rowTitle = isTestGrab
        ? `${selected ? selected.store_name || row.target_store || row.store_name || "Aldi" : row.target_store || row.store_name || "Aldi"} - ${row.ingredient || row.search_item || ""}`
        : row.ingredient || "";
    const titleHtml = productProgressTitleHtml(`${index + 1}. ${rowTitle}`, ["bulk-progress-text"], rowSearchUrl);
    const selectedHtml = productUrl
        ? `<a class="bulk-product-name bulk-product-name-link" href="${escapeAttribute(productUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(selectedName)}</a>`
        : `<div class="bulk-product-name">${escapeHtml(selectedName)}</div>`;
    const promptButtonHtml = selected && !isTestGrab
        ? progressPromptButtonHtml(row, selected)
        : "";
    const hasSavedAlternatives = Boolean(
        selected
        || row.candidates_count
        || (Array.isArray(row.candidates) && row.candidates.length)
    );
    const alternativesButtonHtml = isTestGrab
        ? (hasSavedAlternatives ? testGrabAlternativesButtonHtml(row) : "")
        : `
            <button type="button"
                    class="bulk-alt-toggle"
                    data-item-key="${escapeAttribute(row.item_key || "")}"
                    onclick="openProductAlternatives(this)">
                Alternatives
            </button>
        `;

    return `
        <div class="bulk-progress-item">
            <input type="checkbox" class="bulk-progress-check" disabled ${selected ? "checked" : ""}>
            <div class="bulk-progress-main">
                <div class="bulk-progress-title-line">
                    ${titleHtml}
                </div>
                <div class="bulk-skip-reason">${escapeHtml(skip || (selected ? "selected" : "no valid product selected"))}</div>
            </div>
            <div class="bulk-progress-meta">
                ${selectedHtml}
                ${requestedQuantity ? `<div class="bulk-product-status">${escapeHtml(`Need ${requestedQuantity}`)}</div>` : ""}
                <div class="bulk-product-price">${escapeHtml(selected ? (selected.price || "Price unavailable") : "")}</div>
                <div class="bulk-product-status">${escapeHtml(selected ? selected.store_name : "")}</div>
                ${promptButtonHtml}
            </div>
            ${alternativesButtonHtml}
        </div>
    `;
}

function newProductJobId() {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formActionUrl(form) {
    // Read the attribute directly because named form controls can shadow form.action.
    const action = form ? form.getAttribute("action") : "";
    return new URL(action || window.location.href, window.location.href).toString();
}

function startProductProgressPolling(jobId) {
    stopProductProgressPolling();
    activeProductJobId = jobId;
    pollProductProgress();
    productProgressTimer = window.setInterval(pollProductProgress, 850);
}

function stopProductProgressPolling() {
    if (productProgressTimer) {
        window.clearInterval(productProgressTimer);
        productProgressTimer = null;
    }
}

async function pollProductProgress() {
    if (!activeProductJobId) {
        return;
    }

    try {
        const response = await fetch(`/api/product_progress?job_id=${encodeURIComponent(activeProductJobId)}&t=${Date.now()}`, {
            cache: "no-store",
        });

        if (!response.ok) {
            return;
        }

        const progress = await response.json();

        if (!progress || progress.job_id !== activeProductJobId) {
            return;
        }

        renderProductDownloadProgress(progress);
    } catch (err) {
        // Product progress polling is best-effort; the POST still owns completion.
    }
}

function renderProductDownloadProgress(progress) {
    const statusElement = document.getElementById("productsStatusText");
    const summaryElement = document.getElementById("productsSummary");
    const bar = document.getElementById("productsProgressBar");
    const list = document.getElementById("productsList");
    const downloads = progress.downloads || [];
    const completed = progress.completed || downloads.filter(item => {
        return ["done", "failed", "skipped", "cancelled"].includes(item.state);
    }).length;
    const running = downloads.filter(item => item.state === "running").length;
    const total = progress.total || downloads.length;

    if (statusElement) {
        statusElement.textContent = productDownloadStatusText(progress, completed, total);
    }

    if (summaryElement) {
        const progressSummary = progress.summary || "Preparing product search.";
        summaryElement.textContent = total
            ? `${progressSummary} ${completed} of ${total} download(s) finished. ${running} active. Running up to ${progress.max_workers || 1} at once.`
            : progressSummary;
    }

    if (bar) {
        bar.style.width = `${Math.max(0, Math.min(100, progress.percent || 0))}%`;
    }

    if (list) {
        list.innerHTML = downloads.map(renderProductDownloadRow).join("");
    }
}

function productDownloadStatusText(progress, completed, total) {
    if (!progress.active && progress.status === "complete") {
        return "Product downloads complete.";
    }

    if (!progress.active && progress.status === "failed") {
        return "Product downloads finished with errors.";
    }

    if (!total) {
        return progress.summary || "Preparing product search...";
    }

    return `Downloading product searches ${completed} of ${total} complete...`;
}

function renderProductDownloadRow(row, index) {
    const state = row.state || "waiting";
    const done = state === "done";
    const failed = state === "failed";
    const skipped = state === "skipped";
    const active = state === "running";
    const textClasses = ["bulk-progress-text"];

    if (done || skipped) {
        textClasses.push("done");
    } else if (active) {
        textClasses.push("active");
    }

    const statusClass = failed ? "failed" : (active ? "running" : (done ? "done" : (skipped ? "skipped" : "waiting")));
    const candidateText = row.candidates_count === null || row.candidates_count === undefined
        ? ""
        : `${row.candidates_count} candidate${Number(row.candidates_count) === 1 ? "" : "s"}`;
    const selected = row.selected_product || null;
    const title = `${row.store_name || row.store_key || "Store"} - ${row.ingredient || row.search_term || ""}`;
    const urlHtml = productProgressTitleHtml(title, textClasses, productSearchUrlForRow(row, selected));
    const selectedUrl = selected && selected.product_url && selected.product_url !== selected.search_url
        ? selected.product_url
        : "";
    const selectedName = selected ? (selected.product_name || row.selected_name || "") : "";
    const promptButtonHtml = selected && !row.test_grab
        ? progressPromptButtonHtml(row, selected)
        : "";
    const selectedLabel = row.selected_is_overall ? "Picked" : "Store Pick";
    const selectedRole = row.selected_is_overall ? "picked" : "store pick";
    const hasSavedAlternatives = Boolean(
        selected
        || row.candidates_count
        || (Array.isArray(row.candidates) && row.candidates.length)
    );
    const alternativesButtonHtml = row.test_grab && hasSavedAlternatives ? testGrabAlternativesButtonHtml(row) : "";
    const selectedMeta = selected
        ? [
            selected.requested_quantity ? `need ${selected.requested_quantity}` : "",
            selected.price || row.selected_price || "Price unavailable",
            selected.size || "",
            selected.unit_price || "",
            selectedRole,
        ].filter(Boolean).join(" | ")
        : "";
    const selectedHtml = selectedName
        ? `
            <div class="bulk-picked-product${row.selected_is_overall ? " overall" : ""}">
                <span class="bulk-picked-label">${selectedLabel}</span>
                ${selectedUrl
                    ? `<a class="bulk-picked-link" href="${escapeAttribute(selectedUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(selectedName)}</a>`
                    : `<span class="bulk-picked-name">${escapeHtml(selectedName)}</span>`
                }
                <span class="bulk-picked-meta">${escapeHtml(selectedMeta)}</span>
            </div>
        `
        : "";

    return `
        <div class="bulk-progress-item product-download-row">
            <input type="checkbox" class="bulk-progress-check" disabled ${done ? "checked" : ""}>
            <div class="bulk-progress-main">
                <div class="bulk-progress-title-line">
                    <span class="bulk-progress-text">${index + 1}. </span>
                    ${urlHtml}
                </div>
                <div class="bulk-skip-reason">${escapeHtml(row.message || "waiting...")}</div>
                ${selectedHtml}
            </div>
            <div class="bulk-progress-meta">
                ${selectedName && selectedUrl
                    ? `<a class="bulk-product-name bulk-product-name-link" href="${escapeAttribute(selectedUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(selectedName)}</a>`
                    : `<div class="bulk-product-name">${escapeHtml(selectedName || row.ingredient || "")}</div>`
                }
                <div class="bulk-product-status">${escapeHtml(row.store_name || row.store_key || "")}</div>
                <div class="bulk-product-price">${escapeHtml(selected ? selected.price || candidateText : candidateText)}</div>
                ${promptButtonHtml}
                ${alternativesButtonHtml}
            </div>
            <span class="bulk-download-state ${statusClass}">${escapeHtml(state)}</span>
        </div>
    `;
}

function productProgressTitleHtml(title, classes, url) {
    const className = (classes || ["bulk-progress-text"]).join(" ");

    if (url) {
        return `
            <a class="${escapeAttribute(`${className} bulk-progress-title-link`)}"
               href="${escapeAttribute(url)}"
               target="_blank"
               rel="noopener noreferrer"
               title="${escapeAttribute(url)}">
                ${escapeHtml(title)}
            </a>
        `;
    }

    return `<span class="${escapeAttribute(className)}">${escapeHtml(title)}</span>`;
}

function productSearchUrlForRow(row, selected = null) {
    const sources = [
        row ? row.search_url : "",
        row ? row.source_page_url : "",
        row ? row.rendered_page_url : "",
        selected ? selected.search_url : "",
        selected ? selected.source_page_url : "",
        selected ? selected.rendered_page_url : "",
    ];

    for (const value of sources) {
        if (value && value !== (selected ? selected.product_url : "")) {
            return value;
        }
    }

    const storeResults = row && Array.isArray(row.store_results_list) ? row.store_results_list : [];
    for (const storeResult of storeResults) {
        const value = storeResult
            ? storeResult.search_url || storeResult.source_page_url || storeResult.rendered_page_url || ""
            : "";
        if (value) {
            return value;
        }
    }

    return "";
}

function testGrabAlternativesButtonHtml(row = {}) {
    const itemKey = row.item_key || row.ingredient || "test grab";
    return `
        <button type="button"
                class="bulk-alt-toggle"
                data-item-key="${escapeAttribute(itemKey)}"
                data-store-key="aldi"
                onclick="openTestGrabAlternatives(this)">
            Alternatives
        </button>
    `;
}

function progressPromptButtonHtml(row, selected) {
    return `
        <button type="button"
                class="bulk-prompt-btn bulk-row-prompt-btn"
                data-item-key="${escapeAttribute(row.item_key || row.ingredient || "")}"
                data-store-key="${escapeAttribute(row.store_key || selected.store_key || "")}"
                data-product-id="${escapeAttribute(selected.id || row.selected_product_id || "")}"
                data-product-name="${escapeAttribute(selected.product_name || row.selected_name || "")}"
                onclick="openProductPromptForProgressRow(this)">
            Prompt
        </button>
    `;
}

async function grabBestProducts(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form ? form.querySelector("button") : null;
    const originalText = button ? button.textContent : "";
    const jobId = newProductJobId();
    activeProductJobId = jobId;

    showProductsOverlay();
    setProductsOverlayState(
        "Preparing product downloads...",
        "Using the saved Full Address to find nearby stores and search enabled store websites.",
        3,
        []
    );
    startProductProgressPolling(jobId);

    if (button) {
        button.disabled = true;
        button.textContent = "Grabbing...";
    }

    try {
        const formData = new FormData(form);
        formData.set("ajax", "1");
        formData.set("job_id", jobId);
        const response = await fetch(formActionUrl(form), {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to grab best products.");
        }

        stopProductProgressPolling();
        setProductsOverlayState(
            "Best products saved.",
            `${data.selected_count || 0} of ${data.count || 0} ingredient(s) have a selected product. ${data.download_count || 0} store search download(s) ran with up to ${data.max_workers || 1} in parallel.`,
            100,
            data.results || []
        );
        await refreshStoreMarkup({ cacheBust: true });
    } catch (err) {
        console.warn("Unable to grab best products.", err);
        stopProductProgressPolling();
        setProductsOverlayState("Unable to grab best products.", err.message || "Product search failed.", 100, []);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Grab Best Products";
        }
    }

    return false;
}

function openTestGrabAldiModal(button) {
    if (testGrabAldiRunning) {
        return false;
    }

    activeTestGrabAldiButton = button || null;
    const modal = ensureTestGrabAldiModal();
    const input = document.getElementById("testGrabAldiInput");
    const lastIngredient = localStorage.getItem("testGrabAldiIngredient") || localStorage.getItem("testGrabIngredient") || "eggs";

    if (input) {
        input.value = lastIngredient;
    }

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    window.setTimeout(() => {
        if (input) {
            input.focus();
            input.select();
        }
    }, 0);

    return false;
}

function ensureTestGrabAldiModal() {
    let modal = document.getElementById("testGrabAldiModal");

    if (!modal) {
        modal = document.createElement("div");
        modal.id = "testGrabAldiModal";
        modal.className = "test-grab-modal-backdrop";
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = `
            <div class="test-grab-modal" role="dialog" aria-modal="true" aria-labelledby="testGrabAldiTitle">
                <h2 id="testGrabAldiTitle" class="test-grab-modal-title">Enter Ingredient Or Product</h2>
                <form onsubmit="return submitTestGrabAldiModal(event)">
                    <input id="testGrabAldiInput"
                           class="test-grab-input"
                           type="text"
                           autocomplete="off"
                           placeholder="eggs, butter, yellow onion"
                           aria-label="Enter ingredient or product">
                    <div class="test-grab-modal-actions">
                        <button type="button" class="product-close-btn" onclick="closeTestGrabAldiModal()">Cancel</button>
                        <button type="submit" class="grab-products-btn">Submit</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(modal);
        modal.addEventListener("keydown", event => {
            if (event.key === "Escape") {
                closeTestGrabAldiModal();
            }
        });
    }

    return modal;
}

function closeTestGrabAldiModal() {
    const modal = document.getElementById("testGrabAldiModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }

    if (!document.querySelector(".bulk-alt-modal-backdrop.open") && !document.querySelector(".product-prompt-modal-backdrop.open")) {
        document.body.classList.remove("modal-open");
    }

    return false;
}

function submitTestGrabAldiModal(event) {
    if (event) {
        event.preventDefault();
    }

    const input = document.getElementById("testGrabAldiInput");
    const ingredient = input ? input.value.trim() : "";

    if (!ingredient) {
        if (input) {
            input.focus();
        }
        return false;
    }

    closeTestGrabAldiModal();
    runTestGrabAldi(ingredient, activeTestGrabAldiButton);
    return false;
}

async function runTestGrabAldi(ingredient, button) {
    const originalText = button ? button.textContent : "";
    const jobId = newProductJobId();
    activeProductJobId = jobId;
    testGrabAldiRunning = true;
    localStorage.setItem("testGrabAldiIngredient", ingredient);
    localStorage.setItem("testGrabIngredient", ingredient);

    showProductsOverlay();
    setProductsOverlayState(
        "Opening ALDI...",
        `Searching ALDI for: ${ingredient}`,
        3,
        []
    );
    startProductProgressPolling(jobId);

    if (button) {
        button.disabled = true;
        button.textContent = "Testing...";
    }

    let data = null;
    try {
        const response = await fetch("/test-grab-aldi", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({
                ingredient,
                job_id: jobId,
            }),
        });
        data = await response.json();

        if (!response.ok || !data.ok) {
            const errors = data && Array.isArray(data.errors) ? data.errors.filter(Boolean).join(" ") : "";
            throw new Error(errors || (data && data.error) || "Unable to complete Test Grab ALDI.");
        }

        stopProductProgressPolling();
        setProductsOverlayState(
            "Complete.",
            `Searching ALDI for: ${data.search_term || ingredient}. ${data.selected_count || 0} best product selected.`,
            100,
            data.results || []
        );
    } catch (err) {
        console.warn("Unable to complete Test Grab ALDI.", err);
        stopProductProgressPolling();
        setProductsOverlayState(
            "Failed.",
            err.message || "Test Grab ALDI failed.",
            100,
            data && Array.isArray(data.results) ? data.results : []
        );
    } finally {
        testGrabAldiRunning = false;
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Test Grab ALDI";
        }
    }

    return false;
}

async function testGrabProducts(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form ? form.querySelector("button") : null;
    const originalText = button ? button.textContent : "";
    const previousIngredient = localStorage.getItem("testGrabIngredient") || "eggs";
    const ingredientInput = window.prompt("What ingredient should Test Grab search at ALDI?", previousIngredient);

    if (ingredientInput === null) {
        return false;
    }

    const ingredient = ingredientInput.trim();
    if (!ingredient) {
        alert("Enter an ingredient for Test Grab.");
        return false;
    }

    localStorage.setItem("testGrabIngredient", ingredient);
    const jobId = newProductJobId();
    activeProductJobId = jobId;

    showProductsOverlay();
    setProductsOverlayState(
        "Preparing isolated Test Grab...",
        `Testing ALDI ${ingredient}, using the saved current Full Address.`,
        3,
        []
    );
    startProductProgressPolling(jobId);

    if (button) {
        button.disabled = true;
        button.textContent = "Testing...";
    }

    let data = null;
    try {
        const formData = new FormData(form);
        formData.set("ajax", "1");
        formData.set("job_id", jobId);
        formData.set("ingredient", ingredient);
        const response = await fetch(formActionUrl(form), {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });
        data = await response.json();

        if (!response.ok || !data.ok) {
            const errors = data && Array.isArray(data.errors) ? data.errors.filter(Boolean).join(" ") : "";
            throw new Error(errors || (data && data.error) || "Unable to complete Test Grab.");
        }

        stopProductProgressPolling();
        setProductsOverlayState(
            "Test Grab complete.",
            `ALDI ${data.search_item || ingredient} test selected ${data.selected_count || 0} best product. Result saved to ${data.result_path || "test_grab_result.json"}.`,
            100,
            data.results || []
        );
    } catch (err) {
        console.warn("Unable to complete Test Grab.", err);
        stopProductProgressPolling();
        setProductsOverlayState(
            "Unable to complete Test Grab.",
            err.message || "Test Grab failed.",
            100,
            data && Array.isArray(data.results) ? data.results : []
        );
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Test Grab";
        }
    }

    return false;
}

async function clearProductPicks(event) {
    event.preventDefault();
    const form = event.currentTarget;

    try {
        const formData = new FormData(form);
        formData.set("ajax", "1");
        const response = await fetch(formActionUrl(form), {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });

        if (!response.ok) {
            throw new Error("Unable to clear product picks.");
        }

        await refreshStoreMarkup({ cacheBust: true });
        showRecipeQuantityUpdatedMessage("", "", "", "Product picks cleared.");
    } catch (err) {
        console.warn("Unable to clear product picks.", err);
        alert("Unable to clear product picks.");
    }

    return false;
}

async function openProductAlternatives(button) {
    const itemKey = button ? button.dataset.itemKey || "" : "";
    const storeKey = button ? button.dataset.storeKey || "" : "";

    if (!itemKey) {
        return false;
    }

    const modal = ensureProductAlternativesModal();
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    renderProductAlternativesLoading(itemKey, storeKey);

    try {
        const params = new URLSearchParams({ item_key: itemKey });
        if (storeKey) {
            params.set("store_key", storeKey);
        }
        const response = await fetch(`/api/product_choice?${params.toString()}`, {
            cache: "no-store",
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "No alternatives were found.");
        }

        renderProductAlternatives(data.choice);
    } catch (err) {
        renderProductAlternativesError(err.message || "Unable to load alternatives.");
    }

    return false;
}

async function openTestGrabAlternatives(button) {
    const itemLabel = button ? button.dataset.itemKey || "Test Grab" : "Test Grab";
    const modal = ensureProductAlternativesModal();
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    renderProductAlternativesLoading(itemLabel, "Aldi");

    try {
        const response = await fetch(`/api/test_grab_result?t=${Date.now()}`, {
            cache: "no-store",
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "No Test Grab alternatives were found.");
        }

        renderProductAlternatives(data.choice);
    } catch (err) {
        renderProductAlternativesError(err.message || "Unable to load Test Grab alternatives.");
    }

    return false;
}

function ensureProductAlternativesModal() {
    let modal = document.getElementById("productAlternativesModal");

    if (!modal) {
        modal = document.createElement("div");
        modal.id = "productAlternativesModal";
        modal.className = "bulk-alt-modal-backdrop";
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = `
            <div class="bulk-alt-modal" role="dialog" aria-modal="true" aria-labelledby="productAlternativesTitle">
                <div class="bulk-alt-modal-header">
                    <div style="width:72px;"></div>
                    <h2 id="productAlternativesTitle" class="bulk-alt-modal-title">Product Alternatives</h2>
                    <button type="button" class="product-close-btn" onclick="closeProductAlternatives()">Close</button>
                </div>
                <p id="productAlternativesSubtitle" class="bulk-alt-modal-subtitle"></p>
                <div id="productAlternativesContent" class="bulk-choices open"></div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    return modal;
}

function closeProductAlternatives() {
    const modal = document.getElementById("productAlternativesModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }
}

function renderProductAlternativesLoading(itemKey, storeKey = "") {
    const subtitle = document.getElementById("productAlternativesSubtitle");
    const content = document.getElementById("productAlternativesContent");

    if (subtitle) {
        subtitle.textContent = storeKey ? `${itemKey} at ${storeKey}` : itemKey;
    }

    if (content) {
        content.innerHTML = `<div class="bulk-review-note">Loading alternatives...</div>`;
    }
}

function renderProductAlternatives(choice) {
    const subtitle = document.getElementById("productAlternativesSubtitle");
    const content = document.getElementById("productAlternativesContent");
    const candidates = productAlternativeCandidateList(choice);
    const selectedId = choice.selected_product_id || "";
    const storeName = choice.filtered_store_name || (choice.store_result ? choice.store_result.store_name : "") || "";
    const storeKey = choice.filtered_store_key || "";
    const isTestGrabChoice = Boolean(choice.test_grab);
    activeProductPromptChoice = choice;

    if (subtitle) {
        const itemLabel = choice.ingredient || choice.item_key || "";
        subtitle.textContent = storeName ? `${itemLabel} at ${storeName}` : itemLabel;
    }

    if (!content) {
        return;
    }

    const validSourceCandidates = productAlternativeCandidateList({
        selected_product: choice.selected_product,
        candidates: [],
        valid_alternatives: choice.valid_alternatives,
        alternatives: choice.alternatives,
    });
    const validCandidates = validSourceCandidates.length
        ? validSourceCandidates
        : candidates.filter(candidate => candidate && candidate.viable !== false && candidate.rejected !== true);
    const rejectedCandidates = Array.isArray(choice.rejected_products) && choice.rejected_products.length
        ? choice.rejected_products
        : candidates.filter(candidate => candidate && (candidate.viable === false || candidate.rejected === true));

    if (!candidates.length && !validCandidates.length) {
        content.innerHTML = `<div class="bulk-review-note">No alternatives are saved for this ingredient.</div>`;
        return;
    }

    const finalPromptHtml = hasPromptData(choice.chatgpt_final_selection_prompt)
        ? `
            <div class="bulk-alt-prompt-row">
                <button type="button" class="bulk-prompt-btn" onclick="openProductPromptFromChoice()">
                    Final ChatGPT Prompt
                </button>
            </div>
        `
        : "";

    if (isTestGrabChoice) {
        content.innerHTML = finalPromptHtml + renderTestGrabAlternativeSlider(
            choice,
            validCandidates,
            selectedId,
            storeKey
        );
        return;
    }

    const groupsHtml = [
        renderProductCandidateGroup(
            "Valid Alternatives",
            validCandidates,
            selectedId,
            choice.item_key || "",
            storeKey,
            false
        ),
        renderProductCandidateGroup(
            "Rejected Products",
            rejectedCandidates,
            selectedId,
            choice.item_key || "",
            storeKey,
            true
        ),
    ].filter(Boolean).join("");

    content.innerHTML = finalPromptHtml + (groupsHtml || `<div class="bulk-review-note">No alternatives are saved for this ingredient.</div>`);
}

function productAlternativeCandidateList(choice = {}) {
    return dedupeProductAlternativeCandidates(
        choice.selected_product ? [choice.selected_product] : [],
        choice.valid_alternatives,
        choice.alternatives,
        choice.candidates,
        choice.valid_products,
        choice.alternative_products
    );
}

function dedupeProductAlternativeCandidates(...lists) {
    const rows = [];
    const seen = new Set();

    lists.forEach(list => {
        if (!Array.isArray(list)) {
            return;
        }

        list.forEach(candidate => {
            if (!candidate || typeof candidate !== "object") {
                return;
            }

            const key = productAlternativeCandidateKey(candidate);
            if (key && seen.has(key)) {
                return;
            }
            if (key) {
                seen.add(key);
            }
            rows.push(candidate);
        });
    });

    return rows;
}

function productAlternativeCandidateKey(candidate) {
    return String(
        candidate.product_url
        || candidate.id
        || candidate.product_name
        || candidate.name
        || ""
    ).trim().toLowerCase();
}

function renderTestGrabAlternativeSlider(choice, candidates, selectedId, storeKey) {
    const rows = (candidates || []).filter(candidate => candidate && candidate.viable !== false && candidate.rejected !== true);
    const itemLabel = choice.ingredient || choice.item_key || "product";
    const storeName = choice.filtered_store_name || "ALDI";

    if (!rows.length) {
        return `<div class="bulk-review-note">No valid alternatives are saved for this ingredient.</div>`;
    }

    return `
        <section class="test-grab-storefront">
            <div class="test-grab-storefront-header">
                <div class="test-grab-store-icon">ALDI</div>
                <div>
                    <div class="test-grab-store-name">${escapeHtml(storeName)}</div>
                    <div class="test-grab-store-meta">Localized Test Grab results</div>
                </div>
            </div>
            <div class="test-grab-results-title">Results for "${escapeHtml(itemLabel)}"</div>
            <div class="test-grab-results-count">${rows.length} acceptable alternative${rows.length === 1 ? "" : "s"}</div>
            <div class="test-grab-slider-shell">
                <button type="button"
                        class="test-grab-slider-nav"
                        aria-label="Scroll alternatives left"
                        onclick="scrollTestGrabSlider(-1)">
                    &lsaquo;
                </button>
                <div id="testGrabAlternativeSlider" class="test-grab-slider" tabindex="0">
                    ${rows.map(candidate => renderTestGrabAlternativeCard(candidate, selectedId, choice.item_key || "", storeKey)).join("")}
                </div>
                <button type="button"
                        class="test-grab-slider-nav"
                        aria-label="Scroll alternatives right"
                        onclick="scrollTestGrabSlider(1)">
                    &rsaquo;
                </button>
            </div>
        </section>
    `;
}

function renderTestGrabAlternativeCard(candidate, selectedId, itemKey, storeKey) {
    const selected = candidate.id === selectedId;
    const imageSrc = productCandidateImageSrc(candidate);
    const productUrl = candidate.product_url && candidate.product_url !== candidate.search_url
        ? candidate.product_url
        : "";
    const name = candidate.product_name || "Unnamed product";
    const size = candidate.size_count || candidate.size || candidate.package_size || "";
    const unit = candidate.price_per_egg || candidate.price_per_unit || candidate.unit_price || "";
    const badges = [
        selected ? "Selected" : "",
        /organic/i.test(name) ? "Organic" : "",
        /free range/i.test(name) ? "Free range" : "",
        /cage free/i.test(name) ? "Cage free" : "",
    ].filter(Boolean);

    return `
        <article class="test-grab-product-card${selected ? " selected" : ""}">
            <a class="test-grab-product-image-wrap"
               href="${escapeAttribute(productUrl || "#")}"
               target="${productUrl ? "_blank" : ""}"
               rel="noopener noreferrer"
               aria-label="${escapeAttribute(name)}">
                ${imageSrc
                    ? `<img class="test-grab-product-image" src="${escapeAttribute(imageSrc)}" alt="">`
                    : `<div class="test-grab-product-image-placeholder"></div>`
                }
                ${badges.length
                    ? `<div class="test-grab-product-badges">${badges.slice(0, 2).map(badge => `<span>${escapeHtml(badge)}</span>`).join("")}</div>`
                    : ""
                }
            </a>
            <div class="test-grab-product-price">${escapeHtml(candidate.price || "Price unavailable")}</div>
            <a class="test-grab-product-name"
               href="${escapeAttribute(productUrl || "#")}"
               target="${productUrl ? "_blank" : ""}"
               rel="noopener noreferrer">
                ${escapeHtml(name)}
            </a>
            <div class="test-grab-product-size">${escapeHtml(size)}</div>
            <div class="test-grab-product-unit">${escapeHtml(unit)}</div>
            <button type="button"
                    class="test-grab-card-select${selected ? " selected" : ""}"
                    data-item-key="${escapeAttribute(itemKey || "")}"
                    data-product-id="${escapeAttribute(candidate.id || "")}"
                    data-store-key="${escapeAttribute(storeKey || candidate.store_key || "")}"
                    onclick="selectProductAlternative(this)"
                    ${selected ? "disabled" : ""}>
                ${selected ? "Selected" : "Select"}
            </button>
        </article>
    `;
}

function scrollTestGrabSlider(direction) {
    const slider = document.getElementById("testGrabAlternativeSlider");
    if (!slider) {
        return false;
    }
    slider.scrollBy({
        left: (direction || 1) * Math.max(260, slider.clientWidth * 0.82),
        behavior: "smooth",
    });
    return false;
}

function renderProductCandidateGroup(title, candidates, selectedId, itemKey, storeKey, rejected = false) {
    const rows = (candidates || []).filter(Boolean);

    if (!rows.length) {
        return "";
    }

    return `
        <section class="bulk-alt-group${rejected ? " rejected" : ""}">
            <h3 class="bulk-alt-group-title">${escapeHtml(title)} <span>${rows.length}</span></h3>
            ${rows.map(candidate => renderProductCandidateOption(candidate, selectedId, itemKey, storeKey, rejected)).join("")}
        </section>
    `;
}

function renderProductCandidateOption(candidate, selectedId, itemKey, storeKey, rejected = false) {
    const selected = candidate.id === selectedId;
    const selectable = !rejected && candidate.viable !== false && candidate.rejected !== true;
    const size = candidate.size || candidate.package_size || "";
    const metaParts = rejected
        ? [
            candidate.store_name,
            candidate.ranking_status || "rejected",
            candidate.confidence ? `confidence ${candidate.confidence}` : "",
        ]
        : [
            candidate.store_name,
            candidate.store_location_address || "",
            candidate.price || "Price unavailable",
            size,
            candidate.unit_price || "",
            candidate.price_per_egg ? `per egg ${candidate.price_per_egg}` : "",
            candidate.ranking_status || "",
            selectable ? "" : "not selectable",
            candidate.confidence ? `confidence ${candidate.confidence}` : "",
            candidate.score !== undefined ? `score ${candidate.score}` : "",
        ];
    const meta = metaParts.filter(Boolean).join(" | ");
    const notes = [
        candidate.reason_selected || "",
        candidate.rejection_reason || "",
        ...(candidate.rejection_reasons || []),
        ...(candidate.ranking_reasons || []),
        ...(candidate.skip_reasons || [])
    ]
        .filter(Boolean)
        .slice(0, rejected ? 6 : 4)
        .join(" ");
    const imageSrc = rejected ? "" : productCandidateImageSrc(candidate);
    const imageHtml = imageSrc
        ? `<img class="bulk-alt-image" src="${escapeAttribute(imageSrc)}" alt="">`
        : "";
    const productUrl = !rejected && candidate.product_url && candidate.product_url !== candidate.search_url
        ? candidate.product_url
        : "";
    const productLinkHtml = productUrl
        ? `
                <a class="bulk-alt-link"
                   href="${escapeAttribute(productUrl)}"
                   target="_blank"
                   rel="noopener noreferrer">
                    ${escapeHtml(productUrl)}
                </a>
            `
        : (rejected ? "" : `<div class="bulk-alt-meta">Direct product link unavailable.</div>`);
    const isTestGrabChoice = Boolean(activeProductPromptChoice && activeProductPromptChoice.test_grab);
    const candidateNameHtml = productUrl
        ? `<a class="bulk-alt-name-link" href="${escapeAttribute(productUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(candidate.product_name || "Unnamed product")}</a>`
        : escapeHtml(candidate.product_name || "Unnamed product");
    const promptButtonHtml = !isTestGrabChoice && productPromptEntries(candidate).length
        ? `
            <button type="button"
                    class="bulk-prompt-btn"
                    data-item-key="${escapeAttribute(itemKey || "")}"
                    data-store-key="${escapeAttribute(storeKey || candidate.store_key || "")}"
                    data-product-id="${escapeAttribute(candidate.id || "")}"
                    onclick="openProductPromptForCandidate(this)">
                Prompt
            </button>
        `
        : "";

    return `
        <div class="bulk-alt-option${imageSrc ? " has-image" : ""}${rejected ? " rejected" : ""}">
            ${imageHtml}
            <div>
                <div class="bulk-alt-name">
                    ${candidateNameHtml}
                    ${selected ? `<span class="bulk-selected-badge" style="display:inline;">Selected</span>` : ""}
                </div>
                ${productLinkHtml}
                <div class="bulk-alt-meta">${escapeHtml(meta)}</div>
                <div class="bulk-alt-meta">${escapeHtml(notes)}</div>
                ${promptButtonHtml}
            </div>
            <button type="button"
                    class="bulk-alt-select-btn${selected ? " selected" : ""}${selectable ? "" : " unavailable"}"
                    data-item-key="${escapeAttribute(itemKey || "")}"
                    data-product-id="${escapeAttribute(candidate.id || "")}"
                    data-store-key="${escapeAttribute(storeKey || candidate.store_key || "")}"
                    onclick="selectProductAlternative(this)"
                    ${(selected || !selectable) ? "disabled" : ""}>
                ${selected ? "Selected" : (selectable ? "Select" : "Rejected")}
            </button>
        </div>
    `;
}

function productCandidateImageSrc(candidate) {
    const direct = candidate ? candidate.image_url || "" : "";
    const embedded = candidate ? candidate.embedded_image_base64 || "" : "";
    const hint = candidate ? candidate.image_url_hint || "" : "";
    const rawHtml = candidate ? candidate.raw_product_html_snippet || candidate.product_card_html || "" : "";

    if (direct) {
        return direct;
    }

    if (hint) {
        return hint;
    }

    if (typeof embedded === "string" && embedded.startsWith("data:image/")) {
        return embedded;
    }

    const snippetImage = imageSrcFromHtmlSnippet(rawHtml);
    if (snippetImage) {
        return snippetImage;
    }

    return "";
}

function imageSrcFromHtmlSnippet(html) {
    if (!html || typeof DOMParser === "undefined") {
        return "";
    }

    try {
        const doc = new DOMParser().parseFromString(html, "text/html");
        const image = doc.querySelector("img");
        if (!image) {
            return "";
        }

        const src = image.getAttribute("src") || image.getAttribute("data-src") || "";
        if (src) {
            return src;
        }

        const srcset = image.getAttribute("srcset") || "";
        const first = srcset.split(",", 1)[0].trim();
        return first ? first.split(/\s+/)[0] : "";
    } catch (err) {
        return "";
    }
}

function productPromptEntries(candidate) {
    const entries = [];
    const productId = candidate ? candidate.id || "" : "";
    const storePrompt = candidate && candidate.chatgpt_store_ranking_agent
        ? candidate.chatgpt_store_ranking_agent.prompt
        : null;
    const renderedHtmlPrompt = candidate && candidate.chatgpt_rendered_html_agent
        ? candidate.chatgpt_rendered_html_agent.prompt
        : null;
    const pagePrompt = candidate && candidate.chatgpt_analysis
        ? candidate.chatgpt_analysis.prompt
        : null;
    const finalPrompt = candidate && candidate.final_selection_agent
        ? candidate.final_selection_agent.prompt
        : null;

    if (hasPromptData(storePrompt)) {
        entries.push({
            title: "Store Product Ranking Prompt",
            prompt: hasPromptPayload(storePrompt) ? storePrompt : null,
            prompt_ref: hasPromptReference(storePrompt) ? storePrompt : null,
            prompt_kind: "store_product_ranking",
            product_id: productId,
        });
    }

    if (hasPromptData(renderedHtmlPrompt)) {
        entries.push({
            title: "Rendered HTML Product Reasoning Prompt",
            prompt: hasPromptPayload(renderedHtmlPrompt) ? renderedHtmlPrompt : null,
            prompt_ref: hasPromptReference(renderedHtmlPrompt) ? renderedHtmlPrompt : null,
            prompt_kind: "rendered_html_product_reasoning",
            product_id: productId,
        });
    }

    if (hasPromptData(pagePrompt)) {
        entries.push({
            title: "Product Page Analysis Prompt",
            prompt: hasPromptPayload(pagePrompt) ? pagePrompt : null,
            prompt_ref: hasPromptReference(pagePrompt) ? pagePrompt : null,
            prompt_kind: "product_page_analysis",
            product_id: productId,
        });
    }

    if (hasPromptData(finalPrompt)) {
        entries.push({
            title: "Final Selection Prompt",
            prompt: hasPromptPayload(finalPrompt) ? finalPrompt : null,
            prompt_ref: hasPromptReference(finalPrompt) ? finalPrompt : null,
            prompt_kind: "final_selection",
            product_id: productId,
        });
    }

    return entries;
}

function hasPromptPayload(prompt) {
    return !!(
        prompt &&
        Array.isArray(prompt.messages) &&
        prompt.messages.some(message => message && message.content)
    );
}

function hasPromptReference(prompt) {
    return !!(
        prompt &&
        typeof prompt === "object" &&
        prompt.prompt_path &&
        !hasPromptPayload(prompt)
    );
}

function hasPromptData(prompt) {
    return hasPromptPayload(prompt) || hasPromptReference(prompt);
}

async function openProductPromptFromChoice() {
    const prompt = activeProductPromptChoice && activeProductPromptChoice.chatgpt_final_selection_prompt;

    if (!hasPromptData(prompt)) {
        return false;
    }

    const entries = await resolveProductPromptEntries([
        {
            title: "Final Selection Prompt",
            prompt: hasPromptPayload(prompt) ? prompt : null,
            prompt_ref: hasPromptReference(prompt) ? prompt : null,
            prompt_kind: "choice_final_selection",
        },
    ], activeProductPromptChoice ? activeProductPromptChoice.item_key || "" : "", activeProductPromptChoice ? activeProductPromptChoice.filtered_store_key || "" : "", "");
    openProductPromptModal(entries);
    return false;
}

async function openProductPromptForCandidate(button) {
    const productId = button ? button.dataset.productId || "" : "";
    const itemKey = button ? button.dataset.itemKey || "" : "";
    const storeKey = button ? button.dataset.storeKey || "" : "";
    const candidates = activeProductPromptChoice ? activeProductPromptChoice.candidates || [] : [];
    const candidate = candidates.find(item => item.id === productId);
    const entries = await resolveProductPromptEntries(
        productPromptEntries(candidate || {}),
        itemKey || (activeProductPromptChoice ? activeProductPromptChoice.item_key || "" : ""),
        storeKey || (activeProductPromptChoice ? activeProductPromptChoice.filtered_store_key || "" : ""),
        productId
    );

    if (!entries.length) {
        return false;
    }

    openProductPromptModal(entries, candidate ? candidate.product_name || "" : "");
    return false;
}

async function openProductPromptForProgressRow(button) {
    const itemKey = button ? button.dataset.itemKey || "" : "";
    const storeKey = button ? button.dataset.storeKey || "" : "";
    const productId = button ? button.dataset.productId || "" : "";
    const productName = button ? button.dataset.productName || "" : "";

    if (!itemKey) {
        openProductPromptModal(noProductPromptEntries("No ingredient key was available for this progress row."), productName);
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "Loading...";
    }

    try {
        const params = new URLSearchParams({ item_key: itemKey });
        if (storeKey) {
            params.set("store_key", storeKey);
        }
        const response = await fetch(`/api/product_choice?${params.toString()}`, {
            headers: {
                "X-Requested-With": "fetch",
            },
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "No ChatGPT prompt was found for this product.");
        }

        const choice = data.choice || {};
        const candidates = choice.candidates || [];
        const candidate = candidates.find(item => item.id === productId)
            || choice.selected_product
            || {};
        const entries = [];

        if (hasPromptData(choice.chatgpt_final_selection_prompt)) {
            const prompt = choice.chatgpt_final_selection_prompt;
            entries.push({
                title: "Final Selection Prompt",
                prompt: hasPromptPayload(prompt) ? prompt : null,
                prompt_ref: hasPromptReference(prompt) ? prompt : null,
                prompt_kind: "choice_final_selection",
            });
        }

        productPromptEntries(candidate).forEach(entry => entries.push(entry));
        const resolvedEntries = await resolveProductPromptEntries(entries, itemKey, storeKey, candidate.id || productId);

        openProductPromptModal(
            resolvedEntries.length ? resolvedEntries : noProductPromptEntries("No ChatGPT prompt was saved for this picked product yet."),
            candidate.product_name || productName || choice.ingredient || itemKey
        );
    } catch (err) {
        console.warn("Unable to load product prompt.", err);
        openProductPromptModal(noProductPromptEntries(err.message || "Unable to load the ChatGPT prompt."), productName || itemKey);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Prompt";
        }
    }

    return false;
}

async function resolveProductPromptEntries(entries, itemKey, storeKey, productId) {
    const rows = entries || [];

    return Promise.all(rows.map(async entry => {
        if (hasPromptPayload(entry.prompt)) {
            return entry;
        }

        if (!entry.prompt_ref) {
            return entry;
        }

        try {
            const params = new URLSearchParams({
                item_key: itemKey || "",
                prompt_kind: entry.prompt_kind || "",
            });
            const resolvedProductId = entry.product_id || productId || "";
            if (resolvedProductId) {
                params.set("product_id", resolvedProductId);
            }
            if (storeKey) {
                params.set("store_key", storeKey);
            }
            const response = await fetch(`/api/product_prompt?${params.toString()}`, {
                cache: "no-store",
                headers: {
                    "X-Requested-With": "fetch",
                },
            });
            const data = await response.json();

            if (!response.ok || !data.ok || !hasPromptPayload(data.prompt)) {
                throw new Error((data && data.error) || "Prompt file could not be loaded.");
            }

            return {
                ...entry,
                title: data.title || entry.title,
                prompt: data.prompt,
            };
        } catch (err) {
            return {
                ...entry,
                prompt: {
                    messages: [
                        {
                            role: "status",
                            content: err.message || "Prompt file could not be loaded.",
                        },
                    ],
                },
            };
        }
    }));
}

function noProductPromptEntries(message) {
    return [
        {
            title: "ChatGPT Prompt",
            prompt: {
                messages: [
                    {
                        role: "status",
                        content: message,
                    },
                ],
            },
        },
    ];
}

function openProductPromptModal(entries, subtitle = "") {
    const modal = ensureProductPromptModal();
    const title = document.getElementById("productPromptTitle");
    const sub = document.getElementById("productPromptSubtitle");
    const content = document.getElementById("productPromptContent");

    if (title) {
        title.textContent = "ChatGPT Prompt";
    }

    if (sub) {
        sub.textContent = subtitle || "Full request sent by the product picker.";
    }

    if (content) {
        content.textContent = entries.map(promptEntryToText).join("\n\n");
    }

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
}

function ensureProductPromptModal() {
    let modal = document.getElementById("productPromptModal");

    if (!modal) {
        modal = document.createElement("div");
        modal.id = "productPromptModal";
        modal.className = "product-prompt-modal-backdrop";
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = `
            <div class="product-prompt-modal" role="dialog" aria-modal="true" aria-labelledby="productPromptTitle">
                <div class="bulk-alt-modal-header">
                    <button type="button" class="bulk-prompt-btn" onclick="copyProductPrompt()">Copy</button>
                    <h2 id="productPromptTitle" class="bulk-alt-modal-title">ChatGPT Prompt</h2>
                    <button type="button" class="product-close-btn" onclick="closeProductPromptModal()">Close</button>
                </div>
                <p id="productPromptSubtitle" class="bulk-alt-modal-subtitle"></p>
                <pre id="productPromptContent" class="product-prompt-content"></pre>
            </div>
        `;
        document.body.appendChild(modal);
    }

    return modal;
}

function closeProductPromptModal() {
    const modal = document.getElementById("productPromptModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }

    const alternativesModal = document.getElementById("productAlternativesModal");
    if (!alternativesModal || !alternativesModal.classList.contains("open")) {
        document.body.classList.remove("modal-open");
    }
}

async function copyProductPrompt() {
    const content = document.getElementById("productPromptContent");
    const text = content ? content.textContent || "" : "";

    if (!text || !navigator.clipboard) {
        return false;
    }

    try {
        await navigator.clipboard.writeText(text);
    } catch (err) {
        console.warn("Unable to copy product prompt.", err);
    }

    return false;
}

function promptEntryToText(entry) {
    const prompt = entry.prompt || {};
    const header = [
        entry.title || "Prompt",
        prompt.kind ? `kind: ${prompt.kind}` : "",
        prompt.model ? `model: ${prompt.model}` : "",
        prompt.temperature !== undefined ? `temperature: ${prompt.temperature}` : "",
    ].filter(Boolean).join("\n");
    const messages = (prompt.messages || []).map((message, index) => {
        return [
            `--- ${message.role || `message ${index + 1}`} ---`,
            message.content || "",
        ].join("\n");
    }).join("\n\n");

    return [header, messages].filter(Boolean).join("\n\n");
}

function renderProductAlternativesError(message) {
    const content = document.getElementById("productAlternativesContent");

    if (content) {
        content.innerHTML = `<div class="bulk-error">${escapeHtml(message || "Unable to load alternatives.")}</div>`;
    }
}

async function selectProductAlternative(button) {
    const itemKey = button ? button.dataset.itemKey || "" : "";
    const productId = button ? button.dataset.productId || "" : "";
    const storeKey = button ? button.dataset.storeKey || "" : "";

    if (!itemKey || !productId) {
        return false;
    }

    button.disabled = true;
    button.textContent = "Saving...";
    const isTestGrabSelection = Boolean(activeProductPromptChoice && activeProductPromptChoice.test_grab);
    const endpoint = isTestGrabSelection ? "/api/test_grab_result/select" : "/api/product_choice/select";

    try {
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                item_key: itemKey,
                product_id: productId,
                store_key: storeKey,
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to select product.");
        }

        renderProductAlternatives(data.choice);
        if (isTestGrabSelection) {
            const result = data.result || {};
            setProductsOverlayState(
                "Test Grab product selected.",
                `Selection saved to ${result.result_path || "test_grab_result.json"}.`,
                100,
                Array.isArray(result.results) ? result.results : []
            );
        } else {
            await refreshStoreMarkup({ cacheBust: true });
            showRecipeQuantityUpdatedMessage("", "", "", "Product choice updated.");
        }
    } catch (err) {
        console.warn("Unable to select product alternative.", err);
        alert("Unable to select product alternative.");
    }

    return false;
}

function setFoodRestrictionsStatus(message, isError = false) {
    const status = document.getElementById("foodRestrictionsStatus");

    if (status) {
        status.textContent = message || "";
        status.classList.toggle("error", Boolean(isError));
    }
}

function addFoodRuleRow(section, rule = {}) {
    const list = document.querySelector(`[data-food-rules-list="${section}"]`);

    if (!list) {
        return false;
    }

    list.appendChild(buildFoodRuleRow(section, rule));
    return false;
}

function buildFoodRuleRow(section, rule = {}) {
    const row = document.createElement("div");
    row.className = "food-restriction-edit-row";
    row.dataset.foodRuleRow = "1";

    const label = rule.label || "";
    const terms = Array.isArray(rule.terms)
        ? rule.terms.join(", ")
        : (rule.terms || "");
    const ariaLabel = section === "require"
        ? "Remove required food rule"
        : "Remove avoid food rule";

    row.innerHTML = `
        <label>
            <span>Label</span>
            <input type="text" data-food-rule-label value="${escapeAttribute(label)}">
        </label>
        <label>
            <span>Terms</span>
            <textarea rows="2" data-food-rule-terms>${escapeHtml(terms)}</textarea>
        </label>
        <button type="button"
                class="food-restriction-delete-btn"
                onclick="removeFoodRuleRow(this)"
                aria-label="${escapeAttribute(ariaLabel)}">
            X
        </button>
    `;

    return row;
}

function removeFoodRuleRow(button) {
    const row = button ? button.closest("[data-food-rule-row]") : null;

    if (row) {
        row.remove();
        setFoodRestrictionsStatus("Unsaved changes.");
    }

    return false;
}

function collectFoodRestrictions() {
    const rules = {
        require: [],
        avoid: [],
    };

    document.querySelectorAll("[data-food-rules-list]").forEach(list => {
        const section = list.dataset.foodRulesList;

        if (!rules[section]) {
            return;
        }

        list.querySelectorAll("[data-food-rule-row]").forEach(row => {
            const labelInput = row.querySelector("[data-food-rule-label]");
            const termsInput = row.querySelector("[data-food-rule-terms]");
            const label = labelInput ? labelInput.value.trim() : "";
            const terms = splitFoodRestrictionTerms(termsInput ? termsInput.value : "");

            if (label && terms.length) {
                rules[section].push({ label, terms });
            }
        });
    });

    return rules;
}

function splitFoodRestrictionTerms(value) {
    const seen = new Set();

    return String(value || "")
        .split(/[,;\n]+/)
        .map(term => term.trim().toLowerCase().replace(/\s+/g, " "))
        .filter(term => {
            if (!term || seen.has(term)) {
                return false;
            }

            seen.add(term);
            return true;
        });
}

async function saveFoodRestrictions(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form ? form.querySelector(".food-restrictions-save-btn") : null;
    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Saving...";
    }

    setFoodRestrictionsStatus("Saving food restrictions...");

    try {
        const response = await fetch("/api/food_rules", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({
                food_rules: collectFoodRestrictions(),
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to save food restrictions.");
        }

        await refreshStoreMarkup({ cacheBust: true });
        showRecipeQuantityUpdatedMessage("", "", "", "Food restrictions saved.");
    } catch (err) {
        console.warn("Unable to save food restrictions.", err);
        setFoodRestrictionsStatus(err.message || "Unable to save food restrictions.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Save Food Restrictions";
        }
    }

    return false;
}

async function addFoodRestrictionsWithChatGPT(button) {
    const promptInput = document.getElementById("foodRestrictionsPrompt");
    const prompt = promptInput ? promptInput.value.trim() : "";
    const originalText = button ? button.textContent : "";

    if (!prompt) {
        setFoodRestrictionsStatus("Enter a food restriction prompt.", true);
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "Adding...";
    }

    setFoodRestrictionsStatus("Asking ChatGPT...");

    try {
        const response = await fetch("/api/food_rules/suggest", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({
                prompt,
                food_rules: collectFoodRestrictions(),
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to add food restrictions.");
        }

        if (promptInput) {
            promptInput.value = "";
        }

        await refreshStoreMarkup({ cacheBust: true });
        showRecipeQuantityUpdatedMessage("", "", "", "Food restrictions added.");
    } catch (err) {
        console.warn("Unable to add food restrictions with ChatGPT.", err);
        setFoodRestrictionsStatus(err.message || "Unable to add food restrictions.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Add with ChatGPT";
        }
    }

    return false;
}

let activeRulesEditorSection = "";

function rulesEditorData() {
    const script = document.getElementById("rulesEditorData");

    if (!script) {
        return {
            home_address: {},
            available_stores: [],
            enabled_stores: [],
            rules_display: {},
            food_rules: { require: [], avoid: [] },
        };
    }

    try {
        return JSON.parse(script.textContent || "{}");
    } catch (err) {
        console.warn("Unable to parse rules editor data.", err);
        return {
            home_address: {},
            available_stores: [],
            enabled_stores: [],
            rules_display: {},
            food_rules: { require: [], avoid: [] },
        };
    }
}

function openRulesEditor(section) {
    const modal = document.getElementById("rulesEditorModal");
    const title = document.getElementById("rulesEditorTitle");
    const fields = document.getElementById("rulesEditorFields");

    if (!modal || !title || !fields) {
        return false;
    }

    activeRulesEditorSection = section;
    setRulesEditorStatus("");

    const data = rulesEditorData();
    const titles = {
        home_stores: "Edit Home And Stores",
        best_product_ranking: "Edit Best Product Ranking",
        saved_product_choices: "Edit Saved Product Choices",
        food_restrictions: "Edit Food Restriction Rules",
    };

    title.textContent = titles[section] || "Edit Rules";

    if (section === "home_stores") {
        renderRulesHomeStoresEditor(fields, data);
    } else if (section === "food_restrictions") {
        renderRulesFoodRestrictionsEditor(fields, data.food_rules || { require: [], avoid: [] });
    } else {
        const display = data.rules_display || {};
        const rows = display[section] && Array.isArray(display[section].rows)
            ? display[section].rows
            : [];
        renderRulesTextRowsEditor(fields, rows);
    }

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    return false;
}

function closeRulesEditor() {
    const modal = document.getElementById("rulesEditorModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
    }

    activeRulesEditorSection = "";
}

function setRulesEditorStatus(message, isError = false) {
    const status = document.getElementById("rulesEditorStatus");

    if (status) {
        status.textContent = message || "";
        status.classList.toggle("error", Boolean(isError));
    }
}

function renderRulesHomeStoresEditor(container, data) {
    const address = data.home_address || {};
    const stores = Array.isArray(data.available_stores) ? data.available_stores : [];
    const enabledStores = new Set(Array.isArray(data.enabled_stores) ? data.enabled_stores : []);
    const display = data.rules_display || {};
    const section = display.home_stores || {};
    const rows = Array.isArray(section.rows) ? section.rows : [];

    container.innerHTML = `
        <section class="rules-editor-section">
            <h3>Home Address</h3>
            <div class="rules-editor-address-grid">
                ${rulesAddressInput("street", "Street", address.street)}
                ${rulesAddressInput("apartment", "Apartment", address.apartment)}
                ${rulesAddressInput("city", "City", address.city)}
                ${rulesAddressInput("county", "County", address.county)}
                ${rulesAddressInput("state", "State", address.state)}
                ${rulesAddressInput("zip", "ZIP", address.zip)}
                ${rulesAddressInput("country", "Country", address.country)}
            </div>
        </section>
        <section class="rules-editor-section">
            <h3>Enabled Stores</h3>
            <div class="rules-editor-store-grid">
                ${stores.map(store => `
                    <label class="rules-editor-store-option">
                        <input type="checkbox"
                               data-rules-store-key="${escapeAttribute(store.key || "")}"
                               ${enabledStores.has(store.key) ? "checked" : ""}>
                        <span>${escapeHtml(store.label || store.key || "Store")}</span>
                    </label>
                `).join("")}
            </div>
        </section>
        <section class="rules-editor-section">
            <div class="rules-editor-section-heading">
                <h3>Section Text</h3>
            </div>
            <div id="rulesEditorRows" class="rules-editor-row-list"></div>
        </section>
    `;

    const rowsContainer = container.querySelector("#rulesEditorRows");
    rows.forEach(row => addRulesTextRow(row, rowsContainer, false));
}

function rulesAddressInput(field, label, value) {
    return `
        <label>
            <span>${escapeHtml(label)}</span>
            <input type="text"
                   data-rules-address-field="${escapeAttribute(field)}"
                   value="${escapeAttribute(value || "")}">
        </label>
    `;
}

function renderRulesTextRowsEditor(container, rows) {
    container.innerHTML = `
        <section class="rules-editor-section">
            <div class="rules-editor-section-heading">
                <h3>Rules</h3>
                <button type="button" class="rules-editor-small-btn" onclick="addRulesTextRow()">Add Rule</button>
            </div>
            <div id="rulesEditorRows" class="rules-editor-row-list"></div>
        </section>
    `;

    rows.forEach(row => addRulesTextRow(row));
}

function addRulesTextRow(row = {}, container = null, removable = true) {
    const rowsContainer = container || document.getElementById("rulesEditorRows");

    if (!rowsContainer) {
        return false;
    }

    const item = document.createElement("div");
    item.className = "rules-editor-row";
    item.dataset.rulesTextRow = "1";
    item.innerHTML = `
        <label>
            <span>Label</span>
            <input type="text"
                   data-rules-row-key
                   value="${escapeAttribute(row.key || "")}"
                   hidden>
            <input type="text"
                   data-rules-row-label
                   value="${escapeAttribute(row.label || "")}">
        </label>
        <label>
            <span>Text</span>
            <textarea rows="3" data-rules-row-value>${escapeHtml(row.value || "")}</textarea>
        </label>
        ${removable ? `
            <button type="button"
                    class="rules-editor-delete-btn"
                    onclick="removeRulesEditorRow(this)"
                    aria-label="Remove rule">
                X
            </button>
        ` : ""}
    `;
    rowsContainer.appendChild(item);
    return false;
}

function removeRulesEditorRow(button) {
    const row = button ? button.closest(".rules-editor-row, .rules-editor-food-row") : null;

    if (row) {
        row.remove();
    }

    return false;
}

function renderRulesFoodRestrictionsEditor(container, foodRules) {
    foodRules = foodRules || { require: [], avoid: [] };
    container.innerHTML = `
        <section class="rules-editor-section">
            <div class="rules-editor-section-heading">
                <h3>Required</h3>
                <button type="button" class="rules-editor-small-btn" onclick="addRulesFoodRuleRow('require')">Add Required</button>
            </div>
            <div id="rulesFoodRequireRows" class="rules-editor-row-list" data-rules-food-list="require"></div>
        </section>
        <section class="rules-editor-section">
            <div class="rules-editor-section-heading">
                <h3>Avoid</h3>
                <button type="button" class="rules-editor-small-btn" onclick="addRulesFoodRuleRow('avoid')">Add Avoid</button>
            </div>
            <div id="rulesFoodAvoidRows" class="rules-editor-row-list" data-rules-food-list="avoid"></div>
        </section>
    `;

    (foodRules.require || []).forEach(rule => addRulesFoodRuleRow("require", rule));
    (foodRules.avoid || []).forEach(rule => addRulesFoodRuleRow("avoid", rule));
}

function addRulesFoodRuleRow(section, rule = {}) {
    const list = document.querySelector(`[data-rules-food-list="${section}"]`);

    if (!list) {
        return false;
    }

    const row = document.createElement("div");
    row.className = "rules-editor-food-row";
    row.dataset.rulesFoodRow = "1";
    row.innerHTML = `
        <label>
            <span>Label</span>
            <input type="text"
                   data-rules-food-label
                   value="${escapeAttribute(rule.label || "")}">
        </label>
        <label>
            <span>Terms</span>
            <textarea rows="2" data-rules-food-terms>${escapeHtml(Array.isArray(rule.terms) ? rule.terms.join(", ") : (rule.terms || ""))}</textarea>
        </label>
        <button type="button"
                class="rules-editor-delete-btn"
                onclick="removeRulesEditorRow(this)"
                aria-label="Remove food rule">
            X
        </button>
    `;
    list.appendChild(row);
    return false;
}

function collectRulesTextRows() {
    return [...document.querySelectorAll("#rulesEditorRows [data-rules-text-row]")]
        .map(row => {
            const key = row.querySelector("[data-rules-row-key]");
            const label = row.querySelector("[data-rules-row-label]");
            const value = row.querySelector("[data-rules-row-value]");

            return {
                key: key ? key.value.trim() : "",
                label: label ? label.value.trim() : "",
                value: value ? value.value.trim() : "",
            };
        })
        .filter(row => row.label || row.value);
}

function collectRulesHomeStoresPayload() {
    const address = {};
    document.querySelectorAll("[data-rules-address-field]").forEach(input => {
        address[input.dataset.rulesAddressField] = input.value.trim();
    });

    const enabledStores = [...document.querySelectorAll("[data-rules-store-key]:checked")]
        .map(input => input.dataset.rulesStoreKey)
        .filter(Boolean);

    return {
        address,
        enabled_stores: enabledStores,
        rows: collectRulesTextRows(),
    };
}

function collectRulesFoodRestrictions() {
    const rules = {
        require: [],
        avoid: [],
    };

    document.querySelectorAll("[data-rules-food-list]").forEach(list => {
        const section = list.dataset.rulesFoodList;

        if (!rules[section]) {
            return;
        }

        list.querySelectorAll("[data-rules-food-row]").forEach(row => {
            const label = row.querySelector("[data-rules-food-label]");
            const terms = row.querySelector("[data-rules-food-terms]");
            const item = {
                label: label ? label.value.trim() : "",
                terms: splitFoodRestrictionTerms(terms ? terms.value : ""),
            };

            if (item.label && item.terms.length) {
                rules[section].push(item);
            }
        });
    });

    return rules;
}

async function saveRulesEditor(event) {
    event.preventDefault();
    const button = event.currentTarget ? event.currentTarget.querySelector(".rules-editor-save") : null;
    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Saving...";
    }

    setRulesEditorStatus("Saving changes...");

    try {
        let response;

        if (activeRulesEditorSection === "home_stores") {
            response = await fetch("/api/rules_display/home_stores", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify(collectRulesHomeStoresPayload()),
            });
        } else if (activeRulesEditorSection === "food_restrictions") {
            response = await fetch("/api/food_rules", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    food_rules: collectRulesFoodRestrictions(),
                }),
            });
        } else {
            response = await fetch(`/api/rules_display/${encodeURIComponent(activeRulesEditorSection)}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                },
                body: JSON.stringify({
                    rows: collectRulesTextRows(),
                }),
            });
        }

        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to save rules.");
        }

        closeRulesEditor();
        await refreshStoreMarkup({ cacheBust: true });
        showRecipeQuantityUpdatedMessage("", "", "", "Rules saved.");
    } catch (err) {
        console.warn("Unable to save rules.", err);
        setRulesEditorStatus(err.message || "Unable to save rules.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Save Changes";
        }
    }

    return false;
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
        const response = await fetch(formActionUrl(form), {
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
    const card = content.closest(".app-card");
    localStorage.setItem(`card-collapse:${key}`, isCollapsed ? "collapsed" : "expanded");

    if (card) {
        card.classList.toggle("card-collapsed", isCollapsed);
    }

    if (icon) {
        icon.textContent = isCollapsed ? "Show v" : "Hide ^";
    }

    if (toggle) {
        toggle.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    }

    window.setTimeout(initStoreLocationMaps, 0);
    scheduleAddStoreStickyVisibilityUpdate();

    if (key === "store-options" && isCollapsed) {
        window.setTimeout(scrollStoreOptionsIntoView, 0);
    }
}

function scrollStoreOptionsIntoView() {
    const section = document.getElementById("storeOptionsSection");

    if (!section) {
        return;
    }

    section.scrollIntoView({
        behavior: "smooth",
        block: "start",
    });
}

function cardCollapseDefaultIsCollapsed(content) {
    const mobileDefault = content.dataset.collapseMobileDefault;
    const defaultState = content.dataset.collapseDefault || "collapsed";

    if (mobileDefault && window.matchMedia && window.matchMedia("(max-width: 700px)").matches) {
        return mobileDefault === "collapsed";
    }

    return defaultState === "collapsed";
}

let storeEditReturnFocus = null;

function toggleStorePanel(panelId) {
    return openStoreEditModal(panelId);
}

function openStoreEditModal(formId, trigger) {
    const form = document.getElementById(formId);
    const backdrop = document.getElementById("storeEditModalBackdrop");

    if (!form) {
        return false;
    }

    closeStoreEditModal({ reset: true, returnFocus: false });
    storeEditReturnFocus = trigger || document.activeElement;

    if (backdrop) {
        backdrop.classList.add("open");
        backdrop.setAttribute("aria-hidden", "false");
    }

    form.classList.add("open");
    form.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    window.setTimeout(() => {
        const firstInput = form.querySelector('input[name="store_label"]');

        if (firstInput) {
            firstInput.focus();
            firstInput.select();
        }
    }, 0);

    return false;
}

function closeStoreEditModal(options = {}) {
    const form = document.querySelector(".store-edit-form.open");
    const backdrop = document.getElementById("storeEditModalBackdrop");

    if (form && options.reset) {
        resetStoreEditForm(form);
    }

    if (form) {
        form.classList.remove("open");
        form.setAttribute("aria-hidden", "true");
    }

    if (backdrop) {
        backdrop.classList.remove("open");
        backdrop.setAttribute("aria-hidden", "true");
    }

    if (!document.querySelector("#addStoreModal.open")) {
        document.body.classList.remove("modal-open");
    }

    if (options.returnFocus !== false && storeEditReturnFocus && typeof storeEditReturnFocus.focus === "function") {
        storeEditReturnFocus.focus();
    }

    storeEditReturnFocus = null;
}

function resetStoreEditForm(form) {
    form.reset();
    const passwordInput = form.querySelector('input[name="store_password"]');
    const passwordToggle = form.querySelector(".password-toggle-btn");

    if (passwordInput) {
        passwordInput.type = "password";
    }

    if (passwordToggle) {
        passwordToggle.textContent = "Show";
    }
}

function syncStoreEditFormDefaults(form) {
    form.querySelectorAll("input").forEach(input => {
        input.defaultValue = input.value;
    });
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
        const card = content.closest(".app-card");

        content.classList.toggle("collapsed", shouldCollapse);

        if (card) {
            card.classList.toggle("card-collapsed", shouldCollapse);
        }

        if (icon) {
            icon.textContent = shouldCollapse ? "Show v" : "Hide ^";
        }

        if (toggle) {
            toggle.setAttribute("aria-expanded", shouldCollapse ? "false" : "true");
        }
    });

    scheduleAddStoreStickyVisibilityUpdate();
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
    saveOpenStorePanels(new Set());
    document.querySelectorAll(".store-edit-form.open").forEach(form => {
        form.classList.remove("open");
        form.setAttribute("aria-hidden", "true");
    });
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

function storeOptionsDisplayBodyClass(kind) {
    return kind === "maps" ? "store-maps-hidden" : "store-addresses-hidden";
}

function storeOptionsDisplayStorageKey(kind) {
    return kind === "maps" ? "store-options-show-maps" : "store-options-show-addresses";
}

function setStoreOptionsDisplay(kind, shouldShow, options = {}) {
    const bodyClass = storeOptionsDisplayBodyClass(kind);

    document.body.classList.toggle(bodyClass, !shouldShow);
    document.querySelectorAll(`[data-store-display-toggle="${kind}"]`).forEach(button => {
        button.classList.toggle("active", shouldShow);
        button.setAttribute("aria-pressed", shouldShow ? "true" : "false");
    });

    if (options.persist) {
        localStorage.setItem(storeOptionsDisplayStorageKey(kind), shouldShow ? "1" : "0");
    }

    if (kind === "maps" && shouldShow) {
        window.setTimeout(invalidateStoreLocationMaps, 0);
    }
}

function toggleStoreOptionsDisplay(kind) {
    const bodyClass = storeOptionsDisplayBodyClass(kind);
    const shouldShow = document.body.classList.contains(bodyClass);

    setStoreOptionsDisplay(kind, shouldShow, { persist: true });
}

function restoreStoreOptionsDisplaySettings() {
    ["addresses", "maps"].forEach(kind => {
        const savedValue = localStorage.getItem(storeOptionsDisplayStorageKey(kind));
        setStoreOptionsDisplay(kind, savedValue === null ? true : savedValue === "1");
    });
}

function setActiveStoreIconMode(mode, options = {}) {
    const allowedModes = new Set(["store", "map", "activation"]);
    const nextMode = allowedModes.has(mode) ? mode : "store";

    document.body.classList.toggle("active-store-map-mode", nextMode === "map");
    document.body.classList.toggle("active-store-activation-mode", nextMode === "activation");
    document.querySelectorAll("[data-active-store-mode-toggle]").forEach(button => {
        const active = button.dataset.activeStoreModeToggle === nextMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    document.querySelectorAll("[data-active-store-heading-label]").forEach(label => {
        label.textContent = nextMode === "activation" ? "All stores" : "Active stores";
    });
    document.querySelectorAll(".active-store-card").forEach(card => {
        const storeTitle = card.dataset.storeTitle || card.getAttribute("title") || "";
        const mapTitle = card.dataset.mapTitle || storeTitle;
        const activationTitle = card.dataset.activationTitle || storeTitle;
        const title = nextMode === "activation"
            ? activationTitle
            : (nextMode === "map" ? mapTitle : storeTitle);
        const storeUrl = card.dataset.storeUrl || card.getAttribute("href") || "";

        if (storeUrl) {
            card.setAttribute("href", storeUrl);
        }
        if (title) {
            card.setAttribute("title", title);
            card.setAttribute("aria-label", title);
        }
    });

    if (options.persist) {
        localStorage.setItem("active-store-icon-mode", nextMode);
    }

    filterActiveStores();
}

function restoreActiveStoreIconMode() {
    setActiveStoreIconMode(localStorage.getItem("active-store-icon-mode") || "store");
}

function normalizeActiveStoreSearchText(value) {
    return String(value || "").trim().toLowerCase();
}

function activeStoreCardName(card) {
    const name = card ? card.querySelector(".active-store-name") : null;

    return name ? name.textContent : "";
}

function activeStoreCardIsEligibleForSearch(card) {
    if (document.body.classList.contains("active-store-activation-mode")) {
        return true;
    }

    return card && card.dataset.storeActive === "true";
}

function filterActiveStores(value) {
    const input = document.getElementById("activeStoreSearchInput");
    const query = normalizeActiveStoreSearchText(value !== undefined ? value : (input ? input.value : ""));
    let visibleCount = 0;
    const storeShelf = document.querySelector(".active-store-list");

    if (input && value !== undefined && input.value !== value) {
        input.value = value;
    }

    document.querySelectorAll(".active-store-card").forEach(card => {
        const storeName = normalizeActiveStoreSearchText(activeStoreCardName(card));
        const matchesSearch = !query || storeName.includes(query);
        const eligible = activeStoreCardIsEligibleForSearch(card);

        card.classList.toggle("active-store-search-hidden", !matchesSearch);

        if (matchesSearch && eligible) {
            visibleCount += 1;
        }
    });

    document.querySelectorAll(".active-store-search-empty").forEach(empty => {
        empty.hidden = !query || visibleCount > 0;
    });

    if (value !== undefined && storeShelf) {
        storeShelf.scrollTo({ left: 0, behavior: "smooth" });
    }
}

function visibleActiveStoreCards() {
    return Array.from(document.querySelectorAll(".active-store-card"))
        .filter(card => card.offsetParent !== null);
}

function scrollActiveStoreShelf(direction) {
    const shelf = document.querySelector(".active-store-list");

    if (!shelf) {
        return false;
    }

    const cards = visibleActiveStoreCards();
    const firstCard = cards.length ? cards[0] : null;
    const gap = parseFloat(window.getComputedStyle(shelf).columnGap || "12") || 12;
    const cardWidth = firstCard ? firstCard.getBoundingClientRect().width + gap : 94;
    const distance = Math.max(cardWidth * 2, shelf.clientWidth * 0.72);

    shelf.scrollBy({
        left: direction * distance,
        behavior: "smooth",
    });

    shelf.focus({ preventScroll: true });
    return false;
}

function storeSortName(element, selector) {
    const name = element ? element.querySelector(selector) : null;

    return normalizeActiveStoreSearchText(name ? name.textContent : "");
}

function sortStoreChildren(container, itemClass, nameSelector) {
    if (!container) {
        return 0;
    }

    const children = Array.from(container.children);
    const items = children.filter(child => child.classList.contains(itemClass));
    const trailing = children.filter(child => !child.classList.contains(itemClass));

    items
        .sort((a, b) => storeSortName(a, nameSelector).localeCompare(
            storeSortName(b, nameSelector),
            undefined,
            { numeric: true, sensitivity: "base" }
        ))
        .forEach(item => container.appendChild(item));
    trailing.forEach(item => container.appendChild(item));

    return items.length;
}

function sortStoreOptionsList(options = {}) {
    sortStoreChildren(document.querySelector(".store-manager-list"), "store-manager-row", ".store-manager-label");
    sortStoreChildren(document.querySelector(".active-store-list"), "active-store-card", ".active-store-name");

    if (options.persist !== false) {
        localStorage.setItem("store-options-sort", "name");
    }

    filterActiveStores();
    window.setTimeout(invalidateStoreLocationMaps, 0);
    return false;
}

function restoreStoreOptionsListSort() {
    if (localStorage.getItem("store-options-sort") === "name") {
        sortStoreOptionsList({ persist: false });
    }
}

function openActiveStoreIcon(link, event) {
    if (document.body.classList.contains("active-store-activation-mode")) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        toggleStoreActivationFromCard(link);
        return false;
    }

    if (!document.body.classList.contains("active-store-map-mode")) {
        return true;
    }

    if (!link || !link.dataset.googleMapsUrl) {
        return true;
    }

    return openStoreAddressMap(link, event);
}

function findStoreEnabledInput(storeKey) {
    return Array.from(document.querySelectorAll('input[form="store-options-form"][name="enabled_stores"]'))
        .find(input => input.value === storeKey) || null;
}

function updateActiveStoreCardActivationState(card, isActive) {
    if (!card) {
        return;
    }

    const label = card.querySelector(".active-store-name");
    const storeName = label ? label.textContent.trim() : "store";
    const status = card.querySelector(".active-store-status");

    card.dataset.storeActive = isActive ? "true" : "false";
    card.classList.toggle("active-store-inactive", !isActive);
    card.setAttribute("aria-pressed", isActive ? "true" : "false");
    card.dataset.activationTitle = `${isActive ? "Deactivate" : "Activate"} ${storeName}`;

    if (status) {
        status.textContent = isActive ? "Active" : "Inactive";
    }

    if (document.body.classList.contains("active-store-activation-mode")) {
        card.setAttribute("title", card.dataset.activationTitle);
        card.setAttribute("aria-label", card.dataset.activationTitle);
    }

    filterActiveStores();
}

async function toggleStoreActivationFromCard(card) {
    if (!card || card.classList.contains("saving")) {
        return false;
    }

    const storeKey = card.dataset.storeKey || "";
    const input = findStoreEnabledInput(storeKey);

    if (!input) {
        return false;
    }

    const nextChecked = !input.checked;
    input.checked = nextChecked;
    updateActiveStoreCardActivationState(card, nextChecked);
    card.classList.add("saving");
    card.setAttribute("aria-busy", "true");

    const saved = await saveStoreToggle(input);

    if (!saved) {
        input.checked = !nextChecked;
        updateActiveStoreCardActivationState(card, !nextChecked);
        card.classList.remove("saving");
        card.removeAttribute("aria-busy");
    }

    return saved;
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
        input.dataset.lastSavedValue = String(getRecipeMultiplierValue(input));

        if (input.tagName !== "SELECT") {
            input.addEventListener("input", () => {
                normalizeRecipeQuantityInput(input);
            });
        }

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
    const multiplier = getRecipeMultiplierValue(input);
    input.value = String(multiplier);
    return multiplier;
}

function getRecipeMultiplierValue(input) {
    return parseRecipeScaleMultiplier(input ? input.value : null) || 1;
}

function getRecipeMultiplierSavedValue(input) {
    return parseRecipeScaleMultiplier(
        input.dataset.lastSavedValue
            || input.defaultValue
            || input.getAttribute("value")
            || "1"
    ) || 1;
}

function recipeMultipliersMatch(left, right) {
    return Math.abs((parseRecipeScaleMultiplier(left) || 1) - (parseRecipeScaleMultiplier(right) || 1)) < 0.000001;
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
            const nextQty = getRecipeMultiplierValue(input);
            const savedQty = getRecipeMultiplierSavedValue(input);

            return !recipeMultipliersMatch(nextQty, savedQty);
        });

    if (!inputs.length) {
        showRecipeQuantityUpdatedMessage("", "", "", "No recipe amounts changed.");
        return false;
    }

    const progressItems = buildRecipeQuantityProgressItems(inputs);
    showRecipeQuantityProgressOverlay(progressItems);

    if (button) {
        button.disabled = true;
        button.textContent = "Saving...";
    }

    let failedCount = 0;

    try {
        for (const [index, input] of inputs.entries()) {
            updateRecipeQuantityProgressItem(index, "running", "Updating recipe amount...");

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
                    : "All recipe amounts updated."
            );
        } catch (refreshErr) {
            console.warn("Unable to refresh recipe amounts in the background.", refreshErr);
            setRecipeQuantityProgressSummary("Recipe amounts saved, but the page refresh failed.");
        }

        showRecipeQuantityUpdatedMessage(
            "",
            "",
            "",
            failedCount ? "Some recipe amounts failed." : "Recipe amounts updated."
        );
    } catch (err) {
        console.warn("Unable to save recipe amounts.", err);
        setRecipeQuantityProgressSummary("Unable to save recipe amounts.");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Save";
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
        const previousQty = formatRecipeScaleMultiplierLabel(getRecipeMultiplierSavedValue(input));
        const nextQty = formatRecipeScaleMultiplierLabel(getRecipeMultiplierValue(input));

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
                    <h2 id="recipeQtyProgressTitle">Updating Recipe Amounts</h2>
                    <button type="button" class="recipe-qty-progress-close" onclick="hideRecipeQuantityProgressOverlay()">Hide</button>
                </div>
                <div id="recipeQtyProgressSummary" class="recipe-qty-progress-summary">Starting recipe amount updates...</div>
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
                    <div class="recipe-qty-progress-qty">${escapeHtml(item.previousQty)} -> ${escapeHtml(item.nextQty)}</div>
                </div>
                <div class="recipe-qty-progress-status waiting">Waiting</div>
            </div>
        `).join("");
    }

    setRecipeQuantityProgressSummary("Starting recipe amount updates...");
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
let recipeEditScalingOptions = [];
let activeFoodReviewRow = null;
let activeFoodReviewAlternatives = [];

async function openRecipeEditor(button, options = {}) {
    const url = button ? button.dataset.recipeUrl || "" : "";
    const modal = document.getElementById("recipeEditModal");
    const shouldScrollToFoodReview = options === true || Boolean(options.scrollToFoodReview);
    const targetIngredient = options && typeof options === "object"
        ? String(options.ingredient || options.scrollToIngredient || "").trim()
        : "";

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
        } else if (targetIngredient) {
            await waitForNextPaint();
            scrollRecipeEditorToIngredient(targetIngredient);
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

    window.location.reload();
}

function populateRecipeEditor(recipe, originalUrl) {
    recipeEditOriginalSnapshot = normalizeRecipeEditorSnapshot({
        display_name: recipe.display_name || "",
        recipe_title: recipe.recipe_title || "",
        source_url: recipe.source_url || originalUrl,
        quantity: recipe.quantity || "1",
        servings: recipe.servings || "",
        scaling: recipe.scaling || {},
        ingredients: recipe.ingredients || [],
        equipment: recipe.equipment || [],
        instructions: recipe.instructions || [],
        nutrition: recipe.nutrition || [],
    });

    setValue("recipeEditOriginalUrl", originalUrl);
    setValue("recipeEditDisplayName", recipe.display_name || "");
    setValue("recipeEditTitleInput", recipe.recipe_title || "");
    setValue("recipeEditSourceUrl", recipe.source_display_url || recipe.source_url || originalUrl);
    setValue("recipeEditQuantity", recipe.quantity || "1");
    setValue("recipeEditServings", recipe.servings || "");
    populateRecipeScalingControls(recipe.scaling || {}, recipe.servings || "");
    updateRecipeEditorPdfControls(recipe);

    const sourceInput = document.getElementById("recipeEditSourceUrl");
    if (sourceInput) {
        sourceInput.dataset.canonicalSourceUrl = recipe.source_url || originalUrl;
        sourceInput.dataset.displaySourceUrl = recipe.source_display_url || "";
    }

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

function updateRecipeEditorPdfControls(recipe) {
    const pdfPathInput = document.getElementById("recipeEditPdfPath");
    const pdfButton = document.getElementById("recipeEditPdfButton");
    const deletePdfButton = document.getElementById("recipeEditDeletePdfButton");
    const sourceUrl = recipe && recipe.source_url ? recipe.source_url : "";
    const pdfPath = recipe && recipe.pdf_path ? recipe.pdf_path : "";
    const hasPdf = Boolean(recipe && recipe.pdf_available && sourceUrl);

    if (pdfPathInput) {
        pdfPathInput.value = pdfPath;
    }

    if (pdfButton) {
        pdfButton.hidden = !hasPdf;
        pdfButton.href = hasPdf ? recipeArchivePdfUrl(sourceUrl) : "#";
    }

    if (deletePdfButton) {
        deletePdfButton.hidden = !hasPdf;
    }
}

function recipeArchivePdfUrl(sourceUrl) {
    return `/recipe_archive_pdf?url=${encodeURIComponent(sourceUrl || "")}`;
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

function populateRecipeScalingControls(scaling = {}, servings = "") {
    const select = document.getElementById("recipeEditScaleMultiplier");

    if (!select) {
        return;
    }

    const options = normalizeRecipeScalingOptions(
        scaling.available_multipliers
            || scaling.multipliers
            || scaling.scaling_multipliers
            || []
    );
    const selectedMultiplier = parseRecipeScaleMultiplier(
        scaling.selected_multiplier !== undefined
            ? scaling.selected_multiplier
            : scaling.scaling_multiplier
    ) || 1;
    const baseServings = String(scaling.base_servings || servings || "").trim();

    recipeEditScalingOptions = options;
    select.innerHTML = options
        .map(option => {
            const value = String(option.value);
            const selected = Math.abs(option.value - selectedMultiplier) < 0.000001 ? " selected" : "";
            return `<option value="${escapeAttribute(value)}"${selected}>${escapeHtml(option.label)}</option>`;
        })
        .join("");
    select.dataset.baseServings = baseServings;

    const servingsInput = document.getElementById("recipeEditServings");
    if (servingsInput) {
        servingsInput.dataset.baseServings = baseServings;
    }
}

function normalizeRecipeScalingOptions(options) {
    const normalized = new Map();

    (Array.isArray(options) ? options : []).forEach(option => {
        const rawValue = typeof option === "object" && option !== null
            ? (option.value !== undefined ? option.value : option.multiplier)
            : option;
        const label = typeof option === "object" && option !== null
            ? (option.label || option.text || option.name || "")
            : "";
        const multiplier = parseRecipeScaleMultiplier(rawValue) || parseRecipeScaleMultiplier(label);

        if (!multiplier) {
            return;
        }

        normalized.set(String(multiplier), {
            label: formatRecipeScaleMultiplierLabel(multiplier),
            value: multiplier,
        });
    });

    if (!normalized.size) {
        [
            { label: "1/2x", value: 0.5 },
            { label: "1x", value: 1 },
            { label: "2x", value: 2 },
            { label: "3x", value: 3 },
        ].forEach(option => normalized.set(String(option.value), option));
    }

    if (!normalized.has("1")) {
        normalized.set("1", { label: "1x", value: 1 });
    }

    return [...normalized.values()].sort((a, b) => a.value - b.value);
}

function parseRecipeScaleMultiplier(value) {
    if (value === null || value === undefined) {
        return null;
    }

    if (typeof value === "number") {
        return value > 0 ? value : null;
    }

    let text = String(value || "").trim().toLowerCase().replace("×", "x");
    const xMatch = text.match(/(\d+(?:\.\d+)?|\d+\s*\/\s*\d+)\s*x\b/);

    if (xMatch) {
        text = xMatch[1];
    } else {
        text = text.replace(/x$/, "").trim();
    }

    text = text.replace(/\s+/g, "");
    const fractionMatch = text.match(/^(\d+)\/(\d+)$/);

    if (fractionMatch) {
        const denominator = Number(fractionMatch[2]);
        return denominator ? Number(fractionMatch[1]) / denominator : null;
    }

    const multiplier = Number(text);
    return Number.isFinite(multiplier) && multiplier > 0 ? multiplier : null;
}

function formatRecipeScaleMultiplierLabel(value) {
    const multiplier = parseRecipeScaleMultiplier(value) || 1;

    if (Math.abs(multiplier - 0.5) < 0.000001) {
        return "1/2x";
    }

    if (Number.isInteger(multiplier)) {
        return `${multiplier}x`;
    }

    return `${multiplier}x`;
}

function applyRecipeScaleMultiplier(select) {
    const multiplier = parseRecipeScaleMultiplier(select ? select.value : null) || 1;
    const servingsInput = document.getElementById("recipeEditServings");

    if (servingsInput) {
        const baseServings = (
            select && select.dataset.baseServings
                ? select.dataset.baseServings
                : servingsInput.dataset.baseServings || servingsInput.value
        );

        if (!servingsInput.dataset.baseServings) {
            servingsInput.dataset.baseServings = String(baseServings || "").trim();
        }

        servingsInput.value = scaleServingsForDisplay(baseServings, multiplier);
    }

    document.querySelectorAll("#recipeEditIngredients .recipe-edit-ingredient-row")
        .forEach(row => applyRecipeScaleToIngredientRow(row, multiplier));
}

function applyRecipeScaleToIngredientRow(row, multiplier) {
    const quantityInput = row.querySelector('[data-field="quantity"]');
    const unitInput = row.querySelector('[data-field="unit"]');
    const baseQuantityInput = row.querySelector('[data-field="base_quantity"]');
    const baseUnitInput = row.querySelector('[data-field="base_unit"]');

    if (quantityInput && baseQuantityInput) {
        const baseQuantity = baseQuantityInput.value || quantityInput.value.trim();

        if (!baseQuantityInput.value) {
            baseQuantityInput.value = baseQuantity;
        }

        quantityInput.value = scaleQuantityForDisplay(baseQuantity, multiplier);
    }

    if (unitInput && baseUnitInput) {
        const baseUnit = baseUnitInput.value || unitInput.value.trim();

        if (!baseUnitInput.value) {
            baseUnitInput.value = baseUnit;
        }

        unitInput.value = baseUnit;
    }
}

function collectRecipeScalingPayload() {
    const select = document.getElementById("recipeEditScaleMultiplier");
    const servingsInput = document.getElementById("recipeEditServings");
    const selectedMultiplier = parseRecipeScaleMultiplier(select ? select.value : null) || 1;
    const baseServings = (
        select && select.dataset.baseServings
            ? select.dataset.baseServings
            : servingsInput && servingsInput.dataset.baseServings
                ? servingsInput.dataset.baseServings
                : servingsInput
                    ? servingsInput.value.trim()
                    : ""
    );

    return {
        selected_multiplier: selectedMultiplier,
        base_multiplier: 1,
        base_servings: baseServings,
        available_multipliers: recipeEditScalingOptions.length
            ? recipeEditScalingOptions
            : normalizeRecipeScalingOptions([]),
    };
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

function scrollRecipeEditorToIngredient(ingredientName) {
    const targetKey = normalizeIngredientJumpKey(ingredientName);

    if (!targetKey) {
        return false;
    }

    const rows = [...document.querySelectorAll("#recipeEditIngredients .recipe-edit-ingredient-row")];
    const row = rows.find(candidate => {
        const ingredientInput = candidate.querySelector('[data-field="ingredient"]');
        const originalTextInput = candidate.querySelector('[data-field="original_text"]');
        const ingredientKey = normalizeIngredientJumpKey(ingredientInput ? ingredientInput.value : "");
        const originalTextKey = normalizeIngredientJumpKey(originalTextInput ? originalTextInput.value : "");

        return (
            (ingredientKey && ingredientKey === targetKey)
            || (originalTextKey && originalTextKey === targetKey)
            || (ingredientKey && ingredientKey.includes(targetKey))
            || (ingredientKey && targetKey.includes(ingredientKey))
            || (originalTextKey && originalTextKey.includes(targetKey))
        );
    });

    if (!row) {
        setRecipeEditStatus(`Ingredient not found: ${ingredientName}`, true);
        return false;
    }

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
                ingredientInput.select();
            } catch (err) {
                ingredientInput.focus();
            }
        }, 250);
    }

    setTimeout(() => row.classList.remove("recipe-edit-review-target"), 3000);
    return true;
}

function normalizeIngredientJumpKey(value) {
    return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/&/g, " and ")
        .replace(/[^a-z0-9]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
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
    const baseQuantity = item.base_quantity !== undefined && item.base_quantity !== null
        ? item.base_quantity
        : item.quantity || "";
    const baseUnit = item.base_unit !== undefined && item.base_unit !== null
        ? item.base_unit
        : item.unit || "";
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
        <input type="hidden" data-field="base_quantity" value="${escapeAttribute(baseQuantity || "")}">
        <input type="hidden" data-field="base_unit" value="${escapeAttribute(baseUnit || "")}">
    `;
    wrap.appendChild(row);
    bindRecipeIngredientBaseTracking(row);
    bindRecipeIngredientFoodRuleWarning(row);
    updateRecipeIngredientFoodRuleWarning(row);
}

function bindRecipeIngredientBaseTracking(row) {
    const quantityInput = row.querySelector('[data-field="quantity"]');
    const unitInput = row.querySelector('[data-field="unit"]');

    if (quantityInput) {
        quantityInput.addEventListener("input", () => updateRecipeIngredientBaseFromManualEdit(row));
    }

    if (unitInput) {
        unitInput.addEventListener("input", () => updateRecipeIngredientBaseFromManualEdit(row));
    }
}

function updateRecipeIngredientBaseFromManualEdit(row) {
    const multiplier = currentRecipeEditScaleMultiplier();

    if (Math.abs(multiplier - 1) > 0.000001) {
        return;
    }

    const quantityInput = row.querySelector('[data-field="quantity"]');
    const unitInput = row.querySelector('[data-field="unit"]');
    const baseQuantityInput = row.querySelector('[data-field="base_quantity"]');
    const baseUnitInput = row.querySelector('[data-field="base_unit"]');

    if (quantityInput && baseQuantityInput) {
        baseQuantityInput.value = quantityInput.value.trim();
    }

    if (unitInput && baseUnitInput) {
        baseUnitInput.value = unitInput.value.trim();
    }
}

function currentRecipeEditScaleMultiplier() {
    const select = document.getElementById("recipeEditScaleMultiplier");
    return parseRecipeScaleMultiplier(select ? select.value : null) || 1;
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
    return row;
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

async function estimateRecipeNutrition(button) {
    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Estimating...";
    }

    try {
        setRecipeEditStatus("Estimating nutrition with ChatGPT...");
        const payload = collectRecipeEditorPayload();
        const response = await fetch("/api/recipe_nutrition_estimate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to estimate nutrition.");
        }

        applyEstimatedNutritionRows(data.nutrition || []);
        setRecipeEditStatus("Nutrition estimate added. Review values, then Save Recipe.");
    } catch (err) {
        console.warn("Unable to estimate nutrition.", err);
        setRecipeEditStatus(err.message || "Unable to estimate nutrition.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Estimate per serving_basis";
        }
    }

    return false;
}

function applyEstimatedNutritionRows(rows) {
    (Array.isArray(rows) ? rows : []).forEach(item => {
        if (!item || !item.key) {
            return;
        }

        setRecipeNutritionRowValue(item.key, item.value || "");
    });
}

function setRecipeNutritionRowValue(key, value) {
    const normalizedKey = normalizeNutritionKey(key);
    let row = [...document.querySelectorAll("#recipeEditNutrition .recipe-edit-nutrition-row")]
        .find(candidate => {
            const input = candidate.querySelector('[data-field="key"]');
            return input && normalizeNutritionKey(input.value) === normalizedKey;
        });

    if (!row) {
        row = addRecipeNutritionRow({ key, value: "" });
    }

    const keyInput = row.querySelector('[data-field="key"]');
    const valueInput = row.querySelector('[data-field="value"]');

    if (keyInput) {
        keyInput.value = key;
    }

    if (valueInput) {
        valueInput.value = value;
        valueInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
}

function normalizeNutritionKey(value) {
    return String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
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
        const pdfCreationReason = recipePdfCreationReasonOnSave(payload.recipe);
        const shouldCreatePdf = Boolean(pdfCreationReason);
        const progressItems = buildRecipeSaveProgressItems(payload.recipe);
        let refreshProgressIndex = progressItems.length - 1;
        let pdfProgressIndex = null;
        if (shouldCreatePdf) {
            pdfProgressIndex = refreshProgressIndex;
            progressItems.splice(refreshProgressIndex, 0, {
                label: "Recipe PDF",
                detail: pdfCreationReason === "manual_edits"
                    ? "Regenerating the manual recipe PDF from the saved edits."
                    : "Creating the PDF archive because this recipe does not have one yet.",
            });
            refreshProgressIndex += 1;
        }
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

        let recipeForEditor = data.recipe || null;
        const sourceUrl = (
            recipeForEditor && recipeForEditor.source_url
                ? recipeForEditor.source_url
                : payload.recipe.source_url || payload.original_url
        );

        if (shouldCreatePdf) {
            updateRecipeSaveProgressItem(pdfProgressIndex, "running", "Creating...");
            setRecipeEditStatus("Creating PDF...");
            const pdfData = await createRecipePdfForSource(sourceUrl);
            recipeForEditor = {
                ...(recipeForEditor || {}),
                source_url: pdfData.url || sourceUrl,
                pdf_path: pdfData.pdf_path || "",
                pdf_available: true,
            };
            updateRecipeSaveProgressItem(pdfProgressIndex, "done", "Created");
        }

        updateRecipeSaveProgressItem(refreshProgressIndex, "running", "Refreshing...");
        await refreshStoreMarkup();
        if (recipeForEditor) {
            populateRecipeEditor(recipeForEditor, recipeForEditor.source_url || sourceUrl);
        }
        updateRecipeSaveProgressItem(refreshProgressIndex, "done", "Refreshed");
        setRecipeSaveProgressSummary(
            shouldCreatePdf
                ? "Recipe saved, PDF created, and page values refreshed."
                : "Recipe saved and page values refreshed."
        );
        setRecipeEditStatus("");
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

function recipePdfCreationReasonOnSave(recipe) {
    const pdfButton = document.getElementById("recipeEditPdfButton");
    const createPdfButton = document.getElementById("recipeEditCreatePdfButton");

    if (createPdfButton && !createPdfButton.hidden && pdfButton && pdfButton.hidden) {
        return "missing_pdf";
    }

    if (recipeIsManual(recipe) && recipeEditorHasChanges(recipe)) {
        return "manual_edits";
    }

    return "";
}

function recipeIsManual(recipe) {
    return String(recipe && recipe.source_url ? recipe.source_url : "").trim().toLowerCase().startsWith("manual://");
}

function recipeEditorHasChanges(recipe) {
    const previous = recipeEditOriginalSnapshot || normalizeRecipeEditorSnapshot({});
    const next = normalizeRecipeEditorSnapshot(recipe || {});

    return JSON.stringify(previous) !== JSON.stringify(next);
}

async function createRecipeEditorPdf(button) {
    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Creating...";
    }

    try {
        setRecipeEditStatus("Saving recipe before PDF...");

        const payload = collectRecipeEditorPayload();
        const saveResponse = await fetch("/api/recipe", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });
        const saveData = await saveResponse.json();

        if (!saveResponse.ok || !saveData.ok) {
            throw new Error((saveData && saveData.error) || "Unable to save recipe.");
        }

        const sourceUrl = (
            saveData.recipe && saveData.recipe.source_url
                ? saveData.recipe.source_url
                : payload.recipe.source_url || payload.original_url
        );

        if (saveData.recipe) {
            populateRecipeEditor(saveData.recipe, sourceUrl);
        }

        setRecipeEditStatus("Creating PDF...");
        const pdfData = await createRecipePdfForSource(sourceUrl);

        updateRecipeEditorPdfControls({
            source_url: pdfData.url || sourceUrl,
            pdf_path: pdfData.pdf_path || "",
            pdf_available: true,
        });
        setRecipeEditStatus("PDF created.");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe PDF created.");
    } catch (err) {
        console.warn("Unable to create recipe PDF.", err);
        setRecipeEditStatus("Unable to create PDF.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Create PDF";
        }
    }

    return false;
}

async function createRecipePdfForSource(sourceUrl) {
    if (isLegitimateWebUrl(sourceUrl)) {
        return createRecipePdfFromSourceUrl(sourceUrl);
    }

    return createRecipePdfFromSavedRecipe(sourceUrl);
}

function isLegitimateWebUrl(value) {
    try {
        const url = new URL(String(value || "").trim());
        return ["http:", "https:"].includes(url.protocol) && Boolean(url.hostname);
    } catch (err) {
        return false;
    }
}

async function createRecipePdfFromSourceUrl(sourceUrl) {
    const pdfResponse = await fetch("/api/source_url_pdf", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: sourceUrl }),
    });
    const pdfData = await pdfResponse.json();

    if (!pdfResponse.ok || !pdfData.ok) {
        throw new Error((pdfData && pdfData.error) || "Unable to create PDF.");
    }

    return pdfData;
}

async function createRecipePdfFromSavedRecipe(sourceUrl) {
    const pdfResponse = await fetch("/api/recipe_pdf", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: sourceUrl }),
    });
    const pdfData = await pdfResponse.json();

    if (!pdfResponse.ok || !pdfData.ok) {
        throw new Error((pdfData && pdfData.error) || "Unable to create PDF.");
    }

    return pdfData;
}

async function deleteRecipeEditorPdf(button) {
    const originalText = button ? button.textContent : "";
    const sourceInput = document.getElementById("recipeEditSourceUrl");
    const originalInput = document.getElementById("recipeEditOriginalUrl");
    const sourceUrl = (
        (sourceInput ? sourceInput.value.trim() : "")
        || (originalInput ? originalInput.value.trim() : "")
        || ""
    );

    if (!sourceUrl) {
        setRecipeEditStatus("Recipe URL is required before deleting PDF.", true);
        return false;
    }

    if (!confirm("Delete this recipe PDF?")) {
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "...";
    }

    try {
        setRecipeEditStatus("Deleting PDF...");

        const response = await fetch("/api/recipe_pdf/delete", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ url: sourceUrl }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to delete PDF.");
        }

        updateRecipeEditorPdfControls({
            source_url: data.url || sourceUrl,
            pdf_path: data.pdf_path || "",
            pdf_available: false,
        });
        setRecipeEditStatus("PDF deleted.");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe PDF deleted.");
    } catch (err) {
        console.warn("Unable to delete recipe PDF.", err);
        setRecipeEditStatus(err.message || "Unable to delete PDF.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "X";
        }
    }

    return false;
}

function normalizeRecipeEditorSnapshot(recipe) {
    return {
        display_name: String(recipe.display_name || "").trim(),
        recipe_title: String(recipe.recipe_title || "").trim(),
        source_url: String(recipe.source_url || "").trim(),
        quantity: String(parseRecipeScaleMultiplier(recipe.quantity || "1") || 1),
        servings: String(recipe.servings || "").trim(),
        scaling: normalizeRecipeScalingSnapshot(recipe.scaling || {}),
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

function normalizeRecipeScalingSnapshot(scaling) {
    const normalized = normalizeRecipeScalingOptions(
        scaling.available_multipliers
            || scaling.multipliers
            || scaling.scaling_multipliers
            || []
    );
    const selected = parseRecipeScaleMultiplier(
        scaling.selected_multiplier !== undefined
            ? scaling.selected_multiplier
            : scaling.scaling_multiplier
    ) || 1;

    return {
        selected_multiplier: String(selected),
        base_servings: String(scaling.base_servings || "").trim(),
        available_multipliers: normalized.map(option => `${option.label}:${option.value}`),
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

    if (previous.scaling.selected_multiplier !== next.scaling.selected_multiplier) {
        detailLines.push(`Recipe amount: ${previous.scaling.selected_multiplier || "1"}x -> ${next.scaling.selected_multiplier || "1"}x`);
    }

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
    const quantity = parseRecipeScaleMultiplier(document.getElementById("recipeEditQuantity").value || "1") || 1;
    const sourceUrl = recipeEditorSourceUrlForSave();

    return {
        original_url: originalUrl,
        recipe: {
            display_name: document.getElementById("recipeEditDisplayName").value.trim(),
            recipe_title: document.getElementById("recipeEditTitleInput").value.trim(),
            source_url: sourceUrl,
            quantity,
            servings: document.getElementById("recipeEditServings").value.trim(),
            scaling: collectRecipeScalingPayload(),
            ingredients: collectRecipeIngredientRows(),
            equipment: collectRecipeTextRows("#recipeEditEquipment .recipe-edit-text-row"),
            instructions: collectRecipeInstructionRows(),
            nutrition: collectRecipeNutritionRows(),
        },
    };
}

function recipeEditorSourceUrlForSave() {
    const sourceInput = document.getElementById("recipeEditSourceUrl");

    if (!sourceInput) {
        return "";
    }

    const currentValue = sourceInput.value.trim();
    const displaySourceUrl = sourceInput.dataset.displaySourceUrl || "";
    const canonicalSourceUrl = sourceInput.dataset.canonicalSourceUrl || "";

    if (displaySourceUrl && canonicalSourceUrl && currentValue === displaySourceUrl) {
        return canonicalSourceUrl;
    }

    return currentValue;
}

function collectRecipeIngredientRows() {
    const selectedMultiplier = currentRecipeEditScaleMultiplier();

    return [...document.querySelectorAll("#recipeEditIngredients .recipe-edit-ingredient-row")]
        .map(row => {
            const item = fieldValuesFromRow(row);

            if (Math.abs(selectedMultiplier - 1) < 0.000001) {
                item.base_quantity = item.quantity || "";
                item.base_unit = item.unit || "";
            }

            return item;
        })
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
    const quantity = normalizeRecipeQuantityInput(input);

    if (!options.force && recipeMultipliersMatch(input.dataset.lastSavedValue, quantity) && !input.dataset.savePending) {
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
            showRecipeQuantityUpdatedMessage(
                url,
                formatRecipeScaleMultiplierLabel(quantity),
                input.dataset.recipeNumber || "",
                `${input.dataset.recipeNumber ? `Recipe ${input.dataset.recipeNumber} ` : ""}amount updated to ${formatRecipeScaleMultiplierLabel(quantity)}.`
            );
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
    control.querySelectorAll("button, input, select").forEach(element => {
        element.disabled = isSaving;
    });
}

function updateRecipeQuantityDisplays(recipeUrl, multiplier, apiData = null) {
    const isScaled = !recipeMultipliersMatch(multiplier, 1);

    document.querySelectorAll(`.recipe-servings-scaled[data-recipe-url="${cssEscape(recipeUrl)}"]`).forEach(element => {
        const baseServings = element.dataset.baseServings || "";
        const scaledServings = (apiData && apiData.servings) || scaleServingsForDisplay(baseServings, multiplier);
        element.textContent = isScaled && scaledServings ? ` -> ${scaledServings}` : "";
    });

    document.querySelectorAll(`.recipe-ingredient-scaled-quantity[data-recipe-url="${cssEscape(recipeUrl)}"]`).forEach(element => {
        const ingredientName = element.dataset.ingredientName || "";
        const apiIngredient = findScaledIngredient(apiData, ingredientName);
        const baseQuantity = element.dataset.baseQuantity || "";
        const unit = element.dataset.unit || "";
        const baseDisplay = `${baseQuantity} ${unit}`.trim();

        if (apiIngredient && apiIngredient.display) {
            element.textContent = isScaled ? apiIngredient.display : baseDisplay;
            return;
        }

        const scaledQuantity = scaleQuantityForDisplay(baseQuantity, multiplier);

        if (scaledQuantity) {
            element.textContent = isScaled ? `${scaledQuantity} ${unit}`.trim() : baseDisplay;
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
    currentDisplay.textContent = currentQty || "No recipe amount found.";
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
    ["Recipe", "Default qty", "Unit", "Amount"].forEach(text => {
        const cell = document.createElement("span");
        cell.textContent = text;
        header.appendChild(cell);
    });
    container.appendChild(header);

    sources.forEach(source => {
        const row = document.createElement("div");
        row.className = "item-qty-source-row";

        const label = document.createElement(source.url ? "button" : "span");
        label.className = "item-qty-source-label";
        label.textContent = source.label || "Recipe";
        if (source.url) {
            label.type = "button";
            label.classList.add("item-qty-source-link");
            label.title = source.ingredient
                ? `Edit recipe and jump to ${source.ingredient}`
                : "Edit recipe";
            label.addEventListener("click", () => {
                openRecipeEditorFromItemQtySource(source.url, source.ingredient || "");
            });
        }

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

        const quantityInput = document.createElement("select");
        quantityInput.className = "item-qty-source-value recipe-quantity-input recipe-scaling-select";
        populateItemQtyScalingOptions(quantityInput, source.scaling_options, source.recipe_quantity || 1);
        quantityInput.dataset.recipeUrl = source.url || "";
        quantityInput.dataset.recipeNumber = source.recipe_number || "";
        quantityInput.dataset.lastSavedValue = String(parseRecipeScaleMultiplier(source.recipe_quantity) || 1);
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

function populateItemQtyScalingOptions(select, scalingOptions, selectedMultiplier) {
    const selected = parseRecipeScaleMultiplier(selectedMultiplier) || 1;
    const options = normalizeRecipeScalingOptions(scalingOptions || []);

    if (!options.some(option => recipeMultipliersMatch(option.value, selected))) {
        options.push({
            label: formatRecipeScaleMultiplierLabel(selected),
            value: selected,
        });
        options.sort((a, b) => a.value - b.value);
    }

    select.replaceChildren(...options.map(option => {
        const element = document.createElement("option");
        element.value = String(option.value);
        element.textContent = option.label;
        element.selected = recipeMultipliersMatch(option.value, selected);
        return element;
    }));
}

function openRecipeEditorFromItemQtySource(recipeUrl, ingredientName = "") {
    if (!recipeUrl) {
        return false;
    }

    closeItemQtyEditor();
    openRecipeEditor(
        { dataset: { recipeUrl } },
        { scrollToIngredient: ingredientName }
    );
    return false;
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
        console.warn("Unable to save recipe amount from item modal.", err);
        alert("Unable to save recipe amount.");
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
    currentDisplay.textContent = currentQty || "No recipe amount found.";
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
    const value = normalizeQuantityFractionText(quantity);

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
    const text = normalizeQuantityFractionText(value);
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

function normalizeQuantityFractionText(value) {
    return String(value || "")
        .trim()
        .replace(/[–—]/g, "-")
        .replace(/Â½|½|â…½/g, "1/2")
        .replace(/Â¼|¼|â…¼/g, "1/4")
        .replace(/Â¾|¾|â…¾/g, "3/4")
        .replace(/⅓|â…“/g, "1/3")
        .replace(/⅔|â…”/g, "2/3")
        .replace(/⅛|â…›/g, "1/8")
        .replace(/⅜|â…œ/g, "3/8")
        .replace(/⅝|â…/g, "5/8")
        .replace(/⅞|â…ž/g, "7/8");
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
        event.preventDefault();
        await runFindNearestStores(form, submitter);
        return false;
    }

    event.preventDefault();

    try {
        await saveHomeAddressForm(form);
    } catch (err) {
        // saveHomeAddressForm already logs this; keep the normal save path non-disruptive.
    }

    return false;
}

async function runFindNearestStores(form, button) {
    const originalText = button ? button.textContent : "";
    const formData = new FormData(form);
    formData.set("ajax", "1");
    formData.set("action", "run_find_nearest");

    updateHomeAddressSummaries(buildAddressSummaryFromForm(form));

    if (button) {
        button.disabled = true;
        button.textContent = "Finding stores...";
    }

    try {
        const response = await fetch(formActionUrl(form), {
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
            throw new Error((data && data.error) || "Unable to find nearest stores.");
        }

        if (data && data.home_address) {
            updateHomeAddressSummaries(data.home_address.full_address || "");
        }

        let message = data && data.warning
            ? `Nearest stores not updated: ${data.warning}`
            : "Nearest stores updated.";

        try {
            await refreshStoreMarkup({ cacheBust: true });
        } catch (refreshErr) {
            console.warn("Nearest stores were resolved, but the store markup refresh failed.", refreshErr);
            message += " Refresh the page if the store list does not update.";
        }

        showRecipeQuantityUpdatedMessage("", "", "", message);
    } catch (err) {
        console.warn("Unable to find nearest stores in the background.", err);
        showRecipeQuantityUpdatedMessage("", "", "", err.message || "Unable to find nearest stores.");
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }
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
        const response = await fetch(formActionUrl(form), {
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
        updateHomeAddressMapLink(summary, text);
    }

    if (collapsedSummary) {
        collapsedSummary.textContent = text || "No home address saved.";
        updateHomeAddressMapLink(collapsedSummary, text);
    }
}

function homeAddressGoogleMapsUrl(address) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
}

function homeAddressAppleMapsUrl(address) {
    return `https://maps.apple.com/?q=${encodeURIComponent(address)}`;
}

function updateHomeAddressMapLink(element, address) {
    if (!element || element.tagName !== "A") {
        return;
    }

    if (!address) {
        element.removeAttribute("href");
        element.dataset.googleMapsUrl = "";
        element.dataset.appleMapsUrl = "";
        return;
    }

    const googleMapsUrl = homeAddressGoogleMapsUrl(address);
    const appleMapsUrl = homeAddressAppleMapsUrl(address);
    element.href = googleMapsUrl;
    element.dataset.googleMapsUrl = googleMapsUrl;
    element.dataset.appleMapsUrl = appleMapsUrl;
    element.title = "Open home address in Maps";
}

function adjustStoreSearchRadius(delta) {
    const input = document.getElementById("storeSearchRadiusMiles");

    if (!input) {
        return;
    }

    const min = Number.parseFloat(input.min || "1");
    const max = Number.parseFloat(input.max || "100");
    const step = Number.parseFloat(input.step || "1") || 1;
    const current = Number.parseFloat(input.value);
    const base = Number.isFinite(current) ? current : min;
    const next = Math.max(min, Math.min(max, base + (delta * step)));

    input.value = Number.isInteger(next) ? String(next) : String(Number(next.toFixed(2)));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
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

    return saveStoreOptionsForm(form);
}

async function saveStoreOptionsForm(form) {
    try {
        await submitStoreForm(form);
        await refreshStoreMarkup();
        return true;
    } catch (err) {
        console.warn("Unable to save store options in the background.", err);
        return false;
    }
}

let addStoreReturnFocus = null;

function openAddStoreModal() {
    const modal = document.getElementById("addStoreModal");

    if (!modal) {
        return;
    }

    addStoreReturnFocus = document.activeElement;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    updateAddStoreStickyVisibility();

    window.setTimeout(() => {
        const firstInput = modal.querySelector('input[name="store_label"]');

        if (firstInput) {
            firstInput.focus();
        }
    }, 0);
}

function closeAddStoreModal(options = {}) {
    const modal = document.getElementById("addStoreModal");

    if (!modal) {
        return;
    }

    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    updateAddStoreStickyVisibility();

    if (options.reset) {
        const form = modal.querySelector("form");
        const passwordInput = document.getElementById("add-store-password");
        const passwordToggle = modal.querySelector(".password-toggle-btn");

        if (form) {
            form.reset();
        }

        if (passwordInput) {
            passwordInput.type = "password";
        }

        if (passwordToggle) {
            passwordToggle.textContent = "Show";
        }
    }

    if (options.returnFocus !== false && addStoreReturnFocus && typeof addStoreReturnFocus.focus === "function") {
        addStoreReturnFocus.focus();
    }

    addStoreReturnFocus = null;
}

function updateAddStoreStickyVisibility() {
    const section = document.getElementById("storeOptionsSection");
    const content = document.querySelector('[data-collapse-content="store-options"]');
    const action = document.querySelector(".store-add-sticky-action");
    const modal = document.getElementById("addStoreModal");

    if (!section || !content || !action) {
        return;
    }

    const sectionRect = section.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const expanded = !content.classList.contains("collapsed");
    const actionHeight = action.offsetHeight || 68;
    const sectionStarted = sectionRect.top < viewportHeight - actionHeight;
    const sectionContinuesBelowAction = sectionRect.bottom > viewportHeight + actionHeight;
    const modalOpen = modal && modal.classList.contains("open");
    const shouldShow = expanded && sectionStarted && sectionContinuesBelowAction && !modalOpen;

    action.classList.toggle("is-visible", shouldShow);
    action.setAttribute("aria-hidden", shouldShow ? "false" : "true");

    if (!shouldShow) {
        action.style.left = "";
        action.style.width = "";
        return;
    }

    const horizontalInset = viewportWidth <= 650 ? 12 : 16;
    const maxWidth = Math.max(0, viewportWidth - (horizontalInset * 2));
    const actionWidth = Math.min(sectionRect.width, maxWidth);
    const preferredLeft = sectionRect.left + ((sectionRect.width - actionWidth) / 2);
    const minLeft = horizontalInset;
    const maxLeft = viewportWidth - horizontalInset - actionWidth;
    const actionLeft = Math.max(minLeft, Math.min(preferredLeft, maxLeft));

    action.style.left = `${actionLeft}px`;
    action.style.width = `${actionWidth}px`;
}

function scheduleAddStoreStickyVisibilityUpdate() {
    window.requestAnimationFrame(updateAddStoreStickyVisibility);
}

function closeAddStoreModalFromBackdrop(event) {
    if (event && event.target === event.currentTarget) {
        closeAddStoreModal();
    }
}

function closeAddStoreModalOnEscape(event) {
    if (event.key === "Escape") {
        const storeEditForm = document.querySelector(".store-edit-form.open");

        if (storeEditForm) {
            closeStoreEditModal({ reset: true });
            return;
        }

        const modal = document.getElementById("addStoreModal");

        if (modal && modal.classList.contains("open")) {
            closeAddStoreModal();
        }
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
        closeAddStoreModal({ reset: true, returnFocus: false });
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

function saveStoreDetails(event) {
    event.preventDefault();
    saveStoreDetailsForm(event.currentTarget);

    return false;
}

async function saveStoreDetailsForm(form) {
    const submitButton = form.querySelector('button[type="submit"]');

    if (submitButton) {
        submitButton.disabled = true;
        submitButton.setAttribute("aria-busy", "true");
    }

    try {
        await submitStoreForm(form);
        updateStoreDetailsFromForm(form);
        syncStoreEditFormDefaults(form);
        closeStoreEditModal({ returnFocus: false });
    } catch (err) {
        console.warn("Unable to save store details in the background.", err);
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.removeAttribute("aria-busy");
        }
    }
}

function updateStoreDetailLine(container, label, value) {
    if (!container) {
        return;
    }

    const normalizedLabel = label.toLowerCase();
    let line = Array.from(container.querySelectorAll(".store-detail-line"))
        .find(candidate => {
            const detailLabel = candidate.querySelector(".store-detail-label");
            return ((detailLabel && detailLabel.textContent) || "").trim().toLowerCase() === normalizedLabel;
        });

    if (!line && value) {
        line = document.createElement("div");
        line.className = "store-detail-line";
        line.innerHTML = `<span class="store-detail-label"></span> <a class="store-detail-link" target="_blank"></a>`;
        line.querySelector(".store-detail-label").textContent = label;
        container.appendChild(line);
    }

    if (!line) {
        return;
    }

    const link = line.querySelector(".store-detail-link");

    if (!value) {
        line.remove();
        return;
    }

    if (link) {
        link.href = value;
        link.textContent = value;
    }
}

function updateStoreDetailsFromForm(form) {
    const storeKey = (form.id || "").replace(/^store-edit-/, "");
    const row = form.closest(".store-manager-row");
    const labelInput = form.querySelector('[name="store_label"]');
    const searchUrlInput = form.querySelector('[name="store_url"]');
    const selectorUrlInput = form.querySelector('[name="urlStoreSelector"]');
    const label = ((labelInput && labelInput.value) || "").trim();
    const searchUrl = ((searchUrlInput && searchUrlInput.value) || "").trim();
    const selectorUrl = ((selectorUrlInput && selectorUrlInput.value) || "").trim();
    const storeName = label || "Store";
    const storeUrl = selectorUrl || searchUrl;
    const managerLabel = row ? row.querySelector(".store-manager-label") : null;
    const managerUrl = row ? row.querySelector(".store-manager-url") : null;
    const modalTitle = form.querySelector(".store-edit-modal-header h2");
    const modalClose = form.querySelector(".store-edit-modal-close");
    const activeCard = Array.from(document.querySelectorAll(".active-store-card"))
        .find(card => card.dataset.storeKey === storeKey);

    if (managerLabel) {
        managerLabel.textContent = storeName;
    }

    if (modalTitle) {
        modalTitle.textContent = `Edit ${storeName}`;
    }

    if (modalClose) {
        modalClose.setAttribute("aria-label", `Close ${storeName} editor`);
    }

    updateStoreDetailLine(managerUrl, "Search", searchUrl);
    updateStoreDetailLine(managerUrl, "Store Selector URL", selectorUrl);

    if (!activeCard) {
        return;
    }

    const activeName = activeCard.querySelector(".active-store-name");
    const isActive = activeCard.dataset.storeActive === "true";

    if (activeName) {
        activeName.textContent = storeName;
    }

    if (storeUrl) {
        activeCard.href = storeUrl;
        activeCard.dataset.storeUrl = storeUrl;
    }

    activeCard.dataset.storeTitle = `Open ${storeName}`;
    activeCard.dataset.activationTitle = `${isActive ? "Deactivate" : "Activate"} ${storeName}`;

    if (!activeCard.dataset.googleMapsUrl) {
        activeCard.dataset.mapTitle = activeCard.dataset.storeTitle;
    }

    setActiveStoreIconMode(localStorage.getItem("active-store-icon-mode") || "store");
    restoreStoreOptionsListSort();
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

async function selectNearbyStoreLocation(button) {
    const storeKey = button ? button.dataset.storeKey || "" : "";
    const nearbyIndex = button ? button.dataset.nearbyIndex || "" : "";

    if (!storeKey) {
        return false;
    }

    if (button && button.classList.contains("selecting")) {
        return false;
    }

    const formData = new FormData();
    formData.set("ajax", "1");
    formData.set("nearby_index", nearbyIndex);

    if (button) {
        button.classList.add("selecting");
        button.setAttribute("aria-busy", "true");
        if ("disabled" in button) {
            button.disabled = true;
        }
    }

    try {
        const response = await fetch(`/select_nearby_store_location/${encodeURIComponent(storeKey)}`, {
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
            throw new Error((data && data.error) || "Unable to select store location.");
        }

        await refreshStoreMarkup({ cacheBust: true });
        showRecipeQuantityUpdatedMessage("", "", "", "Store location selected.");
    } catch (err) {
        console.warn("Unable to select store location.", err);
        showRecipeQuantityUpdatedMessage("", "", "", err.message || "Unable to select store location.");

        if (button && button.isConnected) {
            button.classList.remove("selecting");
            button.removeAttribute("aria-busy");
            if ("disabled" in button) {
                button.disabled = false;
            }
        }
    }

    return false;
}

function selectNearbyStoreLocationFromKey(event, element) {
    if (!event || (event.key !== "Enter" && event.key !== " ")) {
        return true;
    }

    event.preventDefault();
    return selectNearbyStoreLocation(element);
}

function shouldOpenAppleMaps() {
    const userAgent = navigator.userAgent || "";
    const platform = navigator.userAgentData && navigator.userAgentData.platform
        ? navigator.userAgentData.platform
        : navigator.platform || "";

    return /iPad|iPhone|iPod|Mac/i.test(`${platform} ${userAgent}`);
}

function openExternalMapUrl(url, windowName = "_blank") {
    if (!url) {
        return false;
    }

    const mapWindow = window.open(url, windowName, "noopener,noreferrer");

    if (mapWindow) {
        mapWindow.opener = null;
        mapWindow.focus();
        return true;
    }

    return false;
}

function openStoreAddressMap(link, event) {
    if (event) {
        event.stopPropagation();
    }

    if (!link) {
        return true;
    }

    const googleMapsUrl = link.dataset.googleMapsUrl || link.href || "";
    const appleMapsUrl = link.dataset.appleMapsUrl || "";
    const mapUrl = shouldOpenAppleMaps() && appleMapsUrl ? appleMapsUrl : googleMapsUrl || appleMapsUrl;

    if (!mapUrl) {
        return true;
    }

    if (event) {
        event.preventDefault();
    }

    if (openExternalMapUrl(mapUrl)) {
        return false;
    }

    link.href = mapUrl;
    return true;
}

function openStoreDirections(link, event) {
    if (event) {
        event.stopPropagation();
    }

    if (!link || !link.href) {
        return false;
    }

    const popup = window.open(link.href, "storeDirections", "popup=yes,width=1120,height=780,noopener,noreferrer");

    if (popup) {
        popup.opener = null;
        popup.focus();
        if (event) {
            event.preventDefault();
        }
        return false;
    }

    return true;
}

function parseMapCoordinate(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function storeLocationMapUrl(lat, lon, zoom = 16) {
    return `https://www.openstreetmap.org/?mlat=${encodeURIComponent(lat)}&mlon=${encodeURIComponent(lon)}#map=${zoom}/${encodeURIComponent(lat)}/${encodeURIComponent(lon)}`;
}

function storeLocationPopupHtml(title, address, distance, lat, lon) {
    const distanceText = distance || distance === 0 ? `<br><span>${escapeHtml(distance)} mi</span>` : "";
    const mapUrl = lat !== null && lon !== null ? storeLocationMapUrl(lat, lon) : "";
    const mapLink = mapUrl
        ? `<br><a href="${escapeAttribute(mapUrl)}" target="_blank" rel="noopener noreferrer">Open location</a>`
        : "";

    return `<strong>${escapeHtml(title)}</strong><br>${escapeHtml(address || "")}${distanceText}${mapLink}`;
}

function storeHomePinMarkup() {
    return [
        '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">',
        '<path d="M3 11.5 12 4l9 7.5"></path>',
        '<path d="M5.5 10.5V20h13v-9.5"></path>',
        '<path d="M9.5 20v-6h5v6"></path>',
        '</svg>',
    ].join("");
}

function cssClassPart(value) {
    return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "custom";
}

function storeLocationMapIcon(className, label, options = {}) {
    const iconSize = options.iconSize || [24, 24];
    const iconHtml = options.html || escapeHtml(label);

    return L.divIcon({
        className: "store-map-pin-shell",
        html: `<span class="store-map-pin ${escapeAttribute(className)}">${iconHtml}</span>`,
        iconSize,
        iconAnchor: [iconSize[0] / 2, iconSize[1] / 2],
        popupAnchor: [0, -12],
    });
}

function coordinatesMatch(latA, lonA, latB, lonB) {
    return latA !== null
        && lonA !== null
        && latB !== null
        && lonB !== null
        && Math.abs(latA - latB) < 0.00001
        && Math.abs(lonA - lonB) < 0.00001;
}

function addressMatches(addressA, addressB) {
    return String(addressA || "").trim().toLowerCase() === String(addressB || "").trim().toLowerCase();
}

function initStoreLocationMaps() {
    if (!window.L) {
        return;
    }

    document.querySelectorAll("[data-store-map]").forEach(container => {
        if (container.dataset.mapReady === "1") {
            if (container._storeLocationMap && container.offsetParent !== null) {
                window.setTimeout(() => container._storeLocationMap.invalidateSize(), 0);
            }
            return;
        }

        if (container.offsetParent === null) {
            return;
        }

        let locations = [];
        try {
            locations = JSON.parse(container.dataset.locations || "[]");
        } catch (err) {
            console.warn("Unable to parse store map locations.", err);
        }

        if (!Array.isArray(locations)) {
            locations = [];
        }

        const homeLat = parseMapCoordinate(container.dataset.homeLat);
        const homeLon = parseMapCoordinate(container.dataset.homeLon);
        const selectedStoresMap = container.dataset.selectedStoresMap === "1";
        const selectedLat = parseMapCoordinate(container.dataset.selectedLat);
        const selectedLon = parseMapCoordinate(container.dataset.selectedLon);
        const selectedAddress = container.dataset.selectedAddress || "";
        const storePins = locations
            .map((location, index) => {
                const lat = parseMapCoordinate(location.latitude);
                const lon = parseMapCoordinate(location.longitude);
                return {
                    index,
                    location,
                    lat,
                    lon,
                    selected: coordinatesMatch(lat, lon, selectedLat, selectedLon)
                        || addressMatches(location.address, selectedAddress),
                };
            })
            .filter(pin => pin.lat !== null && pin.lon !== null);

        if (homeLat === null || homeLon === null || !storePins.length) {
            const mapWrap = container.closest(".store-location-map-wrap");
            if (mapWrap) {
                mapWrap.classList.add("store-location-map-empty");
            }
            return;
        }

        const map = L.map(container, {
            scrollWheelZoom: false,
        });
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap",
        }).addTo(map);

        const bounds = [];
        const storeLabel = container.dataset.storeLabel || "Store";
        const homeAddress = container.dataset.homeAddress || "Current address";

        L.marker([homeLat, homeLon], {
            icon: storeLocationMapIcon("home house", "", {
                html: storeHomePinMarkup(),
                iconSize: [28, 28],
            }),
        }).addTo(map).bindPopup(storeLocationPopupHtml("Current address", homeAddress, "", homeLat, homeLon));
        bounds.push([homeLat, homeLon]);

        storePins.forEach(pin => {
            const markerLabel = selectedStoresMap
                ? String(pin.location.logo_text || pin.location.label || pin.index + 1)
                : String(pin.index + 1);
            const markerClass = selectedStoresMap
                ? `store-logo-pin store-logo-${cssClassPart(pin.location.store_key || pin.location.label)}`
                : (pin.selected ? "store selected" : "store nearby");
            const markerTitle = selectedStoresMap
                ? String(pin.location.label || pin.location.name || storeLabel)
                : (pin.selected ? `Selected ${storeLabel}` : `${storeLabel} ${markerLabel}`);
            const markerIconSize = selectedStoresMap ? [34, 34] : [24, 24];
            L.marker([pin.lat, pin.lon], {
                icon: storeLocationMapIcon(markerClass, markerLabel, {
                    iconSize: markerIconSize,
                }),
            }).addTo(map).bindPopup(storeLocationPopupHtml(
                markerTitle,
                pin.location.address || pin.location.name || "",
                pin.location.distance_miles,
                pin.lat,
                pin.lon,
            ));
            bounds.push([pin.lat, pin.lon]);
        });

        if (bounds.length === 1) {
            map.setView(bounds[0], 14);
        } else {
            map.fitBounds(bounds, {
                padding: [28, 28],
                maxZoom: 14,
            });
        }

        container._storeLocationMap = map;
        container.dataset.mapReady = "1";
        window.setTimeout(() => map.invalidateSize(), 0);
    });
}

function invalidateStoreLocationMaps() {
    initStoreLocationMaps();
    document.querySelectorAll("[data-store-map]").forEach(container => {
        if (container._storeLocationMap && container.offsetParent !== null) {
            container._storeLocationMap.invalidateSize();
        }
    });
}

async function submitStoreForm(form) {
    const formData = new FormData(form);
    formData.set("ajax", "1");

    const response = await fetch(formActionUrl(form), {
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

async function refreshStoreMarkup(options = {}) {
    const scrollX = Number.isFinite(options.scrollX) ? options.scrollX : window.scrollX;
    const scrollY = Number.isFinite(options.scrollY) ? options.scrollY : window.scrollY;
    const refreshUrl = new URL(window.location.href);

    if (options.cacheBust) {
        refreshUrl.searchParams.set("_refresh", String(Date.now()));
    }

    const response = await fetch(refreshUrl.toString(), {
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error("Unable to refresh store markup.");
    }

    const html = await response.text();
    const nextPage = new DOMParser().parseFromString(html, "text/html");
    replaceSectionFromPage(nextPage, "#editItemsSection");
    replaceSectionFromPage(nextPage, "#home-address-section");
    replaceSectionFromPage(nextPage, "#storeOptionsSection");
    const recipeLogWasRefreshed = replaceSectionFromPage(nextPage, "#currentRecipeUrlLogCard");
    replaceSectionFromPage(nextPage, "#foodRestrictionsCard");
    replaceSectionFromPage(nextPage, "#rulesCard");
    replaceSectionFromPage(nextPage, "#sectionView");
    replaceSectionFromPage(nextPage, "#storeView");
    replaceSectionFromPage(nextPage, "#recipeView");

    if (options.requireRecipeLog && !recipeLogWasRefreshed) {
        throw new Error("Recipe log refresh target was not found.");
    }

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
    restoreStoreOptionsDisplaySettings();
    restoreActiveStoreIconMode();
    restoreStoreOptionsListSort();
    initStoreLocationMaps();
    restoreWindowScroll(scrollX, scrollY);
    window.setTimeout(updateAddStoreStickyVisibility, 140);
}

function restoreWindowScroll(scrollX, scrollY) {
    const targetX = Math.max(0, scrollX || 0);
    const targetY = Math.max(0, scrollY || 0);
    const scrollBack = () => window.scrollTo(targetX, targetY);

    scrollBack();
    window.requestAnimationFrame(scrollBack);
    window.setTimeout(scrollBack, 0);
    window.setTimeout(scrollBack, 120);
}

function replaceSectionFromPage(nextPage, selector) {
    const currentSection = document.querySelector(selector);
    const nextSection = nextPage.querySelector(selector);

    if (currentSection && nextSection) {
        currentSection.replaceWith(nextSection);
        return true;
    }

    return false;
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
    restoreStoreOptionsDisplaySettings();
    restoreActiveStoreIconMode();
    restoreStoreOptionsListSort();
    initStoreLocationMaps();
    startExtractionProgressPolling();
    document.addEventListener("keydown", closeAddStoreModalOnEscape);
    updateAddStoreStickyVisibility();
});

window.addEventListener("resize", updateRecipeEditStickyOffsets);
window.addEventListener("resize", updateViewSwitcherStickyOffset);
window.addEventListener("resize", invalidateStoreLocationMaps);
window.addEventListener("resize", scheduleAddStoreStickyVisibilityUpdate);
window.addEventListener("scroll", scheduleAddStoreStickyVisibilityUpdate, { passive: true });

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
