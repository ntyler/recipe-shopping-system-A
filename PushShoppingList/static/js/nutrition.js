(() => {
    "use strict";

    const body = document.body;
    if (!body || !body.hasAttribute("data-nutrition-page")) {
        return;
    }

    const NUTRIENTS = [
        "calories",
        "protein",
        "carbohydrates",
        "fat",
        "fiber",
        "sugar",
        "sodium",
    ];
    const NUTRIENT_ALIASES = {
        calories: ["calories", "calories_kcal", "kcal"],
        protein: ["protein", "protein_g"],
        carbohydrates: ["carbohydrates", "carbohydrate", "carbs", "carbs_g"],
        fat: ["fat", "fat_g", "total_fat"],
        fiber: ["fiber", "fiber_g", "dietary_fiber"],
        sugar: ["sugar", "sugar_g", "sugars"],
        sodium: ["sodium", "sodium_mg"],
    };
    const MEAL_TYPES = new Set(["breakfast", "lunch", "dinner", "snack"]);
    const PHOTO_TYPES = new Set([
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    ]);
    const PHOTO_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "heic", "heif"]);
    const SVG_NS = "http://www.w3.org/2000/svg";

    class NutritionApiError extends Error {
        constructor(message, status = 0, fieldErrors = {}) {
            super(message);
            this.name = "NutritionApiError";
            this.status = status;
            this.fieldErrors = fieldErrors && typeof fieldErrors === "object" ? fieldErrors : {};
        }
    }

    const state = {
        activeCalendarTrigger: null,
        calendarView: null,
        photoFile: null,
        photoObjectUrl: "",
        hasExistingPhoto: false,
        mediaId: "",
        analysisId: "",
        mealPending: false,
        analysisPending: false,
        savedMealPending: false,
        waterPending: false,
        deletePending: false,
        deleteUrl: "",
        deleteKind: "entry",
        mealRequestId: createRequestId(),
    };

    function query(selector, scope = document) {
        return scope.querySelector(selector);
    }

    function queryAll(selector, scope = document) {
        return Array.from(scope.querySelectorAll(selector));
    }

    function createRequestId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        return `nutrition-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function parseJsonScript(element, fallback) {
        if (!element) {
            return fallback;
        }
        try {
            return JSON.parse(element.textContent || "");
        } catch (_error) {
            return fallback;
        }
    }

    function parseIsoDate(value) {
        const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
        if (!match) {
            return null;
        }
        const year = Number(match[1]);
        const month = Number(match[2]) - 1;
        const day = Number(match[3]);
        const result = new Date(year, month, day, 12, 0, 0, 0);
        if (
            result.getFullYear() !== year
            || result.getMonth() !== month
            || result.getDate() !== day
        ) {
            return null;
        }
        return result;
    }

    function isoFromDate(date) {
        if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
            return "";
        }
        const year = String(date.getFullYear()).padStart(4, "0");
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    function addLocalDays(value, amount) {
        const date = value instanceof Date ? new Date(value.getTime()) : parseIsoDate(value);
        if (!date) {
            return null;
        }
        date.setDate(date.getDate() + Number(amount || 0));
        date.setHours(12, 0, 0, 0);
        return date;
    }

    function longDateLabel(value) {
        const date = parseIsoDate(value);
        if (!date) {
            return String(value || "");
        }
        return new Intl.DateTimeFormat(undefined, {
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
        }).format(date);
    }

    function shortDateLabel(value) {
        const date = parseIsoDate(value);
        if (!date) {
            return String(value || "");
        }
        return new Intl.DateTimeFormat(undefined, {
            weekday: "short",
            day: "numeric",
        }).format(date);
    }

    function currentLocalTime() {
        const now = new Date();
        return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    }

    function timeZonePayload() {
        let timeZone = "";
        try {
            timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
        } catch (_error) {
            timeZone = "";
        }
        return {
            timezone: timeZone,
            timezone_offset_minutes: -new Date().getTimezoneOffset(),
        };
    }

    function nullableNumber(value) {
        if (value === null || value === undefined || value === "") {
            return null;
        }
        if (typeof value === "number") {
            return Number.isFinite(value) ? value : null;
        }
        const normalized = String(value).replace(/,/g, "").trim();
        if (!normalized) {
            return null;
        }
        const parsed = Number.parseFloat(normalized);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function firstDefinedNumber(object, keys) {
        if (!object || typeof object !== "object") {
            return null;
        }
        for (const key of keys) {
            if (Object.prototype.hasOwnProperty.call(object, key)) {
                const value = nullableNumber(object[key]);
                if (value !== null) {
                    return value;
                }
            }
        }
        return null;
    }

    function nutrientNumber(object, key) {
        return firstDefinedNumber(object, NUTRIENT_ALIASES[key] || [key]);
    }

    function rounded(value, digits = 2) {
        if (!Number.isFinite(value)) {
            return null;
        }
        const factor = 10 ** digits;
        return Math.round((value + Number.EPSILON) * factor) / factor;
    }

    function editableNumber(value) {
        if (value === null || value === undefined || !Number.isFinite(Number(value))) {
            return "";
        }
        return String(rounded(Number(value), 2));
    }

    function displayNumber(value, maximumFractionDigits = 1) {
        if (value === null || value === undefined || !Number.isFinite(Number(value))) {
            return "—";
        }
        return new Intl.NumberFormat(undefined, {
            maximumFractionDigits,
        }).format(Number(value));
    }

    function setStatus(element, message = "", isError = false) {
        if (!element) {
            return;
        }
        element.textContent = message;
        element.classList.toggle("is-error", Boolean(message && isError));
    }

    function setButtonPending(button, pending) {
        if (!button) {
            return;
        }
        button.disabled = Boolean(pending);
        button.setAttribute("aria-busy", pending ? "true" : "false");
    }

    function apiErrorMessage(payload, fallback) {
        if (payload && typeof payload === "object") {
            return payload.error || payload.message || payload.detail || fallback;
        }
        if (typeof payload === "string" && payload.trim()) {
            return payload.trim();
        }
        return fallback;
    }

    async function apiRequest(url, options = {}) {
        const requestOptions = {
            credentials: "same-origin",
            ...options,
            headers: {
                Accept: "application/json",
                ...(options.headers || {}),
            },
        };
        const csrfToken = body.dataset.csrfToken || "";
        if (csrfToken) {
            requestOptions.headers["X-CSRF-Token"] = csrfToken;
        }
        if (options.idempotencyKey) {
            requestOptions.headers["X-Idempotency-Key"] = options.idempotencyKey;
            delete requestOptions.idempotencyKey;
        }

        const response = await fetch(url, requestOptions);
        const contentType = response.headers.get("content-type") || "";
        let payload = null;
        if (contentType.includes("application/json")) {
            payload = await response.json().catch(() => null);
        } else {
            payload = await response.text().catch(() => "");
        }
        if (!response.ok) {
            throw new NutritionApiError(
                apiErrorMessage(payload, "AI Pantry could not complete that request."),
                response.status,
                payload && typeof payload === "object" ? payload.field_errors : {},
            );
        }
        return payload && typeof payload === "object" ? payload : {};
    }

    function jsonRequest(url, method, payload, idempotencyKey = "") {
        return apiRequest(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            idempotencyKey,
        });
    }

    function openDialog(dialog, trigger = null) {
        if (!dialog || dialog.open) {
            return;
        }
        dialog.__nutritionReturnFocus = trigger instanceof HTMLElement ? trigger : null;
        body.classList.add("nutrition-dialog-open");
        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "");
        }
    }

    function closeDialog(dialog, restoreFocus = true) {
        if (!dialog || !dialog.open) {
            return;
        }
        const focusTarget = restoreFocus ? dialog.__nutritionReturnFocus : null;
        if (typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
            handleDialogClosed(dialog);
        }
        if (focusTarget && document.contains(focusTarget)) {
            window.requestAnimationFrame(() => focusTarget.focus());
        }
    }

    function handleDialogClosed(dialog) {
        if (!query("dialog[open]")) {
            body.classList.remove("nutrition-dialog-open");
        }
        if (dialog) {
            dialog.classList.remove("is-anchored");
        }
    }

    function initializeDialogs() {
        queryAll(".nutrition-dialog").forEach((dialog) => {
            dialog.addEventListener("close", () => handleDialogClosed(dialog));
            dialog.addEventListener("click", (event) => {
                if (event.target === dialog) {
                    closeDialog(dialog);
                }
            });
        });
        queryAll("[data-nutrition-dialog-close]").forEach((button) => {
            button.addEventListener("click", () => closeDialog(button.closest("dialog")));
        });
    }

    function navigateToDate(isoDate, sourceUrl = window.location.href) {
        if (!parseIsoDate(isoDate) || isoDate > body.dataset.todayDate) {
            return;
        }
        const url = new URL(sourceUrl, window.location.href);
        url.searchParams.set(body.dataset.dateQueryKey || "date", isoDate);
        window.location.assign(url.toString());
    }

    function initializeDateNavigation() {
        queryAll("[data-nutrition-selected-date-label]").forEach((label) => {
            const value = label.getAttribute("datetime") || body.dataset.selectedDate;
            label.textContent = longDateLabel(value);
        });
        queryAll("[data-meal-date-label]").forEach((label) => {
            const value = label.getAttribute("datetime") || body.dataset.selectedDate;
            label.textContent = longDateLabel(value);
        });
        queryAll("[data-nutrition-date-value]").forEach((link) => {
            link.addEventListener("click", (event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                    return;
                }
                event.preventDefault();
                navigateToDate(link.dataset.nutritionDateValue, link.href);
            });
        });
        queryAll("[data-nutrition-date-step]").forEach((button) => {
            button.addEventListener("click", () => {
                const next = addLocalDays(body.dataset.selectedDate, Number(button.dataset.nutritionDateStep));
                if (next) {
                    navigateToDate(isoFromDate(next));
                }
            });
        });
        queryAll("[data-nutrition-filter-key]").forEach((link) => {
            link.addEventListener("click", (event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                    return;
                }
                event.preventDefault();
                const url = new URL(link.href, window.location.href);
                url.searchParams.set(body.dataset.dateQueryKey || "date", body.dataset.selectedDate);
                url.searchParams.set(link.dataset.nutritionFilterKey, link.dataset.nutritionFilterValue);
                window.location.assign(url.toString());
            });
        });
    }

    function selectedCalendarDate() {
        const target = state.activeCalendarTrigger?.dataset.calendarTarget;
        if (target === "form") {
            const input = query('[data-nutrition-meal-form] input[name="local_date"]');
            return input?.value || body.dataset.selectedDate;
        }
        return body.dataset.selectedDate;
    }

    function positionCalendar(dialog, trigger) {
        if (!dialog || !trigger || window.matchMedia("(max-width: 700px)").matches) {
            dialog?.classList.remove("is-anchored");
            return;
        }
        dialog.classList.add("is-anchored");
        const rect = trigger.getBoundingClientRect();
        const width = Math.min(360, window.innerWidth - 24);
        const measuredHeight = dialog.offsetHeight || 470;
        const left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12));
        let top = rect.bottom + 8;
        if (top + measuredHeight > window.innerHeight - 12) {
            top = Math.max(12, rect.top - measuredHeight - 8);
        }
        dialog.style.setProperty("--nutrition-calendar-left", `${Math.round(left)}px`);
        dialog.style.setProperty("--nutrition-calendar-top", `${Math.round(top)}px`);
    }

    function renderCalendar(focusIso = "") {
        const dialog = query("[data-nutrition-calendar-dialog]");
        const grid = query("[data-calendar-grid]", dialog || document);
        if (!dialog || !grid || !state.calendarView) {
            return;
        }
        const view = state.calendarView;
        const year = view.getFullYear();
        const month = view.getMonth();
        const first = new Date(year, month, 1, 12);
        const daysInMonth = new Date(year, month + 1, 0, 12).getDate();
        const mondayOffset = (first.getDay() + 6) % 7;
        const selectedIso = selectedCalendarDate();
        const todayIso = body.dataset.todayDate;
        const monthLabel = query("[data-calendar-month-label]", dialog);
        if (monthLabel) {
            monthLabel.textContent = new Intl.DateTimeFormat(undefined, {
                month: "long",
                year: "numeric",
            }).format(first);
        }

        grid.replaceChildren();
        for (let index = 0; index < mondayOffset; index += 1) {
            const spacer = document.createElement("span");
            spacer.className = "nutrition-calendar-spacer";
            spacer.setAttribute("aria-hidden", "true");
            grid.appendChild(spacer);
        }
        for (let day = 1; day <= daysInMonth; day += 1) {
            const date = new Date(year, month, day, 12);
            const iso = isoFromDate(date);
            const button = document.createElement("button");
            button.type = "button";
            button.className = "nutrition-calendar-day";
            button.textContent = String(day);
            button.dataset.calendarDate = iso;
            button.setAttribute("aria-label", longDateLabel(iso));
            if (iso === selectedIso) {
                button.classList.add("is-selected");
                button.setAttribute("aria-selected", "true");
            } else {
                button.setAttribute("aria-selected", "false");
            }
            if (iso === todayIso) {
                button.classList.add("is-today");
                button.setAttribute("aria-label", `${longDateLabel(iso)}, today`);
            }
            if (iso > todayIso) {
                button.disabled = true;
                button.setAttribute("aria-disabled", "true");
                button.setAttribute("aria-label", `${longDateLabel(iso)}, unavailable`);
            }
            button.addEventListener("click", () => chooseCalendarDate(iso));
            grid.appendChild(button);
        }

        const nextMonthButton = query('[data-calendar-month-step="1"]', dialog);
        if (nextMonthButton) {
            const today = parseIsoDate(todayIso);
            const atCurrentOrFutureMonth = today
                ? (year > today.getFullYear() || (year === today.getFullYear() && month >= today.getMonth()))
                : false;
            nextMonthButton.disabled = atCurrentOrFutureMonth;
            nextMonthButton.setAttribute("aria-disabled", atCurrentOrFutureMonth ? "true" : "false");
        }

        if (focusIso) {
            window.requestAnimationFrame(() => {
                const target = query(`[data-calendar-date="${focusIso}"]`, grid);
                target?.focus();
            });
        }
    }

    function chooseCalendarDate(isoDate) {
        if (!parseIsoDate(isoDate) || isoDate > body.dataset.todayDate) {
            return;
        }
        const dialog = query("[data-nutrition-calendar-dialog]");
        if (state.activeCalendarTrigger?.dataset.calendarTarget === "form") {
            const form = query("[data-nutrition-meal-form]");
            const input = query('input[name="local_date"]', form || document);
            const label = query("[data-meal-date-label]", form || document);
            if (input) {
                input.value = isoDate;
                input.dispatchEvent(new Event("change", { bubbles: true }));
            }
            if (label) {
                label.setAttribute("datetime", isoDate);
                label.textContent = longDateLabel(isoDate);
            }
            clearMealFieldError("local_date");
            closeDialog(dialog);
            return;
        }
        closeDialog(dialog, false);
        navigateToDate(isoDate);
    }

    function moveCalendarFocus(currentIso, dayDelta) {
        const targetDate = addLocalDays(currentIso, dayDelta);
        const targetIso = isoFromDate(targetDate);
        if (!targetDate || targetIso > body.dataset.todayDate) {
            return;
        }
        if (
            targetDate.getFullYear() !== state.calendarView.getFullYear()
            || targetDate.getMonth() !== state.calendarView.getMonth()
        ) {
            state.calendarView = new Date(targetDate.getFullYear(), targetDate.getMonth(), 1, 12);
            renderCalendar(targetIso);
            return;
        }
        query(`[data-calendar-date="${targetIso}"]`)?.focus();
    }

    function initializeCalendar() {
        const dialog = query("[data-nutrition-calendar-dialog]");
        if (!dialog) {
            return;
        }
        queryAll("[data-nutrition-calendar-open]").forEach((trigger) => {
            trigger.addEventListener("click", () => {
                state.activeCalendarTrigger = trigger;
                const selected = parseIsoDate(selectedCalendarDate()) || parseIsoDate(body.dataset.todayDate) || new Date();
                state.calendarView = new Date(selected.getFullYear(), selected.getMonth(), 1, 12);
                positionCalendar(dialog, trigger);
                renderCalendar();
                openDialog(dialog, trigger);
                window.requestAnimationFrame(() => {
                    positionCalendar(dialog, trigger);
                    const selectedButton = query(".nutrition-calendar-day.is-selected:not(:disabled)", dialog);
                    (selectedButton || query(".nutrition-calendar-day:not(:disabled)", dialog))?.focus();
                });
            });
        });
        queryAll("[data-calendar-month-step]", dialog).forEach((button) => {
            button.addEventListener("click", () => {
                if (!state.calendarView) {
                    return;
                }
                state.calendarView = new Date(
                    state.calendarView.getFullYear(),
                    state.calendarView.getMonth() + Number(button.dataset.calendarMonthStep),
                    1,
                    12,
                );
                renderCalendar();
            });
        });
        query("[data-calendar-today]", dialog)?.addEventListener("click", () => {
            chooseCalendarDate(body.dataset.todayDate);
        });
        query("[data-calendar-grid]", dialog)?.addEventListener("keydown", (event) => {
            const current = event.target.closest("[data-calendar-date]");
            if (!current) {
                return;
            }
            const deltas = {
                ArrowLeft: -1,
                ArrowRight: 1,
                ArrowUp: -7,
                ArrowDown: 7,
            };
            if (Object.prototype.hasOwnProperty.call(deltas, event.key)) {
                event.preventDefault();
                moveCalendarFocus(current.dataset.calendarDate, deltas[event.key]);
            } else if (event.key === "Home" || event.key === "End") {
                event.preventDefault();
                const currentDate = parseIsoDate(current.dataset.calendarDate);
                const weekdayFromMonday = (currentDate.getDay() + 6) % 7;
                moveCalendarFocus(current.dataset.calendarDate, event.key === "Home" ? -weekdayFromMonday : 6 - weekdayFromMonday);
            } else if (event.key === "PageUp" || event.key === "PageDown") {
                event.preventDefault();
                const direction = event.key === "PageUp" ? -1 : 1;
                const date = parseIsoDate(current.dataset.calendarDate);
                date.setMonth(date.getMonth() + direction);
                const targetIso = isoFromDate(date);
                if (targetIso <= body.dataset.todayDate) {
                    state.calendarView = new Date(date.getFullYear(), date.getMonth(), 1, 12);
                    renderCalendar(targetIso);
                }
            }
        });
        window.addEventListener("resize", () => {
            if (dialog.open) {
                positionCalendar(dialog, state.activeCalendarTrigger);
            }
        });
    }

    function mealForm() {
        return query("[data-nutrition-meal-form]");
    }

    function findMealError(name) {
        return queryAll("[data-field-error]", mealForm() || document)
            .find((element) => element.dataset.fieldError === name) || null;
    }

    function mealFieldControls(name) {
        const form = mealForm();
        if (!form) {
            return [];
        }
        if (name === "source") {
            return [query(".nutrition-source-picker", form)].filter(Boolean);
        }
        if (name === "photo") {
            return queryAll("[data-photo-input]", form);
        }
        if (name === "local_date") {
            return [query("[data-nutrition-calendar-open][data-calendar-target='form']", form)].filter(Boolean);
        }
        return queryAll(`[name="${name}"]`, form);
    }

    function setMealFieldError(name, message) {
        const error = findMealError(name);
        if (error) {
            error.textContent = message;
        }
        mealFieldControls(name).forEach((control) => control.setAttribute("aria-invalid", "true"));
    }

    function clearMealFieldError(name) {
        const error = findMealError(name);
        if (error) {
            error.textContent = "";
        }
        mealFieldControls(name).forEach((control) => control.removeAttribute("aria-invalid"));
    }

    function clearMealErrors() {
        const form = mealForm();
        if (!form) {
            return;
        }
        queryAll("[data-field-error]", form).forEach((element) => {
            element.textContent = "";
        });
        queryAll('[aria-invalid="true"]', form).forEach((element) => element.removeAttribute("aria-invalid"));
        queryAll("[data-row-error]", form).forEach((element) => {
            element.textContent = "";
        });
    }

    function activeSourceType() {
        return query('[name="source_type"]:checked', mealForm() || document)?.value || "";
    }

    function updateSourcePanels() {
        const sourceType = activeSourceType();
        queryAll("[data-source-panel]", mealForm() || document).forEach((panel) => {
            panel.hidden = panel.dataset.sourcePanel !== sourceType;
        });
        const servings = query("[data-source-servings]", mealForm() || document);
        if (servings) {
            servings.hidden = sourceType === "details";
        }
        clearMealFieldError("source");
    }

    function validPhotoFile(file) {
        if (!file) {
            return { valid: false, message: "" };
        }
        const extension = String(file.name || "").split(".").pop().toLowerCase();
        if ((file.type && !PHOTO_TYPES.has(file.type.toLowerCase())) || (!file.type && !PHOTO_EXTENSIONS.has(extension))) {
            return {
                valid: false,
                message: "Choose a JPEG, PNG, WebP, HEIC, or HEIF meal photo.",
            };
        }
        const maxBytes = Number(body.dataset.photoMaxBytes || 10485760);
        if (!Number.isFinite(file.size) || file.size <= 0) {
            return { valid: false, message: "The selected meal photo is empty." };
        }
        if (file.size > maxBytes) {
            return { valid: false, message: `Choose a meal photo smaller than ${Math.round(maxBytes / 1048576)} MB.` };
        }
        return { valid: true, message: "" };
    }

    function revokePhotoObjectUrl() {
        if (state.photoObjectUrl) {
            URL.revokeObjectURL(state.photoObjectUrl);
            state.photoObjectUrl = "";
        }
    }

    function showPhotoPreview(file) {
        const form = mealForm();
        const empty = query("[data-photo-empty]", form || document);
        const preview = query("[data-photo-preview]", form || document);
        const image = query("[data-photo-preview-image]", form || document);
        const name = query("[data-photo-name]", form || document);
        if (!empty || !preview || !image) {
            return;
        }
        revokePhotoObjectUrl();
        state.photoObjectUrl = URL.createObjectURL(file);
        image.src = state.photoObjectUrl;
        if (name) {
            name.textContent = file.name || "Meal photo";
        }
        empty.hidden = true;
        preview.hidden = false;
        state.hasExistingPhoto = false;
    }

    function removePhoto() {
        revokePhotoObjectUrl();
        state.photoFile = null;
        state.mediaId = "";
        state.hasExistingPhoto = false;
        queryAll("[data-photo-input]", mealForm() || document).forEach((input) => {
            input.value = "";
        });
        const preview = query("[data-photo-preview]", mealForm() || document);
        const empty = query("[data-photo-empty]", mealForm() || document);
        const image = query("[data-photo-preview-image]", mealForm() || document);
        if (preview) {
            preview.hidden = true;
        }
        if (empty) {
            empty.hidden = false;
        }
        image?.removeAttribute("src");
        clearMealFieldError("photo");
    }

    function initializePhotoField() {
        const form = mealForm();
        if (!form) {
            return;
        }
        state.mediaId = form.dataset.mediaId || "";
        state.analysisId = form.dataset.analysisId || "";
        state.hasExistingPhoto = Boolean(query("[data-photo-preview]:not([hidden])", form));
        queryAll("[data-photo-input]", form).forEach((input) => {
            input.addEventListener("change", () => {
                const file = input.files?.[0] || null;
                if (!file) {
                    return;
                }
                const validation = validPhotoFile(file);
                if (!validation.valid) {
                    input.value = "";
                    setMealFieldError("photo", validation.message);
                    return;
                }
                queryAll("[data-photo-input]", form).forEach((otherInput) => {
                    if (otherInput !== input) {
                        otherInput.value = "";
                    }
                });
                state.photoFile = file;
                state.mediaId = "";
                state.analysisId = "";
                clearMealFieldError("photo");
                clearMealFieldError("source");
                showPhotoPreview(file);
            });
        });
        queryAll("[data-photo-picker-target]", form).forEach((button) => {
            button.addEventListener("click", () => {
                const input = document.getElementById(button.dataset.photoPickerTarget || "");
                if (input instanceof HTMLInputElement) {
                    input.click();
                }
            });
        });
        query("[data-photo-remove]", form)?.addEventListener("click", removePhoto);
        window.addEventListener("pagehide", revokePhotoObjectUrl, { once: true });
    }

    function initializeDescription() {
        const textarea = query('[data-nutrition-meal-form] textarea[name="description"]');
        const counter = query("[data-description-count]", mealForm() || document);
        if (!textarea || !counter) {
            return;
        }
        const update = () => {
            if (textarea.value.length > 200) {
                textarea.value = textarea.value.slice(0, 200);
                setMealFieldError("description", "Descriptions are limited to 200 characters.");
            }
            counter.textContent = String(textarea.value.length);
            if (textarea.value.length <= 200 && !textarea.dataset.pasteExceeded) {
                clearMealFieldError("description");
            }
            if (textarea.value.trim()) {
                clearMealFieldError("source");
            }
        };
        textarea.addEventListener("paste", (event) => {
            const pasted = event.clipboardData?.getData("text") || "";
            const start = textarea.selectionStart ?? textarea.value.length;
            const end = textarea.selectionEnd ?? start;
            const available = 200 - (textarea.value.length - (end - start));
            if (pasted.length > available) {
                event.preventDefault();
                const accepted = pasted.slice(0, Math.max(0, available));
                textarea.setRangeText(accepted, start, end, "end");
                textarea.dataset.pasteExceeded = "true";
                setMealFieldError("description", "The pasted description exceeded 200 characters; only the text that fits was added.");
                update();
            }
        });
        textarea.addEventListener("input", () => {
            if (textarea.dataset.pasteExceeded && textarea.value.length < 200) {
                delete textarea.dataset.pasteExceeded;
            }
            update();
        });
        update();
    }

    function validateMealDetails() {
        const form = mealForm();
        if (!form) {
            return false;
        }
        clearMealErrors();
        let valid = true;
        const mealType = query('[name="meal_type"]', form)?.value || "";
        const localDate = query('[name="local_date"]', form)?.value || "";
        const sourceType = activeSourceType();
        const description = query('[name="description"]', form)?.value || "";
        const recipeId = query('[name="recipe_id"]', form)?.value || "";
        const savedMealId = query('[name="saved_meal_id"]', form)?.value || "";
        const servings = nullableNumber(query('[name="servings"]', form)?.value);

        if (!MEAL_TYPES.has(mealType)) {
            setMealFieldError("meal_type", "Choose Breakfast, Lunch, Dinner, or Snack.");
            valid = false;
        }
        if (!parseIsoDate(localDate)) {
            setMealFieldError("local_date", "Choose a valid date.");
            valid = false;
        } else if (localDate > body.dataset.todayDate) {
            setMealFieldError("local_date", "Future dates are not available for nutrition entries.");
            valid = false;
        }
        if (description.length > 200) {
            setMealFieldError("description", "Descriptions are limited to 200 characters.");
            valid = false;
        }
        if (!sourceType) {
            setMealFieldError("source", "Choose how you want to log this meal.");
            valid = false;
        } else if (sourceType === "details" && !description.trim() && !state.photoFile && !state.mediaId && !state.hasExistingPhoto) {
            setMealFieldError("source", "Add a meal photo or description before continuing.");
            valid = false;
        } else if (sourceType === "recipe" && !recipeId) {
            setMealFieldError("recipe_id", "Choose an AI Pantry recipe.");
            setMealFieldError("source", "Choose a recipe before continuing.");
            valid = false;
        } else if (sourceType === "saved" && !savedMealId) {
            setMealFieldError("saved_meal_id", "Choose a Saved Meal.");
            setMealFieldError("source", "Choose a Saved Meal before continuing.");
            valid = false;
        }
        if (sourceType !== "details" && (servings === null || servings < 0.25 || servings > 100)) {
            setMealFieldError("servings", "Enter a serving amount from 0.25 to 100.");
            valid = false;
        }

        if (!valid) {
            const firstInvalid = query('[aria-invalid="true"]', form);
            firstInvalid?.focus();
        }
        return valid;
    }

    function analysisFormData() {
        const form = mealForm();
        const sourceType = activeSourceType();
        const data = new FormData();
        data.set("meal_type", query('[name="meal_type"]', form)?.value || "");
        data.set("local_date", query('[name="local_date"]', form)?.value || "");
        data.set("source_type", sourceType);
        data.set("client_request_id", createRequestId());
        const zone = timeZonePayload();
        data.set("timezone", zone.timezone);
        data.set("timezone_offset_minutes", String(zone.timezone_offset_minutes));
        if (sourceType === "details") {
            data.set("description", query('[name="description"]', form)?.value || "");
            if (state.photoFile) {
                data.set("photo", state.photoFile, state.photoFile.name || "meal-photo");
            }
            if (state.mediaId) {
                data.set("photo_id", state.mediaId);
            }
        } else if (sourceType === "recipe") {
            data.set("recipe_id", query('[name="recipe_id"]', form)?.value || "");
            data.set("servings", query('[name="servings"]', form)?.value || "1");
        } else if (sourceType === "saved") {
            data.set("saved_meal_id", query('[name="saved_meal_id"]', form)?.value || "");
            data.set("servings", query('[name="servings"]', form)?.value || "1");
        }
        return data;
    }

    function normalizedFoodItem(item = {}) {
        const quantity = nullableNumber(item.quantity ?? item.serving_amount ?? item.amount) ?? 1;
        const totalSource = item.nutrition && typeof item.nutrition === "object"
            ? item.nutrition
            : (item.totals && typeof item.totals === "object" ? item.totals : item);
        const perUnitSource = item.nutrition_per_unit && typeof item.nutrition_per_unit === "object"
            ? item.nutrition_per_unit
            : {};
        const nutrition = {};
        const perUnit = {};
        NUTRIENTS.forEach((key) => {
            let totalValue = nutrientNumber(totalSource, key);
            let perUnitValue = nutrientNumber(perUnitSource, key);
            if (totalValue === null && perUnitValue !== null) {
                totalValue = perUnitValue * quantity;
            }
            if (perUnitValue === null && totalValue !== null && quantity > 0) {
                perUnitValue = totalValue / quantity;
            }
            nutrition[key] = totalValue === null ? null : rounded(totalValue, 2);
            perUnit[key] = perUnitValue === null ? null : rounded(perUnitValue, 6);
        });
        return {
            id: item.id || item.food_item_id || "",
            name: item.name || item.food || item.label || "",
            quantity,
            unit: item.unit || item.serving_unit || item.portion_unit || "serving",
            nutrition,
            nutrition_per_unit: perUnit,
            confidence: item.confidence ?? item.confidence_score ?? null,
        };
    }

    function reviewTemplate() {
        return query("#nutritionReviewRowTemplate");
    }

    function buildReviewRow(rawItem = {}) {
        const template = reviewTemplate();
        if (!template) {
            return null;
        }
        const item = normalizedFoodItem(rawItem);
        const row = template.content.firstElementChild.cloneNode(true);
        row.dataset.itemId = item.id;
        row.dataset.baseServing = "1";
        const nameInput = query('[data-item-field="name"]', row);
        const quantityInput = query('[data-item-field="serving_amount"]', row);
        const unitInput = query('[data-item-field="serving_unit"]', row);
        nameInput.value = item.name;
        quantityInput.value = editableNumber(item.quantity);
        unitInput.value = item.unit;
        NUTRIENTS.forEach((key) => {
            const input = query(`[data-nutrient="${key}"]`, row);
            if (!input) {
                return;
            }
            input.value = editableNumber(item.nutrition[key]);
            input.dataset.perUnit = item.nutrition_per_unit[key] === null
                ? ""
                : String(item.nutrition_per_unit[key]);
        });
        const confidence = nullableNumber(item.confidence);
        const confidenceLabel = query("[data-item-confidence]", row);
        if (confidence !== null && confidenceLabel) {
            const percent = confidence <= 1 ? confidence * 100 : confidence;
            confidenceLabel.textContent = `AI confidence: ${Math.max(0, Math.min(100, Math.round(percent)))}%`;
            confidenceLabel.hidden = false;
            row.dataset.confidence = String(confidence);
        }
        return row;
    }

    function showReview(items = [], options = {}) {
        const form = mealForm();
        const review = query("[data-meal-review]", form || document);
        const list = query("[data-review-list]", form || document);
        if (!review || !list) {
            return;
        }
        list.replaceChildren();
        const normalizedItems = Array.isArray(items) ? items : [];
        normalizedItems.forEach((item) => {
            const row = buildReviewRow(item);
            if (row) {
                list.appendChild(row);
            }
        });
        if (!list.children.length && options.ensureBlank) {
            const row = buildReviewRow({ quantity: 1, unit: "serving" });
            if (row) {
                list.appendChild(row);
            }
        }
        review.hidden = false;
        recalculateReviewTotals();
        if (options.focus) {
            window.requestAnimationFrame(() => {
                review.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
                query('[data-item-field="name"]', list)?.focus({ preventScroll: true });
            });
        }
    }

    function reducedMotion() {
        return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    function scaleReviewRow(row) {
        const quantity = nullableNumber(query('[data-item-field="serving_amount"]', row)?.value);
        if (quantity === null || quantity <= 0) {
            recalculateReviewTotals();
            return;
        }
        NUTRIENTS.forEach((key) => {
            const input = query(`[data-nutrient="${key}"]`, row);
            const perUnit = nullableNumber(input?.dataset.perUnit);
            if (input && perUnit !== null) {
                input.value = editableNumber(perUnit * quantity);
            }
        });
        recalculateReviewTotals();
    }

    function updatePerUnitFromInput(input, row) {
        const value = nullableNumber(input.value);
        const quantity = nullableNumber(query('[data-item-field="serving_amount"]', row)?.value);
        input.dataset.perUnit = value === null || quantity === null || quantity <= 0
            ? ""
            : String(value / quantity);
        recalculateReviewTotals();
    }

    function reviewTotals() {
        const totals = Object.fromEntries(NUTRIENTS.map((key) => [key, null]));
        queryAll("[data-review-row]", mealForm() || document).forEach((row) => {
            NUTRIENTS.forEach((key) => {
                const value = nullableNumber(query(`[data-nutrient="${key}"]`, row)?.value);
                if (value !== null) {
                    totals[key] = (totals[key] ?? 0) + value;
                }
            });
        });
        NUTRIENTS.forEach((key) => {
            if (totals[key] !== null) {
                totals[key] = rounded(totals[key], 2);
            }
        });
        return totals;
    }

    function recalculateReviewTotals() {
        const totals = reviewTotals();
        NUTRIENTS.forEach((key) => {
            const output = query(`[data-review-total="${key}"]`, mealForm() || document);
            if (output) {
                output.textContent = displayNumber(totals[key], key === "calories" ? 0 : 1);
            }
        });
        return totals;
    }

    function clearReviewValidation() {
        queryAll("[data-review-row]", mealForm() || document).forEach((row) => {
            queryAll('[aria-invalid="true"]', row).forEach((input) => input.removeAttribute("aria-invalid"));
            const error = query("[data-row-error]", row);
            if (error) {
                error.textContent = "";
            }
        });
    }

    function validateReview() {
        const rows = queryAll("[data-review-row]", mealForm() || document);
        clearReviewValidation();
        if (!rows.length) {
            setStatus(query("[data-meal-form-status]"), "Add at least one food item before saving.", true);
            return false;
        }
        let valid = true;
        let hasNutrition = false;
        rows.forEach((row) => {
            const messages = [];
            const name = query('[data-item-field="name"]', row);
            const quantity = query('[data-item-field="serving_amount"]', row);
            const unit = query('[data-item-field="serving_unit"]', row);
            const quantityValue = nullableNumber(quantity?.value);
            if (!name?.value.trim()) {
                name?.setAttribute("aria-invalid", "true");
                messages.push("Enter a food name.");
            }
            if (quantityValue === null || quantityValue <= 0 || quantityValue > 10000) {
                quantity?.setAttribute("aria-invalid", "true");
                messages.push("Enter a serving amount greater than zero.");
            }
            if (!unit?.value.trim()) {
                unit?.setAttribute("aria-invalid", "true");
                messages.push("Enter a serving unit.");
            }
            NUTRIENTS.forEach((key) => {
                const input = query(`[data-nutrient="${key}"]`, row);
                const value = nullableNumber(input?.value);
                if (value !== null) {
                    hasNutrition = true;
                    if (value < 0 || value > 100000) {
                        input?.setAttribute("aria-invalid", "true");
                        messages.push(`${key === "carbohydrates" ? "Carbohydrates" : key[0].toUpperCase() + key.slice(1)} must be from 0 to 100,000.`);
                    }
                }
            });
            const error = query("[data-row-error]", row);
            if (messages.length && error) {
                error.textContent = messages.join(" ");
                valid = false;
            }
        });
        if (!hasNutrition) {
            setStatus(query("[data-meal-form-status]"), "Enter calories or at least one nutrient before saving.", true);
            valid = false;
        }
        if (!valid) {
            query('[data-review-row] [aria-invalid="true"]', mealForm() || document)?.focus();
        }
        return valid;
    }

    function collectReviewItems() {
        return queryAll("[data-review-row]", mealForm() || document).map((row) => {
            const quantity = nullableNumber(query('[data-item-field="serving_amount"]', row)?.value) ?? 1;
            const nutrition = {};
            const nutritionPerUnit = {};
            NUTRIENTS.forEach((key) => {
                const input = query(`[data-nutrient="${key}"]`, row);
                const total = nullableNumber(input?.value);
                let perUnit = nullableNumber(input?.dataset.perUnit);
                if (perUnit === null && total !== null && quantity > 0) {
                    perUnit = total / quantity;
                }
                nutrition[key] = total === null ? null : rounded(total, 2);
                nutritionPerUnit[key] = perUnit === null ? null : rounded(perUnit, 6);
            });
            return {
                id: row.dataset.itemId || undefined,
                name: query('[data-item-field="name"]', row)?.value.trim() || "",
                quantity,
                unit: query('[data-item-field="serving_unit"]', row)?.value.trim() || "",
                nutrition_per_unit: nutritionPerUnit,
                nutrition,
                confidence: nullableNumber(row.dataset.confidence),
            };
        });
    }

    function applyMealApiFieldErrors(fieldErrors) {
        if (!fieldErrors || typeof fieldErrors !== "object") {
            return;
        }
        Object.entries(fieldErrors).forEach(([field, message]) => {
            const text = Array.isArray(message) ? message.join(" ") : String(message || "");
            if (field.startsWith("food_items") || field.startsWith("nutrition")) {
                setStatus(query("[data-meal-form-status]"), text, true);
                return;
            }
            const aliases = {
                date: "local_date",
                meal_source: "source",
                photo_id: "photo",
                recipe_snapshot: "recipe_id",
                saved_meal_snapshot: "saved_meal_id",
            };
            setMealFieldError(aliases[field] || field, text);
        });
    }

    function analysisItems(payload) {
        const analysis = payload?.analysis || payload?.review || payload?.data || payload || {};
        if (Array.isArray(analysis)) {
            return analysis;
        }
        return analysis.food_items || analysis.items || payload?.food_items || payload?.items || [];
    }

    async function analyzeMeal(button) {
        if (state.analysisPending || !validateMealDetails()) {
            return;
        }
        state.analysisPending = true;
        setButtonPending(button, true);
        const formStatus = query("[data-meal-form-status]");
        setStatus(formStatus, "Analyzing your meal…");
        try {
            const payload = await apiRequest(body.dataset.analyzeApiUrl, {
                method: "POST",
                body: analysisFormData(),
                idempotencyKey: createRequestId(),
            });
            const items = analysisItems(payload);
            const analysis = payload.analysis || payload.review || payload.data || payload;
            state.mediaId = analysis.media_id || analysis.photo_id || payload.media_id || payload.photo_id || state.mediaId;
            state.analysisId = analysis.analysis_id || analysis.id || payload.analysis_id || state.analysisId;
            if (!Array.isArray(items) || !items.length) {
                throw new NutritionApiError("AI analysis did not return any food items.", 422);
            }
            showReview(items, { focus: true });
            setStatus(formStatus, "Review the estimated food and nutrition below before saving.");
        } catch (error) {
            if (error instanceof NutritionApiError) {
                applyMealApiFieldErrors(error.fieldErrors);
            }
            showReview([], { ensureBlank: true, focus: true });
            setStatus(
                formStatus,
                `${error.message || "AI analysis is unavailable."} Enter the food and nutrition manually below; no values were fabricated.`,
                true,
            );
        } finally {
            state.analysisPending = false;
            setButtonPending(button, false);
        }
    }

    function startManualReview() {
        if (!validateMealDetails()) {
            return;
        }
        showReview([], { ensureBlank: true, focus: true });
        setStatus(query("[data-meal-form-status]"), "Enter the meal’s nutrition, then review and save.");
    }

    function mealSavePayload() {
        const form = mealForm();
        const sourceType = activeSourceType();
        const localDate = query('[name="local_date"]', form)?.value || body.dataset.selectedDate;
        const localTimeInput = query('[name="local_time"]', form);
        const localTime = localTimeInput?.value || currentLocalTime();
        if (localTimeInput && !localTimeInput.value) {
            localTimeInput.value = localTime;
        }
        const zone = timeZonePayload();
        const payload = {
            date: localDate,
            local_date: localDate,
            local_time: localTime,
            meal_type: query('[name="meal_type"]', form)?.value || "",
            source_type: sourceType,
            description: sourceType === "details" ? query('[name="description"]', form)?.value.trim() || "" : "",
            photo_id: sourceType === "details" ? state.mediaId || null : null,
            recipe_id: sourceType === "recipe" ? query('[name="recipe_id"]', form)?.value || null : null,
            saved_meal_id: sourceType === "saved" ? query('[name="saved_meal_id"]', form)?.value || null : null,
            servings: sourceType === "details" ? 1 : nullableNumber(query('[name="servings"]', form)?.value),
            food_items: collectReviewItems(),
            nutrition: reviewTotals(),
            analysis_id: state.analysisId || null,
            client_request_id: state.mealRequestId,
            is_estimate: true,
            ...zone,
        };
        const saveTemplate = query("[data-save-template-toggle]", form)?.checked || false;
        payload.save_as_template = saveTemplate;
        payload.template_name = saveTemplate ? query('[name="template_name"]', form)?.value.trim() || "" : "";
        return payload;
    }

    function mealDashboardUrl(date) {
        const url = new URL(body.dataset.dashboardUrl || "/nutrition", window.location.href);
        url.searchParams.set(body.dataset.dateQueryKey || "date", date);
        url.searchParams.set("meal", "all");
        return url.toString();
    }

    function submitMealPayload(form, payload) {
        const method = form.dataset.editingId ? "PATCH" : "POST";
        if (activeSourceType() === "details" && state.photoFile && !state.mediaId) {
            const multipart = new FormData();
            multipart.set("payload", JSON.stringify(payload));
            multipart.set("meal_type", payload.meal_type);
            multipart.set("local_date", payload.local_date);
            multipart.set("local_time", payload.local_time);
            multipart.set("description", payload.description);
            multipart.set("food_items", JSON.stringify(payload.food_items));
            multipart.set("nutrition", JSON.stringify(payload.nutrition));
            multipart.set("client_request_id", payload.client_request_id);
            multipart.set("photo", state.photoFile, state.photoFile.name || "meal-photo");
            return apiRequest(form.dataset.saveUrl, {
                method,
                body: multipart,
                idempotencyKey: state.mealRequestId,
            });
        }
        return jsonRequest(form.dataset.saveUrl, method, payload, state.mealRequestId);
    }

    async function saveMeal(event) {
        event.preventDefault();
        const form = mealForm();
        if (!form || state.mealPending) {
            return;
        }
        const review = query("[data-meal-review]", form);
        if (review?.hidden) {
            setStatus(query("[data-meal-form-status]", form), "Analyze the meal or enter nutrition manually before saving.", true);
            query("[data-analyze-meal]", form)?.focus();
            return;
        }
        const detailValid = validateMealDetails();
        const reviewValid = validateReview();
        const templateToggle = query("[data-save-template-toggle]", form);
        if (templateToggle?.checked && !query('[name="template_name"]', form)?.value.trim()) {
            setMealFieldError("template_name", "Enter a useful name for this Saved Meal.");
            query('[name="template_name"]', form)?.focus();
            return;
        }
        if (!detailValid || !reviewValid) {
            return;
        }

        const saveButton = query("[data-save-meal]", form);
        state.mealPending = true;
        setButtonPending(saveButton, true);
        setStatus(query("[data-meal-form-status]", form), "Saving meal…");
        const payload = mealSavePayload();
        try {
            const result = await submitMealPayload(form, payload);
            setStatus(query("[data-meal-form-status]", form), "Meal saved.");
            window.location.assign(result.redirect_url || mealDashboardUrl(payload.local_date));
        } catch (error) {
            if (error instanceof NutritionApiError) {
                applyMealApiFieldErrors(error.fieldErrors);
            }
            setStatus(query("[data-meal-form-status]", form), error.message || "Unable to save this meal.", true);
        } finally {
            state.mealPending = false;
            setButtonPending(saveButton, false);
        }
    }

    function initializeMealForm() {
        const form = mealForm();
        if (!form) {
            return;
        }
        initializePhotoField();
        initializeDescription();
        queryAll('[name="source_type"]', form).forEach((radio) => radio.addEventListener("change", updateSourcePanels));
        updateSourcePanels();
        query("[data-analyze-meal]", form)?.addEventListener("click", (event) => analyzeMeal(event.currentTarget));
        query("[data-start-manual]", form)?.addEventListener("click", startManualReview);
        query("[data-add-food]", form)?.addEventListener("click", () => {
            const row = buildReviewRow({ quantity: 1, unit: "serving" });
            if (row) {
                query("[data-review-list]", form)?.appendChild(row);
                recalculateReviewTotals();
                query('[data-item-field="name"]', row)?.focus();
            }
        });
        query("[data-review-list]", form)?.addEventListener("click", (event) => {
            const removeButton = event.target.closest("[data-remove-food]");
            if (!removeButton) {
                return;
            }
            removeButton.closest("[data-review-row]")?.remove();
            recalculateReviewTotals();
        });
        query("[data-review-list]", form)?.addEventListener("input", (event) => {
            const row = event.target.closest("[data-review-row]");
            if (!row) {
                return;
            }
            if (event.target.matches('[data-item-field="serving_amount"]')) {
                scaleReviewRow(row);
            } else if (event.target.matches("[data-nutrient]")) {
                updatePerUnitFromInput(event.target, row);
            }
            const error = query("[data-row-error]", row);
            if (error) {
                error.textContent = "";
            }
            event.target.removeAttribute("aria-invalid");
        });
        query("[data-save-template-toggle]", form)?.addEventListener("change", (event) => {
            const nameField = query("[data-template-name-field]", form);
            if (nameField) {
                nameField.hidden = !event.target.checked;
                if (event.target.checked) {
                    query('[name="template_name"]', nameField)?.focus();
                } else {
                    clearMealFieldError("template_name");
                }
            }
        });
        form.addEventListener("submit", saveMeal);

        const initialItems = parseJsonScript(query("[data-initial-review-items]", form), []);
        if (Array.isArray(initialItems) && initialItems.length) {
            showReview(initialItems);
        }
    }

    function savedMealDialog() {
        return query("[data-saved-meal-dialog]");
    }

    function populateSavedMealDialog(source) {
        const dialog = savedMealDialog();
        const form = query("[data-saved-meal-form]", dialog || document);
        if (!dialog || !form || !source) {
            return;
        }
        form.dataset.url = source.dataset.savedUrl || "";
        query('[name="saved_meal_id"]', form).value = source.dataset.savedId || "";
        query('[name="name"]', form).value = source.dataset.savedName || "";
        query('[name="meal_type"]', form).value = source.dataset.savedMealType || "snack";
        query('[name="servings"]', form).value = source.dataset.savedServings || "1";
        queryAll("[data-saved-field-error]", form).forEach((element) => { element.textContent = ""; });
        setStatus(query("[data-saved-dialog-status]", form));
        openDialog(dialog, source instanceof HTMLElement ? source : null);
        window.requestAnimationFrame(() => query('[name="name"]', form)?.focus());
    }

    async function saveSavedMeal(event) {
        event.preventDefault();
        const form = event.currentTarget;
        if (state.savedMealPending) {
            return;
        }
        const name = query('[name="name"]', form)?.value.trim() || "";
        const mealType = query('[name="meal_type"]', form)?.value || "";
        const servings = nullableNumber(query('[name="servings"]', form)?.value);
        let valid = true;
        queryAll("[data-saved-field-error]", form).forEach((element) => { element.textContent = ""; });
        if (!name) {
            query('[data-saved-field-error="name"]', form).textContent = "Enter a Saved Meal name.";
            valid = false;
        }
        if (servings === null || servings < 0.25 || servings > 100) {
            query('[data-saved-field-error="servings"]', form).textContent = "Enter servings from 0.25 to 100.";
            valid = false;
        }
        if (!valid || !MEAL_TYPES.has(mealType)) {
            query('[name="name"]', form)?.focus();
            return;
        }
        const submit = query('[type="submit"]', form);
        state.savedMealPending = true;
        setButtonPending(submit, true);
        setStatus(query("[data-saved-dialog-status]", form), "Saving changes…");
        try {
            await jsonRequest(form.dataset.url, "PATCH", {
                name,
                meal_type: mealType,
                default_meal_type: mealType,
                servings,
                base_servings: servings,
            });
            setStatus(query("[data-saved-dialog-status]", form), "Saved Meal updated.");
            window.location.reload();
        } catch (error) {
            setStatus(query("[data-saved-dialog-status]", form), error.message || "Unable to update this Saved Meal.", true);
        } finally {
            state.savedMealPending = false;
            setButtonPending(submit, false);
        }
    }

    function initializeSavedMeals() {
        queryAll("[data-edit-saved-meal]").forEach((button) => {
            button.addEventListener("click", () => populateSavedMealDialog(button));
        });
        query("[data-saved-meal-form]")?.addEventListener("submit", saveSavedMeal);
        const dialog = savedMealDialog();
        if (dialog?.dataset.autopen === "true") {
            populateSavedMealDialog(dialog);
        }
    }

    function waterDisplayUnit() {
        return query('[data-chart-key="water"]')?.dataset.chartUnit === "mL" ? "ml" : "fl_oz";
    }

    function waterDialog() {
        return query("[data-water-dialog]");
    }

    function populateWaterDialog(source = null) {
        const dialog = waterDialog();
        const form = query("[data-water-form]", dialog || document);
        if (!dialog || !form) {
            return;
        }
        const editing = source?.hasAttribute("data-edit-water") || false;
        form.dataset.url = editing ? source.dataset.waterUrl : body.dataset.waterApiUrl;
        query('[name="entry_id"]', form).value = editing ? source.dataset.waterId || "" : "";
        query('[name="amount"]', form).value = editing ? source.dataset.waterAmount || "" : "";
        query('[name="unit"]', form).value = editing ? source.dataset.waterUnit || "fl_oz" : waterDisplayUnit();
        query('[name="local_time"]', form).value = editing ? source.dataset.waterTime || currentLocalTime() : currentLocalTime();
        query("[data-water-dialog-title]", form).textContent = editing ? "Edit water" : "Add water";
        queryAll("[data-water-field-error]", form).forEach((element) => { element.textContent = ""; });
        setStatus(query("[data-water-dialog-status]", form));
        openDialog(dialog, source);
        window.requestAnimationFrame(() => query('[name="amount"]', form)?.focus());
    }

    function validateWater(amount, unit, localTime, form) {
        queryAll("[data-water-field-error]", form).forEach((element) => { element.textContent = ""; });
        let valid = true;
        const maximum = unit === "ml" ? 10000 : 338;
        if (amount === null || amount <= 0) {
            query('[data-water-field-error="amount"]', form).textContent = "Enter a water amount greater than zero.";
            valid = false;
        } else if (amount > maximum) {
            query('[data-water-field-error="amount"]', form).textContent = `Enter no more than ${maximum.toLocaleString()} ${unit === "ml" ? "mL" : "fl oz"} at a time.`;
            valid = false;
        }
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(localTime)) {
            query('[data-water-field-error="local_time"]', form).textContent = "Choose a valid time.";
            valid = false;
        }
        return valid;
    }

    async function quickAddWater(button) {
        if (button.dataset.pending === "true") {
            return;
        }
        const status = query("[data-water-quick-status]");
        const amount = nullableNumber(button.dataset.amount);
        const unit = button.dataset.unit;
        button.dataset.pending = "true";
        setButtonPending(button, true);
        setStatus(status, `Adding ${displayNumber(amount)} fl oz…`);
        const requestId = createRequestId();
        try {
            await jsonRequest(body.dataset.waterApiUrl, "POST", {
                date: body.dataset.selectedDate,
                local_date: body.dataset.selectedDate,
                local_time: currentLocalTime(),
                amount,
                unit,
                source: "quick_add",
                client_request_id: requestId,
                ...timeZonePayload(),
            }, requestId);
            setStatus(status, `${displayNumber(amount)} fl oz added.`);
            window.location.reload();
        } catch (error) {
            setStatus(status, error.message || "Unable to add water.", true);
        } finally {
            delete button.dataset.pending;
            setButtonPending(button, false);
        }
    }

    async function saveWater(event) {
        event.preventDefault();
        const form = event.currentTarget;
        if (state.waterPending) {
            return;
        }
        const amount = nullableNumber(query('[name="amount"]', form)?.value);
        const unit = query('[name="unit"]', form)?.value || "";
        const localTime = query('[name="local_time"]', form)?.value || "";
        if (!validateWater(amount, unit, localTime, form)) {
            query('[name="amount"]', form)?.focus();
            return;
        }
        const editing = Boolean(query('[name="entry_id"]', form)?.value);
        const submit = query("[data-water-submit]", form);
        const requestId = createRequestId();
        state.waterPending = true;
        setButtonPending(submit, true);
        setStatus(query("[data-water-dialog-status]", form), "Saving water…");
        try {
            await jsonRequest(form.dataset.url, editing ? "PATCH" : "POST", {
                date: body.dataset.selectedDate,
                local_date: body.dataset.selectedDate,
                local_time: localTime,
                amount,
                unit,
                source: editing ? "edited" : "manual",
                client_request_id: requestId,
                ...timeZonePayload(),
            }, requestId);
            setStatus(query("[data-water-dialog-status]", form), "Water saved.");
            window.location.reload();
        } catch (error) {
            setStatus(query("[data-water-dialog-status]", form), error.message || "Unable to save water.", true);
        } finally {
            state.waterPending = false;
            setButtonPending(submit, false);
        }
    }

    function initializeWater() {
        queryAll("[data-water-quick-add]").forEach((button) => {
            button.addEventListener("click", () => quickAddWater(button));
        });
        queryAll("[data-water-custom-open]").forEach((button) => {
            button.addEventListener("click", () => populateWaterDialog(button));
        });
        queryAll("[data-edit-water]").forEach((button) => {
            button.addEventListener("click", () => populateWaterDialog(button));
        });
        query("[data-water-form]")?.addEventListener("submit", saveWater);
    }

    function initializeDeleteConfirmation() {
        const dialog = query("[data-nutrition-confirm-dialog]");
        const deleteButton = query("[data-confirm-delete]", dialog || document);
        if (!dialog || !deleteButton) {
            return;
        }
        queryAll("[data-nutrition-delete]").forEach((trigger) => {
            trigger.addEventListener("click", () => {
                state.deleteUrl = trigger.dataset.deleteUrl || "";
                state.deleteKind = trigger.dataset.deleteKind || "entry";
                const name = trigger.dataset.deleteName || "this entry";
                query("[data-confirm-title]", dialog).textContent = `Delete ${state.deleteKind}?`;
                query("[data-confirm-message]", dialog).textContent = state.deleteKind === "saved meal"
                    ? `Delete “${name}”? Previously logged meals will stay unchanged.`
                    : `Delete “${name}”? This action cannot be undone.`;
                setStatus(query("[data-confirm-status]", dialog));
                openDialog(dialog, trigger);
                window.requestAnimationFrame(() => deleteButton.focus());
            });
        });
        deleteButton.addEventListener("click", async () => {
            if (state.deletePending || !state.deleteUrl) {
                return;
            }
            state.deletePending = true;
            setButtonPending(deleteButton, true);
            setStatus(query("[data-confirm-status]", dialog), `Deleting ${state.deleteKind}…`);
            try {
                await apiRequest(state.deleteUrl, { method: "DELETE" });
                setStatus(query("[data-confirm-status]", dialog), "Deleted.");
                window.location.reload();
            } catch (error) {
                setStatus(query("[data-confirm-status]", dialog), error.message || "Unable to delete this entry.", true);
            } finally {
                state.deletePending = false;
                setButtonPending(deleteButton, false);
            }
        });
    }

    function chartDays(payload) {
        if (Array.isArray(payload)) {
            return payload;
        }
        if (!payload || typeof payload !== "object") {
            return [];
        }
        const candidates = [payload.days, payload.weekly, payload.data, payload.values];
        for (const candidate of candidates) {
            if (Array.isArray(candidate)) {
                return candidate;
            }
        }
        const dateEntries = Object.entries(payload).filter(([key, value]) => parseIsoDate(key) && value && typeof value === "object");
        if (dateEntries.length) {
            return dateEntries.map(([date, value]) => ({ date, ...value }));
        }
        return [];
    }

    function chartDate(day) {
        return day?.local_date || day?.date || day?.iso_date || day?.iso || "";
    }

    function chartNutrient(day, key) {
        const source = day?.nutrition && typeof day.nutrition === "object"
            ? day.nutrition
            : (day?.totals && typeof day.totals === "object" ? day.totals : day);
        return nutrientNumber(source, key);
    }

    function chartWater(day, requestedUnit) {
        const water = day?.water && typeof day.water === "object" ? day.water : day || {};
        const displayAmount = nullableNumber(water.display_amount);
        const displayUnit = water.display_unit || water.unit || "";
        const wantsMl = requestedUnit === "mL";
        if (displayAmount !== null) {
            if ((wantsMl && displayUnit === "ml") || (!wantsMl && displayUnit === "fl_oz")) {
                return displayAmount;
            }
        }
        const totalMl = firstDefinedNumber(water, ["total_ml", "water_total_ml", "amount_ml"])
            ?? firstDefinedNumber(day, ["water_total_ml", "total_ml", "amount_ml"]);
        if (totalMl !== null) {
            return wantsMl ? totalMl : totalMl / 29.5735295625;
        }
        const direct = firstDefinedNumber(water, ["value", "amount", "total"]);
        if (direct === null) {
            return null;
        }
        if ((wantsMl && displayUnit === "fl_oz") || (!wantsMl && displayUnit === "ml")) {
            return wantsMl ? direct * 29.5735295625 : direct / 29.5735295625;
        }
        return direct;
    }

    function chartSeriesFor(figure, days) {
        const key = figure.dataset.chartKey;
        if (key === "macros") {
            return [
                { key: "protein", label: "Protein", values: days.map((day) => chartNutrient(day, "protein")) },
                { key: "carbohydrates", label: "Carbohydrates", values: days.map((day) => chartNutrient(day, "carbohydrates")) },
                { key: "fat", label: "Fat", values: days.map((day) => chartNutrient(day, "fat")) },
            ];
        }
        if (key === "water") {
            return [{ key: "water", label: "Water", values: days.map((day) => chartWater(day, figure.dataset.chartUnit)) }];
        }
        const label = key === "sugar" ? "Sugar" : "Calories";
        return [{ key, label, values: days.map((day) => chartNutrient(day, key)) }];
    }

    function niceMaximum(value) {
        if (!Number.isFinite(value) || value <= 0) {
            return 1;
        }
        const padded = value * 1.12;
        const magnitude = 10 ** Math.floor(Math.log10(padded));
        const fraction = padded / magnitude;
        const niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
        return niceFraction * magnitude;
    }

    function svgElement(name, attributes = {}) {
        const element = document.createElementNS(SVG_NS, name);
        Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
        return element;
    }

    function appendSvgText(svg, text, attributes) {
        const element = svgElement("text", attributes);
        element.textContent = text;
        svg.appendChild(element);
        return element;
    }

    function chartPath(values, xForIndex, yForValue) {
        let path = "";
        let segmentOpen = false;
        values.forEach((value, index) => {
            if (value === null) {
                segmentOpen = false;
                return;
            }
            const command = segmentOpen ? "L" : "M";
            path += `${command}${xForIndex(index).toFixed(2)} ${yForValue(value).toFixed(2)} `;
            segmentOpen = true;
        });
        return path.trim();
    }

    function buildChartTable(figure, days, series) {
        const container = query("[data-chart-table]", figure);
        const details = query("[data-chart-data-details]", figure);
        if (!container || !details) {
            return;
        }
        const table = document.createElement("table");
        table.className = "nutrition-chart-table";
        const thead = document.createElement("thead");
        const headRow = document.createElement("tr");
        ["Date", ...series.map((item) => item.label)].forEach((label) => {
            const th = document.createElement("th");
            th.scope = "col";
            th.textContent = label;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        days.forEach((day, index) => {
            const row = document.createElement("tr");
            const dateCell = document.createElement("th");
            dateCell.scope = "row";
            dateCell.textContent = longDateLabel(chartDate(day));
            row.appendChild(dateCell);
            series.forEach((item) => {
                const cell = document.createElement("td");
                const value = item.values[index];
                cell.textContent = value === null ? "Missing" : `${displayNumber(value)} ${figure.dataset.chartUnit}`;
                row.appendChild(cell);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        container.replaceChildren(table);
        details.hidden = false;
    }

    function buildChartSummary(figure, days, series) {
        const parts = days.map((day, index) => {
            const values = series.map((item) => {
                const value = item.values[index];
                return `${item.label} ${value === null ? "missing" : `${displayNumber(value)} ${figure.dataset.chartUnit}`}`;
            });
            return `${longDateLabel(chartDate(day))}: ${values.join(", ")}`;
        });
        return `${figure.dataset.chartTitle}. ${parts.join("; ")}.`;
    }

    function renderChart(figure, payload) {
        const stage = query("[data-chart-stage]", figure);
        const empty = query("[data-chart-empty]", figure);
        const screenSummary = query("[data-chart-screen-reader-summary]", figure);
        const days = chartDays(payload);
        const series = chartSeriesFor(figure, days);
        const values = series.flatMap((item) => item.values.filter((value) => value !== null));
        if (!days.length || !values.length) {
            stage.replaceChildren();
            stage.hidden = true;
            stage.setAttribute("aria-busy", "false");
            empty.hidden = false;
            if (screenSummary) {
                screenSummary.textContent = `No ${figure.dataset.chartTitle.toLowerCase()} values were logged for this week.`;
            }
            return;
        }

        stage.hidden = false;
        empty.hidden = true;
        const width = 360;
        const height = 174;
        const margins = { top: 18, right: 10, bottom: 31, left: 34 };
        const plotWidth = width - margins.left - margins.right;
        const plotHeight = height - margins.top - margins.bottom;
        const goal = nullableNumber(figure.dataset.chartGoal);
        const maxRaw = Math.max(0, ...values, goal ?? 0);
        const maxValue = niceMaximum(maxRaw);
        const xForIndex = (index) => margins.left + (days.length === 1 ? plotWidth / 2 : (plotWidth * index) / (days.length - 1));
        const yForValue = (value) => margins.top + plotHeight - (Math.max(0, value) / maxValue) * plotHeight;
        const svg = svgElement("svg", {
            class: "nutrition-chart-svg",
            viewBox: `0 0 ${width} ${height}`,
            role: "img",
            "aria-label": `${figure.dataset.chartTitle}, seven days ending ${longDateLabel(chartDate(days[days.length - 1]))}`,
        });
        const title = svgElement("title");
        title.textContent = `${figure.dataset.chartTitle} weekly trend`;
        svg.appendChild(title);

        [0, 0.5, 1].forEach((ratio) => {
            const value = maxValue * ratio;
            const y = yForValue(value);
            svg.appendChild(svgElement("line", {
                x1: margins.left,
                x2: width - margins.right,
                y1: y,
                y2: y,
                class: "nutrition-chart-grid-line",
            }));
            appendSvgText(svg, displayNumber(value, value < 10 ? 1 : 0), {
                x: margins.left - 5,
                y: y + 3,
                "text-anchor": "end",
                class: "nutrition-chart-axis-label",
            });
        });

        days.forEach((day, index) => {
            appendSvgText(svg, shortDateLabel(chartDate(day)), {
                x: xForIndex(index),
                y: height - 8,
                "text-anchor": "middle",
                class: "nutrition-chart-axis-label",
            });
        });

        if (goal !== null && goal > 0) {
            const goalY = yForValue(goal);
            svg.appendChild(svgElement("line", {
                x1: margins.left,
                x2: width - margins.right,
                y1: goalY,
                y2: goalY,
                class: "nutrition-chart-goal-line",
            }));
            appendSvgText(svg, `Goal ${displayNumber(goal)}`, {
                x: width - margins.right,
                y: Math.max(8, goalY - 4),
                "text-anchor": "end",
                class: "nutrition-chart-goal-label",
            });
        }

        series.forEach((item, seriesIndex) => {
            const pathData = chartPath(item.values, xForIndex, yForValue);
            if (pathData) {
                svg.appendChild(svgElement("path", {
                    d: pathData,
                    class: `nutrition-chart-line nutrition-chart-series-${seriesIndex}`,
                }));
            }
            item.values.forEach((value, index) => {
                if (value === null) {
                    return;
                }
                const circle = svgElement("circle", {
                    cx: xForIndex(index),
                    cy: yForValue(value),
                    r: 3.2,
                    class: `nutrition-chart-point nutrition-chart-series-${seriesIndex}`,
                    tabindex: "0",
                    "aria-label": `${longDateLabel(chartDate(days[index]))}, ${item.label} ${displayNumber(value)} ${figure.dataset.chartUnit}`,
                });
                const pointTitle = svgElement("title");
                pointTitle.textContent = `${item.label}: ${displayNumber(value)} ${figure.dataset.chartUnit}`;
                circle.appendChild(pointTitle);
                svg.appendChild(circle);
                if (series.length === 1) {
                    appendSvgText(svg, displayNumber(value, value < 10 ? 1 : 0), {
                        x: xForIndex(index),
                        y: Math.max(9, yForValue(value) - 7),
                        "text-anchor": "middle",
                        class: "nutrition-chart-point-label",
                    });
                }
            });
        });

        const existingLegend = query(".nutrition-chart-legend", figure);
        existingLegend?.remove();
        if (series.length > 1) {
            const legend = document.createElement("ul");
            legend.className = "nutrition-chart-legend";
            legend.setAttribute("aria-label", "Chart legend");
            series.forEach((item) => {
                const entry = document.createElement("li");
                const swatch = document.createElement("i");
                swatch.setAttribute("aria-hidden", "true");
                entry.append(swatch, document.createTextNode(item.label));
                legend.appendChild(entry);
            });
            stage.before(legend);
        }
        stage.replaceChildren(svg);
        stage.setAttribute("aria-busy", "false");
        if (screenSummary) {
            screenSummary.textContent = buildChartSummary(figure, days, series);
        }
        buildChartTable(figure, days, series);
    }

    function initializeCharts() {
        const payload = parseJsonScript(query("[data-nutrition-chart-payload]"), []);
        queryAll("[data-nutrition-chart]").forEach((figure) => renderChart(figure, payload));
    }

    function initialize() {
        initializeDialogs();
        initializeDateNavigation();
        initializeCalendar();
        initializeMealForm();
        initializeSavedMeals();
        initializeWater();
        initializeDeleteConfirmation();
        initializeCharts();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
