(function () {
    const POLL_INTERVAL_MS = 700;
    const REFRESH_DELAY_MS = 1200;
    let activeJobId = "";
    let pollTimer = null;
    let activeImageJobId = "";
    let imagePollTimer = null;
    let imageRefreshTimer = null;

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

    function initMasterDataBackfill() {
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
        document.addEventListener("DOMContentLoaded", initMasterDataBackfill);
    } else {
        initMasterDataBackfill();
    }
}());
