function saveScroll() {
    localStorage.setItem("scrollY", window.scrollY);
}

const PHONE_COUNTRIES = [
    ["AF", "Afghanistan", "93"],
    ["AX", "Aland Islands", "358"],
    ["AL", "Albania", "355"],
    ["DZ", "Algeria", "213"],
    ["AS", "American Samoa", "1"],
    ["AD", "Andorra", "376"],
    ["AO", "Angola", "244"],
    ["AI", "Anguilla", "1"],
    ["AG", "Antigua and Barbuda", "1"],
    ["AR", "Argentina", "54"],
    ["AM", "Armenia", "374"],
    ["AW", "Aruba", "297"],
    ["AU", "Australia", "61"],
    ["AT", "Austria", "43"],
    ["AZ", "Azerbaijan", "994"],
    ["BS", "Bahamas", "1"],
    ["BH", "Bahrain", "973"],
    ["BD", "Bangladesh", "880"],
    ["BB", "Barbados", "1"],
    ["BY", "Belarus", "375"],
    ["BE", "Belgium", "32"],
    ["BZ", "Belize", "501"],
    ["BJ", "Benin", "229"],
    ["BM", "Bermuda", "1"],
    ["BT", "Bhutan", "975"],
    ["BO", "Bolivia", "591"],
    ["BQ", "Bonaire, Sint Eustatius and Saba", "599"],
    ["BA", "Bosnia and Herzegovina", "387"],
    ["BW", "Botswana", "267"],
    ["BR", "Brazil", "55"],
    ["IO", "British Indian Ocean Territory", "246"],
    ["VG", "British Virgin Islands", "1"],
    ["BN", "Brunei", "673"],
    ["BG", "Bulgaria", "359"],
    ["BF", "Burkina Faso", "226"],
    ["BI", "Burundi", "257"],
    ["KH", "Cambodia", "855"],
    ["CM", "Cameroon", "237"],
    ["CA", "Canada", "1"],
    ["CV", "Cape Verde", "238"],
    ["KY", "Cayman Islands", "1"],
    ["CF", "Central African Republic", "236"],
    ["TD", "Chad", "235"],
    ["CL", "Chile", "56"],
    ["CN", "China", "86"],
    ["CX", "Christmas Island", "61"],
    ["CC", "Cocos Islands", "61"],
    ["CO", "Colombia", "57"],
    ["KM", "Comoros", "269"],
    ["CG", "Congo", "242"],
    ["CD", "Congo, Democratic Republic", "243"],
    ["CK", "Cook Islands", "682"],
    ["CR", "Costa Rica", "506"],
    ["CI", "Cote d'Ivoire", "225"],
    ["HR", "Croatia", "385"],
    ["CU", "Cuba", "53"],
    ["CW", "Curacao", "599"],
    ["CY", "Cyprus", "357"],
    ["CZ", "Czech Republic", "420"],
    ["DK", "Denmark", "45"],
    ["DJ", "Djibouti", "253"],
    ["DM", "Dominica", "1"],
    ["DO", "Dominican Republic", "1"],
    ["EC", "Ecuador", "593"],
    ["EG", "Egypt", "20"],
    ["SV", "El Salvador", "503"],
    ["GQ", "Equatorial Guinea", "240"],
    ["ER", "Eritrea", "291"],
    ["EE", "Estonia", "372"],
    ["SZ", "Eswatini", "268"],
    ["ET", "Ethiopia", "251"],
    ["FK", "Falkland Islands", "500"],
    ["FO", "Faroe Islands", "298"],
    ["FJ", "Fiji", "679"],
    ["FI", "Finland", "358"],
    ["FR", "France", "33"],
    ["GF", "French Guiana", "594"],
    ["PF", "French Polynesia", "689"],
    ["GA", "Gabon", "241"],
    ["GM", "Gambia", "220"],
    ["GE", "Georgia", "995"],
    ["DE", "Germany", "49"],
    ["GH", "Ghana", "233"],
    ["GI", "Gibraltar", "350"],
    ["GR", "Greece", "30"],
    ["GL", "Greenland", "299"],
    ["GD", "Grenada", "1"],
    ["GP", "Guadeloupe", "590"],
    ["GU", "Guam", "1"],
    ["GT", "Guatemala", "502"],
    ["GG", "Guernsey", "44"],
    ["GN", "Guinea", "224"],
    ["GW", "Guinea-Bissau", "245"],
    ["GY", "Guyana", "592"],
    ["HT", "Haiti", "509"],
    ["HN", "Honduras", "504"],
    ["HK", "Hong Kong", "852"],
    ["HU", "Hungary", "36"],
    ["IS", "Iceland", "354"],
    ["IN", "India", "91"],
    ["ID", "Indonesia", "62"],
    ["IR", "Iran", "98"],
    ["IQ", "Iraq", "964"],
    ["IE", "Ireland", "353"],
    ["IM", "Isle of Man", "44"],
    ["IL", "Israel", "972"],
    ["IT", "Italy", "39"],
    ["JM", "Jamaica", "1"],
    ["JP", "Japan", "81"],
    ["JE", "Jersey", "44"],
    ["JO", "Jordan", "962"],
    ["KZ", "Kazakhstan", "7"],
    ["KE", "Kenya", "254"],
    ["KI", "Kiribati", "686"],
    ["XK", "Kosovo", "383"],
    ["KW", "Kuwait", "965"],
    ["KG", "Kyrgyzstan", "996"],
    ["LA", "Laos", "856"],
    ["LV", "Latvia", "371"],
    ["LB", "Lebanon", "961"],
    ["LS", "Lesotho", "266"],
    ["LR", "Liberia", "231"],
    ["LY", "Libya", "218"],
    ["LI", "Liechtenstein", "423"],
    ["LT", "Lithuania", "370"],
    ["LU", "Luxembourg", "352"],
    ["MO", "Macau", "853"],
    ["MG", "Madagascar", "261"],
    ["MW", "Malawi", "265"],
    ["MY", "Malaysia", "60"],
    ["MV", "Maldives", "960"],
    ["ML", "Mali", "223"],
    ["MT", "Malta", "356"],
    ["MH", "Marshall Islands", "692"],
    ["MQ", "Martinique", "596"],
    ["MR", "Mauritania", "222"],
    ["MU", "Mauritius", "230"],
    ["YT", "Mayotte", "262"],
    ["MX", "Mexico", "52"],
    ["FM", "Micronesia", "691"],
    ["MD", "Moldova", "373"],
    ["MC", "Monaco", "377"],
    ["MN", "Mongolia", "976"],
    ["ME", "Montenegro", "382"],
    ["MS", "Montserrat", "1"],
    ["MA", "Morocco", "212"],
    ["MZ", "Mozambique", "258"],
    ["MM", "Myanmar", "95"],
    ["NA", "Namibia", "264"],
    ["NR", "Nauru", "674"],
    ["NP", "Nepal", "977"],
    ["NL", "Netherlands", "31"],
    ["NC", "New Caledonia", "687"],
    ["NZ", "New Zealand", "64"],
    ["NI", "Nicaragua", "505"],
    ["NE", "Niger", "227"],
    ["NG", "Nigeria", "234"],
    ["NU", "Niue", "683"],
    ["NF", "Norfolk Island", "672"],
    ["KP", "North Korea", "850"],
    ["MK", "North Macedonia", "389"],
    ["MP", "Northern Mariana Islands", "1"],
    ["NO", "Norway", "47"],
    ["OM", "Oman", "968"],
    ["PK", "Pakistan", "92"],
    ["PW", "Palau", "680"],
    ["PS", "Palestine", "970"],
    ["PA", "Panama", "507"],
    ["PG", "Papua New Guinea", "675"],
    ["PY", "Paraguay", "595"],
    ["PE", "Peru", "51"],
    ["PH", "Philippines", "63"],
    ["PL", "Poland", "48"],
    ["PT", "Portugal", "351"],
    ["PR", "Puerto Rico", "1"],
    ["QA", "Qatar", "974"],
    ["RE", "Reunion", "262"],
    ["RO", "Romania", "40"],
    ["RU", "Russia", "7"],
    ["RW", "Rwanda", "250"],
    ["BL", "Saint Barthelemy", "590"],
    ["SH", "Saint Helena", "290"],
    ["KN", "Saint Kitts and Nevis", "1"],
    ["LC", "Saint Lucia", "1"],
    ["MF", "Saint Martin", "590"],
    ["PM", "Saint Pierre and Miquelon", "508"],
    ["VC", "Saint Vincent and the Grenadines", "1"],
    ["WS", "Samoa", "685"],
    ["SM", "San Marino", "378"],
    ["ST", "Sao Tome and Principe", "239"],
    ["SA", "Saudi Arabia", "966"],
    ["SN", "Senegal", "221"],
    ["RS", "Serbia", "381"],
    ["SC", "Seychelles", "248"],
    ["SL", "Sierra Leone", "232"],
    ["SG", "Singapore", "65"],
    ["SX", "Sint Maarten", "1"],
    ["SK", "Slovakia", "421"],
    ["SI", "Slovenia", "386"],
    ["SB", "Solomon Islands", "677"],
    ["SO", "Somalia", "252"],
    ["ZA", "South Africa", "27"],
    ["KR", "South Korea", "82"],
    ["SS", "South Sudan", "211"],
    ["ES", "Spain", "34"],
    ["LK", "Sri Lanka", "94"],
    ["SD", "Sudan", "249"],
    ["SR", "Suriname", "597"],
    ["SJ", "Svalbard and Jan Mayen", "47"],
    ["SE", "Sweden", "46"],
    ["CH", "Switzerland", "41"],
    ["SY", "Syria", "963"],
    ["TW", "Taiwan", "886"],
    ["TJ", "Tajikistan", "992"],
    ["TZ", "Tanzania", "255"],
    ["TH", "Thailand", "66"],
    ["TL", "Timor-Leste", "670"],
    ["TG", "Togo", "228"],
    ["TK", "Tokelau", "690"],
    ["TO", "Tonga", "676"],
    ["TT", "Trinidad and Tobago", "1"],
    ["TN", "Tunisia", "216"],
    ["TR", "Turkey", "90"],
    ["TM", "Turkmenistan", "993"],
    ["TC", "Turks and Caicos Islands", "1"],
    ["TV", "Tuvalu", "688"],
    ["VI", "U.S. Virgin Islands", "1"],
    ["UG", "Uganda", "256"],
    ["UA", "Ukraine", "380"],
    ["AE", "United Arab Emirates", "971"],
    ["GB", "United Kingdom", "44"],
    ["US", "United States", "1"],
    ["UY", "Uruguay", "598"],
    ["UZ", "Uzbekistan", "998"],
    ["VU", "Vanuatu", "678"],
    ["VA", "Vatican City", "39"],
    ["VE", "Venezuela", "58"],
    ["VN", "Vietnam", "84"],
    ["WF", "Wallis and Futuna", "681"],
    ["EH", "Western Sahara", "212"],
    ["YE", "Yemen", "967"],
    ["ZM", "Zambia", "260"],
    ["ZW", "Zimbabwe", "263"],
];

function phoneDigits(value) {
    return String(value || "").replace(/\D/g, "");
}

function preferredPhoneCountryForDialCode(dialCode) {
    if (dialCode === "1") {
        return phoneCountryByIso("US");
    }

    if (dialCode === "44") {
        return phoneCountryByIso("GB");
    }

    if (dialCode === "7") {
        return phoneCountryByIso("RU");
    }

    for (const country of PHONE_COUNTRIES) {
        if (country[2] === dialCode) {
            return country;
        }
    }

    return phoneCountryByIso("US");
}

function phoneCountryByIso(iso) {
    for (const country of PHONE_COUNTRIES) {
        if (country[0] === iso) {
            return country;
        }
    }

    return PHONE_COUNTRIES.find(country => country[0] === "US") || PHONE_COUNTRIES[0];
}

function phoneCountryFromNumber(value) {
    const digits = phoneDigits(value);
    const raw = String(value || "").trim();

    if (!digits) {
        return {
            country: phoneCountryByIso("US"),
            localDigits: "",
        };
    }

    if (!raw.startsWith("+") && digits.length === 10) {
        return {
            country: phoneCountryByIso("US"),
            localDigits: digits,
        };
    }

    const countriesByCodeLength = PHONE_COUNTRIES.slice().sort((a, b) => b[2].length - a[2].length);

    for (const country of countriesByCodeLength) {
        if (digits.startsWith(country[2])) {
            const preferredCountry = preferredPhoneCountryForDialCode(country[2]);

            return {
                country: preferredCountry,
                localDigits: digits.slice(country[2].length),
            };
        }
    }

    return {
        country: phoneCountryByIso("US"),
        localDigits: digits,
    };
}

function populatePhoneCountrySelect(select, selectedCountry) {
    if (!select) {
        return;
    }

    const selectedIso = (selectedCountry || phoneCountryByIso("US"))[0];
    select.innerHTML = "";

    PHONE_COUNTRIES.forEach(country => {
        const option = document.createElement("option");
        option.value = country[0];
        option.dataset.dialCode = country[2];
        option.textContent = `${country[1]} (${country[0]}) +${country[2]}`;
        select.appendChild(option);
    });

    select.value = selectedIso;

    if (select.value !== selectedIso) {
        select.value = "US";
    }
}

function selectedPhoneDialCode(select) {
    if (!select) {
        return "1";
    }

    const option = select.options[select.selectedIndex];
    return option ? String(option.dataset.dialCode || "1") : "1";
}

function normalizedPhoneValue(localValue, countrySelect) {
    const raw = String(localValue || "").trim();
    const digits = phoneDigits(raw);

    if (!digits) {
        return "";
    }

    if (raw.startsWith("+")) {
        return `+${digits}`;
    }

    const dialCode = selectedPhoneDialCode(countrySelect);

    if (digits.startsWith(dialCode) && digits.length > dialCode.length + 4) {
        return `+${digits}`;
    }

    return `+${dialCode}${digits}`;
}

function initPhoneCountryInputs() {
    document.querySelectorAll("[data-phone-field]").forEach(field => {
        if (field.dataset.phoneInitialized === "1") {
            return;
        }

        field.dataset.phoneInitialized = "1";
        const select = field.querySelector("[data-phone-country]");
        const input = field.querySelector("[data-phone-local]");

        if (!select || !input) {
            return;
        }

        const parsed = phoneCountryFromNumber(input.value);
        populatePhoneCountrySelect(select, parsed.country);

        if (parsed.localDigits) {
            input.value = parsed.localDigits;
        }

        input.addEventListener("blur", () => {
            if (!String(input.value || "").trim().startsWith("+")) {
                return;
            }

            const updated = phoneCountryFromNumber(input.value);
            populatePhoneCountrySelect(select, updated.country);
            input.value = updated.localDigits;
        });

        const form = field.closest("form");

        if (form) {
            form.addEventListener("submit", () => {
                input.value = normalizedPhoneValue(input.value, select);
            });
        }
    });

    const forgotCountrySelect = document.getElementById("forgotPasswordPhoneCountry");

    if (forgotCountrySelect) {
        populatePhoneCountrySelect(forgotCountrySelect, phoneCountryByIso("US"));
    }

    const forgotForm = document.getElementById("forgotPasswordForm");

    if (forgotForm && forgotForm.dataset.phoneInitialized !== "1") {
        forgotForm.dataset.phoneInitialized = "1";
        forgotForm.addEventListener("submit", () => {
            const selected = forgotForm.querySelector('input[name="reset_method"]:checked');
            const input = document.getElementById("forgotPasswordIdentityInput");

            if (selected && selected.value === "phone" && input) {
                input.value = normalizedPhoneValue(input.value, forgotCountrySelect);
            }
        });
    }
}

function toggleUserProfileEditor() {
    const form = document.getElementById("userProfileEditForm");

    if (!form) {
        return false;
    }

    form.hidden = !form.hidden;
    return false;
}

function toggleForgotPasswordForm() {
    const form = document.getElementById("forgotPasswordForm");

    if (!form) {
        return false;
    }

    form.hidden = !form.hidden;

    if (!form.hidden) {
        updateForgotPasswordResetMethod();
        const input = form.querySelector('input[name="identity"]');

        if (input) {
            input.focus();
        }
    }

    return false;
}

function updateForgotPasswordResetMethod() {
    const form = document.getElementById("forgotPasswordForm");
    const input = document.getElementById("forgotPasswordIdentityInput");
    const label = document.getElementById("forgotPasswordIdentityLabel");
    const note = document.getElementById("forgotPasswordMethodNote");
    const button = document.getElementById("forgotPasswordSubmitButton");
    const phoneCountryWrap = document.getElementById("forgotPasswordPhoneCountryWrap");
    const selected = form ? form.querySelector('input[name="reset_method"]:checked') : null;
    const method = selected ? selected.value : "email";
    const emailConfigured = input ? input.dataset.emailConfigured === "1" : false;
    const smsConfigured = input ? input.dataset.smsConfigured === "1" : false;

    if (!form || !input) {
        return false;
    }

    if (form.hasAttribute("data-firebase-forgot-form")) {
        input.type = "email";
        input.inputMode = "";
        input.autocomplete = "email";
        input.placeholder = "";

        if (phoneCountryWrap) {
            phoneCountryWrap.hidden = true;
        }

        if (label) {
            label.textContent = "Email";
        }

        if (note) {
            note.textContent = "Enter your email and Firebase will send a password reset link.";
        }

        if (button) {
            button.textContent = "Send Reset Email";
        }

        return false;
    }

    if (method === "phone") {
        input.type = "tel";
        input.inputMode = "tel";
        input.autocomplete = "tel";
        input.placeholder = "309 660 6603";

        if (phoneCountryWrap) {
            phoneCountryWrap.hidden = false;
        }

        if (label) {
            label.textContent = "Phone Number";
        }

        if (note) {
            note.textContent = smsConfigured
                ? "Enter the verified phone number on your account and the app will text a one-time reset link."
                : "Enter the verified phone number on your account and the app will prepare a one-time local reset link.";
        }

        if (button) {
            button.textContent = smsConfigured ? "Send Reset Text" : "Prepare Phone Reset Link";
        }

        return false;
    }

    input.type = "text";
    input.inputMode = "";
    input.autocomplete = "username";
    input.placeholder = "";

    if (phoneCountryWrap) {
        phoneCountryWrap.hidden = true;
    }

    if (label) {
        label.textContent = "Username or Email";
    }

    if (note) {
        note.textContent = emailConfigured
            ? "Enter your username or email and the app will email a one-time reset link."
            : "Enter your username or email and the app will prepare a one-time local reset link.";
    }

    if (button) {
        button.textContent = emailConfigured ? "Send Reset Email" : "Prepare Reset Link";
    }

    return false;
}

async function copyAccountNtfyLink(button) {
    const url = button ? String(button.dataset.ntfyUrl || "").trim() : "";
    const card = button ? button.closest("[data-push-notifications-panel]") : null;
    const status = card ? card.querySelector("[data-push-notifications-status], .user-ntfy-copy-status") : null;

    if (!url) {
        if (status) {
            status.hidden = false;
            status.textContent = "Push notification link is not ready.";
        }

        return false;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(url);
        } else {
            const temp = document.createElement("textarea");
            temp.value = url;
            temp.setAttribute("readonly", "readonly");
            temp.style.position = "fixed";
            temp.style.left = "-9999px";
            document.body.appendChild(temp);
            temp.select();
            document.execCommand("copy");
            document.body.removeChild(temp);
        }

        if (status) {
            status.hidden = false;
            status.textContent = "Push notification link copied.";
        }
    } catch (err) {
        console.warn("Unable to copy push notification link.", err);

        if (status) {
            status.hidden = false;
            status.textContent = "Open the ntfy topic link to copy it.";
        }
    }

    return false;
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
    const storeLabel = button ? button.dataset.storeLabel || storeKey : storeKey;

    if (!itemKey) {
        return false;
    }

    const modal = ensureProductAlternativesModal();
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    renderProductAlternativesLoading(itemKey, storeLabel);

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

async function selectItemStoreFromPriceHeader(button) {
    const itemKey = button ? button.dataset.itemKey || "" : "";
    const storeKey = button ? button.dataset.storeKey || "" : "";

    if (!itemKey || !storeKey) {
        return false;
    }

    button.disabled = true;
    button.setAttribute("aria-busy", "true");

    try {
        await saveItemStoreSelection(itemKey, storeKey);
    } finally {
        button.disabled = false;
        button.removeAttribute("aria-busy");
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
        showRecipeQuantityUpdatedMessage("", "", "", data.message || "Food restrictions added.");
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
    modal.dataset.activeSection = section || "";
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
        delete modal.dataset.activeSection;
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
    const userCanManageStores = data.can_manage_stores === true;
    const userCanToggleStores = data.can_toggle_stores === true || userCanManageStores;
    const display = data.rules_display || {};
    const section = display.home_stores || {};
    const rows = Array.isArray(section.rows) ? section.rows : [];
    const enabledStoresSection = userCanToggleStores
        ? `
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
        `
        : "";

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
        ${enabledStoresSection}
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
                <div class="rules-editor-food-heading-actions">
                    <div class="rules-editor-food-ai">
                        <input type="text"
                               data-rules-food-prompt="require"
                               aria-label="Ask ChatGPT to add a required food rule"
                               placeholder="Required prompt"
                               onkeydown="return submitRulesFoodRulePrompt(event, 'require', this)">
                        <button type="button"
                                class="rules-editor-small-btn rules-editor-ai-btn"
                                data-rules-food-ai-button
                                onclick="suggestRulesFoodRule('require', this)">
                            Ask ChatGPT
                        </button>
                    </div>
                    <button type="button" class="rules-editor-small-btn" onclick="addRulesFoodRuleRow('require')">Add Required</button>
                </div>
            </div>
            <div id="rulesFoodRequireRows" class="rules-editor-row-list" data-rules-food-list="require"></div>
        </section>
        <section class="rules-editor-section">
            <div class="rules-editor-section-heading">
                <h3>Avoid</h3>
                <div class="rules-editor-food-heading-actions">
                    <div class="rules-editor-food-ai">
                        <input type="text"
                               data-rules-food-prompt="avoid"
                               aria-label="Ask ChatGPT to add an avoid food rule"
                               placeholder="Avoid prompt"
                               onkeydown="return submitRulesFoodRulePrompt(event, 'avoid', this)">
                        <button type="button"
                                class="rules-editor-small-btn rules-editor-ai-btn"
                                data-rules-food-ai-button
                                onclick="suggestRulesFoodRule('avoid', this)">
                            Ask ChatGPT
                        </button>
                    </div>
                    <button type="button" class="rules-editor-small-btn" onclick="addRulesFoodRuleRow('avoid')">Add Avoid</button>
                </div>
            </div>
            <div id="rulesFoodAvoidRows" class="rules-editor-row-list" data-rules-food-list="avoid"></div>
        </section>
    `;

    (foodRules.require || []).forEach(rule => addRulesFoodRuleRow("require", rule));
    (foodRules.avoid || []).forEach(rule => addRulesFoodRuleRow("avoid", rule));
}

function submitRulesFoodRulePrompt(event, section, input) {
    if (!event || event.key !== "Enter") {
        return true;
    }

    event.preventDefault();
    const wrapper = input ? input.closest(".rules-editor-food-ai") : null;
    const button = wrapper ? wrapper.querySelector("[data-rules-food-ai-button]") : null;
    suggestRulesFoodRule(section, button);
    return false;
}

async function suggestRulesFoodRule(section, button) {
    const promptInput = document.querySelector(`[data-rules-food-prompt="${section}"]`);
    const prompt = promptInput ? promptInput.value.trim() : "";
    const originalText = button ? button.textContent : "";
    const sectionLabel = section === "require" ? "required" : "avoid";

    if (!prompt) {
        setRulesEditorStatus(`Enter a ${sectionLabel} food rule prompt.`, true);
        if (promptInput) {
            promptInput.focus();
        }
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "Asking...";
    }

    setRulesEditorStatus("Asking ChatGPT...");

    try {
        const response = await fetch("/api/food_rules/suggest", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({
                prompt,
                section,
                food_rules: collectRulesFoodRestrictions(),
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to add food restrictions.");
        }

        mergeRulesFoodRulesIntoEditor(data.added || { require: [], avoid: [] });
        updateRulesEditorFoodData(data.food_rules || collectRulesFoodRestrictions());

        if (promptInput) {
            promptInput.value = "";
        }

        setRulesEditorStatus(data.message || rulesFoodChangesMessage(data.changes));
    } catch (err) {
        console.warn("Unable to add rules food restriction with ChatGPT.", err);
        setRulesEditorStatus(err.message || "Unable to add food restrictions.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Ask ChatGPT";
        }
    }

    return false;
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
        <div class="rules-editor-food-row-menu-wrap recipe-edit-row-menu-wrap">
            <button type="button"
                    class="recipe-edit-row-menu-btn rules-editor-food-row-menu-btn"
                    aria-label="Food restriction rule actions"
                    title="Food restriction rule actions"
                    aria-haspopup="true"
                    aria-expanded="false"
                    onclick="return toggleRecipeEditRowMenu(this, event)">
                <span aria-hidden="true"></span>
            </button>
            <div class="recipe-edit-row-menu rules-editor-food-row-menu" hidden>
                <button type="button"
                        class="delete"
                        onclick="removeRulesEditorRow(this); closeRecipeEditRowMenus(); return false;">
                    Delete food restriction rule
                </button>
            </div>
        </div>
    `;
    list.appendChild(row);
    return false;
}

function mergeRulesFoodRulesIntoEditor(foodRules) {
    const changes = {
        added: 0,
        updated: 0,
        matched: 0,
    };
    const rules = foodRules || {};

    ["require", "avoid"].forEach(section => {
        const sectionRules = Array.isArray(rules[section]) ? rules[section] : [];
        sectionRules.forEach(rule => {
            const change = upsertRulesFoodRuleRow(section, rule);

            if (change === "added") {
                changes.added += 1;
            } else if (change === "updated") {
                changes.updated += 1;
            } else if (change === "matched") {
                changes.matched += 1;
            }
        });
    });

    return changes;
}

function upsertRulesFoodRuleRow(section, rule) {
    const list = document.querySelector(`[data-rules-food-list="${section}"]`);
    const label = String(rule && rule.label ? rule.label : "").trim();
    const incomingTerms = Array.isArray(rule && rule.terms)
        ? splitFoodRestrictionTerms(rule.terms.join(", "))
        : splitFoodRestrictionTerms(rule && rule.terms ? rule.terms : "");

    if (!list || !label || !incomingTerms.length) {
        return "";
    }

    const matchingRow = findMatchingRulesFoodRow(list, label, incomingTerms);

    if (!matchingRow) {
        addRulesFoodRuleRow(section, {
            label,
            terms: incomingTerms,
        });
        return "added";
    }

    const labelInput = matchingRow.querySelector("[data-rules-food-label]");
    const termsInput = matchingRow.querySelector("[data-rules-food-terms]");
    const existingTerms = splitFoodRestrictionTerms(termsInput ? termsInput.value : "");
    const mergedTerms = sortedUniqueFoodTerms(existingTerms.concat(incomingTerms));
    const termsChanged = mergedTerms.join("|") !== sortedUniqueFoodTerms(existingTerms).join("|");

    if (labelInput) {
        labelInput.value = labelInput.value.trim() || label;
    }

    if (termsInput) {
        termsInput.value = mergedTerms.join(", ");
    }

    return termsChanged ? "updated" : "matched";
}

function rulesFoodChangesMessage(changes) {
    const list = Array.isArray(changes) ? changes : [];

    if (!list.length) {
        return "ChatGPT did not add or update any food restriction rules.";
    }

    const first = list[0] || {};
    const label = first.label || "this rule";
    const section = first.section === "require" ? "Required" : "Avoid";

    if (first.action === "added") {
        return `ChatGPT added a new ${section} rule: ${label}.`;
    }

    if (first.action === "updated_existing") {
        return `ChatGPT found the existing ${section} rule '${label}' and updated it.`;
    }

    return `ChatGPT found the existing ${section} rule '${label}' already meets this requirement.`;
}

function findMatchingRulesFoodRow(list, label, terms) {
    const normalizedLabel = normalizeRulesFoodText(label);
    const normalizedTerms = sortedUniqueFoodTerms(terms).join("|");
    const rows = [...list.querySelectorAll("[data-rules-food-row]")];

    return rows.find(row => {
        const labelInput = row.querySelector("[data-rules-food-label]");
        const termsInput = row.querySelector("[data-rules-food-terms]");
        const existingLabel = normalizeRulesFoodText(labelInput ? labelInput.value : "");
        const existingTerms = sortedUniqueFoodTerms(
            splitFoodRestrictionTerms(termsInput ? termsInput.value : "")
        ).join("|");

        return (
            (normalizedLabel && existingLabel === normalizedLabel) ||
            (normalizedTerms && existingTerms === normalizedTerms)
        );
    });
}

function sortedUniqueFoodTerms(terms) {
    return splitFoodRestrictionTerms(Array.isArray(terms) ? terms.join(", ") : terms)
        .sort((left, right) => left.localeCompare(right));
}

function normalizeRulesFoodText(value) {
    return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function updateRulesEditorFoodData(foodRules) {
    const script = document.getElementById("rulesEditorData");

    if (!script || !foodRules) {
        return;
    }

    try {
        const data = JSON.parse(script.textContent || "{}");
        data.food_rules = foodRules;
        script.textContent = JSON.stringify(data);
    } catch (err) {
        console.warn("Unable to update rules editor food data.", err);
    }
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

function setCookbookStatus(message, isError = false) {
    const status = document.getElementById("cookbookStatus");

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("error", Boolean(isError));
}

function selectedCookbookRecipeCount() {
    return document.querySelectorAll("[data-cookbook-recipe-checkbox]:checked").length;
}

function selectedCookbookRestoreCount() {
    return document.querySelectorAll("[data-cookbook-restore-checkbox]:checked").length;
}

function updateCookbookMoveButton() {
    const button = document.getElementById("cookbookMoveButton");
    const select = document.getElementById("cookbookMoveTarget");
    const selectedCount = selectedCookbookRecipeCount();

    if (!button) {
        return;
    }

    button.disabled = selectedCount === 0 || !select || !select.value;
    button.textContent = selectedCount
        ? `Move ${selectedCount} Recipe${selectedCount === 1 ? "" : "s"}`
        : "Move Selected";
}

function updateCookbookRestoreButton() {
    const button = document.getElementById("cookbookRestoreButton");
    const selectedCount = selectedCookbookRestoreCount();

    if (!button) {
        return;
    }

    button.disabled = selectedCount === 0;
    button.textContent = selectedCount
        ? `Add ${selectedCount} to Recipe Log`
        : "Add Selected to Recipe Log";
}

let pendingCookbookOverwriteResolve = null;

function cookbookOverwriteConflictNames(conflicts) {
    return (Array.isArray(conflicts) ? conflicts : [])
        .map(conflict => String((conflict && conflict.name) || "").trim())
        .filter(Boolean);
}

function cookbookOverwriteMessage(names, cookbookName) {
    const count = names.length || 1;
    const recipeLabel = count === 1 ? "recipe" : "recipes";
    const targetLabel = cookbookName ? ` in ${cookbookName}` : "";

    return `${count} selected ${recipeLabel} already exists${targetLabel}. Overwrite the saved cookbook ${recipeLabel}?`;
}

function promptCookbookOverwrite(conflicts, cookbookName) {
    const modal = document.getElementById("cookbookOverwriteModal");
    const message = document.getElementById("cookbookOverwriteMessage");
    const list = document.getElementById("cookbookOverwriteList");
    const names = cookbookOverwriteConflictNames(conflicts);

    if (!modal || !message || !list) {
        return Promise.resolve(window.confirm(`${cookbookOverwriteMessage(names, cookbookName)}\n\nOK = Overwrite\nCancel = Cancel`));
    }

    if (pendingCookbookOverwriteResolve) {
        pendingCookbookOverwriteResolve(false);
    }

    message.textContent = cookbookOverwriteMessage(names, cookbookName);
    list.innerHTML = "";
    names.forEach(name => {
        const item = document.createElement("li");
        item.textContent = name;
        list.appendChild(item);
    });

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    return new Promise(resolve => {
        pendingCookbookOverwriteResolve = resolve;
    });
}

function resolveCookbookOverwritePrompt(shouldOverwrite) {
    const modal = document.getElementById("cookbookOverwriteModal");
    const resolve = pendingCookbookOverwriteResolve;

    pendingCookbookOverwriteResolve = null;

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }

    if (!document.querySelector(".cookbook-name-modal-backdrop.open") && !document.querySelector(".store-add-modal-backdrop.open") && !document.querySelector(".store-edit-form.open")) {
        document.body.classList.remove("modal-open");
    }

    if (resolve) {
        resolve(Boolean(shouldOverwrite));
    }
}

const COOKBOOK_RECIPE_SEARCH_SESSION_KEY = "cookbook-recipe-search";

function normalizedCookbookSearchText(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .trim();
}

function cookbookRecipeSearchTerms() {
    const input = document.getElementById("cookbookRecipeSearchInput");
    const query = normalizedCookbookSearchText(input ? input.value : "");

    return query ? query.split(/\s+/).filter(Boolean) : [];
}

function cookbookCardCollapseStorageKey(cookbookId) {
    return cookbookId ? `cookbook-card-collapse:${cookbookId}` : "";
}

function updateCookbookCardCollapseDisplay(card) {
    if (!card) {
        return;
    }

    const isStoredCollapsed = card.dataset.cookbookCollapsed === "1";
    const searchActive = cookbookRecipeSearchTerms().length > 0;
    const forceOpenForSearch = searchActive && !card.hidden;
    const isVisuallyCollapsed = isStoredCollapsed && !forceOpenForSearch;
    const toggle = card.querySelector("[data-cookbook-toggle]");
    const icon = card.querySelector("[data-cookbook-toggle-icon]");

    card.classList.toggle("cookbook-card-collapsed", isVisuallyCollapsed);
    card.classList.toggle("cookbook-card-search-open", forceOpenForSearch);
    card.setAttribute("aria-expanded", isVisuallyCollapsed ? "false" : "true");

    if (toggle) {
        toggle.setAttribute("aria-expanded", isVisuallyCollapsed ? "false" : "true");
    }

    if (icon) {
        icon.textContent = isVisuallyCollapsed ? "Show v" : "Hide ^";
    }
}

function setCookbookCardCollapsed(card, isCollapsed) {
    if (!card) {
        return;
    }

    card.dataset.cookbookCollapsed = isCollapsed ? "1" : "0";
    updateCookbookCardCollapseDisplay(card);
}

function restoreCookbookCardCollapseState() {
    document.querySelectorAll("[data-cookbook-card]").forEach(card => {
        const storageKey = cookbookCardCollapseStorageKey(card.dataset.cookbookId || "");
        const savedState = storageKey ? localStorage.getItem(storageKey) : null;

        setCookbookCardCollapsed(card, savedState === "collapsed");
    });
}

function toggleCookbookCard(button) {
    const card = button ? button.closest("[data-cookbook-card]") : null;

    if (!card) {
        return false;
    }

    const isCollapsed = card.dataset.cookbookCollapsed === "1";
    const storageKey = cookbookCardCollapseStorageKey(card.dataset.cookbookId || "");
    const nextCollapsed = !isCollapsed;

    setCookbookCardCollapsed(card, nextCollapsed);

    if (storageKey) {
        localStorage.setItem(storageKey, nextCollapsed ? "collapsed" : "expanded");
    }

    return false;
}

function toggleCookbookCardFromSurface(card, event = null) {
    if (eventStartedInNestedInteractive(event, card)) {
        return true;
    }

    if (event && event.target && event.target.closest && event.target.closest("[data-cookbook-recipe-card]")) {
        return true;
    }

    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    return toggleCookbookCard(card);
}

function handleCookbookCardSurfaceKeydown(card, event) {
    if (!event || (event.key !== "Enter" && event.key !== " ")) {
        return true;
    }

    return toggleCookbookCardFromSurface(card, event);
}

function recipeCardMatchesCookbookSearch(recipeCard, terms) {
    if (!terms.length) {
        return true;
    }

    const title = recipeCard.dataset.cookbookRecipeName || recipeCard.textContent || "";
    const text = normalizedCookbookSearchText(title);

    return terms.every(term => text.includes(term));
}

function setCookbookRecipeSearchValue(value) {
    try {
        sessionStorage.setItem(COOKBOOK_RECIPE_SEARCH_SESSION_KEY, value || "");
    } catch (err) {
        // Session storage is optional; search still works without persistence.
    }
}

function restoreCookbookRecipeSearchValue() {
    const input = document.getElementById("cookbookRecipeSearchInput");

    if (!input) {
        return;
    }

    try {
        input.value = sessionStorage.getItem(COOKBOOK_RECIPE_SEARCH_SESSION_KEY) || input.value || "";
    } catch (err) {
        input.value = input.value || "";
    }
}

function applyCookbookRecipeSearch() {
    const terms = cookbookRecipeSearchTerms();
    const searchActive = terms.length > 0;
    const globalEmpty = document.getElementById("cookbookRecipeSearchEmpty");
    let visibleRecipes = 0;

    document.querySelectorAll("[data-cookbook-card]").forEach(card => {
        const recipes = Array.from(card.querySelectorAll("[data-cookbook-recipe-card]"));
        let matchingRecipes = 0;

        recipes.forEach(recipeCard => {
            const isMatch = recipeCardMatchesCookbookSearch(recipeCard, terms);
            recipeCard.hidden = !isMatch;
            recipeCard.classList.toggle("cookbook-recipe-search-hidden", !isMatch);

            if (isMatch) {
                matchingRecipes += 1;
            }
        });

        visibleRecipes += matchingRecipes;
        card.hidden = searchActive && matchingRecipes === 0;
        card.classList.toggle("cookbook-card-search-hidden", Boolean(card.hidden));

        const cardEmpty = card.querySelector("[data-cookbook-search-empty]");
        if (cardEmpty) {
            cardEmpty.hidden = !searchActive || matchingRecipes > 0;
        }

        updateCookbookCardCollapseDisplay(card);
    });

    if (globalEmpty) {
        globalEmpty.hidden = !searchActive || visibleRecipes > 0;
    }
}

function cookbookRecipeCollapseStorageKey(recipeKey) {
    return recipeKey ? `cookbook-recipe-collapse:${recipeKey}` : "";
}

function setCookbookRecipeCollapsed(card, isCollapsed) {
    if (!card) {
        return;
    }

    const details = card.querySelector("[data-cookbook-recipe-details]");
    const toggle = card.querySelector("[data-cookbook-recipe-toggle]");
    const icon = card.querySelector("[data-cookbook-recipe-toggle-icon]");

    if (!details && !toggle && !icon) {
        card.classList.remove("cookbook-recipe-collapsed");
        return;
    }

    card.classList.toggle("cookbook-recipe-collapsed", isCollapsed);

    if (details) {
        details.classList.toggle("collapsed", isCollapsed);
    }

    if (toggle) {
        toggle.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    }

    if (icon) {
        icon.textContent = isCollapsed ? "Show v" : "Hide ^";
    }
}

function restoreCookbookRecipeCollapseState() {
    document.querySelectorAll("[data-cookbook-recipe-card]").forEach(card => {
        const storageKey = cookbookRecipeCollapseStorageKey(card.dataset.cookbookRecipeKey || "");
        const savedState = storageKey ? localStorage.getItem(storageKey) : null;

        setCookbookRecipeCollapsed(card, savedState !== "expanded");
    });
}

function toggleCookbookRecipeDetails(button) {
    const card = button ? button.closest("[data-cookbook-recipe-card]") : null;

    if (!card) {
        return false;
    }

    const isCollapsed = !card.classList.contains("cookbook-recipe-collapsed");
    const storageKey = cookbookRecipeCollapseStorageKey(card.dataset.cookbookRecipeKey || "");

    setCookbookRecipeCollapsed(card, isCollapsed);

    if (storageKey) {
        localStorage.setItem(storageKey, isCollapsed ? "collapsed" : "expanded");
    }

    return false;
}

function cookbookOrder(list) {
    return [...list.querySelectorAll("[data-cookbook-card]")]
        .map(card => card.dataset.cookbookId || "")
        .filter(Boolean);
}

function updateCookbookDragLabels(list) {
    [...list.querySelectorAll("[data-cookbook-card]")].forEach((card, index) => {
        const title = card.querySelector(".cookbook-card-title h3");
        const handle = card.querySelector("[data-cookbook-drag-handle]");
        const label = title ? title.textContent.trim() : `cookbook ${index + 1}`;

        if (handle) {
            handle.setAttribute("aria-label", `Reorder ${label}`);
        }
    });
}

function bindCookbookDragAndDrop() {
    const list = document.querySelector("[data-cookbook-sort-list]");

    if (!list || list.dataset.dragBound === "1") {
        return;
    }

    list.dataset.dragBound = "1";
    list.dataset.savedOrder = cookbookOrder(list).join("\n");

    list.querySelectorAll("[data-cookbook-card]").forEach(card => {
        const handle = card.querySelector("[data-cookbook-drag-handle]");

        card.setAttribute("draggable", "true");
        card.setAttribute("aria-grabbed", "false");

        if (handle) {
            handle.addEventListener("pointerdown", () => {
                card.dataset.dragHandleActive = "1";
            });
            handle.addEventListener("pointerup", () => {
                delete card.dataset.dragHandleActive;
            });
            handle.addEventListener("blur", () => {
                delete card.dataset.dragHandleActive;
            });
            handle.addEventListener("click", event => {
                event.stopPropagation();
            });
        }

        card.addEventListener("dragstart", event => {
            if (event.target && event.target.closest && event.target.closest("[data-cookbook-recipe-card]")) {
                return;
            }

            if (card.dataset.dragHandleActive !== "1") {
                event.preventDefault();
                return;
            }

            closeRecipeEditRowMenus();
            card.classList.add("is-dragging");
            card.setAttribute("aria-grabbed", "true");
            list.classList.add("is-dragging");
            document.body.classList.add("recipe-url-dragging");

            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", card.dataset.cookbookId || "");
            }
        });

        card.addEventListener("dragend", () => {
            const changed = list.dataset.savedOrder !== cookbookOrder(list).join("\n");

            card.classList.remove("is-dragging");
            card.setAttribute("aria-grabbed", "false");
            delete card.dataset.dragHandleActive;
            list.classList.remove("is-dragging");
            document.body.classList.remove("recipe-url-dragging");
            updateCookbookDragLabels(list);

            if (changed) {
                saveCookbookOrder(list);
            }
        });
    });

    list.addEventListener("dragover", event => {
        const draggingCard = list.querySelector("[data-cookbook-card].is-dragging");
        const targetCard = event.target.closest("[data-cookbook-card]");

        if (!draggingCard || !targetCard || targetCard === draggingCard || targetCard.parentElement !== list) {
            return;
        }

        event.preventDefault();

        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
        }

        const rect = targetCard.getBoundingClientRect();
        const shouldPlaceAfter = event.clientY > rect.top + rect.height / 2;
        list.insertBefore(draggingCard, shouldPlaceAfter ? targetCard.nextElementSibling : targetCard);
        updateCookbookDragLabels(list);
    });

    list.addEventListener("drop", event => {
        if (list.querySelector("[data-cookbook-card].is-dragging")) {
            event.preventDefault();
        }
    });

    updateCookbookDragLabels(list);
}

async function saveCookbookOrder(list) {
    const cookbookIds = cookbookOrder(list);

    if (!cookbookIds.length || list.dataset.savePending === "1") {
        return;
    }

    list.dataset.savePending = "1";
    list.classList.add("is-saving");
    setCookbookStatus("Saving cookbook order...");

    try {
        const data = await postCookbookOrder(cookbookIds);
        const savedIds = Array.isArray(data.cookbook_ids) && data.cookbook_ids.length
            ? data.cookbook_ids
            : cookbookIds;

        list.dataset.savedOrder = savedIds.join("\n");
        setCookbookStatus("Cookbook order updated.");
    } catch (err) {
        console.warn("Unable to save cookbook order.", err);
        setCookbookStatus(err.message || "Unable to save cookbook order.", true);
        alert(err.message || "Unable to save cookbook order.");
    } finally {
        list.classList.remove("is-saving");
        delete list.dataset.savePending;
    }
}

async function postCookbookOrder(cookbookIds) {
    const endpoints = ["/api/cookbooks/reorder"];
    const hostname = window.location.hostname;

    if (
        window.location.port !== "5000"
        && ["127.0.0.1", "localhost"].includes(hostname)
    ) {
        endpoints.push(`${window.location.protocol}//${hostname}:5000/api/cookbooks/reorder`);
    }

    let lastError = null;

    for (const endpoint of endpoints) {
        try {
            return await postCookbookOrderToEndpoint(endpoint, cookbookIds);
        } catch (err) {
            lastError = err;

            if (!err.canTryNextCookbookOrderEndpoint) {
                break;
            }
        }
    }

    throw lastError || new Error("Unable to save cookbook order.");
}

async function postCookbookOrderToEndpoint(endpoint, cookbookIds) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ cookbook_ids: cookbookIds }),
    });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
        ? await response.json()
        : null;

    if (!response.ok || !data || !data.ok) {
        const error = new Error(
            (data && data.error)
            || (
                response.status === 404
                    ? "Cookbook reorder is not available on this running server."
                    : "Unable to save cookbook order."
            )
        );
        error.canTryNextCookbookOrderEndpoint = response.status === 404 || !contentType.includes("application/json");
        throw error;
    }

    return data;
}

function draggedRecipeRow() {
    return document.querySelector("[data-cookbook-recipe-card].is-dragging, [data-current-recipe-row].is-dragging");
}

function draggedRecipeUrl(row) {
    return row ? row.dataset.recipeUrl || "" : "";
}

function clearCookbookRecipeDropState() {
    document.querySelectorAll(".cookbook-card-recipe-drop-active").forEach(card => {
        card.classList.remove("cookbook-card-recipe-drop-active");
    });
    document.querySelectorAll(".cookbook-recipe-drop-before, .cookbook-recipe-drop-after").forEach(card => {
        card.classList.remove("cookbook-recipe-drop-before", "cookbook-recipe-drop-after");
    });
}

function cookbookRecipeDropPosition(event, cookbookCard) {
    const source = draggedRecipeRow();
    const recipeUrl = draggedRecipeUrl(source);

    if (!source || !recipeUrl || !cookbookCard) {
        return null;
    }

    const targetRecipe = event && event.target && event.target.closest
        ? event.target.closest("[data-cookbook-recipe-card]")
        : null;
    const targetCookbook = targetRecipe ? targetRecipe.closest("[data-cookbook-card]") : null;

    if (targetRecipe && (targetCookbook !== cookbookCard || targetRecipe === source)) {
        return null;
    }

    const targetRecipeUrl = targetRecipe ? targetRecipe.dataset.recipeUrl || "" : "";
    const shouldInsertAfter = targetRecipe
        ? event.clientY > targetRecipe.getBoundingClientRect().top + targetRecipe.getBoundingClientRect().height / 2
        : false;

    if (targetRecipe) {
        return {
            cookbookId: cookbookCard.dataset.cookbookId || "",
            recipeUrl,
            insertBeforeRecipeUrl: shouldInsertAfter ? "" : targetRecipeUrl,
            insertAfterRecipeUrl: shouldInsertAfter ? targetRecipeUrl : "",
            targetRecipe,
            shouldInsertAfter,
        };
    }

    return {
        cookbookId: cookbookCard.dataset.cookbookId || "",
        recipeUrl,
        insertBeforeRecipeUrl: "",
        insertAfterRecipeUrl: "",
        targetRecipe: null,
        shouldInsertAfter: false,
    };
}

function updateCookbookRecipeDropState(event, cookbookCard) {
    clearCookbookRecipeDropState();

    const position = cookbookRecipeDropPosition(event, cookbookCard);

    if (!position || !position.cookbookId || !position.recipeUrl) {
        return null;
    }

    cookbookCard.classList.add("cookbook-card-recipe-drop-active");

    if (position.targetRecipe) {
        position.targetRecipe.classList.add(position.shouldInsertAfter ? "cookbook-recipe-drop-after" : "cookbook-recipe-drop-before");
    }

    return position;
}

async function saveCookbookRecipeDrop(position) {
    if (!position || !position.cookbookId || !position.recipeUrl) {
        return;
    }

    setCookbookStatus("Moving recipe...");

    await moveRecipeUrlToCookbook(position.recipeUrl, position.cookbookId, {
        insertBeforeRecipeUrl: position.insertBeforeRecipeUrl,
        insertAfterRecipeUrl: position.insertAfterRecipeUrl,
    });

    await refreshStoreMarkup({
        cacheBust: true,
        requireRecipeLog: true,
    });
    showRecipeQuantityUpdatedMessage("", "", "", "Recipe moved.");
}

function bindCookbookRecipeDragAndDrop() {
    document.querySelectorAll("[data-cookbook-recipe-card]").forEach(card => {
        if (card.dataset.recipeDragBound === "1") {
            return;
        }

        const handle = card.querySelector("[data-cookbook-recipe-drag-handle]");
        card.dataset.recipeDragBound = "1";
        card.setAttribute("draggable", "true");
        card.setAttribute("aria-grabbed", "false");

        if (handle) {
            handle.addEventListener("pointerdown", () => {
                card.dataset.dragHandleActive = "1";
            });
            handle.addEventListener("pointerup", () => {
                delete card.dataset.dragHandleActive;
            });
            handle.addEventListener("blur", () => {
                delete card.dataset.dragHandleActive;
            });
            handle.addEventListener("click", event => {
                event.stopPropagation();
            });
        }

        card.addEventListener("dragstart", event => {
            if (card.dataset.dragHandleActive !== "1") {
                event.preventDefault();
                return;
            }

            closeRecipeEditRowMenus();
            card.classList.add("is-dragging");
            card.setAttribute("aria-grabbed", "true");
            document.body.classList.add("recipe-url-dragging");

            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", card.dataset.recipeUrl || "");
            }
        });

        card.addEventListener("dragend", () => {
            card.classList.remove("is-dragging");
            card.setAttribute("aria-grabbed", "false");
            delete card.dataset.dragHandleActive;
            document.body.classList.remove("recipe-url-dragging");
            clearCookbookRecipeDropState();
        });
    });

    document.querySelectorAll("[data-cookbook-card]").forEach(cookbookCard => {
        if (cookbookCard.dataset.recipeDropBound === "1") {
            return;
        }

        cookbookCard.dataset.recipeDropBound = "1";

        cookbookCard.addEventListener("dragover", event => {
            const source = draggedRecipeRow();

            if (!source) {
                return;
            }

            const position = updateCookbookRecipeDropState(event, cookbookCard);

            if (!position) {
                return;
            }

            event.preventDefault();

            if (event.dataTransfer) {
                event.dataTransfer.dropEffect = "move";
            }
        });

        cookbookCard.addEventListener("dragleave", event => {
            if (event.relatedTarget && cookbookCard.contains(event.relatedTarget)) {
                return;
            }

            clearCookbookRecipeDropState();
        });

        cookbookCard.addEventListener("drop", event => {
            const position = updateCookbookRecipeDropState(event, cookbookCard);

            if (!position) {
                return;
            }

            event.preventDefault();
            clearCookbookRecipeDropState();
            saveCookbookRecipeDrop(position).catch(err => {
                console.warn("Unable to move dropped recipe.", err);
                setCookbookStatus(err.message || "Unable to move recipe.", true);
                window.alert(err.message || "Unable to move recipe.");
            });
        });
    });
}

function bindCookbooks() {
    document.querySelectorAll("[data-cookbook-recipe-checkbox]").forEach(checkbox => {
        if (checkbox.dataset.cookbookBound === "1") {
            return;
        }

        checkbox.dataset.cookbookBound = "1";
        checkbox.addEventListener("change", updateCookbookMoveButton);
    });

    document.querySelectorAll("[data-cookbook-restore-checkbox]").forEach(checkbox => {
        if (checkbox.dataset.cookbookRestoreBound === "1") {
            return;
        }

        checkbox.dataset.cookbookRestoreBound = "1";
        checkbox.addEventListener("change", updateCookbookRestoreButton);
    });

    const target = document.getElementById("cookbookMoveTarget");
    if (target && target.dataset.cookbookBound !== "1") {
        target.dataset.cookbookBound = "1";
        target.addEventListener("change", updateCookbookMoveButton);
    }

    const searchInput = document.getElementById("cookbookRecipeSearchInput");
    if (searchInput && searchInput.dataset.cookbookSearchBound !== "1") {
        searchInput.dataset.cookbookSearchBound = "1";
        searchInput.addEventListener("input", () => {
            setCookbookRecipeSearchValue(searchInput.value);
            applyCookbookRecipeSearch();
        });
    }

    updateCookbookMoveButton();
    updateCookbookRestoreButton();
    restoreCookbookCardCollapseState();
    restoreCookbookRecipeCollapseState();
    restoreCookbookRecipeSearchValue();
    applyCookbookRecipeSearch();
    bindCookbookDragAndDrop();
    bindCookbookRecipeDragAndDrop();
}

async function refreshCookbooksMarkup() {
    const refreshUrl = new URL(window.location.href);
    refreshUrl.searchParams.set("_refresh", String(Date.now()));

    const response = await fetch(refreshUrl.toString(), {
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error("Unable to refresh cookbooks.");
    }

    const html = await response.text();
    const nextPage = new DOMParser().parseFromString(html, "text/html");

    if (!replaceSectionFromPage(nextPage, "#cookbooksCard")) {
        throw new Error("Cookbooks section was not found.");
    }

    restoreCardCollapseState();
    bindCookbooks();
}

async function submitCookbookForm(form, options = {}) {
    const formData = options.formData || new FormData(form);
    formData.set("ajax", "1");

    const response = await fetch(formActionUrl(form), {
        method: options.method || form.getAttribute("method") || "POST",
        headers: {
            "X-Requested-With": "fetch",
        },
        body: formData,
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
        const error = new Error((data && data.error) || "Cookbook update failed.");
        error.status = response.status;
        error.data = data;
        throw error;
    }

    return data;
}

async function createCookbook(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = form ? form.querySelector("button[type='submit']") : null;
    const originalText = button ? button.textContent : "";

    try {
        if (button) {
            button.disabled = true;
            button.textContent = "Adding...";
        }

        setCookbookStatus("Adding cookbook...");
        await submitCookbookForm(form);
        await refreshCookbooksMarkup();
        showRecipeQuantityUpdatedMessage("", "", "", "Cookbook added.");
    } catch (err) {
        console.warn("Unable to add cookbook.", err);
        setCookbookStatus(err.message || "Unable to add cookbook.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Add Cookbook";
        }
    }

    return false;
}

async function submitCookbookApi(url, formData = new FormData(), method = "POST") {
    formData.set("ajax", "1");

    const response = await fetch(url, {
        method,
        headers: {
            "X-Requested-With": "fetch",
        },
        body: formData,
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
        const error = new Error((data && data.error) || "Cookbook update failed.");
        error.status = response.status;
        error.data = data;
        throw error;
    }

    return data;
}

function recipeLogCookbookActionData(button) {
    const row = button
        ? button.closest(".recipe-url-summary-row, .recipe-view-card, .recipe-edit-cookbook-field")
        : null;

    return {
        recipeUrl: (button && button.dataset.recipeUrl) || (row && (row.dataset.recipeUrl || row.dataset.recipeViewUrl)) || "",
        cookbookId: button ? button.dataset.cookbookId || "" : "",
        cookbookName: button ? button.dataset.cookbookName || "" : "",
        cookbookIsUnclassified: Boolean(button && button.dataset.cookbookUnclassified === "1"),
    };
}

async function moveRecipeUrlToCookbook(recipeUrl, cookbookId, options = {}) {
    const formData = new FormData();
    formData.set("cookbook_id", cookbookId || "");
    formData.set("overwrite_existing", "1");
    formData.append("recipe_urls", recipeUrl || "");

    if (options.insertBeforeRecipeUrl) {
        formData.set("insert_before_recipe_url", options.insertBeforeRecipeUrl);
    }

    if (options.insertAfterRecipeUrl) {
        formData.set("insert_after_recipe_url", options.insertAfterRecipeUrl);
    }

    return submitCookbookApi("/api/cookbooks/move_recipes", formData);
}

async function finishRecipeLogCookbookChange(message) {
    await refreshStoreMarkup({
        cacheBust: true,
        requireRecipeLog: true,
    });
    showRecipeQuantityUpdatedMessage("", "", "", message || "Cookbook updated.");
}

async function moveRecipeLogCookbook(button) {
    const { recipeUrl, cookbookId, cookbookName, cookbookIsUnclassified } = recipeLogCookbookActionData(button);

    if (!recipeUrl || !cookbookId) {
        return false;
    }

    const originalText = button ? button.textContent : "";

    try {
        closeRecipeEditRowMenus();

        if (button) {
            button.disabled = true;
            button.textContent = "Moving...";
        }

        await moveRecipeUrlToCookbook(recipeUrl, cookbookId);
        await finishRecipeLogCookbookChange(`Recipe moved to ${cookbookName || "cookbook"}.`);
        updateRecipeEditorCookbookAssignment(recipeUrl, cookbookId, cookbookName, cookbookIsUnclassified);
    } catch (err) {
        console.warn("Unable to move recipe cookbook.", err);
        setCookbookStatus(err.message || "Unable to move recipe.", true);
        window.alert(err.message || "Unable to move recipe.");
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Move";
        }
    }

    return false;
}

async function deleteRecipeLogCookbookAssignment(button) {
    return moveRecipeLogCookbook(button);
}

async function createRecipeLogCookbook(button) {
    const { recipeUrl } = recipeLogCookbookActionData(button);
    const name = window.prompt("New cookbook name");

    if (!recipeUrl || !name || !name.trim()) {
        return false;
    }

    const originalText = button ? button.textContent : "";

    try {
        closeRecipeEditRowMenus();

        if (button) {
            button.disabled = true;
            button.textContent = "Creating...";
        }

        const formData = new FormData();
        formData.set("name", name.trim());
        const data = await submitCookbookApi("/api/cookbooks", formData);
        const cookbook = data.cookbook || {};

        if (!cookbook.id) {
            throw new Error("Cookbook was created, but its id was not returned.");
        }

        await moveRecipeUrlToCookbook(recipeUrl, cookbook.id);
        await finishRecipeLogCookbookChange(`Recipe moved to ${cookbook.name || name.trim()}.`);
        updateRecipeEditorCookbookAssignment(recipeUrl, cookbook.id, cookbook.name || name.trim(), false);
    } catch (err) {
        console.warn("Unable to create recipe cookbook.", err);
        setCookbookStatus(err.message || "Unable to create cookbook.", true);
        window.alert(err.message || "Unable to create cookbook.");
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Create New Cookbook";
        }
    }

    return false;
}

async function moveRecipesToCookbook(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = document.getElementById("cookbookMoveButton");
    const target = document.getElementById("cookbookMoveTarget");
    const originalText = button ? button.textContent : "";
    const formData = new FormData();

    if (target) {
        formData.set("cookbook_id", target.value);
    }

    document.querySelectorAll("[data-cookbook-recipe-checkbox]:checked").forEach(checkbox => {
        formData.append("recipe_urls", checkbox.value);
    });

    try {
        if (button) {
            button.disabled = true;
            button.textContent = "Moving...";
        }

        setCookbookStatus("Moving recipes...");
        try {
            await submitCookbookForm(form, { formData });
        } catch (err) {
            const isOverwriteConflict = err.data && err.data.conflict === "cookbook_recipe_exists";

            if (!isOverwriteConflict) {
                throw err;
            }

            const targetName = target && target.selectedOptions && target.selectedOptions[0]
                ? target.selectedOptions[0].textContent.trim()
                : "";
            const shouldOverwrite = await promptCookbookOverwrite(err.data.conflicts || [], targetName);

            if (!shouldOverwrite) {
                setCookbookStatus("Move canceled.");
                return false;
            }

            formData.set("overwrite_existing", "1");

            if (button) {
                button.textContent = "Overwriting...";
            }

            setCookbookStatus("Overwriting recipe...");
            await submitCookbookForm(form, { formData });
        }

        await refreshStoreMarkup({
            cacheBust: true,
            requireRecipeLog: true,
        });
        showRecipeQuantityUpdatedMessage("", "", "", "Recipes moved.");
    } catch (err) {
        console.warn("Unable to move cookbook recipes.", err);
        setCookbookStatus(err.message || "Unable to move recipes.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Move Selected";
            updateCookbookMoveButton();
        }
    }

    return false;
}

async function restoreCookbookRecipes(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = document.getElementById("cookbookRestoreButton");
    const originalText = button ? button.textContent : "";
    const formData = new FormData();

    document.querySelectorAll("[data-cookbook-restore-checkbox]:checked").forEach(checkbox => {
        formData.append("recipe_urls", checkbox.value);
    });

    try {
        if (button) {
            button.disabled = true;
            button.textContent = "Adding...";
        }

        setCookbookStatus("Adding recipes to recipe log...");
        const data = await submitCookbookForm(form, { formData });
        await refreshStoreMarkup({
            cacheBust: true,
            requireRecipeLog: true,
        });
        const restoredCount = data && data.restored_count ? data.restored_count : selectedCookbookRestoreCount();
        showRecipeQuantityUpdatedMessage(
            "",
            "",
            "",
            `${restoredCount || "Selected"} recipe${restoredCount === 1 ? "" : "s"} added to recipe log.`
        );
    } catch (err) {
        console.warn("Unable to restore cookbook recipes.", err);
        setCookbookStatus(err.message || "Unable to add recipes to recipe log.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Add Selected to Recipe Log";
            updateCookbookRestoreButton();
        }
    }

    return false;
}

async function restoreSingleCookbookRecipe(button) {
    const recipeUrl = button ? button.dataset.recipeUrl || "" : "";
    const originalText = button ? button.textContent : "";
    const formData = new FormData();

    if (!recipeUrl) {
        return false;
    }

    formData.append("recipe_urls", recipeUrl);

    try {
        closeRecipeEditRowMenus();

        if (button) {
            button.disabled = true;
            button.textContent = "Adding...";
        }

        setCookbookStatus("Adding recipe to current recipes...");
        await submitCookbookApi("/api/cookbooks/restore_recipes", formData);
        await refreshStoreMarkup({
            cacheBust: true,
            requireRecipeLog: true,
        });
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe added to current recipes.");
    } catch (err) {
        console.warn("Unable to add cookbook recipe to current recipes.", err);
        setCookbookStatus(err.message || "Unable to add recipe to current recipes.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Add to current recipes";
        }
    }

    return false;
}

async function removeCookbookRecipe(button) {
    if (!button) {
        return false;
    }

    const formData = new FormData();
    formData.set("cookbook_id", button.dataset.cookbookId || "");
    formData.set("recipe_url", button.dataset.recipeUrl || "");

    const originalText = button.textContent;

    try {
        button.disabled = true;
        button.textContent = "Removing...";
        setCookbookStatus("Removing recipe...");

        const response = await fetch("/api/cookbooks/remove_recipe", {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
            body: formData,
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to remove recipe.");
        }

        await refreshStoreMarkup({
            cacheBust: true,
            requireRecipeLog: true,
        });
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe removed.");
    } catch (err) {
        console.warn("Unable to remove cookbook recipe.", err);
        setCookbookStatus(err.message || "Unable to remove recipe.", true);
    } finally {
        button.disabled = false;
        button.textContent = originalText || "Remove";
    }

    return false;
}

function setCookbookNameEditorStatus(message, isError = false) {
    const status = document.getElementById("cookbookNameEditorStatus");

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("error", Boolean(isError));
}

function openCookbookNameEditor(button) {
    const modal = document.getElementById("cookbookNameEditorModal");
    const form = document.getElementById("cookbookNameEditorForm");
    const input = document.getElementById("cookbookNameEditorInput");

    if (!button || !modal || !form || !input) {
        return false;
    }

    const cookbookId = button.dataset.cookbookId || "";
    const cookbookName = button.dataset.cookbookName || "";

    if (!cookbookId) {
        return false;
    }

    form.setAttribute("action", `/api/cookbooks/${encodeURIComponent(cookbookId)}/rename`);
    input.value = cookbookName;
    setCookbookNameEditorStatus("");

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    window.setTimeout(() => {
        input.focus();
        input.select();
    }, 0);

    return false;
}

function closeCookbookNameEditor() {
    const modal = document.getElementById("cookbookNameEditorModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
    }

    setCookbookNameEditorStatus("");

    if (!document.querySelector(".store-add-modal-backdrop.open") && !document.querySelector(".store-edit-form.open")) {
        document.body.classList.remove("modal-open");
    }
}

async function saveCookbookName(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = form ? form.querySelector(".cookbook-name-save-btn") : null;
    const originalText = button ? button.textContent : "";

    try {
        if (button) {
            button.disabled = true;
            button.textContent = "Saving...";
        }

        setCookbookNameEditorStatus("Saving cookbook name...");
        await submitCookbookForm(form);
        closeCookbookNameEditor();
        await refreshStoreMarkup({
            cacheBust: true,
            requireRecipeLog: true,
        });
        showRecipeQuantityUpdatedMessage("", "", "", "Cookbook name saved.");
    } catch (err) {
        console.warn("Unable to rename cookbook.", err);
        setCookbookNameEditorStatus(err.message || "Unable to save cookbook name.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Save Name";
        }
    }

    return false;
}

async function deleteCookbook(button) {
    if (!button) {
        return false;
    }

    const cookbookId = button.dataset.cookbookId || "";
    const cookbookName = button.dataset.cookbookName || "this cookbook";

    if (!cookbookId || !window.confirm(`Delete ${cookbookName}?`)) {
        return false;
    }

    const originalText = button.textContent;

    try {
        button.disabled = true;
        button.textContent = "...";
        setCookbookStatus("Deleting cookbook...");

        const response = await fetch(`/api/cookbooks/${encodeURIComponent(cookbookId)}`, {
            method: "DELETE",
            headers: {
                "X-Requested-With": "fetch",
            },
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to delete cookbook.");
        }

        await refreshStoreMarkup({
            cacheBust: true,
            requireRecipeLog: true,
        });
        showRecipeQuantityUpdatedMessage("", "", "", "Cookbook deleted.");
    } catch (err) {
        console.warn("Unable to delete cookbook.", err);
        setCookbookStatus(err.message || "Unable to delete cookbook.", true);
    } finally {
        button.disabled = false;
        button.textContent = originalText || "X";
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

function cardCollapseStorageKey(key, content) {
    const explicitKey = content && content.dataset
        ? content.dataset.collapseStorageKey
        : "";

    return `card-collapse:${explicitKey || key}`;
}

function getSavedCardCollapseState(key, content) {
    try {
        return localStorage.getItem(cardCollapseStorageKey(key, content));
    } catch (err) {
        return null;
    }
}

function setSavedCardCollapseState(key, content, state) {
    try {
        localStorage.setItem(cardCollapseStorageKey(key, content), state);
    } catch (err) {
        // Collapse state is a convenience preference; keep the UI usable if storage is unavailable.
    }
}

function toggleCardCollapse(key) {
    const content = document.querySelector(`[data-collapse-content="${key}"]`);
    const storeOptionsStickyTop = key === "store-options"
        ? storeOptionsStickyStackTop()
        : null;

    if (!content) {
        return;
    }

    const isCollapsed = content.classList.toggle("collapsed");
    const card = content.closest(".app-card");
    setSavedCardCollapseState(key, content, isCollapsed ? "collapsed" : "expanded");

    if (card) {
        card.classList.toggle("card-collapsed", isCollapsed);
    }

    updateCardCollapseToggleState(key, isCollapsed);

    window.setTimeout(initStoreLocationMaps, 0);
    scheduleAddStoreStickyVisibilityUpdate();

    if (key === "store-options" && isCollapsed) {
        preserveStoreOptionsStickyPosition(storeOptionsStickyTop);
    }

    if (key === "rules" && isCollapsed) {
        window.setTimeout(scrollRulesIntoView, 0);
    }
}

function storeOptionsStickyStackTop() {
    const stack = document.querySelector("#storeOptionsSection .store-options-sticky-stack");

    return stack ? stack.getBoundingClientRect().top : null;
}

function preserveStoreOptionsStickyPosition(previousTop) {
    if (!Number.isFinite(previousTop)) {
        return;
    }

    const nextTop = storeOptionsStickyStackTop();

    if (!Number.isFinite(nextTop)) {
        return;
    }

    const delta = nextTop - previousTop;

    if (Math.abs(delta) > 0.5) {
        window.scrollBy(0, delta);
    }
}

function updateCardCollapseToggleState(key, isCollapsed) {
    const icon = document.querySelector(`[data-collapse-icon="${key}"]`);
    const toggle = document.querySelector(`[data-collapse-toggle="${key}"]`);

    if (icon) {
        icon.dataset.collapseState = isCollapsed ? "collapsed" : "expanded";

        if (!icon.classList.contains("card-collapse-switch")) {
            icon.textContent = isCollapsed ? "Show v" : "Hide ^";
        }
    }

    if (toggle) {
        toggle.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
        toggle.classList.toggle("card-collapse-toggle-collapsed", isCollapsed);
    }
}

function scrollRulesIntoView() {
    scrollCardIntoView("rulesCard");
}

function scrollCardIntoView(cardId, options = {}) {
    const section = document.getElementById(cardId);

    if (!section) {
        return;
    }

    section.scrollIntoView({
        behavior: options.behavior || "smooth",
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

function storeOptionsSection() {
    return document.getElementById("storeOptionsSection");
}

function canManageStores() {
    const section = storeOptionsSection();
    return section ? section.dataset.storeCanManage === "true" : false;
}

function canToggleStores() {
    const section = storeOptionsSection();
    return section ? section.dataset.storeCanToggle === "true" : false;
}

function canEditStoreCredentials() {
    const section = storeOptionsSection();
    return section ? section.dataset.storeCanEditCredentials === "true" : false;
}

function toggleStorePanel(panelId) {
    return openStoreEditModal(panelId);
}

function openStoreEditModal(formId, trigger) {
    const form = document.getElementById(formId);
    const backdrop = document.getElementById("storeEditModalBackdrop");

    if (!form || (!canManageStores() && !canEditStoreCredentials())) {
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
        const firstInput = form.querySelector('input[name="store_label"], input[name="store_username"], input[name="store_password"]');

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
        const savedState = getSavedCardCollapseState(key, content);
        const shouldCollapse = savedState
            ? savedState === "collapsed"
            : cardCollapseDefaultIsCollapsed(content);
        const card = content.closest(".app-card");

        content.classList.toggle("collapsed", shouldCollapse);

        if (card) {
            card.classList.toggle("card-collapsed", shouldCollapse);
        }

        updateCardCollapseToggleState(key, shouldCollapse);
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
    const activeView = Object.prototype.hasOwnProperty.call(views, viewName)
        ? viewName
        : "section";
    const buttons = {
        section: document.getElementById("sectionViewBtn"),
        store: document.getElementById("storeViewBtn"),
        recipe: document.getElementById("recipeViewBtn"),
    };

    Object.entries(views).forEach(([key, view]) => {
        if (view) {
            view.style.display = key === activeView ? "" : "none";
        }
    });

    Object.entries(buttons).forEach(([key, button]) => {
        if (button) {
            const isActive = key === activeView;
            button.classList.toggle("active", isActive);
            button.setAttribute("aria-pressed", isActive ? "true" : "false");
        }
    });

    const switcher = document.getElementById("viewSwitcherSticky");
    if (switcher) {
        switcher.dataset.activeView = activeView;
    }

    localStorage.setItem("shopping-view", activeView);
    updateViewSwitcherStickyOffset();
}

function eventStartedInNestedInteractive(event, container) {
    if (!event || !event.target || !event.target.closest || !container) {
        return false;
    }

    const interactive = event.target.closest("a, button, input, select, textarea, label, [role='button'], [contenteditable='true']");
    return Boolean(interactive && interactive !== container);
}

function jumpToRecipeViewRecipe(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const recipeUrl = button ? button.dataset.recipeUrl || "" : "";

    if (!recipeUrl) {
        return false;
    }

    showView("recipe");

    const target = document.querySelector(`[data-recipe-view-url="${cssEscape(recipeUrl)}"]`);

    if (!target) {
        return false;
    }

    const toggle = target.querySelector("[data-recipe-card-toggle]");

    if (typeof setRecipeCardCollapsed === "function") {
        setRecipeCardCollapsed(target, toggle, false);
        localStorage.setItem(`recipe-card-collapsed:${target.dataset.recipeCardKey || (toggle && toggle.dataset.recipeCardKey) || recipeUrl}`, "0");
    } else {
        target.classList.remove("recipe-view-collapsed");
    }

    scrollRecipeJumpTargetIntoView(target);

    return false;
}

function jumpToCurrentRecipeLog(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const recipeUrl = button ? button.dataset.recipeUrl || "" : "";

    return jumpToCurrentRecipeLogUrl(recipeUrl);
}

function jumpToCurrentRecipeLogUrl(recipeUrl) {
    if (!recipeUrl) {
        return false;
    }

    const content = document.querySelector('[data-collapse-content="recipe-url-log"]');

    if (content && content.classList.contains("collapsed")) {
        toggleCardCollapse("recipe-url-log");
    }

    const target = document.querySelector(`[data-current-recipe-row][data-recipe-url="${cssEscape(recipeUrl)}"]`)
        || document.getElementById("currentRecipeUrlLogCard");

    scrollRecipeJumpTargetIntoView(target);

    return false;
}

function scrollRecipeJumpTargetIntoView(target) {
    if (!target) {
        return;
    }

    target.classList.remove("recipe-jump-highlight");
    void target.offsetWidth;
    target.classList.add("recipe-jump-highlight");
    target.scrollIntoView({
        behavior: "auto",
        block: "start",
        inline: "nearest",
    });

    window.setTimeout(() => {
        target.classList.remove("recipe-jump-highlight");
    }, 1400);
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

function saveShowImagesByDefaultSetting() {
    saveToggleSetting("showImagesByDefaultToggle", "show-images-by-default", null);
    applyRecipeImageDefaultVisibility();
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

    syncViewBehaviorMenuToggles(inputId);
}

function toggleViewBehaviorMenuSetting(button) {
    const inputId = button ? button.dataset.viewBehaviorInput || "" : "";
    const input = inputId ? document.getElementById(inputId) : null;

    if (!input) {
        return false;
    }

    input.checked = !input.checked;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    syncViewBehaviorMenuToggles(inputId);

    return false;
}

function syncViewBehaviorMenuToggles(inputId = "") {
    document.querySelectorAll("[data-view-behavior-input]").forEach(button => {
        const targetInputId = button.dataset.viewBehaviorInput || "";

        if (inputId && targetInputId !== inputId) {
            return;
        }

        const input = document.getElementById(targetInputId);
        const checked = Boolean(input && input.checked);

        button.setAttribute("aria-pressed", checked ? "true" : "false");
        button.classList.toggle("active", checked);
    });
}

function restoreViewBehaviorSettings() {
    restoreToggleSetting("openStoreUrlsToggle", "open-store-urls", true);
    restoreToggleSetting("showItemButtonsToggle", "show-item-buttons", true, "hide-item-buttons", true);
    restoreToggleSetting("showBestProductToggle", "show-best-product", true, "hide-best-product", true);
    restoreToggleSetting("showQtyToggle", "show-qty", true, "hide-qty", true);
    restoreToggleSetting("hideCheckedItemsToggle", "hide-checked-items", false, "hide-checked-items");
    restoreToggleSetting("compactModeToggle", "compact-mode", false, "compact-mode");
    restoreToggleSetting("showImagesByDefaultToggle", "show-images-by-default", true);
    applyRecipeImageDefaultVisibility();
    syncViewBehaviorMenuToggles();
    showView(localStorage.getItem("shopping-view") || "section");
}

const SCREEN_PREVIEW_MODE_KEY = "screen-preview-mode";
const SCREEN_PREVIEW_WIDTH_KEY = "screen-preview-custom-width";
const SCREEN_PREVIEW_HEIGHT_KEY = "screen-preview-custom-height";
const SCREEN_PREVIEW_PHONE_ORIENTATION_KEY = "screen-preview-phone-orientation";
const SCREEN_PREVIEW_DEFAULTS = {
    live: { label: "Live", width: 0, height: 0 },
    phone: { label: "Phone", width: 390, height: 844 },
    computer: { label: "Computer", width: 1280, height: 900 },
    custom: { label: "Custom", width: 430, height: 860 },
};

function isScreenPreviewFrame() {
    return new URLSearchParams(window.location.search).get("screen_preview_frame") === "1";
}

function hasAccountActionToken() {
    const params = new URLSearchParams(window.location.search);
    return Boolean(
        params.get("two_factor_recovery_token")
        || params.get("reset_token")
        || params.get("account_delete_token")
    );
}

function restoreScreenSettings() {
    if (isScreenPreviewFrame()) {
        document.body.classList.add("screen-preview-frame-page");
        const params = new URLSearchParams(window.location.search);
        const mode = screenPreviewMode(params.get("screen_preview_mode") || "live");
        const width = clampScreenPreviewNumber(params.get("screen_preview_width"), window.innerWidth || SCREEN_PREVIEW_DEFAULTS.phone.width);

        document.body.dataset.screenPreviewMode = mode;
        document.body.classList.toggle("screen-preview-mobile-frame", mode === "phone" || width <= 650);
        return;
    }

    if (hasAccountActionToken()) {
        localStorage.setItem(SCREEN_PREVIEW_MODE_KEY, "live");
        setScreenPreviewMode("live", { persist: false });
        return;
    }

    const customWidth = screenPreviewStoredNumber(SCREEN_PREVIEW_WIDTH_KEY, SCREEN_PREVIEW_DEFAULTS.custom.width);
    const customHeight = screenPreviewStoredNumber(SCREEN_PREVIEW_HEIGHT_KEY, SCREEN_PREVIEW_DEFAULTS.custom.height);
    const widthInput = document.getElementById("screenCustomWidth");
    const heightInput = document.getElementById("screenCustomHeight");

    if (widthInput) {
        widthInput.value = String(customWidth);
    }

    if (heightInput) {
        heightInput.value = String(customHeight);
    }

    setScreenPreviewMode(localStorage.getItem(SCREEN_PREVIEW_MODE_KEY) || "live", { persist: false });
}

function cancelAccountActionLink() {
    localStorage.setItem(SCREEN_PREVIEW_MODE_KEY, "live");

    const url = new URL(window.location.href);
    [
        "two_factor_recovery_token",
        "reset_token",
        "account_delete_token",
        "screen_preview_frame",
        "screen_preview_mode",
        "screen_preview_width",
    ].forEach(param => url.searchParams.delete(param));
    url.hash = "userAccountSection";
    window.location.href = url.toString();
    return false;
}

function screenPreviewStoredNumber(key, fallback) {
    return clampScreenPreviewNumber(localStorage.getItem(key), fallback);
}

function clampScreenPreviewNumber(value, fallback) {
    const parsed = Number.parseInt(value, 10);

    if (!Number.isFinite(parsed)) {
        return fallback;
    }

    return Math.max(320, Math.min(1920, parsed));
}

function screenPreviewDimensions(mode) {
    const normalizedMode = screenPreviewMode(mode);

    if (normalizedMode === "phone") {
        const orientation = screenPreviewPhoneOrientation();
        const phone = SCREEN_PREVIEW_DEFAULTS.phone;
        const isLandscape = orientation === "landscape";

        return {
            ...phone,
            label: isLandscape ? "Phone Landscape" : "Phone Portrait",
            width: isLandscape ? phone.height : phone.width,
            height: isLandscape ? phone.width : phone.height,
            orientation,
        };
    }

    if (normalizedMode === "custom") {
        return {
            ...SCREEN_PREVIEW_DEFAULTS.custom,
            width: screenPreviewStoredNumber(SCREEN_PREVIEW_WIDTH_KEY, SCREEN_PREVIEW_DEFAULTS.custom.width),
            height: Math.max(480, Math.min(1400, screenPreviewStoredNumber(
                SCREEN_PREVIEW_HEIGHT_KEY,
                SCREEN_PREVIEW_DEFAULTS.custom.height
            ))),
        };
    }

    return SCREEN_PREVIEW_DEFAULTS[normalizedMode] || SCREEN_PREVIEW_DEFAULTS.live;
}

function screenPreviewPhoneOrientation() {
    return localStorage.getItem(SCREEN_PREVIEW_PHONE_ORIENTATION_KEY) === "landscape"
        ? "landscape"
        : "portrait";
}

function screenPreviewMode(mode) {
    return Object.prototype.hasOwnProperty.call(SCREEN_PREVIEW_DEFAULTS, mode) ? mode : "live";
}

function setScreenPreviewMode(mode, options = {}) {
    const normalizedMode = screenPreviewMode(mode);
    const isLive = normalizedMode === "live";
    const dimensions = screenPreviewDimensions(normalizedMode);
    const stage = document.getElementById("screenPreviewStage");
    const frame = document.getElementById("screenPreviewFrame");
    const label = document.getElementById("screenPreviewLabel");
    const size = document.getElementById("screenPreviewSize");

    document.body.classList.toggle("screen-preview-active", !isLive);
    document.body.dataset.screenPreviewMode = normalizedMode;
    document.body.dataset.screenPhoneOrientation = screenPreviewPhoneOrientation();
    document.querySelectorAll("[data-screen-mode-button]").forEach(button => {
        const active = button.dataset.screenModeButton === normalizedMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    updatePhoneOrientationControl(normalizedMode);

    if (stage) {
        stage.hidden = isLive;
    }

    if (label) {
        label.textContent = dimensions.label;
    }

    if (size) {
        size.textContent = isLive ? "Auto" : `${dimensions.width} x ${dimensions.height}`;
    }

    document.documentElement.style.setProperty("--screen-preview-width", `${Math.max(1, dimensions.width)}px`);
    document.documentElement.style.setProperty("--screen-preview-height", `${Math.max(1, dimensions.height)}px`);

    if (!isLive && frame) {
        const previewUrl = screenPreviewUrl();
        if (frame.dataset.previewSrc !== previewUrl) {
            frame.src = previewUrl;
            frame.dataset.previewSrc = previewUrl;
        }
    }

    if (options.persist !== false) {
        localStorage.setItem(SCREEN_PREVIEW_MODE_KEY, normalizedMode);
    }

    window.setTimeout(updateAddStoreStickyVisibility, 80);
}

function updatePhoneOrientationControl(mode) {
    const button = document.getElementById("screenPhoneRotateBtn");

    if (!button) {
        return;
    }

    const orientation = screenPreviewPhoneOrientation();
    const isPhone = mode === "phone";
    const isLandscape = orientation === "landscape";

    button.disabled = !isPhone;
    button.classList.toggle("active", isPhone && isLandscape);
    button.setAttribute("aria-pressed", isPhone && isLandscape ? "true" : "false");
    button.setAttribute(
        "aria-label",
        isLandscape ? "Rotate phone preview to portrait" : "Rotate phone preview to landscape"
    );
    button.title = isPhone
        ? (isLandscape ? "Rotate phone preview to portrait" : "Rotate phone preview to landscape")
        : "Select Phone to rotate the preview.";
}

function rotatePhonePreview() {
    const nextOrientation = screenPreviewPhoneOrientation() === "landscape" ? "portrait" : "landscape";
    localStorage.setItem(SCREEN_PREVIEW_PHONE_ORIENTATION_KEY, nextOrientation);
    setScreenPreviewMode("phone");
}

function screenPreviewUrl() {
    const url = new URL(window.location.href);
    const mode = screenPreviewMode(localStorage.getItem(SCREEN_PREVIEW_MODE_KEY) || "live");
    const dimensions = screenPreviewDimensions(mode);

    url.searchParams.set("screen_preview_frame", "1");
    url.searchParams.set("screen_preview_mode", mode);
    url.searchParams.set("screen_preview_width", String(dimensions.width || window.innerWidth || 0));
    return url.toString();
}

function applyCustomScreenPreview() {
    const widthInput = document.getElementById("screenCustomWidth");
    const heightInput = document.getElementById("screenCustomHeight");
    const width = clampScreenPreviewNumber(widthInput ? widthInput.value : "", SCREEN_PREVIEW_DEFAULTS.custom.width);
    const height = Math.max(480, Math.min(1400, clampScreenPreviewNumber(
        heightInput ? heightInput.value : "",
        SCREEN_PREVIEW_DEFAULTS.custom.height
    )));

    localStorage.setItem(SCREEN_PREVIEW_WIDTH_KEY, String(width));
    localStorage.setItem(SCREEN_PREVIEW_HEIGHT_KEY, String(height));

    if (widthInput) {
        widthInput.value = String(width);
    }

    if (heightInput) {
        heightInput.value = String(height);
    }

    setScreenPreviewMode("custom");
}

function refreshScreenPreview() {
    const frame = document.getElementById("screenPreviewFrame");
    const stage = document.getElementById("screenPreviewStage");

    if (frame && stage && !stage.hidden) {
        frame.src = screenPreviewUrl();
        frame.dataset.previewSrc = frame.src;
    }
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
    const allowedModes = new Set(["store", "map", "activation", "edit"]);

    if (!canToggleStores()) {
        allowedModes.delete("activation");
    }

    if (!canManageStores() && !canEditStoreCredentials()) {
        allowedModes.delete("edit");
    }

    const nextMode = allowedModes.has(mode) ? mode : "store";

    document.body.classList.toggle("active-store-map-mode", nextMode === "map");
    document.body.classList.toggle("active-store-activation-mode", nextMode === "activation");
    document.body.classList.toggle("active-store-edit-mode", nextMode === "edit");
    document.querySelectorAll("[data-active-store-mode-toggle]").forEach(button => {
        const active = button.dataset.activeStoreModeToggle === nextMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    document.querySelectorAll("[data-active-store-heading-label]").forEach(label => {
        label.textContent = (nextMode === "activation" || nextMode === "edit") ? "All stores" : "Active stores";
    });
    document.querySelectorAll(".active-store-card").forEach(card => {
        const storeTitle = card.dataset.storeTitle || card.getAttribute("title") || "";
        const mapTitle = card.dataset.mapTitle || storeTitle;
        const activationTitle = card.dataset.activationTitle || storeTitle;
        const editTitle = card.dataset.editTitle || storeTitle;
        const storeKey = card.dataset.storeKey || "";
        const title = nextMode === "edit"
            ? editTitle
            : (nextMode === "activation"
            ? activationTitle
            : (nextMode === "map" ? mapTitle : storeTitle));
        const storeUrl = card.dataset.storeUrl || card.getAttribute("href") || "";

        if (nextMode === "edit") {
            card.setAttribute("href", `#store-edit-${storeKey}`);
            card.removeAttribute("target");
        } else if (storeUrl) {
            card.setAttribute("href", storeUrl);
            card.setAttribute("target", "_blank");
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

function storeManagerRowName(row) {
    const name = row ? row.querySelector(".store-manager-label") : null;

    return name ? name.textContent : "";
}

function storeNameMatchesSearch(storeName, query) {
    const normalizedName = normalizeActiveStoreSearchText(storeName);

    if (!query) {
        return true;
    }

    return normalizedName.includes(query);
}

function activeStoreCardIsEligibleForSearch(card) {
    if (
        document.body.classList.contains("active-store-activation-mode") ||
        document.body.classList.contains("active-store-edit-mode")
    ) {
        return true;
    }

    return card && card.dataset.storeActive === "true";
}

function filterActiveStores(value) {
    const input = document.getElementById("activeStoreSearchInput");
    const query = normalizeActiveStoreSearchText(value !== undefined ? value : (input ? input.value : ""));
    let visibleCount = 0;
    let visibleManagerCount = 0;
    const storeShelf = document.querySelector(".active-store-list");

    if (input && value !== undefined && input.value !== value) {
        input.value = value;
    }

    document.querySelectorAll(".active-store-card").forEach(card => {
        const matchesSearch = storeNameMatchesSearch(activeStoreCardName(card), query);
        const eligible = activeStoreCardIsEligibleForSearch(card);

        card.classList.toggle("active-store-search-hidden", !matchesSearch);

        if (matchesSearch && eligible) {
            visibleCount += 1;
        }
    });

    document.querySelectorAll(".store-manager-row").forEach(row => {
        const matchesSearch = storeNameMatchesSearch(storeManagerRowName(row), query);

        row.hidden = !matchesSearch;

        if (matchesSearch) {
            visibleManagerCount += 1;
        }
    });

    document.querySelectorAll(".active-store-search-empty").forEach(empty => {
        empty.hidden = !query || visibleCount > 0;
    });

    document.querySelectorAll(".store-manager-search-empty").forEach(empty => {
        empty.hidden = !query || visibleManagerCount > 0;
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
    if (document.body.classList.contains("active-store-edit-mode")) {
        if (!canManageStores() && !canEditStoreCredentials()) {
            return true;
        }

        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        return openStoreEditModal(`store-edit-${link ? link.dataset.storeKey || "" : ""}`, link);
    }

    if (document.body.classList.contains("active-store-activation-mode")) {
        if (!canToggleStores()) {
            return true;
        }

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
    if (!canToggleStores()) {
        return false;
    }

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

async function toggleStoreActivationFromMenu(button) {
    closeRecipeEditRowMenus();

    if (!canToggleStores()) {
        return false;
    }

    const storeKey = button ? button.dataset.storeToggleMenuAction || "" : "";
    const input = findStoreEnabledInput(storeKey);

    if (!input) {
        return false;
    }

    const previousChecked = input.checked;
    input.checked = !previousChecked;

    if (button) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
    }

    const saved = await saveStoreToggle(input);

    if (!saved) {
        input.checked = previousChecked;
    }

    if (button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
    }

    return false;
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

    syncViewBehaviorMenuToggles(inputId);
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
        syncItemCheckedState(row, checkbox, itemText);

        checkbox.addEventListener("change", () => {
            syncItemCheckedState(row, checkbox, itemText);
            localStorage.setItem(`item-checked:${key}`, checkbox.checked ? "1" : "0");
        });

        if (itemText && itemText.dataset.itemTextToggleBound !== "1") {
            itemText.dataset.itemTextToggleBound = "1";
            itemText.tabIndex = 0;
            itemText.setAttribute("role", "button");
            itemText.setAttribute("aria-label", `Toggle ${itemText.textContent.trim()}`);
            itemText.addEventListener("click", () => {
                toggleItemCheckbox(row, checkbox, itemText, key);
            });
            itemText.addEventListener("keydown", event => {
                if (event.key !== "Enter" && event.key !== " ") {
                    return;
                }

                event.preventDefault();
                toggleItemCheckbox(row, checkbox, itemText, key);
            });
        }
    });
}

function syncItemCheckedState(row, checkbox, itemText) {
    row.classList.toggle("row-checked", checkbox.checked);
    if (itemText) {
        itemText.classList.toggle("checked-item-text", checkbox.checked);
        itemText.setAttribute("aria-pressed", checkbox.checked ? "true" : "false");
    }
}

function toggleItemCheckbox(row, checkbox, itemText, key) {
    if (!checkbox) {
        return;
    }

    checkbox.checked = !checkbox.checked;
    syncItemCheckedState(row, checkbox, itemText);
    localStorage.setItem(`item-checked:${key}`, checkbox.checked ? "1" : "0");
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
}

function filterPantryItems(value) {
    const query = String(value || "").trim().toLowerCase();
    let visibleCount = 0;

    document.querySelectorAll("[data-pantry-item]").forEach(item => {
        const searchText = item.dataset.pantrySearch || item.textContent || "";
        const visible = !query || searchText.toLowerCase().includes(query);
        item.hidden = !visible;

        if (visible) {
            visibleCount += 1;
        }
    });

    document.querySelectorAll("[data-pantry-search-empty]").forEach(empty => {
        empty.hidden = !query || visibleCount > 0;
    });
}

function pantryInventoryForFeelingPrompt() {
    return Array.from(document.querySelectorAll("[data-pantry-item]"))
        .map(item => {
            const ingredient = String(item.dataset.pantryIngredient || "").trim();
            const product = String(item.dataset.pantryProduct || "").trim();
            const quantity = String(item.dataset.pantryQuantity || "").trim();
            const unit = String(item.dataset.pantryUnit || "").trim();
            const category = String(item.dataset.pantryCategory || "").trim();
            const amount = [quantity, unit].filter(Boolean).join(" ");
            const details = [
                product && product !== ingredient ? product : "",
                amount,
                category,
            ].filter(Boolean);

            if (!ingredient) {
                return "";
            }

            return details.length ? `${ingredient} (${details.join(", ")})` : ingredient;
        })
        .filter(Boolean)
        .slice(0, 40);
}

function pantryRecipeTitlesForFeelingPrompt() {
    return Array.from(document.querySelectorAll("#aiPantryCookWithWhatIHave .ai-pantry-recipe-card h4"))
        .map(title => title.textContent.trim())
        .filter(Boolean)
        .slice(0, 12);
}

function setPantryFeelingStatus(message, isError = false) {
    const status = document.getElementById("pantryFeelingStatus");

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("error", Boolean(isError));
}

function buildPantryFeelingPrompt(form) {
    const activeForm = form && form.querySelector
        ? form
        : document.querySelector(".ai-pantry-feeling-form");
    const feelingInput = activeForm ? activeForm.querySelector("#pantryFeelingInput") : null;
    const constraintsInput = activeForm ? activeForm.querySelector("#pantryFeelingConstraints") : null;
    const servingsInput = activeForm ? activeForm.querySelector("#pantryFeelingServings") : null;
    const output = activeForm ? activeForm.querySelector("#pantryFeelingPromptOutput") : null;
    const feeling = feelingInput ? feelingInput.value.trim() : "";
    const constraints = constraintsInput ? constraintsInput.value.trim() : "";
    const servings = servingsInput ? servingsInput.value.trim() : "";

    if (!feeling) {
        setPantryFeelingStatus("Enter a cuisine, mood, or genre first.", true);
        if (feelingInput) {
            feelingInput.focus();
        }
        return false;
    }

    const pantryItems = pantryInventoryForFeelingPrompt();
    const recipeTitles = pantryRecipeTitlesForFeelingPrompt();
    const promptParts = [
        `I want to cook something in this style or mood: ${feeling}.`,
        servings ? `Target servings: ${servings}.` : "",
        constraints ? `Constraints or preferences: ${constraints}.` : "",
        pantryItems.length
            ? `Pantry inventory I can use:\n- ${pantryItems.join("\n- ")}`
            : "No pantry inventory is saved yet, so suggest a practical recipe idea and list the missing ingredients clearly.",
        recipeTitles.length
            ? `Recipes already in my app that may be useful:\n- ${recipeTitles.join("\n- ")}`
            : "",
        "Suggest 3 meal ideas that fit the mood. Pick the best one, explain why, list ingredients I already have, list missing ingredients, and give concise cooking steps.",
    ].filter(Boolean);

    if (output) {
        output.value = promptParts.join("\n\n");
        output.focus();
        output.setSelectionRange(0, 0);
    }

    setPantryFeelingStatus("Prompt built.");
    return false;
}

async function copyPantryFeelingPrompt(button) {
    const form = button ? button.closest(".ai-pantry-feeling-form") : document.querySelector(".ai-pantry-feeling-form");
    const output = form ? form.querySelector("#pantryFeelingPromptOutput") : null;

    if (!output) {
        return false;
    }

    if (!output.value.trim()) {
        buildPantryFeelingPrompt(form);
    }

    if (!output.value.trim()) {
        return false;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(output.value);
        } else {
            output.select();
            document.execCommand("copy");
        }
        setPantryFeelingStatus("Prompt copied.");
    } catch (err) {
        console.warn("Unable to copy pantry feeling prompt.", err);
        output.select();
        setPantryFeelingStatus("Prompt selected. Use Ctrl+C to copy.", true);
    }

    return false;
}

function pdfShareRowForButton(button) {
    return button ? button.closest("[data-pdf-share-row]") : null;
}

function setPdfShareStatus(row, message, isError = false) {
    const status = row ? row.querySelector(".pdf-share-status") : null;

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("error", Boolean(isError));
}

function updatePdfShareRow(row, data) {
    const panel = row ? row.querySelector(".pdf-share-active") : null;
    const input = row ? row.querySelector(".pdf-share-url") : null;
    const expires = row ? row.querySelector(".pdf-share-expires") : null;
    const revokeButton = row ? row.querySelector(".pdf-share-action-btn.danger") : null;

    if (!row || !panel || !input) {
        return;
    }

    row.dataset.pdfShareToken = data.token || "";
    input.value = data.share_url || "";
    panel.hidden = !input.value;

    if (expires) {
        expires.textContent = data.expires_at ? `Expires ${data.expires_at}` : "";
    }

    if (revokeButton) {
        revokeButton.dataset.pdfShareToken = data.token || "";
    }
}

function updatePdfCloudflareRow(row, data) {
    const publicUrl = data.pdf_public_url || data.public_url || "";
    const openLink = row ? row.querySelector("[data-pdf-open-link]") : null;
    const panel = row ? row.querySelector(".pdf-cloudflare-active") : null;
    const input = row ? row.querySelector(".pdf-cloudflare-url") : null;

    if (!row || !publicUrl) {
        return;
    }

    row.dataset.pdfPublicUrl = publicUrl;

    if (openLink) {
        openLink.href = publicUrl;
    }

    if (input) {
        input.value = publicUrl;
    }

    if (panel) {
        panel.hidden = false;
    }
}

async function uploadPdfToCloudflare(button) {
    const row = pdfShareRowForButton(button);
    const pdfFilename = row ? row.dataset.pdfFilename : "";

    if (!row || !pdfFilename) {
        return false;
    }

    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Uploading...";
    }

    try {
        const response = await fetch("/pdfs/cloudflare_upload", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({ pdf_filename: pdfFilename }),
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to upload PDF to Cloudflare.");
        }

        updatePdfCloudflareRow(row, data);
        setPdfShareStatus(
            row,
            data.already_exists
                ? "Cloudflare PDF link saved."
                : "Uploaded to Cloudflare."
        );
    } catch (err) {
        console.warn("Unable to upload PDF to Cloudflare.", err);
        setPdfShareStatus(row, err.message || "Unable to upload PDF to Cloudflare.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Upload to Cloudflare";
        }
    }

    return false;
}

async function copyPdfCloudflareLink(button) {
    const row = pdfShareRowForButton(button);
    const input = row ? row.querySelector(".pdf-cloudflare-url") : null;
    const publicUrl = (
        (row && row.dataset.pdfPublicUrl ? row.dataset.pdfPublicUrl : "")
        || (input ? input.value.trim() : "")
    );

    if (!publicUrl) {
        setPdfShareStatus(row, "Cloudflare link is not ready yet.", true);
        return false;
    }

    if (!isShareablePublicPdfUrl(publicUrl)) {
        setPdfShareStatus(row, "Cloudflare PDF link is not ready yet.", true);
        return false;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(publicUrl);
        } else if (input) {
            input.select();
            document.execCommand("copy");
        }

        setPdfShareStatus(row, "Cloudflare link copied.");
    } catch (err) {
        console.warn("Unable to copy Cloudflare PDF link.", err);
        if (input) {
            input.select();
        }
        setPdfShareStatus(row, "PDF link selected. Use Ctrl+C to copy.", true);
    }

    return false;
}

async function createPdfShareLink(button) {
    const row = pdfShareRowForButton(button);
    const pdfFilename = row ? row.dataset.pdfFilename : "";

    if (!row || !pdfFilename) {
        return false;
    }

    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Creating...";
    }

    try {
        const response = await fetch("/pdfs/share", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({ pdf_filename: pdfFilename }),
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to create PDF share link.");
        }

        updatePdfShareRow(row, data);
        setPdfShareStatus(row, data.created ? "Share link created." : "Share link ready.");
    } catch (err) {
        console.warn("Unable to create PDF share link.", err);
        setPdfShareStatus(row, err.message || "Unable to create PDF share link.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    return false;
}

async function copyPdfShareLink(button) {
    const row = pdfShareRowForButton(button);
    const input = row ? row.querySelector(".pdf-share-url") : null;
    const shareUrl = input ? input.value.trim() : "";

    if (!shareUrl) {
        setPdfShareStatus(row, "Create a share link first.", true);
        return false;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(shareUrl);
        } else if (input) {
            input.select();
            document.execCommand("copy");
        }

        setPdfShareStatus(row, "Share link copied.");
    } catch (err) {
        console.warn("Unable to copy PDF share link.", err);
        if (input) {
            input.select();
        }
        setPdfShareStatus(row, "Share link selected. Use Ctrl+C to copy.", true);
    }

    return false;
}

async function revokePdfShareLink(button) {
    const row = pdfShareRowForButton(button);
    const token = row
        ? ((button && button.dataset.pdfShareToken) || row.dataset.pdfShareToken || "")
        : "";

    if (!row || !token) {
        setPdfShareStatus(row, "No active share link to revoke.", true);
        return false;
    }

    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Revoking...";
    }

    try {
        const response = await fetch("/pdfs/share/revoke", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({ token }),
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to revoke PDF share link.");
        }

        updatePdfShareRow(row, {
            token: "",
            share_url: "",
            expires_at: "",
        });
        setPdfShareStatus(row, "Share link revoked.");
    } catch (err) {
        console.warn("Unable to revoke PDF share link.", err);
        setPdfShareStatus(row, err.message || "Unable to revoke PDF share link.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    return false;
}

function checkedShoppingItemsForPantry() {
    return Array.from(document.querySelectorAll("#sectionView .row"))
        .filter(row => {
            const checkbox = row.querySelector(".item-check");
            return checkbox && checkbox.checked;
        })
        .map(row => {
            const itemText = row.querySelector(".item-text");
            return {
                name: row.dataset.itemName || (itemText ? itemText.textContent.trim() : ""),
                quantity: 1,
            };
        })
        .filter(item => item.name);
}

async function moveBoughtItemsToPantry(button) {
    const items = checkedShoppingItemsForPantry();

    if (!items.length) {
        showRecipeQuantityUpdatedMessage("", "", "", "Check at least one shopping list item before moving it to the pantry.");
        return false;
    }

    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Moving...";
    }

    try {
        const response = await fetch("/pantry/move_bought_items", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({ items }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to move bought items to pantry.");
        }

        showRecipeQuantityUpdatedMessage("", "", "", data.message || "Bought items moved to pantry.");
        await refreshStoreMarkup({ cacheBust: true });
    } catch (err) {
        console.warn("Unable to move bought items to pantry.", err);
        showRecipeQuantityUpdatedMessage("", "", "", err.message || "Unable to move bought items to pantry.");
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText || "Move Bought Items to Pantry";
        }
    }

    return false;
}

function bindRecipeUrlLogDragAndDrop() {
    const list = document.querySelector("[data-recipe-url-sort-list]");

    if (!list || list.dataset.dragBound === "1") {
        return;
    }

    list.dataset.dragBound = "1";
    list.dataset.savedOrder = recipeUrlOrder(list).join("\n");

    list.querySelectorAll("[data-current-recipe-row]").forEach(row => {
        const handle = row.querySelector("[data-recipe-drag-handle]");
        row.setAttribute("draggable", "true");

        if (handle) {
            handle.addEventListener("pointerdown", () => {
                row.dataset.dragHandleActive = "1";
            });
            handle.addEventListener("pointerup", () => {
                delete row.dataset.dragHandleActive;
            });
            handle.addEventListener("blur", () => {
                delete row.dataset.dragHandleActive;
            });
        }

        row.addEventListener("dragstart", event => {
            if (row.dataset.dragHandleActive !== "1") {
                event.preventDefault();
                return;
            }

            row.classList.add("is-dragging");
            row.setAttribute("aria-grabbed", "true");
            list.classList.add("is-dragging");
            document.body.classList.add("recipe-url-dragging");

            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", row.dataset.recipeUrl || "");
            }
        });

        row.addEventListener("dragend", () => {
            const changed = list.dataset.savedOrder !== recipeUrlOrder(list).join("\n");

            row.classList.remove("is-dragging");
            row.setAttribute("aria-grabbed", "false");
            delete row.dataset.dragHandleActive;
            list.classList.remove("is-dragging");
            document.body.classList.remove("recipe-url-dragging");
            updateRecipeUrlOrderNumbers(list);

            if (changed) {
                saveRecipeUrlOrder(list);
            }
        });
    });

    list.addEventListener("dragover", event => {
        const draggingRow = list.querySelector("[data-current-recipe-row].is-dragging");
        const targetRow = event.target.closest("[data-current-recipe-row]");

        if (!draggingRow || !targetRow || targetRow === draggingRow || targetRow.parentElement !== list) {
            return;
        }

        event.preventDefault();

        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
        }

        const rect = targetRow.getBoundingClientRect();
        const shouldPlaceAfter = event.clientY > rect.top + rect.height / 2;
        list.insertBefore(draggingRow, shouldPlaceAfter ? targetRow.nextElementSibling : targetRow);
        updateRecipeUrlOrderNumbers(list);
    });

    list.addEventListener("drop", event => {
        if (list.querySelector("[data-current-recipe-row].is-dragging")) {
            event.preventDefault();
        }
    });
}

function bindRecipeViewDragAndDrop() {
    const list = document.querySelector("[data-recipe-view-sort-list]");

    if (!list || list.dataset.dragBound === "1") {
        return;
    }

    list.dataset.dragBound = "1";
    list.dataset.savedOrder = recipeViewOrder(list).join("\n");

    list.querySelectorAll("[data-recipe-view-card]").forEach(row => {
        const handle = row.querySelector("[data-recipe-drag-handle]");
        row.setAttribute("draggable", "true");
        row.setAttribute("aria-grabbed", "false");

        if (handle) {
            handle.addEventListener("pointerdown", () => {
                row.dataset.dragHandleActive = "1";
            });
            handle.addEventListener("pointerup", () => {
                delete row.dataset.dragHandleActive;
            });
            handle.addEventListener("blur", () => {
                delete row.dataset.dragHandleActive;
            });
        }

        row.addEventListener("dragstart", event => {
            if (row.dataset.dragHandleActive !== "1") {
                event.preventDefault();
                return;
            }

            closeRecipeEditRowMenus();
            row.classList.add("is-dragging");
            row.setAttribute("aria-grabbed", "true");
            list.classList.add("is-dragging");
            document.body.classList.add("recipe-url-dragging");

            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", row.dataset.recipeViewUrl || "");
            }
        });

        row.addEventListener("dragend", () => {
            const changed = list.dataset.savedOrder !== recipeViewOrder(list).join("\n");

            row.classList.remove("is-dragging");
            row.setAttribute("aria-grabbed", "false");
            delete row.dataset.dragHandleActive;
            list.classList.remove("is-dragging");
            document.body.classList.remove("recipe-url-dragging");
            updateRecipeViewOrderNumbers(list);

            if (changed) {
                saveRecipeViewOrder(list);
            }
        });
    });

    list.addEventListener("dragover", event => {
        const draggingRow = list.querySelector("[data-recipe-view-card].is-dragging");
        const targetRow = event.target.closest("[data-recipe-view-card]");

        if (!draggingRow || !targetRow || targetRow === draggingRow || targetRow.parentElement !== list) {
            return;
        }

        event.preventDefault();

        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
        }

        const rect = targetRow.getBoundingClientRect();
        const shouldPlaceAfter = event.clientY > rect.top + rect.height / 2;
        list.insertBefore(draggingRow, shouldPlaceAfter ? targetRow.nextElementSibling : targetRow);
        updateRecipeViewOrderNumbers(list);
    });

    list.addEventListener("drop", event => {
        if (list.querySelector("[data-recipe-view-card].is-dragging")) {
            event.preventDefault();
        }
    });
}

function recipeUrlSummaryCollapseStorageKey(row) {
    const recipeUrl = row ? row.dataset.recipeUrl || "" : "";
    return recipeUrl ? `recipe-url-summary-collapsed:${recipeUrl}` : "";
}

function setCurrentRecipeUrlSummaryCollapsed(row, collapsed) {
    if (!row) {
        return false;
    }

    row.classList.toggle("recipe-url-summary-collapsed", collapsed);
    const titleToggle = row.querySelector("[data-recipe-url-summary-toggle]");

    if (titleToggle) {
        titleToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }

    updateCurrentRecipeUrlSummaryCollapseMenuToggle(row);
    return true;
}

function toggleCurrentRecipeUrlSummary(button, event = null) {
    if (eventStartedInNestedInteractive(event, button)) {
        return true;
    }

    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const row = button ? button.closest("[data-current-recipe-row]") : null;
    const storageKey = recipeUrlSummaryCollapseStorageKey(row);

    if (!row || !storageKey) {
        return false;
    }

    const shouldCollapse = !row.classList.contains("recipe-url-summary-collapsed");

    setCurrentRecipeUrlSummaryCollapsed(row, shouldCollapse);
    localStorage.setItem(storageKey, shouldCollapse ? "1" : "0");
    closeRecipeEditRowMenus();
    return false;
}

function handleCurrentRecipeUrlSummaryTitleKeydown(button, event) {
    if (!event || (event.key !== "Enter" && event.key !== " ")) {
        return true;
    }

    return toggleCurrentRecipeUrlSummary(button, event);
}

function toggleCurrentRecipeUrlSummaryFromMenu(button) {
    const row = recipeEditActionRowFromButton(button);
    const storageKey = recipeUrlSummaryCollapseStorageKey(row);

    if (!row || !storageKey) {
        return false;
    }

    const shouldCollapse = !row.classList.contains("recipe-url-summary-collapsed");

    setCurrentRecipeUrlSummaryCollapsed(row, shouldCollapse);
    localStorage.setItem(storageKey, shouldCollapse ? "1" : "0");
    closeRecipeEditRowMenus();
    return false;
}

function setCurrentRecipeUrlSummaryImagesVisible(row, visible) {
    if (!row) {
        return false;
    }

    row.classList.remove("recipe-url-summary-images-hidden");
    row.querySelectorAll(".recipe-url-summary-main, .recipe-url-summary-cover").forEach(panel => {
        panel.classList.remove("recipe-image-visibility-hidden");
        panel.setAttribute("aria-hidden", "false");
    });
    return true;
}

function clearCurrentRecipeUrlSummaryImageHiddenState(row) {
    const recipeUrl = row ? row.dataset.recipeUrl || "" : "";

    if (!recipeUrl) {
        return;
    }

    localStorage.removeItem(`recipe-url-summary-images-hidden:${recipeUrl}`);
}

function setCurrentRecipeUrlSummaryImagesVisibleFromMenu(button, visible) {
    const row = recipeEditActionRowFromButton(button);

    if (!row) {
        closeRecipeEditRowMenus();
        return false;
    }

    clearCurrentRecipeUrlSummaryImageHiddenState(row);
    setCurrentRecipeUrlSummaryImagesVisible(row, true);

    if (visible) {
        const collapseStorageKey = recipeUrlSummaryCollapseStorageKey(row);

        setCurrentRecipeUrlSummaryCollapsed(row, false);

        if (collapseStorageKey) {
            localStorage.setItem(collapseStorageKey, "0");
        }
    }

    closeRecipeEditRowMenus();
    return false;
}

function currentRecipeViewCardFromMenuButton(button) {
    const row = recipeEditActionRowFromButton(button);
    const recipeUrl = row ? row.dataset.recipeUrl || "" : "";

    return recipeUrl
        ? document.querySelector(`[data-recipe-view-url="${cssEscape(recipeUrl)}"]`)
        : null;
}

async function generateCurrentRecipeImagesFromMenu(button, options = {}) {
    const card = currentRecipeViewCardFromMenuButton(button);

    closeRecipeEditRowMenus();

    if (!card) {
        return false;
    }

    if (typeof showView === "function") {
        showView("recipe");
    }

    card.scrollIntoView({
        behavior: "auto",
        block: "start",
        inline: "nearest",
    });

    await generateRecipeImagesInCard(card, options);
    return false;
}

function setAllCurrentRecipeUrlSummariesCollapsed(collapsed) {
    document.querySelectorAll("[data-current-recipe-row]").forEach(row => {
        const storageKey = recipeUrlSummaryCollapseStorageKey(row);

        setCurrentRecipeUrlSummaryCollapsed(row, collapsed);

        if (storageKey) {
            localStorage.setItem(storageKey, collapsed ? "1" : "0");
        }
    });

    closeRecipeEditRowMenus();
    return false;
}

function updateCurrentRecipeUrlSummaryCollapseMenuToggle(row) {
    const button = row && row.classList.contains("recipe-url-summary-row")
        ? row.querySelector(".recipe-url-summary-collapse-menu-toggle")
        : null;

    if (!button) {
        return;
    }

    button.textContent = row.classList.contains("recipe-url-summary-collapsed") ? "Expand this recipe" : "Collapse this recipe";
}

function bindCurrentRecipeUrlSummaryToggles() {
    document.querySelectorAll("[data-current-recipe-row]").forEach(row => {
        const titleToggle = row.querySelector("[data-recipe-url-summary-toggle]");
        const storageKey = recipeUrlSummaryCollapseStorageKey(row);

        if (!titleToggle || !storageKey) {
            return;
        }

        setCurrentRecipeUrlSummaryCollapsed(row, localStorage.getItem(storageKey) === "1");
        clearCurrentRecipeUrlSummaryImageHiddenState(row);
        setCurrentRecipeUrlSummaryImagesVisible(row, true);
    });
}

function recipeUrlOrder(list) {
    return [...list.querySelectorAll("[data-current-recipe-row]")]
        .map(row => row.dataset.recipeUrl || "")
        .filter(Boolean);
}

function updateRecipeUrlOrderNumbers(list) {
    const rows = [...list.querySelectorAll("[data-current-recipe-row]")];

    rows.forEach((row, index) => {
        const recipeNumber = index + 1;
        const numberLabel = row.querySelector("[data-recipe-index-label]");
        const quantityInput = row.querySelector(".recipe-quantity-input");
        const removeButton = row.querySelector(".recipe-url-summary-remove");

        row.classList.toggle("recipe-url-summary-row-last", index === rows.length - 1);

        if (numberLabel) {
            numberLabel.textContent = `Recipe ${recipeNumber}:`;
        }

        if (quantityInput) {
            quantityInput.dataset.recipeNumber = String(recipeNumber);
            quantityInput.setAttribute("aria-label", `Recipe ${recipeNumber} amount`);
        }

        if (removeButton) {
            removeButton.setAttribute("aria-label", `Remove recipe ${recipeNumber}`);
        }
    });
}

async function saveRecipeUrlOrder(list) {
    const urls = recipeUrlOrder(list);

    if (!urls.length || list.dataset.savePending === "1") {
        return;
    }

    list.dataset.savePending = "1";
    list.classList.add("is-saving");

    try {
        await postRecipeUrlOrder(urls);

        list.dataset.savedOrder = urls.join("\n");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe order updated.");
        await refreshStoreMarkup({
            cacheBust: true,
            scrollX: window.scrollX,
            scrollY: window.scrollY,
        });
    } catch (err) {
        console.warn("Unable to save recipe URL order.", err);
        alert(err.message || "Unable to save recipe order.");
    } finally {
        list.classList.remove("is-saving");
        delete list.dataset.savePending;
    }
}

function recipeViewOrder(list) {
    return [...list.querySelectorAll("[data-recipe-view-card]")]
        .map(row => row.dataset.recipeViewUrl || "")
        .filter(Boolean);
}

function updateRecipeViewOrderNumbers(list) {
    const rows = [...list.querySelectorAll("[data-recipe-view-card]")];

    rows.forEach((row, index) => {
        const recipeNumber = index + 1;
        const numberLabel = row.querySelector(".recipe-view-number");
        const quantityInput = row.querySelector(".recipe-quantity-input");
        const removeButton = row.querySelector(".recipe-view-remove");
        const dragHandle = row.querySelector("[data-recipe-drag-handle]");
        const titleMenuButton = row.querySelector(".recipe-view-title-menu-btn");

        if (numberLabel) {
            numberLabel.textContent = `Recipe ${recipeNumber}:`;
            numberLabel.setAttribute("aria-label", `Jump to Recipe ${recipeNumber} in Current Recipes`);
        }

        if (quantityInput) {
            quantityInput.dataset.recipeNumber = String(recipeNumber);
            quantityInput.setAttribute("aria-label", `Recipe ${recipeNumber} amount`);
        }

        if (removeButton) {
            removeButton.setAttribute("aria-label", `Remove recipe ${recipeNumber}`);
        }

        if (dragHandle) {
            dragHandle.setAttribute("aria-label", `Reorder recipe ${recipeNumber}`);
        }

        if (titleMenuButton) {
            titleMenuButton.setAttribute("aria-label", `Recipe ${recipeNumber} actions`);
        }
    });
}

async function saveRecipeViewOrder(list) {
    const urls = recipeViewOrder(list);

    if (!urls.length || list.dataset.savePending === "1") {
        return;
    }

    list.dataset.savePending = "1";
    list.classList.add("is-saving");

    try {
        await postRecipeUrlOrder(urls);

        list.dataset.savedOrder = urls.join("\n");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe order updated.");
        await refreshStoreMarkup({
            cacheBust: true,
            scrollX: window.scrollX,
            scrollY: window.scrollY,
        });
    } catch (err) {
        console.warn("Unable to save recipe view order.", err);
        alert(err.message || "Unable to save recipe order.");
    } finally {
        list.classList.remove("is-saving");
        delete list.dataset.savePending;
    }
}

async function postRecipeUrlOrder(urls) {
    const endpoints = ["/api/recipe_urls/reorder"];
    const hostname = window.location.hostname;

    if (
        window.location.port !== "5000"
        && ["127.0.0.1", "localhost"].includes(hostname)
    ) {
        endpoints.push(`${window.location.protocol}//${hostname}:5000/api/recipe_urls/reorder`);
    }

    let lastError = null;

    for (const endpoint of endpoints) {
        try {
            return await postRecipeUrlOrderToEndpoint(endpoint, urls);
        } catch (err) {
            lastError = err;

            if (!err.canTryNextRecipeOrderEndpoint) {
                break;
            }
        }
    }

    throw lastError || new Error("Unable to save recipe order.");
}

async function postRecipeUrlOrderToEndpoint(endpoint, urls) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ urls }),
    });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
        ? await response.json()
        : null;

    if (!response.ok || !data || !data.ok) {
        const error = new Error(
            (data && data.error)
            || (
                response.status === 404
                    ? "Recipe reorder is not available on this running server."
                    : "Unable to save recipe order."
            )
        );
        error.canTryNextRecipeOrderEndpoint = response.status === 404 || !contentType.includes("application/json");
        throw error;
    }

    return data;
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

        if (input.dataset.inlineQuantitySave !== "1") {
            input.addEventListener("change", () => handleRecipeQuantitySelectChange(input));
        }

        input.addEventListener("blur", () => {
            normalizeRecipeQuantityInput(input);
        });
    });

}

function handleRecipeQuantitySelectChange(input) {
    normalizeRecipeQuantityInput(input);

    if (input.dataset.manualQuantitySaveOnly === "1") {
        return false;
    }

    saveRecipeQuantity(input, {
        message: false,
        cacheBust: true,
    });

    return false;
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
let recipeEditDraggedRow = null;
let recipeEditPointerDrag = null;

async function openRecipeEditor(button, options = {}) {
    const url = button ? button.dataset.recipeUrl || "" : "";
    const modal = document.getElementById("recipeEditModal");
    const shouldScrollToFoodReview = options === true || Boolean(options.scrollToFoodReview);
    const targetIngredient = options && typeof options === "object"
        ? String(options.ingredient || options.scrollToIngredient || "").trim()
        : "";
    const targetSection = options && typeof options === "object"
        ? String(options.section || options.scrollToSection || "").trim()
        : "";

    if (!url || !modal) {
        return;
    }

    setRecipeEditStatus("Loading recipe...");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    document.body.classList.add("recipe-editor-open");

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
        } else if (targetSection) {
            await waitForNextPaint();
            scrollRecipeEditorToSection(targetSection);
        }
    } catch (err) {
        console.warn("Unable to open recipe editor.", err);
        setRecipeEditStatus("Unable to load recipe.", true);
    }
}

function openRecipeEditorSection(button, sectionKey) {
    closeRecipeEditRowMenus();
    openRecipeEditor(button, { scrollToSection: sectionKey });
    return false;
}

function openIngredientFoodReviewFromRecipeView(button) {
    const ingredientName = button ? button.dataset.ingredientName || "" : "";

    closeRecipeEditRowMenus();
    openRecipeEditor(button, {
        scrollToIngredient: ingredientName,
    });
    return false;
}

function closeRecipeEditor() {
    const modal = document.getElementById("recipeEditModal");

    if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
        document.body.classList.remove("recipe-editor-open");
    }

    window.location.reload();
}

function populateRecipeEditor(recipe, originalUrl) {
    const coverImage = normalizeRecipeEditorCoverImage(recipe.cover_image || {});

    recipeEditOriginalSnapshot = normalizeRecipeEditorSnapshot({
        display_name: recipe.display_name || "",
        recipe_title: recipe.recipe_title || "",
        source_url: recipe.source_url || originalUrl,
        quantity: recipe.quantity || "1",
        servings: recipe.servings || "",
        cover_image: coverImage,
        level: recipe.level || "",
        total_time: recipe.total_time || "",
        prep_time: recipe.prep_time || "",
        inactive_time: recipe.inactive_time || "",
        cook_time: recipe.cook_time || "",
        rating: recipe.rating || 0,
        reflection_notes: recipe.reflection_notes || [],
        chatgpt_feedback: recipe.chatgpt_feedback || "",
        chatgpt_feedback_created_at: recipe.chatgpt_feedback_created_at || "",
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
    setValue("recipeEditLevel", recipe.level || "");
    setValue("recipeEditTotalTime", recipe.total_time || "");
    setValue("recipeEditPrepTime", recipe.prep_time || "");
    setValue("recipeEditInactiveTime", recipe.inactive_time || "");
    setValue("recipeEditCookTime", recipe.cook_time || "");
    setRecipeRating(recipe.rating || 0);
    setRecipeEditorCookbook(recipe, originalUrl);
    populateRecipeScalingControls(recipe.scaling || {}, recipe.servings || "");
    updateRecipeEditorPdfControls(recipe);
    setRecipeEditorCoverImage(coverImage, recipe.recipe_title || recipe.display_name || "Recipe title image");

    const sourceInput = document.getElementById("recipeEditSourceUrl");
    if (sourceInput) {
        sourceInput.dataset.canonicalSourceUrl = recipe.source_url || originalUrl;
        sourceInput.dataset.displaySourceUrl = recipe.source_display_url || "";
        if (sourceInput.dataset.sourceLinkBound !== "true") {
            sourceInput.dataset.sourceLinkBound = "true";
            sourceInput.addEventListener("input", updateRecipeEditSourceUrlLink);
        }
    }
    updateRecipeEditSourceUrlLink();

    const ingredientWrap = document.getElementById("recipeEditIngredients");
    const equipmentWrap = document.getElementById("recipeEditEquipment");
    const instructionWrap = document.getElementById("recipeEditInstructions");
    const nutritionWrap = document.getElementById("recipeEditNutrition");
    const reflectionWrap = document.getElementById("recipeEditReflectionNotes");

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

    if (reflectionWrap) {
        reflectionWrap.innerHTML = "";
        (recipe.reflection_notes || []).forEach(item => addRecipeReflectionNoteRow(item));
    }

    updateRecipeEditStickyOffsets();
    applyKnownRecipeImageProgressItems();
    scheduleRecipeImageProgressPoll(250);
}

function recipeEditorCurrentUrl() {
    const input = document.getElementById("recipeEditOriginalUrl");
    return input ? String(input.value || "").trim() : "";
}

function updateRecipeEditorCookbookAssignment(recipeUrl, cookbookId, cookbookName, cookbookIsUnclassified = false) {
    const modal = document.getElementById("recipeEditModal");
    const currentUrl = recipeEditorCurrentUrl();

    if (!modal || !modal.classList.contains("open") || !currentUrl || currentUrl !== recipeUrl) {
        return;
    }

    setRecipeEditorCookbook({
        source_url: recipeUrl,
        cookbook_id: cookbookId || "",
        cookbook_name: cookbookName || "",
        cookbook_is_unclassified: Boolean(cookbookIsUnclassified),
    }, recipeUrl);
}

function setRecipeEditorCookbook(recipe, fallbackUrl = "") {
    const field = document.getElementById("recipeEditCookbookField");
    const cookbookName = document.getElementById("recipeEditCookbookName");
    const value = field ? field.querySelector(".recipe-edit-cookbook-value") : null;
    const name = recipe && recipe.cookbook_name
        ? String(recipe.cookbook_name).trim()
        : "";
    const cookbookId = recipe && recipe.cookbook_id
        ? String(recipe.cookbook_id).trim()
        : "";
    const recipeUrl = recipe && recipe.source_url
        ? String(recipe.source_url).trim()
        : String(fallbackUrl || "").trim();
    const isUnclassified = Boolean(recipe && recipe.cookbook_is_unclassified);

    if (!field || !cookbookName) {
        return;
    }

    field.dataset.recipeUrl = recipeUrl;
    field.dataset.currentCookbookId = cookbookId;
    field.dataset.currentCookbookName = name;

    cookbookName.textContent = name || "No cookbook assigned.";
    cookbookName.classList.toggle("muted", !name);
    cookbookName.title = name || "";

    if (value) {
        value.classList.toggle("muted", !name);
    }

    field.querySelectorAll("[data-recipe-edit-cookbook-action]").forEach(button => {
        button.dataset.recipeUrl = recipeUrl;
    });

    field.querySelectorAll("[data-recipe-edit-cookbook-option]").forEach(button => {
        const optionId = button.dataset.cookbookId || "";
        button.hidden = Boolean(cookbookId && optionId === cookbookId);
    });

    field.querySelectorAll("[data-recipe-edit-cookbook-delete]").forEach(button => {
        button.hidden = !name || isUnclassified;
    });
}

function updateRecipeEditorPdfControls(recipe) {
    const pdfPathInput = document.getElementById("recipeEditPdfPath");
    const pdfPathLink = document.getElementById("recipeEditPdfPathLink");
    const pdfPublicUrlField = document.getElementById("recipeEditPdfPublicUrlField");
    const pdfPublicUrlInput = document.getElementById("recipeEditPdfPublicUrl");
    const pdfPublicUrlLink = document.getElementById("recipeEditPdfPublicUrlLink");
    const pdfButton = document.getElementById("recipeEditPdfButton");
    const pdfPanelButton = document.getElementById("recipeEditPdfButtonPanel");
    const pdfMenuButton = document.getElementById("recipeEditPdfMenuButton");
    const localPdfDownloadButton = document.getElementById("recipeEditLocalPdfDownloadButton");
    const deletePdfButton = document.getElementById("recipeEditDeletePdfButton");
    const copyPdfLinkButton = document.getElementById("recipeEditCopyPdfLinkButton");
    const uploadPdfButton = document.getElementById("recipeEditUploadPdfButton");
    const sourceUrl = recipe && recipe.source_url ? recipe.source_url : "";
    const pdfPath = recipe && recipe.pdf_path ? recipe.pdf_path : "";
    const pdfPublicUrl = recipe && recipe.pdf_public_url ? recipe.pdf_public_url : "";
    const hasLocalPdf = Boolean(recipe && (recipe.pdf_local_available || (recipe.pdf_available && !pdfPublicUrl)) && sourceUrl);
    const hasPdf = Boolean(recipe && sourceUrl && (pdfPublicUrl || recipe.pdf_available || hasLocalPdf));
    const archiveUrl = hasPdf ? (pdfPublicUrl || recipeArchivePdfUrl(sourceUrl)) : "#";

    if (pdfPathInput) {
        pdfPathInput.value = pdfPath;
    }

    if (pdfPathLink) {
        pdfPathLink.href = archiveUrl;
        pdfPathLink.hidden = !hasPdf;
        pdfPathLink.setAttribute("aria-disabled", hasPdf ? "false" : "true");
        pdfPathLink.title = hasPdf ? "Open PDF" : "PDF not available";
        pdfPathLink.setAttribute("aria-label", hasPdf ? "Open PDF" : "PDF not available");
    }

    if (pdfPublicUrlInput) {
        pdfPublicUrlInput.value = pdfPublicUrl;
    }

    if (pdfPublicUrlField) {
        pdfPublicUrlField.hidden = !pdfPublicUrl;
        if (pdfPublicUrlLink) {
            const hasPublicPdfUrl = Boolean(pdfPublicUrl);
            const canOpenPublicPdfUrl = hasPublicPdfUrl && isShareablePublicPdfUrl(pdfPublicUrl);
            pdfPublicUrlLink.href = canOpenPublicPdfUrl ? pdfPublicUrl : "#";
            pdfPublicUrlLink.hidden = !canOpenPublicPdfUrl;
            pdfPublicUrlLink.setAttribute("aria-disabled", canOpenPublicPdfUrl ? "false" : "true");
            pdfPublicUrlLink.title = canOpenPublicPdfUrl ? "Open PDF public URL" : "No public PDF URL";
            pdfPublicUrlLink.setAttribute("aria-label", canOpenPublicPdfUrl ? "Open PDF public URL" : "No public PDF URL");
        }
    }

    [pdfButton, pdfPanelButton, pdfMenuButton].forEach((button) => {
        if (button) {
            button.hidden = !hasPdf;
            button.href = archiveUrl;
            button.dataset.recipePdfUrl = archiveUrl;
        }
    });

    if (deletePdfButton) {
        deletePdfButton.hidden = !hasLocalPdf && !pdfPublicUrl;
    }

    if (localPdfDownloadButton) {
        localPdfDownloadButton.hidden = !hasLocalPdf;
        localPdfDownloadButton.href = hasLocalPdf ? recipeArchivePdfDownloadUrl(sourceUrl) : "#";
    }

    if (copyPdfLinkButton) {
        copyPdfLinkButton.hidden = !pdfPublicUrl;
        copyPdfLinkButton.dataset.pdfPublicUrl = pdfPublicUrl;
    }

    if (uploadPdfButton) {
        uploadPdfButton.hidden = !sourceUrl || !hasLocalPdf || Boolean(pdfPublicUrl);
    }
}

function recipeArchivePdfUrl(sourceUrl) {
    return `/recipe_archive_pdf?url=${encodeURIComponent(sourceUrl || "")}`;
}

function recipeArchivePdfDownloadUrl(sourceUrl) {
    return `/recipe_archive_pdf?url=${encodeURIComponent(sourceUrl || "")}&download=1`;
}

function openRecipeEditorPdf(link, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const url = link && (link.dataset.recipePdfUrl || link.getAttribute("href"));

    if (!url || url === "#") {
        setRecipeEditStatus("Recipe PDF is not ready yet.", true);
        return false;
    }

    try {
        const targetWindow = isScreenPreviewFrame() && window.top ? window.top : window;
        const opened = targetWindow.open(url, "_blank");

        if (opened) {
            try {
                opened.opener = null;
            } catch (err) {
                // Some PDF viewers do not expose opener; the tab still opened.
            }
            return false;
        }
    } catch (err) {
        // If a mobile browser blocks the popup, the fallback below still opens the PDF.
    }

    window.location.assign(url);
    return false;
}

function updateRecipeEditStickyOffsets() {
    document.querySelectorAll(".recipe-edit-equipment-section, .recipe-edit-instructions-section, .recipe-edit-nutrition-section, .recipe-edit-reflection-section")
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

function normalizeRecipeRatingValue(value) {
    const rating = parseInt(value, 10);

    if (!Number.isFinite(rating)) {
        return 0;
    }

    return Math.max(0, Math.min(5, rating));
}

function currentRecipeRating() {
    const input = document.getElementById("recipeEditRating");
    return normalizeRecipeRatingValue(input ? input.value : 0);
}

function setRecipeRating(value) {
    const rating = normalizeRecipeRatingValue(value);
    const input = document.getElementById("recipeEditRating");

    if (input) {
        input.value = String(rating);
    }

    updateRecipeRatingStars(rating);
    return false;
}

function updateRecipeRatingStars(rating) {
    const normalizedRating = normalizeRecipeRatingValue(rating);

    document.querySelectorAll("#recipeEditRatingStars .recipe-edit-rating-star").forEach(button => {
        const value = normalizeRecipeRatingValue(button.dataset.ratingValue);
        const active = value > 0 && value <= normalizedRating;

        button.classList.toggle("active", active);
        button.setAttribute("aria-checked", value === normalizedRating ? "true" : "false");
        button.textContent = active ? "\u2605" : "\u2606";
    });
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

function normalizeRecipeEditorCoverImage(value = {}) {
    if (typeof value === "string") {
        const url = value.trim();
        return url ? { url, src: url } : {};
    }

    if (!value || typeof value !== "object") {
        return {};
    }

    const path = String(value.path || "").trim();
    const url = String(value.url || "").trim();
    const src = String(value.src || "").trim();
    const alt = String(value.alt || "").trim();
    const mimeType = String(value.mime_type || value.mimeType || "").trim();
    const source = String(value.source || "").trim();
    const normalized = {};

    if (path) {
        normalized.path = path;
    }

    if (url) {
        normalized.url = url;
    } else if (!path && src) {
        normalized.url = src;
    }

    if (src) {
        normalized.src = src;
    }

    if (alt) {
        normalized.alt = alt;
    }

    if (mimeType) {
        normalized.mime_type = mimeType;
    }

    if (source) {
        normalized.source = source;
    }

    return normalized.path || normalized.url || normalized.src ? normalized : {};
}

function setRecipeEditorCoverImage(coverImage = {}, fallbackAlt = "") {
    const normalized = normalizeRecipeEditorCoverImage(coverImage);
    const field = document.getElementById("recipeEditCoverField");
    const image = document.getElementById("recipeEditCoverImage");
    const empty = document.getElementById("recipeEditCoverEmpty");
    const status = document.getElementById("recipeEditCoverStatus");
    const uploadLabel = document.getElementById("recipeEditCoverUploadLabel");
    const alt = normalized.alt || fallbackAlt || "Recipe title image";
    const src = normalized.src || normalized.url || "";
    const hasImage = Boolean(src || normalized.path || normalized.url);

    if (field) {
        field.classList.toggle("has-cover", hasImage);
    }

    if (image) {
        const nextSrc = src || (
            normalized.path && recipeEditorCurrentUrl()
                ? `/recipe_cover_image?url=${encodeURIComponent(recipeEditorCurrentUrl())}`
                : ""
        );
        image.alt = alt;
        if (nextSrc) {
            image.src = nextSrc;
            image.hidden = false;
        } else {
            image.removeAttribute("src");
            image.hidden = true;
        }
    }

    if (empty) {
        empty.hidden = hasImage;
    }

    if (status) {
        status.textContent = hasImage
            ? "This image is shown on recipe cards."
            : "Upload or replace the image shown on recipe cards.";
    }

    if (uploadLabel) {
        uploadLabel.textContent = hasImage ? "Replace title image" : "Upload title image";
    }

    setValue("recipeEditCoverPath", normalized.path || "");
    setValue("recipeEditCoverUrl", normalized.url || "");
    setValue("recipeEditCoverAlt", alt);
    setValue("recipeEditCoverMimeType", normalized.mime_type || "");
    setValue("recipeEditCoverSource", normalized.source || "");
}

function collectRecipeEditorCoverImage() {
    const pathInput = document.getElementById("recipeEditCoverPath");
    const urlInput = document.getElementById("recipeEditCoverUrl");
    const altInput = document.getElementById("recipeEditCoverAlt");
    const mimeTypeInput = document.getElementById("recipeEditCoverMimeType");
    const sourceInput = document.getElementById("recipeEditCoverSource");
    const path = String(pathInput ? pathInput.value : "").trim();
    const url = String(urlInput ? urlInput.value : "").trim();
    const alt = String(altInput ? altInput.value : "").trim();
    const mimeType = String(mimeTypeInput ? mimeTypeInput.value : "").trim();
    const source = String(sourceInput ? sourceInput.value : "").trim();
    const coverImage = {};

    if (path) {
        coverImage.path = path;
    }

    if (url) {
        coverImage.url = url;
    }

    if (alt) {
        coverImage.alt = alt;
    }

    if (mimeType) {
        coverImage.mime_type = mimeType;
    }

    if (source) {
        coverImage.source = source;
    }

    return coverImage.path || coverImage.url ? coverImage : {};
}

function normalizeRecipeCoverImageSnapshot(value = {}) {
    const coverImage = normalizeRecipeEditorCoverImage(value);

    return {
        path: String(coverImage.path || "").trim(),
        url: String(coverImage.url || "").trim(),
        alt: String(coverImage.alt || "").trim(),
        mime_type: String(coverImage.mime_type || "").trim(),
        source: String(coverImage.source || "").trim(),
    };
}

function cacheBustRecipeCoverSrc(src) {
    if (!src || !src.startsWith("/recipe_cover_image")) {
        return src || "";
    }

    const separator = src.includes("?") ? "&" : "?";
    return `${src}${separator}_cover=${Date.now()}`;
}

function openRecipeCoverUpload() {
    const input = document.getElementById("recipeEditCoverUpload");

    if (input) {
        input.click();
    }

    return false;
}

async function uploadRecipeCoverImage(input) {
    const file = input && input.files ? input.files[0] : null;

    if (!file) {
        return false;
    }

    const originalUrl = recipeEditorCurrentUrl();
    const sourceUrl = recipeEditorSourceUrlForSave() || originalUrl;
    const titleInput = document.getElementById("recipeEditTitleInput");
    const displayInput = document.getElementById("recipeEditDisplayName");
    const fallbackAlt = (titleInput ? titleInput.value.trim() : "")
        || (displayInput ? displayInput.value.trim() : "")
        || "Recipe title image";

    if (!originalUrl) {
        setRecipeEditStatus("Unable to upload title image: missing recipe URL.", true);
        input.value = "";
        return false;
    }

    const formData = new FormData();
    formData.append("url", originalUrl);
    formData.append("source_url", sourceUrl);
    formData.append("alt", fallbackAlt);
    formData.append("cover_image", file);

    try {
        setRecipeEditStatus("Uploading title image...");
        const response = await fetch("/api/recipe_cover_image", {
            method: "POST",
            body: formData,
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to upload title image.");
        }

        const coverImage = normalizeRecipeEditorCoverImage(data.cover_image || {});
        if (coverImage.src) {
            coverImage.src = cacheBustRecipeCoverSrc(coverImage.src);
        }

        setRecipeEditorCoverImage(coverImage, fallbackAlt);
        setRecipeEditStatus("Title image updated. Save Recipe to keep any other edits.");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe title image updated.");
    } catch (err) {
        console.warn("Unable to upload recipe title image.", err);
        setRecipeEditStatus(err.message || "Unable to upload title image.", true);
    } finally {
        if (input) {
            input.value = "";
        }
    }

    return false;
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
    const match = rows.reduce((best, candidate) => {
        const ingredientInput = candidate.querySelector('[data-field="ingredient"]');
        const originalTextInput = candidate.querySelector('[data-field="original_text"]');
        const ingredientKey = normalizeIngredientJumpKey(ingredientInput ? ingredientInput.value : "");
        const originalTextKey = normalizeIngredientJumpKey(originalTextInput ? originalTextInput.value : "");
        const score = ingredientJumpMatchScore(targetKey, ingredientKey, originalTextKey);

        return score > best.score ? { row: candidate, score } : best;
    }, { row: null, score: 0 });
    const row = match.row;

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

function ingredientJumpMatchScore(targetKey, ingredientKey, originalTextKey) {
    if (!targetKey) {
        return 0;
    }

    if (ingredientKey && ingredientKey === targetKey) {
        return 1000;
    }
    if (originalTextKey && originalTextKey === targetKey) {
        return 950;
    }
    if (ingredientKey && ingredientKey.includes(targetKey)) {
        return 700 + targetKey.length;
    }
    if (originalTextKey && originalTextKey.includes(targetKey)) {
        return 650 + targetKey.length;
    }
    if (ingredientKey && ingredientKey.length >= 12 && targetKey.includes(ingredientKey)) {
        return 500 + ingredientKey.length;
    }
    if (originalTextKey && originalTextKey.length >= 12 && targetKey.includes(originalTextKey)) {
        return 450 + originalTextKey.length;
    }

    return 0;
}

function scrollRecipeEditorToSection(sectionKey) {
    const normalized = String(sectionKey || "").trim().toLowerCase().replace(/[^a-z]+/g, "");
    const selector = {
        ingredients: ".recipe-edit-ingredients-section",
        equipment: ".recipe-edit-equipment-section",
        instructions: ".recipe-edit-instructions-section",
        nutrition: ".recipe-edit-nutrition-section",
        notes: ".recipe-edit-reflection-section",
        reflection: ".recipe-edit-reflection-section",
    }[normalized];
    const section = selector ? document.querySelector(selector) : null;

    if (!section) {
        setRecipeEditStatus("Recipe section not found.", true);
        return false;
    }

    document.querySelectorAll(".recipe-edit-review-target").forEach(element => {
        element.classList.remove("recipe-edit-review-target");
    });
    section.classList.add("recipe-edit-review-target");
    section.scrollIntoView({
        behavior: "smooth",
        block: "start",
        inline: "nearest",
    });

    const focusTarget = section.querySelector(
        ".recipe-edit-ingredient-row input, " +
        ".recipe-edit-equipment-row input, " +
        ".recipe-edit-instruction-row textarea, " +
        ".recipe-edit-nutrition-row input, " +
        ".recipe-edit-reflection-note-row textarea, " +
        "input, textarea, select"
    );

    if (focusTarget) {
        setTimeout(() => {
            try {
                focusTarget.focus({ preventScroll: true });
                if (typeof focusTarget.select === "function") {
                    focusTarget.select();
                }
            } catch (err) {
                focusTarget.focus();
            }
        }, 250);
    }

    setTimeout(() => section.classList.remove("recipe-edit-review-target"), 3000);
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

    expandRecipeIngredientRow(row);

    if (marker.dataset.reviewKind === "ingredient_choice" || marker.dataset.reviewKind === "ingredient_text_choice") {
        await waitForNextPaint();
        focusIngredientChoiceReview(row);
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

function recipeEditSvgIcon(name) {
    const icons = {
        drag: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><circle cx="9" cy="5" r="1.5"></circle><circle cx="15" cy="5" r="1.5"></circle><circle cx="9" cy="12" r="1.5"></circle><circle cx="15" cy="12" r="1.5"></circle><circle cx="9" cy="19" r="1.5"></circle><circle cx="15" cy="19" r="1.5"></circle></svg>',
        leaf: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M5 19c8 0 14-6 14-14C11 5 5 11 5 19Z"></path><path d="M5 19c3-4 7-7 12-10"></path></svg>',
        jar: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M8 4h8l-1 3H9L8 4Z"></path><path d="M7 9h10l1 10a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L7 9Z"></path><path d="M9 13h6"></path></svg>',
        basket: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M7 9 10 4"></path><path d="m17 9-3-5"></path><path d="M4 9h16l-2 10H6L4 9Z"></path><path d="M9 13v3"></path><path d="M15 13v3"></path></svg>',
        search: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"></circle><path d="m16 16 4 4"></path></svg>',
        nutrition: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M12 21c4-4 8-8 8-12a8 8 0 0 0-16 0c0 4 4 8 8 12Z"></path><path d="M12 8v5"></path><path d="M9.5 10.5h5"></path></svg>',
        trash: '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true"><path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M6 7l1 14h10l1-14"></path><path d="M9 7V4h6v3"></path></svg>',
    };
    const icon = icons[name] || icons.basket;

    return `<span class="recipe-edit-inline-icon recipe-edit-inline-icon-${escapeAttribute(name)}" aria-hidden="true">${icon}</span>`;
}

function recipeIngredientIconName(item = {}) {
    const section = String(item.store_section || item.section || "").toUpperCase();

    if (section.includes("PRODUCE")) {
        return "leaf";
    }

    if (section.includes("SPICE") || section.includes("SEASON")) {
        return "jar";
    }

    if (section.includes("BAKING")) {
        return "search";
    }

    return "basket";
}

function recipeIngredientBadgesHtml(item = {}) {
    const badges = [];
    const ingredient = String(item.ingredient || "").trim();
    const purchasable = String(item.purchasable_item || item.buy_as || "").trim();
    const section = String(item.store_section || item.section || "").toUpperCase();
    const pantryText = `${ingredient} ${purchasable} ${section}`.toUpperCase();

    if (item.optional) {
        badges.push(["Optional", "optional"]);
    }

    if (pantryText.includes("BEAN") || pantryText.includes("LEGUME") || pantryText.includes("SPICE")) {
        badges.push(["Pantry Staple", "pantry"]);
    } else if (ingredient && purchasable && !/\s+\bor\b\s+/i.test(ingredient)) {
        badges.push(["Best Match", "best"]);
    }

    return badges.map(([label, kind]) => (
        `<span class="recipe-edit-ingredient-badge ${escapeAttribute(kind)}">${escapeHtml(label)}</span>`
    )).join("");
}

function resizeRecipeIngredientNameField(field) {
    if (!field || field.tagName !== "TEXTAREA") {
        return;
    }

    field.style.height = "auto";
    field.style.height = `${field.scrollHeight + 4}px`;
}

function bindRecipeIngredientNameField(row) {
    const field = row ? row.querySelector('textarea[data-field="ingredient"]') : null;

    if (!field) {
        return;
    }

    field.addEventListener("input", () => resizeRecipeIngredientNameField(field));
    field.addEventListener("focus", () => resizeRecipeIngredientNameField(field));
    window.requestAnimationFrame(() => resizeRecipeIngredientNameField(field));
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
        <span class="recipe-edit-row-handle" aria-hidden="true">${recipeEditSvgIcon("drag")}</span>
        <span class="recipe-edit-row-number" data-ingredient-row-number></span>
        <div class="recipe-edit-ingredient-name-label">
            <span class="sr-only">Ingredient</span>
            <span class="recipe-edit-ingredient-title-line">
                <textarea data-field="ingredient" rows="1">${escapeHtml(item.ingredient || "")}</textarea>
                <span class="recipe-edit-ingredient-markers">
                    <span class="recipe-edit-ingredient-badges" data-ingredient-badges>${recipeIngredientBadgesHtml(item)}</span>
                    <span class="recipe-edit-food-warning food-rule-marker"
                          role="button"
                          tabindex="0"
                          onclick="openFoodReviewAlternatives(this)"
                          onkeydown="openFoodReviewAlternativesFromKey(event, this)"
                          hidden>Food Review</span>
                </span>
            </span>
            <label class="recipe-edit-preparation-inline">
                <span class="sr-only">Preparation</span>
                <input type="text" data-field="preparation" value="${escapeAttribute(item.preparation || "")}" placeholder="-">
            </label>
            <label class="recipe-edit-original-text-label">
                <span>Original Recipe Text</span>
                <input type="text" data-field="original_text" value="${escapeAttribute(item.original_text || "")}">
            </label>
            <span class="recipe-edit-choice-review" data-ingredient-choice-review hidden>
                <span class="recipe-edit-choice-prompt">Pick one option</span>
                <span class="recipe-edit-choice-options" data-ingredient-choice-options></span>
            </span>
        </div>
        <label class="recipe-edit-qty-label">
            <span>Qty</span>
            <input type="text" data-field="quantity" value="${escapeAttribute(item.quantity || "")}">
        </label>
        <label class="recipe-edit-unit-label">
            <span>Unit</span>
            <input type="text" data-field="unit" value="${escapeAttribute(item.unit || "")}">
        </label>
        <label class="recipe-edit-buy-as-label">
            <span>Buy As</span>
            <input type="text"
                   data-field="purchasable_item"
                   list="itemQtyBuyAsOptions"
                   placeholder="e.g. eggs"
                   value="${escapeAttribute(item.purchasable_item || item.buy_as || "")}"
                   oninput="syncRecipeIngredientPurchaseGroup(this)">
        </label>
        <label class="recipe-edit-store-section-label">
            <span>Store Section</span>
            <select data-field="store_section">${recipeStoreSectionOptions(item.store_section || "")}</select>
        </label>
        <label class="recipe-edit-check-label recipe-edit-optional-label">
            <span>Optional</span>
            <input type="checkbox" data-field="optional" ${item.optional ? "checked" : ""}>
        </label>
        <div class="recipe-edit-row-menu-wrap">
            <button type="button"
                    class="recipe-edit-row-menu-btn"
                    aria-label="Ingredient actions"
                    title="Ingredient actions"
                    aria-haspopup="true"
                    aria-expanded="false"
                    onclick="return toggleRecipeEditRowMenu(this, event)">
                <span aria-hidden="true"></span>
            </button>
            <div class="recipe-edit-row-menu" hidden>
                <button type="button" onclick="duplicateRecipeIngredientRow(this)">Duplicate ingredient</button>
                <button type="button" class="recipe-edit-row-collapse-toggle" onclick="toggleRecipeIngredientRowCollapsed(this)">Collapse ingredient</button>
                <button type="button" onclick="moveRecipeEditRow(this, -1)">Move ingredient up</button>
                <button type="button" onclick="moveRecipeEditRow(this, 1)">Move ingredient down</button>
                <button type="button" class="delete" onclick="removeRecipeEditRow(this)">Delete ingredient</button>
            </div>
        </div>
        <input type="hidden" data-field="section" value="${escapeAttribute(item.section || "")}">
        <input type="hidden" data-field="base_quantity" value="${escapeAttribute(baseQuantity || "")}">
        <input type="hidden" data-field="base_unit" value="${escapeAttribute(baseUnit || "")}">
        <input type="hidden" data-field="recipe_qty" value="${escapeAttribute(item.recipe_qty || item.quantity || "")}">
        <input type="hidden" data-field="purchase_group" value="${escapeAttribute(item.purchase_group || "")}">
    `;
    const ingredientTextReview = normalizeIngredientTextReview(item.food_review || null);
    if (ingredientTextReview) {
        row.dataset.ingredientTextReview = JSON.stringify(ingredientTextReview);
        row.dataset.ingredientTextReviewKey = ingredientTextReview.text_key || ingredientTextReviewKeyFromItem(item);
    }
    wrap.appendChild(row);
    bindRecipeIngredientNameField(row);
    bindRecipeIngredientBaseTracking(row);
    bindRecipeIngredientFoodRuleWarning(row);
    bindRecipeIngredientSummaryUpdates(row);
    bindRecipeEditDragAndDrop(row);
    updateRecipeIngredientFoodRuleWarning(row);
    updateRecipeIngredientRowIndexes();
    return row;
}

function bindRecipeIngredientSummaryUpdates(row) {
    row.querySelectorAll('[data-field="ingredient"], [data-field="purchasable_item"], [data-field="store_section"], [data-field="optional"]').forEach(input => {
        const eventName = input.type === "checkbox" || input.tagName === "SELECT" ? "change" : "input";
        input.addEventListener(eventName, () => updateRecipeIngredientSummary(row));
    });
}

function updateRecipeIngredientSummary(row) {
    const badges = row ? row.querySelector("[data-ingredient-badges]") : null;

    if (badges) {
        badges.innerHTML = recipeIngredientBadgesHtml(fieldValuesFromRow(row));
    }
}

function updateRecipeIngredientRowIndexes() {
    const rows = [...document.querySelectorAll("#recipeEditIngredients .recipe-edit-ingredient-row")];
    const count = document.getElementById("recipeEditIngredientCount");

    rows.forEach((row, index) => {
        const number = row.querySelector("[data-ingredient-row-number]");

        if (number) {
            number.textContent = String(index + 1);
        }
    });

    if (count) {
        count.textContent = `(${rows.length})`;
    }
}

function toggleRecipeEditRowMenu(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (button && button.getAttribute("aria-expanded") === "true") {
        closeRecipeEditRowMenus();
        return false;
    }

    const wrap = button ? button.closest(".recipe-edit-row-menu-wrap") : null;
    const row = recipeEditActionRowFromButton(button);
    const menu = wrap ? wrap.querySelector(".recipe-edit-row-menu") : (row ? row.querySelector(".recipe-edit-row-menu") : null);
    const shouldOpen = menu ? menu.hidden : false;

    closeRecipeEditRowMenus();

    if (menu && shouldOpen) {
        updateRecipeIngredientRowCollapseToggle(row);
        updateRecipeEditRowImageMenu(row);
        updateCurrentRecipeUrlSummaryCollapseMenuToggle(row);
        updateRecipeViewCardCollapseMenuToggle(row);
        updateRecipeDetailMenuToggleForButton(button);
        if (row) {
            row.classList.add("recipe-edit-menu-open");
        }
        if (wrap) {
            wrap.classList.add("recipe-edit-menu-wrap-open");
        }
        menu.hidden = false;
        positionRecipeEditPopupMenu(menu, button);
        button.setAttribute("aria-expanded", "true");
    }

    return false;
}

function toggleRecipeEditSectionMenu(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const wrap = button ? button.closest(".recipe-edit-section-menu-wrap") : null;
    const menu = wrap ? wrap.querySelector(".recipe-edit-section-menu") : null;
    const shouldOpen = menu ? menu.hidden : false;

    closeRecipeEditRowMenus();

    if (menu && shouldOpen) {
        menu.hidden = false;
        positionRecipeEditPopupMenu(menu, button);
        button.setAttribute("aria-expanded", "true");
    }

    return false;
}

function positionRecipeEditPopupMenu(menu, button) {
    if (!menu || !button) {
        return;
    }

    const margin = 8;
    const gap = 6;
    const dialog = button.closest(".recipe-edit-dialog");
    const dialogRect = dialog
        ? dialog.getBoundingClientRect()
        : { top: 0, bottom: window.innerHeight };

    menu.classList.add("recipe-edit-floating-menu");
    portalRecipeEditPopupMenu(menu, button);
    menu.style.left = "0px";
    menu.style.top = "0px";
    menu.style.right = "auto";
    menu.style.minWidth = "";

    const buttonRect = button.getBoundingClientRect();
    if (menu.classList.contains("recipe-edit-cookbook-menu")) {
        menu.style.minWidth = `${Math.ceil(buttonRect.width)}px`;
    }
    const menuRect = menu.getBoundingClientRect();
    const menuWidth = menuRect.width;
    const menuHeight = menuRect.height;
    const topLimit = Math.max(margin, dialogRect.top + margin);
    const bottomLimit = Math.min(window.innerHeight - margin, dialogRect.bottom - margin);
    const rightLimit = window.innerWidth - margin;

    let left = buttonRect.right - menuWidth;
    left = Math.max(margin, Math.min(left, rightLimit - menuWidth));

    let top = buttonRect.bottom + gap;
    const hasRoomAbove = buttonRect.top - gap - menuHeight >= topLimit;
    const spillsBelow = top + menuHeight > bottomLimit;

    if (spillsBelow && hasRoomAbove) {
        top = buttonRect.top - menuHeight - gap;
    } else if (spillsBelow) {
        top = bottomLimit - menuHeight;
    }

    top = Math.max(topLimit, Math.min(top, window.innerHeight - menuHeight - margin));

    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
}

function portalRecipeEditPopupMenu(menu, button) {
    if (!menu || !menu.classList.contains("recipe-edit-row-menu") || !menu.parentNode || !document.body) {
        return;
    }

    menu.recipeEditAnchorButton = button || menu.recipeEditAnchorButton || null;

    if (menu.dataset.recipeEditPortaled === "1") {
        return;
    }

    const placeholder = document.createComment("recipe-edit-menu-placeholder");
    menu.recipeEditMenuPlaceholder = placeholder;
    menu.parentNode.insertBefore(placeholder, menu);
    document.body.appendChild(menu);
    menu.dataset.recipeEditPortaled = "1";
}

function restoreRecipeEditPopupMenu(menu) {
    if (!menu || menu.dataset.recipeEditPortaled !== "1") {
        return;
    }

    const placeholder = menu.recipeEditMenuPlaceholder;

    if (placeholder && placeholder.parentNode) {
        placeholder.parentNode.insertBefore(menu, placeholder);
        placeholder.remove();
    }

    delete menu.recipeEditAnchorButton;
    delete menu.recipeEditMenuPlaceholder;
    delete menu.dataset.recipeEditPortaled;
}

function recipeEditActionRowFromButton(button) {
    const directRow = button
        ? button.closest(recipeEditMovableRowSelector())
        : null;

    if (directRow) {
        return directRow;
    }

    const menu = button ? button.closest(".recipe-edit-row-menu") : null;
    const anchorButton = menu ? menu.recipeEditAnchorButton : null;

    return anchorButton
        ? anchorButton.closest(recipeEditMovableRowSelector())
        : null;
}

function recipeEditMenuAnchorButtonFromButton(button) {
    const menu = button ? button.closest(".recipe-edit-row-menu") : null;
    return menu ? menu.recipeEditAnchorButton : null;
}

function recipeDetailHeaderFromMenuButton(button) {
    const directHeader = button ? button.closest(".recipe-detail-header") : null;

    if (directHeader) {
        return directHeader;
    }

    const anchorButton = recipeEditMenuAnchorButtonFromButton(button);
    return anchorButton ? anchorButton.closest(".recipe-detail-header") : null;
}

function toggleRecipeIngredientRowMenu(button, event = null) {
    return toggleRecipeEditRowMenu(button, event);
}

function recipeEditMovableRowSelector() {
    return ".recipe-edit-ingredient-row, .recipe-edit-equipment-row, .recipe-edit-instruction-row, .recipe-edit-nutrition-row, .recipe-edit-reflection-note-row, .recipe-edit-cookbook-field, .recipe-url-summary-row, .store-manager-row, .recipe-view-card, .cookbook-card, .cookbook-recipe-card, .rules-group, .rules-editor-food-row";
}

function recipeEditMoveSelectorForRow(row) {
    if (!row) {
        return "";
    }

    if (row.classList.contains("recipe-edit-ingredient-row")) {
        return ".recipe-edit-ingredient-row";
    }

    if (row.classList.contains("recipe-edit-equipment-row")) {
        return ".recipe-edit-equipment-row";
    }

    if (row.classList.contains("recipe-edit-instruction-row")) {
        return ".recipe-edit-instruction-row";
    }

    if (row.classList.contains("recipe-edit-nutrition-row")) {
        return ".recipe-edit-nutrition-row";
    }

    if (row.classList.contains("recipe-edit-reflection-note-row")) {
        return ".recipe-edit-reflection-note-row";
    }

    if (row.classList.contains("recipe-url-summary-row")) {
        return ".recipe-url-summary-row";
    }

    if (row.classList.contains("recipe-view-card")) {
        return ".recipe-view-card";
    }

    return ".recipe-edit-text-row";
}

function bindRecipeEditDragAndDrop(row) {
    const handle = row ? row.querySelector(".recipe-edit-row-handle") : null;

    if (!row || !handle || row.dataset.recipeEditDragBound === "true") {
        return;
    }

    row.dataset.recipeEditDragBound = "true";
    row.classList.add("recipe-edit-row-draggable");
    handle.draggable = true;
    handle.removeAttribute("aria-hidden");
    handle.setAttribute("role", "button");
    handle.setAttribute("tabindex", "0");
    handle.setAttribute("aria-label", "Drag to reorder");
    handle.setAttribute("title", "Drag to reorder");

    handle.addEventListener("dragstart", event => {
        recipeEditDraggedRow = row;
        closeRecipeEditRowMenus();
        row.classList.add("recipe-edit-row-dragging");

        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", recipeEditMoveSelectorForRow(row));

            try {
                event.dataTransfer.setDragImage(row, 24, 24);
            } catch (err) {
                // Some browsers only allow visible elements as drag images.
            }
        }
    });

    handle.addEventListener("dragend", () => {
        clearRecipeEditDragState();
    });

    handle.addEventListener("pointerdown", event => {
        startRecipeEditPointerDrag(row, handle, event);
    });

    handle.addEventListener("pointermove", event => {
        moveRecipeEditPointerDrag(event);
    });

    handle.addEventListener("pointerup", event => {
        endRecipeEditPointerDrag(event);
    });

    handle.addEventListener("pointercancel", event => {
        endRecipeEditPointerDrag(event, true);
    });

    row.addEventListener("dragover", event => {
        if (!recipeEditCanDropOnRow(recipeEditDraggedRow, row)) {
            return;
        }

        event.preventDefault();

        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
        }

        updateRecipeEditDropIndicator(row, recipeEditDropShouldInsertAfter(event, row));
    });

    row.addEventListener("dragleave", event => {
        if (!row.contains(event.relatedTarget)) {
            row.classList.remove("recipe-edit-row-drop-before", "recipe-edit-row-drop-after");
        }
    });

    row.addEventListener("drop", event => {
        if (!recipeEditCanDropOnRow(recipeEditDraggedRow, row)) {
            return;
        }

        event.preventDefault();
        dropRecipeEditRow(recipeEditDraggedRow, row, recipeEditDropShouldInsertAfter(event, row));
    });
}

function startRecipeEditPointerDrag(row, handle, event) {
    if (!event || event.pointerType === "mouse" || (event.button !== undefined && event.button !== 0)) {
        return;
    }

    closeRecipeEditRowMenus();
    recipeEditPointerDrag = {
        active: false,
        handle,
        insertAfter: false,
        pointerId: event.pointerId,
        row,
        startX: event.clientX,
        startY: event.clientY,
        targetRow: null,
    };

    row.classList.add("recipe-edit-row-dragging");

    try {
        handle.setPointerCapture(event.pointerId);
    } catch (err) {
        // Pointer capture is not supported in every embedded browser.
    }

    event.preventDefault();
}

function moveRecipeEditPointerDrag(event) {
    const drag = recipeEditPointerDrag;

    if (!drag || !event || drag.pointerId !== event.pointerId) {
        return;
    }

    const movement = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);

    if (!drag.active && movement < 6) {
        return;
    }

    drag.active = true;
    event.preventDefault();
    autoScrollRecipeEditDialogForDrag(event.clientY);

    const targetRow = recipeEditDropTargetFromPoint(event.clientX, event.clientY, drag.row);

    if (!recipeEditCanDropOnRow(drag.row, targetRow)) {
        drag.targetRow = null;
        clearRecipeEditDropIndicators();
        return;
    }

    drag.targetRow = targetRow;
    drag.insertAfter = recipeEditDropShouldInsertAfter(event, targetRow);
    updateRecipeEditDropIndicator(targetRow, drag.insertAfter);
}

function endRecipeEditPointerDrag(event, cancelled = false) {
    const drag = recipeEditPointerDrag;

    if (!drag || (event && drag.pointerId !== event.pointerId)) {
        return;
    }

    try {
        drag.handle.releasePointerCapture(drag.pointerId);
    } catch (err) {
        // Pointer capture may already be released.
    }

    if (!cancelled && drag.active && recipeEditCanDropOnRow(drag.row, drag.targetRow)) {
        dropRecipeEditRow(drag.row, drag.targetRow, drag.insertAfter);
    } else {
        clearRecipeEditDragState();
    }
}

function recipeEditDropTargetFromPoint(clientX, clientY, draggedRow) {
    const target = document.elementFromPoint(clientX, clientY);
    const selector = recipeEditMoveSelectorForRow(draggedRow);

    return target ? target.closest(selector) : null;
}

function autoScrollRecipeEditDialogForDrag(clientY) {
    const dialog = document.querySelector(".recipe-edit-dialog");

    if (!dialog) {
        return;
    }

    const rect = dialog.getBoundingClientRect();
    const threshold = 72;

    if (clientY < rect.top + threshold) {
        dialog.scrollTop -= 18;
    } else if (clientY > rect.bottom - threshold) {
        dialog.scrollTop += 18;
    }
}

function recipeEditCanDropOnRow(draggedRow, targetRow) {
    return Boolean(
        draggedRow
        && targetRow
        && draggedRow !== targetRow
        && draggedRow.parentElement === targetRow.parentElement
        && recipeEditMoveSelectorForRow(draggedRow) === recipeEditMoveSelectorForRow(targetRow)
    );
}

function recipeEditDropShouldInsertAfter(event, row) {
    const rect = row.getBoundingClientRect();
    const pointerY = event && typeof event.clientY === "number"
        ? event.clientY
        : rect.top + (rect.height / 2);
    const splitOffset = Math.min(rect.height / 2, 96);

    return pointerY > rect.top + splitOffset;
}

function updateRecipeEditDropIndicator(row, insertAfter) {
    clearRecipeEditDropIndicators();
    row.classList.toggle("recipe-edit-row-drop-before", !insertAfter);
    row.classList.toggle("recipe-edit-row-drop-after", insertAfter);
}

function clearRecipeEditDropIndicators() {
    document.querySelectorAll(".recipe-edit-row-drop-before, .recipe-edit-row-drop-after").forEach(row => {
        row.classList.remove("recipe-edit-row-drop-before", "recipe-edit-row-drop-after");
    });
}

function clearRecipeEditDragState() {
    clearRecipeEditDropIndicators();

    if (recipeEditDraggedRow) {
        recipeEditDraggedRow.classList.remove("recipe-edit-row-dragging");
    }

    if (recipeEditPointerDrag && recipeEditPointerDrag.row) {
        recipeEditPointerDrag.row.classList.remove("recipe-edit-row-dragging");
    }

    document.querySelectorAll(".recipe-edit-row-dragging").forEach(row => {
        row.classList.remove("recipe-edit-row-dragging");
    });

    recipeEditDraggedRow = null;
    recipeEditPointerDrag = null;
}

function dropRecipeEditRow(draggedRow, targetRow, insertAfter) {
    if (!recipeEditCanDropOnRow(draggedRow, targetRow)) {
        clearRecipeEditDragState();
        return false;
    }

    if (insertAfter) {
        targetRow.after(draggedRow);
    } else {
        targetRow.before(draggedRow);
    }

    updateRecipeEditRowOrder(draggedRow);
    clearRecipeEditDragState();
    return true;
}

function updateRecipeEditRowOrder(row) {
    closeRecipeEditRowMenus();

    if (!row) {
        return;
    }

    if (row.classList.contains("recipe-edit-ingredient-row")) {
        updateRecipeIngredientRowIndexes();
    }
    if (row.classList.contains("recipe-edit-equipment-row")) {
        updateRecipeEquipmentRowNumbers();
    }
    if (row.classList.contains("recipe-edit-instruction-row")) {
        updateRecipeInstructionStepNumbers();
    }
    if (row.classList.contains("recipe-url-summary-row")) {
        const list = row.closest("[data-recipe-url-sort-list]");

        if (list) {
            updateRecipeUrlOrderNumbers(list);
            saveRecipeUrlOrder(list);
        }
    }
    if (row.classList.contains("recipe-view-card")) {
        const list = row.closest("#recipeView");

        if (list) {
            updateRecipeViewOrderNumbers(list);
            saveRecipeViewOrder(list);
        }
    }
}

function recipeEditAdjacentMovableRow(row, direction) {
    const selector = recipeEditMoveSelectorForRow(row);
    let sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling;

    while (sibling && !sibling.matches(selector)) {
        sibling = direction < 0 ? sibling.previousElementSibling : sibling.nextElementSibling;
    }

    return sibling;
}

function closeRecipeEditRowMenus() {
    document.querySelectorAll(".recipe-edit-row-menu").forEach(menu => {
        menu.hidden = true;
        menu.classList.remove("recipe-edit-floating-menu");
        menu.style.left = "";
        menu.style.top = "";
        menu.style.right = "";
        restoreRecipeEditPopupMenu(menu);
    });
    document.querySelectorAll(".recipe-edit-menu-wrap-open").forEach(wrap => {
        wrap.classList.remove("recipe-edit-menu-wrap-open");
    });
    document.querySelectorAll(recipeEditMovableRowSelector()).forEach(row => {
        row.classList.remove("recipe-edit-menu-open");
    });
    document.querySelectorAll(".recipe-edit-row-menu-btn").forEach(button => {
        button.setAttribute("aria-expanded", "false");
    });
    closeRecipeViewGenerateSubmenus();
}

function closeRecipeViewGenerateSubmenus(scope = document) {
    scope.querySelectorAll(".recipe-view-generate-submenu").forEach(menu => {
        menu.hidden = true;
        menu.style.top = "";
    });
    scope.querySelectorAll(".recipe-view-generate-submenu-toggle").forEach(button => {
        button.setAttribute("aria-expanded", "false");
    });
}

function toggleRecipeViewGenerateSubmenu(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const row = button ? button.closest(".recipe-view-generate-submenu-row") : null;
    const menu = row ? row.querySelector(".recipe-view-generate-submenu") : null;
    const parentMenu = button ? button.closest(".recipe-view-global-menu, .recipe-view-title-menu") : null;
    const shouldOpen = menu ? menu.hidden : false;

    closeRecipeViewGenerateSubmenus(parentMenu || document);

    if (menu && shouldOpen) {
        menu.hidden = false;
        button.setAttribute("aria-expanded", "true");
        positionRecipeViewGenerateSubmenu(menu);
    }

    return false;
}

function positionRecipeViewGenerateSubmenu(menu) {
    if (!menu) {
        return;
    }

    menu.style.top = "";

    if (window.matchMedia("(max-width: 650px)").matches) {
        return;
    }

    const margin = 8;
    const rect = menu.getBoundingClientRect();
    let offset = 0;

    if (rect.bottom > window.innerHeight - margin) {
        offset -= rect.bottom - (window.innerHeight - margin);
    }
    if (rect.top + offset < margin) {
        offset += margin - (rect.top + offset);
    }
    if (offset) {
        menu.style.top = `${Math.round(offset)}px`;
    }
}

function recipeEditRowMenuIsOpen() {
    return Boolean(document.querySelector(".recipe-edit-row-menu:not([hidden])"));
}

function handleRecipeEditRowMenuOutsideClick(event) {
    if (!recipeEditRowMenuIsOpen()) {
        return;
    }

    const target = event ? event.target : null;

    if (
        target
        && typeof target.closest === "function"
        && target.closest(".recipe-edit-row-menu, .recipe-edit-row-menu-btn")
    ) {
        return;
    }

    closeRecipeEditRowMenus();
}

function handleRecipeEditRowMenuScrollOrResize() {
    if (!recipeEditRowMenuIsOpen()) {
        return;
    }

    window.requestAnimationFrame(() => {
        document.querySelectorAll(".recipe-edit-row-menu:not([hidden])").forEach(menu => {
            const wrap = menu.closest(".recipe-edit-row-menu-wrap, .recipe-edit-section-menu-wrap");
            const button = menu.recipeEditAnchorButton || (wrap ? wrap.querySelector(".recipe-edit-row-menu-btn") : null);

            if (button && button.isConnected) {
                positionRecipeEditPopupMenu(menu, button);
            } else {
                menu.hidden = true;
                menu.classList.remove("recipe-edit-floating-menu");
                restoreRecipeEditPopupMenu(menu);
            }
        });
    });
}

function closeRecipeIngredientRowMenus() {
    closeRecipeEditRowMenus();
}

async function confirmDeleteRecipeFromEditor(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const urlInput = document.getElementById("recipeEditOriginalUrl");
    const titleInput = document.getElementById("recipeEditTitleInput");
    const url = urlInput ? urlInput.value.trim() : "";
    const title = titleInput ? titleInput.value.trim() : "";

    if (!url) {
        setRecipeEditStatus("Unable to delete recipe: missing recipe URL.", true);
        return false;
    }

    const label = title || "this recipe";
    const shouldDelete = window.confirm(`Delete ${label}? This will remove it from the recipe log and shopping list.`);

    if (!shouldDelete) {
        closeRecipeEditRowMenus();
        return false;
    }

    const originalText = button ? button.textContent : "";

    try {
        if (button) {
            button.disabled = true;
            button.textContent = "Deleting...";
        }

        setRecipeEditStatus("Deleting recipe...");
        const formData = new FormData();
        formData.append("url", url);

        const response = await fetch("/remove_recipe", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            throw new Error("Unable to delete recipe.");
        }

        window.location.href = "/";
    } catch (err) {
        console.warn("Unable to delete recipe from editor.", err);
        setRecipeEditStatus(err.message || "Unable to delete recipe.", true);

        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Delete recipe";
        }
    }

    return false;
}

function duplicateRecipeIngredientRow(button) {
    const row = button ? button.closest(".recipe-edit-ingredient-row") : null;

    if (!row) {
        return false;
    }

    const duplicate = addRecipeIngredientRow(fieldValuesFromRow(row));
    row.after(duplicate);
    closeRecipeEditRowMenus();
    updateRecipeIngredientRowIndexes();
    return false;
}

function isRecipeIngredientRowCollapsed(row) {
    const list = row ? row.closest("#recipeEditIngredients") : null;

    if (!row) {
        return false;
    }

    if (row.classList.contains("recipe-edit-row-collapsed")) {
        return true;
    }

    return Boolean(
        list
        && list.classList.contains("recipe-edit-ingredients-collapsed")
        && !row.classList.contains("recipe-edit-row-expanded")
    );
}

function setRecipeIngredientRowCollapsed(row, collapsed) {
    const list = row ? row.closest("#recipeEditIngredients") : null;

    if (!row || !row.classList.contains("recipe-edit-ingredient-row")) {
        return;
    }

    if (collapsed) {
        row.classList.add("recipe-edit-row-collapsed");
        row.classList.remove("recipe-edit-row-expanded");
    } else {
        row.classList.remove("recipe-edit-row-collapsed");

        if (list && list.classList.contains("recipe-edit-ingredients-collapsed")) {
            row.classList.add("recipe-edit-row-expanded");
        } else {
            row.classList.remove("recipe-edit-row-expanded");
        }
    }

    updateRecipeIngredientRowCollapseToggle(row);
}

function expandRecipeIngredientRow(row) {
    setRecipeIngredientRowCollapsed(row, false);
}

function toggleRecipeIngredientRowCollapsed(button) {
    const row = recipeEditActionRowFromButton(button);

    if (!row || !row.classList.contains("recipe-edit-ingredient-row")) {
        return false;
    }

    setRecipeIngredientRowCollapsed(row, !isRecipeIngredientRowCollapsed(row));
    closeRecipeEditRowMenus();
    return false;
}

function updateRecipeIngredientRowCollapseToggle(row) {
    const button = row ? row.querySelector(".recipe-edit-row-collapse-toggle") : null;

    if (!button) {
        return;
    }

    button.textContent = isRecipeIngredientRowCollapsed(row) ? "Expand ingredient" : "Collapse ingredient";
}

function updateRecipeViewCardCollapseMenuToggle(row) {
    const button = row && row.classList.contains("recipe-view-card")
        ? row.querySelector(".recipe-view-card-collapse-menu-toggle")
        : null;

    if (!button) {
        return;
    }

    button.textContent = row.classList.contains("recipe-view-collapsed") ? "Expand this recipe" : "Collapse this recipe";
}

function moveRecipeEditRow(button, direction) {
    const row = recipeEditActionRowFromButton(button);

    if (!row) {
        return false;
    }

    const sibling = recipeEditAdjacentMovableRow(row, direction);

    if (direction < 0 && sibling) {
        sibling.before(row);
    } else if (direction > 0 && sibling) {
        sibling.after(row);
    }

    updateRecipeEditRowOrder(row);
    return false;
}

function moveRecipeIngredientRow(button, direction) {
    return moveRecipeEditRow(button, direction);
}

function toggleRecipeIngredientsCollapsed(button) {
    const list = document.getElementById("recipeEditIngredients");
    const label = button ? button.querySelector("span:last-child") : null;
    const icon = button ? button.querySelector(".recipe-edit-button-icon") : null;

    if (!list) {
        return false;
    }

    const collapsed = list.classList.toggle("recipe-edit-ingredients-collapsed");

    list.querySelectorAll(".recipe-edit-ingredient-row").forEach(row => {
        row.classList.remove("recipe-edit-row-collapsed");
        row.classList.remove("recipe-edit-row-expanded");
        updateRecipeIngredientRowCollapseToggle(row);
    });

    if (label) {
        label.textContent = collapsed ? "Expand All" : "Collapse All";
    }

    if (icon) {
        icon.textContent = collapsed ? "v" : "^";
    }

    return false;
}

function autoSortRecipeIngredients() {
    const list = document.getElementById("recipeEditIngredients");

    if (!list) {
        return false;
    }

    [...list.querySelectorAll(".recipe-edit-ingredient-row")]
        .sort((left, right) => {
            const leftValues = fieldValuesFromRow(left);
            const rightValues = fieldValuesFromRow(right);
            const leftKey = `${leftValues.store_section || ""} ${leftValues.ingredient || ""}`.toLowerCase();
            const rightKey = `${rightValues.store_section || ""} ${rightValues.ingredient || ""}`.toLowerCase();
            return leftKey.localeCompare(rightKey);
        })
        .forEach(row => list.appendChild(row));

    updateRecipeIngredientRowIndexes();
    return false;
}

function syncRecipeIngredientPurchaseGroup(input) {
    const row = input ? input.closest(".recipe-edit-ingredient-row") : null;
    const purchaseGroupInput = row ? row.querySelector('[data-field="purchase_group"]') : null;

    if (purchaseGroupInput) {
        purchaseGroupInput.value = "";
    }
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
    const recipeQtyInput = row.querySelector('[data-field="recipe_qty"]');

    if (quantityInput && baseQuantityInput) {
        baseQuantityInput.value = quantityInput.value.trim();
    }

    if (quantityInput && recipeQtyInput) {
        recipeQtyInput.value = quantityInput.value.trim();
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
    row.querySelectorAll('[data-field="ingredient"], [data-field="original_text"], [data-field="purchasable_item"], [data-field="preparation"]').forEach(input => {
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
    const ingredientChoiceReview = ingredientChoiceReviewFromRow(row);
    const ingredientTextReview = ingredientTextReviewFromRow(row);
    const isReviewed = row.dataset.foodReviewState === "reviewed";

    row.classList.toggle("has-ingredient-choice-review", Boolean(ingredientChoiceReview));
    renderIngredientChoiceReview(row, ingredientChoiceReview);
    marker.classList.toggle("reviewed", !ingredientChoiceReview && blockedBy.length === 0 && isReviewed);

    if (ingredientChoiceReview) {
        marker.hidden = false;
        marker.textContent = "Food Review";
        marker.title = ingredientChoiceReview.reason || "Pick one ingredient option.";
        marker.dataset.reviewKind = ingredientChoiceReview.sourceField === "ingredient_text_review"
            ? "ingredient_text_choice"
            : "ingredient_choice";
        marker.dataset.blockedBy = JSON.stringify(blockedBy);
        marker.tabIndex = 0;
        return;
    }

    if (ingredientTextReview) {
        marker.hidden = false;
        marker.textContent = "Food Review";
        marker.title = ingredientTextReview.reason || "This ingredient may need review before shopping.";
        marker.dataset.reviewKind = "ingredient_text";
        marker.dataset.blockedBy = JSON.stringify(blockedBy);
        marker.tabIndex = 0;
        return;
    }

    if (blockedBy.length) {
        marker.hidden = false;
        marker.textContent = "Food Review";
        marker.title = `Food rule review: ${blockedBy.join("; ")}`;
        marker.dataset.reviewKind = "food_rule";
        marker.dataset.blockedBy = JSON.stringify(blockedBy);
        marker.tabIndex = 0;
        return;
    }

    if (isReviewed) {
        marker.hidden = false;
        marker.textContent = "Reviewed";
        marker.title = "Reviewed with a ChatGPT alternative.";
        marker.dataset.reviewKind = "reviewed";
        marker.dataset.blockedBy = "[]";
        marker.tabIndex = 0;
        return;
    }

    marker.hidden = true;
    marker.textContent = "Food Review";
    marker.title = "";
    delete marker.dataset.reviewKind;
    marker.dataset.blockedBy = JSON.stringify(blockedBy);
    marker.tabIndex = -1;
}

function ingredientChoiceReviewFromRow(row) {
    const ingredientTextReview = ingredientTextReviewFromRow(row);

    if (ingredientTextReview && Array.isArray(ingredientTextReview.options) && ingredientTextReview.options.length) {
        return {
            sourceField: "ingredient_text_review",
            prompt: ingredientTextReview.prompt || "Pick grocery item",
            reason: ingredientTextReview.reason || "",
            options: ingredientTextReview.options,
        };
    }

    const ingredientInput = row.querySelector('[data-field="ingredient"]');
    const purchasableInput = row.querySelector('[data-field="purchasable_item"]');
    const originalTextInput = row.querySelector('[data-field="original_text"]');
    const primaryCandidates = [
        ["ingredient", ingredientInput ? ingredientInput.value : ""],
        ["purchasable_item", purchasableInput ? purchasableInput.value : ""],
    ];
    const primaryReview = primaryCandidates
        .map(([field, value]) => ingredientChoiceReviewFromText(value, field))
        .find(Boolean);

    if (primaryReview) {
        return primaryReview;
    }

    const hasNamedIngredient = primaryCandidates.some(([, value]) => String(value || "").trim());

    if (!hasNamedIngredient) {
        return ingredientChoiceReviewFromText(originalTextInput ? originalTextInput.value : "", "original_text");
    }

    return null;
}

function normalizeIngredientTextReview(value) {
    if (!value || typeof value !== "object" || !value.needs_review) {
        return null;
    }

    const options = Array.isArray(value.options)
        ? value.options
            .map(normalizeIngredientChoiceOptionData)
            .filter(option => option.ingredient)
        : [];

    if (!options.length) {
        return null;
    }

    return {
        needs_review: true,
        kind: value.kind || "ingredient_text",
        reason: String(value.reason || "").trim(),
        prompt: String(value.prompt || "Pick grocery item").trim(),
        options,
        source: String(value.source || "chatgpt").trim(),
        text_key: String(value.text_key || "").trim(),
    };
}

function ingredientTextReviewFromRow(row) {
    if (!row || !row.dataset.ingredientTextReview) {
        return null;
    }

    try {
        const review = normalizeIngredientTextReview(JSON.parse(row.dataset.ingredientTextReview));
        const expectedKey = row.dataset.ingredientTextReviewKey || "";
        const currentKey = ingredientTextReviewKeyFromRow(row);

        if (!review || (expectedKey && currentKey && expectedKey !== currentKey)) {
            return null;
        }

        return review;
    } catch (err) {
        return null;
    }
}

function ingredientTextReviewKeyFromRow(row) {
    if (!row) {
        return "";
    }

    const ingredientInput = row.querySelector('[data-field="ingredient"]');
    const originalTextInput = row.querySelector('[data-field="original_text"]');
    const preparationInput = row.querySelector('[data-field="preparation"]');

    return normalizeIngredientTextReviewKey([
        ingredientInput ? ingredientInput.value : "",
        originalTextInput ? originalTextInput.value : "",
        preparationInput ? preparationInput.value : "",
    ].join(" "));
}

function ingredientTextReviewKeyFromItem(item = {}) {
    return normalizeIngredientTextReviewKey([
        item.ingredient || "",
        item.original_text || "",
        item.preparation || "",
    ].join(" "));
}

function normalizeIngredientTextReviewKey(value) {
    return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function ingredientChoiceReviewFromText(value, sourceField) {
    const text = String(value || "").trim();
    const choiceText = text.replace(/\([^)]*\)/g, " ");

    if (!/\s+\bor\b\s+/i.test(choiceText)) {
        return null;
    }

    const options = uniqueIngredientChoiceOptions(
        expandIngredientChoiceSharedNouns(
            choiceText.split(/\s+\bor\b\s+/i).map(cleanIngredientChoiceOption)
        )
    );

    if (options.length < 2 || options.length > 4) {
        return null;
    }

    return {
        sourceField,
        options,
    };
}

function cleanIngredientChoiceOption(value) {
    return String(value || "")
        .replace(/\([^)]*\)/g, " ")
        .replace(/^[\s,;:/-]+/, "")
        .replace(/^[\d\s./]+/, "")
        .replace(/^(?:cups?|tablespoons?|tbsp\.?|teaspoons?|tsp\.?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|pinch(?:es)?|dash(?:es)?|cloves?|slices?|cans?|packages?|pkg\.?)\b\s+/i, "")
        .replace(/\b(?:divided|optional|to taste|as needed)\b/gi, " ")
        .replace(/^[\s,;:/-]+|[\s,;:/-]+$/g, "")
        .replace(/\s+/g, " ")
        .trim();
}

function expandIngredientChoiceSharedNouns(options) {
    const cleaned = options
        .map(option => String(option || "").trim())
        .filter(Boolean);

    if (cleaned.some(option => /\btortillas?\b/i.test(option))) {
        return cleaned.map(normalizeTortillaChoiceOption);
    }

    return cleaned;
}

function normalizeTortillaChoiceOption(option) {
    const cleaned = String(option || "")
        .replace(/\bflower\b/gi, "flour")
        .replace(/\btortillas\b/gi, "tortilla")
        .replace(/\s+/g, " ")
        .trim();

    if (!cleaned) {
        return "";
    }

    if (/\btortilla\b/i.test(cleaned)) {
        return cleaned;
    }

    return `${cleaned} tortilla`;
}

function uniqueIngredientChoiceOptions(options) {
    const seen = new Set();
    const cleaned = [];

    options.forEach(option => {
        const value = String(option || "").trim();
        const key = normalizeFoodKey(value);

        if (!value || value.length < 2 || !key || seen.has(key)) {
            return;
        }

        seen.add(key);
        cleaned.push(value);
    });

    return cleaned;
}

function renderIngredientChoiceReview(row, review) {
    const panel = row.querySelector("[data-ingredient-choice-review]");
    const optionsWrap = row.querySelector("[data-ingredient-choice-options]");

    if (!panel || !optionsWrap) {
        return;
    }

    if (!review) {
        panel.hidden = true;
        panel.dataset.sourceField = "";
        optionsWrap.innerHTML = "";
        return;
    }

    const options = (review.options || [])
        .map(normalizeIngredientChoiceOptionData)
        .filter(option => option.ingredient);

    panel.hidden = false;
    panel.dataset.sourceField = review.sourceField || "";
    const prompt = panel.querySelector(".recipe-edit-choice-prompt");

    if (prompt) {
        prompt.textContent = review.prompt || "Pick one option";
    }

    optionsWrap.innerHTML = options.map((option, index) => {
        const optionData = recipeIngredientChoiceDataAttributes(option, review);
        const canCreateIngredient = review.sourceField === "ingredient_text_review" && index > 0;

        return `
            <span class="recipe-edit-choice-row">
                <button type="button"
                        class="recipe-edit-choice-option"
                        ${optionData}
                        onclick="return selectRecipeIngredientChoice(this, event)">
                    ${escapeHtml(option.ingredient)}
                </button>
                ${canCreateIngredient ? `
                    <button type="button"
                            class="recipe-edit-choice-create"
                            ${optionData}
                            onclick="return createIngredientFromFoodReviewChoice(this, event)">
                        Create Ingredient
                    </button>
                ` : ""}
            </span>
        `;
    }).join("");
}

function recipeIngredientChoiceDataAttributes(option, review) {
    return `
        data-ingredient-choice-option="${escapeAttribute(option.ingredient)}"
        data-ingredient-choice-buy-as="${escapeAttribute(option.purchasable_item || option.ingredient)}"
        data-ingredient-choice-quantity="${escapeAttribute(option.quantity || "")}"
        data-ingredient-choice-unit="${escapeAttribute(option.unit || "")}"
        data-ingredient-choice-original-text="${escapeAttribute(option.original_text || "")}"
        data-ingredient-choice-preparation="${escapeAttribute(option.preparation || "")}"
        data-ingredient-choice-store-section="${escapeAttribute(option.store_section || "")}"
        data-ingredient-choice-source="${escapeAttribute(review.sourceField || "")}"
        title="${escapeAttribute(option.reason || review.reason || "")}"
    `;
}

function normalizeIngredientChoiceOptionData(option) {
    if (typeof option === "string") {
        const ingredient = option.trim();
        return {
            ingredient,
            purchasable_item: ingredient,
            reason: "",
        };
    }

    if (!option || typeof option !== "object") {
        return {
            ingredient: "",
            purchasable_item: "",
            reason: "",
        };
    }

    const ingredient = String(option.ingredient || option.name || "").trim();
    return {
        ingredient,
        purchasable_item: String(option.purchasable_item || option.buy_as || ingredient).trim(),
        quantity: String(option.quantity || "").trim(),
        unit: String(option.unit || "").trim(),
        original_text: String(option.original_text || "").trim(),
        preparation: String(option.preparation || "").trim(),
        store_section: String(option.store_section || "").trim(),
        reason: String(option.reason || "").trim(),
    };
}

function focusIngredientChoiceReview(row) {
    const panel = row.querySelector("[data-ingredient-choice-review]");
    const firstOption = panel ? panel.querySelector("[data-ingredient-choice-option]") : null;

    if (panel) {
        panel.classList.add("active");
        setTimeout(() => panel.classList.remove("active"), 1400);
    }

    if (firstOption) {
        firstOption.focus();
    }
}

function selectRecipeIngredientChoice(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const row = button ? button.closest(".recipe-edit-ingredient-row") : null;
    const option = button ? button.dataset.ingredientChoiceOption || "" : "";
    const buyAs = button ? button.dataset.ingredientChoiceBuyAs || option : option;
    const source = button ? button.dataset.ingredientChoiceSource || "" : "";

    if (!row || !option) {
        return false;
    }

    setRowFieldValue(row, "ingredient", option);
    setRowFieldValue(row, "purchasable_item", buyAs);

    if (button.dataset.ingredientChoiceSource === "original_text") {
        setRowFieldValue(row, "original_text", option);
    } else if (source === "ingredient_text_review") {
        const quantity = button.dataset.ingredientChoiceQuantity || "";
        const unit = button.dataset.ingredientChoiceUnit || "";
        const originalText = button.dataset.ingredientChoiceOriginalText || "";

        if (quantity) {
            setRowFieldValue(row, "quantity", quantity);
        }

        if (unit) {
            setRowFieldValue(row, "unit", unit);
        }

        if (originalText) {
            setRowFieldValue(row, "original_text", originalText);
        }
    }

    const purchaseGroupInput = row.querySelector('[data-field="purchase_group"]');

    if (purchaseGroupInput) {
        purchaseGroupInput.value = "";
    }

    delete row.dataset.foodReviewState;
    updateRecipeIngredientFoodRuleWarning(row);
    showRecipeQuantityUpdatedMessage("", "", "", "Ingredient option selected. Save Recipe to keep it.");
    return false;
}

function createIngredientFromFoodReviewChoice(button, event = null) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const row = button ? button.closest(".recipe-edit-ingredient-row") : null;
    const option = button ? button.dataset.ingredientChoiceOption || "" : "";

    if (!row || !option) {
        return false;
    }

    const newIngredient = recipeIngredientFromChoiceButton(button, row);
    const newRow = addRecipeIngredientRow(newIngredient);

    if (newRow) {
        row.after(newRow);
        expandRecipeIngredientRow(newRow);
        updateRecipeIngredientRowIndexes();
        const ingredientInput = newRow.querySelector('[data-field="ingredient"]');

        if (ingredientInput) {
            ingredientInput.focus();
        }
    }

    showRecipeQuantityUpdatedMessage("", "", "", "Ingredient row created. Save Recipe to keep it.");
    return false;
}

function recipeIngredientFromChoiceButton(button, sourceRow) {
    const ingredient = button.dataset.ingredientChoiceOption || "";
    const purchasable = button.dataset.ingredientChoiceBuyAs || ingredient;
    const quantity = button.dataset.ingredientChoiceQuantity || "";
    const unit = button.dataset.ingredientChoiceUnit || "";
    const originalText = button.dataset.ingredientChoiceOriginalText || [quantity, unit, ingredient]
        .filter(Boolean)
        .join(" ");
    const sourceStoreSection = sourceRow ? sourceRow.querySelector('[data-field="store_section"]') : null;
    const storeSection = button.dataset.ingredientChoiceStoreSection
        || (sourceStoreSection ? sourceStoreSection.value : "");

    return {
        ingredient,
        original_text: originalText || ingredient,
        quantity,
        unit,
        preparation: button.dataset.ingredientChoicePreparation || "",
        purchasable_item: purchasable,
        buy_as: purchasable,
        store_section: storeSection,
        optional: false,
    };
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

    const equipmentText = typeof value === "object" && value !== null
        ? (value.equipment || value.text || value.name || "")
        : value;
    const equipmentImageUrl = typeof value === "object" && value !== null
        ? (value.equipment_image_url || value.image_url || "")
        : "";
    const equipmentImageGeneratedAt = typeof value === "object" && value !== null
        ? (value.equipment_image_generated_at || value.image_generated_at || "")
        : "";
    const recipeUrl = recipeEditorCurrentUrl();
    const row = document.createElement("div");
    row.className = "recipe-edit-text-row recipe-edit-equipment-row";
    row.innerHTML = `
        <span class="recipe-edit-row-handle" aria-hidden="true">${recipeEditSvgIcon("drag")}</span>
        <span class="recipe-edit-row-number" data-equipment-row-number></span>
        <label>
            <span class="sr-only">Equipment</span>
            <input type="text" data-field="text" value="${escapeAttribute(equipmentText || "")}">
        </label>
        <div class="recipe-edit-row-image-panel recipe-step-image-panel recipe-equipment-image-panel"
             data-equipment-image-panel
             data-recipe-url="${escapeAttribute(recipeUrl)}"
             data-equipment-index="">
            <div class="recipe-step-image-status${equipmentImageUrl ? " empty" : ""}"
                 data-equipment-image-status>
                ${equipmentImageUrl ? "" : "No image generated for this equipment."}
            </div>
            <img class="recipe-step-image recipe-equipment-image"
                 ${equipmentImageUrl ? `src="${escapeAttribute(equipmentImageUrl)}"` : ""}
                 alt="Equipment image"
                 loading="lazy"
                 ${equipmentImageUrl ? "" : "hidden"}>
            <div class="recipe-step-image-actions">
                <button type="button"
                        class="recipe-step-image-btn"
                        data-equipment-image-generate
                        onclick="return generateRecipeEquipmentImage(this)">
                    ${equipmentImageUrl ? "Regenerate equipment image" : "Generate equipment image"}
                </button>
                <a class="recipe-step-image-download"
                   data-equipment-image-download
                   href="${escapeAttribute(equipmentImageUrl || "#")}"
                   download
                   ${equipmentImageUrl ? "" : "hidden"}>
                    Download
                </a>
                <button type="button"
                        class="recipe-step-image-upload"
                        data-recipe-image-upload-button
                        onclick="return openRecipeDetailImageUpload(this)">
                    ${equipmentImageUrl ? "Replace" : "Upload"}
                </button>
                <input type="file"
                       class="recipe-step-image-file-input"
                       data-recipe-image-upload
                       accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,image/avif"
                       onchange="return uploadRecipeDetailImage(this)">
            </div>
            <input type="hidden" data-field="equipment_image_url" value="${escapeAttribute(equipmentImageUrl)}">
            <input type="hidden" data-field="equipment_image_generated_at" value="${escapeAttribute(equipmentImageGeneratedAt)}">
        </div>
        <div class="recipe-edit-row-menu-wrap">
            <button type="button"
                    class="recipe-edit-row-menu-btn"
                    aria-label="Equipment actions"
                    title="Equipment actions"
                    aria-haspopup="true"
                    aria-expanded="false"
                    onclick="return toggleRecipeEditRowMenu(this, event)">
                <span aria-hidden="true"></span>
            </button>
            <div class="recipe-edit-row-menu overflow-menu recipe-edit-text-row-menu" hidden>
                <div class="overflow-menu-section">
                    <div class="overflow-menu-section-title">Content</div>
                    <button type="button" onclick="moveRecipeEditRow(this, -1)">Move equipment up</button>
                    <button type="button" onclick="moveRecipeEditRow(this, 1)">Move equipment down</button>
                    <button type="button" class="delete" onclick="removeRecipeEditRow(this)">Delete equipment</button>
                </div>
                <div class="overflow-menu-section">
                    <div class="overflow-menu-section-title">Generate Images</div>
                    <button type="button"
                            data-recipe-edit-row-image-generate
                            onclick="return generateRecipeEditRowImageFromMenu(this)">
                        ${equipmentImageUrl ? "Regenerate equipment image" : "Generate equipment image"}
                    </button>
                </div>
                <div class="overflow-menu-section">
                    <div class="overflow-menu-section-title">Show or Hide Images</div>
                    <button type="button"
                            data-recipe-edit-row-image-show
                            onclick="return setRecipeEditRowImageVisibleFromMenu(this, true)"
                            hidden>
                        Show equipment image
                    </button>
                    <button type="button"
                            data-recipe-edit-row-image-hide
                            onclick="return setRecipeEditRowImageVisibleFromMenu(this, false)">
                        Hide equipment image
                    </button>
                    <button type="button"
                            onclick="return setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'equipment' })">
                        Show all equipment images
                    </button>
                    <button type="button"
                            onclick="return setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'equipment' })">
                        Hide all equipment images
                    </button>
                </div>
            </div>
        </div>
    `;
    wrap.appendChild(row);
    bindRecipeEditDragAndDrop(row);
    updateRecipeEquipmentRowNumbers();
    return row;
}

function recipeEquipmentHeaderHtml() {
    return `
        <div class="recipe-edit-equipment-header" aria-hidden="true">
            <span></span>
            <span>#</span>
            <span>Equipment</span>
            <span></span>
        </div>
    `;
}

function updateRecipeEquipmentRowNumbers() {
    [...document.querySelectorAll("#recipeEditEquipment .recipe-edit-equipment-row")]
        .forEach((row, index) => {
            const number = row.querySelector("[data-equipment-row-number]");
            const panel = row.querySelector("[data-equipment-image-panel]");
            const value = String(index + 1);

            if (number) {
                number.textContent = value;
            }

            if (panel) {
                panel.dataset.equipmentIndex = value;
                panel.dataset.recipeUrl = recipeEditorCurrentUrl();
            }
        });
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
    const stepImageUrl = typeof value === "object" && value !== null
        ? (value.step_image_url || value.image_url || "")
        : "";
    const stepImageGeneratedAt = typeof value === "object" && value !== null
        ? (value.step_image_generated_at || value.image_generated_at || "")
        : "";
    const nextStepNumber = sourceStepNumber || nextRecipeInstructionNumber();
    const recipeUrl = recipeEditorCurrentUrl();
    const row = document.createElement("div");
    row.className = "recipe-edit-text-row recipe-edit-instruction-row";
    row.innerHTML = `
        <span class="recipe-edit-row-handle" aria-hidden="true">${recipeEditSvgIcon("drag")}</span>
        <label class="recipe-edit-step-number">
            <span class="sr-only">Step #</span>
            <span class="recipe-edit-row-number" data-instruction-row-number></span>
            <input type="hidden" data-field="step_number" value="${escapeAttribute(nextStepNumber)}">
        </label>
        <label class="recipe-edit-step-text">
            <span class="sr-only">Instructions</span>
            <textarea data-field="text" rows="3">${escapeHtml(instruction || "")}</textarea>
        </label>
        <div class="recipe-edit-row-image-panel recipe-step-image-panel"
             data-step-image-panel
             data-recipe-url="${escapeAttribute(recipeUrl)}"
             data-step-number="${escapeAttribute(nextStepNumber)}">
            <div class="recipe-step-image-status${stepImageUrl ? " empty" : ""}"
                 data-step-image-status>
                ${stepImageUrl ? "" : "No image generated for this step."}
            </div>
            <img class="recipe-step-image"
                 ${stepImageUrl ? `src="${escapeAttribute(stepImageUrl)}"` : ""}
                 alt="Instruction step image"
                 loading="lazy"
                 ${stepImageUrl ? "" : "hidden"}>
            <div class="recipe-step-image-actions">
                <button type="button"
                        class="recipe-step-image-btn"
                        data-step-image-generate
                        onclick="return generateRecipeStepImage(this)">
                    ${stepImageUrl ? "Regenerate step image" : "Generate step image"}
                </button>
                <a class="recipe-step-image-download"
                   data-step-image-download
                   href="${escapeAttribute(stepImageUrl || "#")}"
                   download
                   ${stepImageUrl ? "" : "hidden"}>
                    Download
                </a>
                <button type="button"
                        class="recipe-step-image-upload"
                        data-recipe-image-upload-button
                        onclick="return openRecipeDetailImageUpload(this)">
                    ${stepImageUrl ? "Replace" : "Upload"}
                </button>
                <input type="file"
                       class="recipe-step-image-file-input"
                       data-recipe-image-upload
                       accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,image/avif"
                       onchange="return uploadRecipeDetailImage(this)">
            </div>
            <input type="hidden" data-field="step_image_url" value="${escapeAttribute(stepImageUrl)}">
            <input type="hidden" data-field="step_image_generated_at" value="${escapeAttribute(stepImageGeneratedAt)}">
        </div>
        <div class="recipe-edit-row-menu-wrap">
            <button type="button"
                    class="recipe-edit-row-menu-btn"
                    aria-label="Instruction actions"
                    title="Instruction actions"
                    aria-haspopup="true"
                    aria-expanded="false"
                    onclick="return toggleRecipeEditRowMenu(this, event)">
                <span aria-hidden="true"></span>
            </button>
            <div class="recipe-edit-row-menu overflow-menu recipe-edit-text-row-menu" hidden>
                <div class="overflow-menu-section">
                    <div class="overflow-menu-section-title">Content</div>
                    <button type="button" onclick="moveRecipeEditRow(this, -1)">Move step up</button>
                    <button type="button" onclick="moveRecipeEditRow(this, 1)">Move step down</button>
                    <button type="button" class="delete" onclick="removeRecipeEditRow(this)">Delete step</button>
                </div>
                <div class="overflow-menu-section">
                    <div class="overflow-menu-section-title">Generate Images</div>
                    <button type="button"
                            data-recipe-edit-row-image-generate
                            onclick="return generateRecipeEditRowImageFromMenu(this)">
                        ${stepImageUrl ? "Regenerate step image" : "Generate step image"}
                    </button>
                </div>
                <div class="overflow-menu-section">
                    <div class="overflow-menu-section-title">Show or Hide Images</div>
                    <button type="button"
                            data-recipe-edit-row-image-show
                            onclick="return setRecipeEditRowImageVisibleFromMenu(this, true)"
                            hidden>
                        Show step image
                    </button>
                    <button type="button"
                            data-recipe-edit-row-image-hide
                            onclick="return setRecipeEditRowImageVisibleFromMenu(this, false)">
                        Hide step image
                    </button>
                    <button type="button"
                            onclick="return setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'instructions' })">
                        Show all instruction images
                    </button>
                    <button type="button"
                            onclick="return setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'instructions' })">
                        Hide all instruction images
                    </button>
                </div>
            </div>
        </div>
    `;
    wrap.appendChild(row);
    bindRecipeEditDragAndDrop(row);
    updateRecipeInstructionStepNumbers();
    return row;
}

function recipeInstructionsHeaderHtml() {
    return `
        <div class="recipe-edit-instructions-header" aria-hidden="true">
            <span></span>
            <span>#</span>
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

function updateRecipeInstructionStepNumbers() {
    [...document.querySelectorAll("#recipeEditInstructions .recipe-edit-instruction-row")]
        .forEach((row, index) => {
            const input = row.querySelector('[data-field="step_number"]');
            const number = row.querySelector("[data-instruction-row-number]");
            const panel = row.querySelector("[data-step-image-panel]");
            const value = String(index + 1);

            if (input) {
                input.value = value;
            }

            if (number) {
                number.textContent = value;
            }

            if (panel) {
                panel.dataset.stepNumber = value;
                panel.dataset.recipeUrl = recipeEditorCurrentUrl();
            }
        });
}

function addRecipeNutritionRow(item = {}) {
    const wrap = document.getElementById("recipeEditNutrition");

    if (!wrap) {
        return;
    }

    const row = document.createElement("div");
    row.className = "recipe-edit-nutrition-row";
    row.innerHTML = `
        <span class="recipe-edit-row-handle" aria-hidden="true">${recipeEditSvgIcon("drag")}</span>
        <label>
            <input type="text" data-field="key" aria-label="Nutrition label" placeholder="Label" value="${escapeAttribute(item.key || "")}">
        </label>
        <label>
            <input type="text" data-field="value" aria-label="Nutrition value" placeholder="Value" value="${escapeAttribute(item.value || "")}">
        </label>
        <div class="recipe-edit-row-menu-wrap">
            <button type="button"
                    class="recipe-edit-row-menu-btn"
                    aria-label="Nutrition actions"
                    title="Nutrition actions"
                    aria-haspopup="true"
                    aria-expanded="false"
                    onclick="return toggleRecipeEditRowMenu(this, event)">
                <span aria-hidden="true"></span>
            </button>
            <div class="recipe-edit-row-menu" hidden>
                <button type="button" onclick="moveRecipeEditRow(this, -1)">Move nutrition row up</button>
                <button type="button" onclick="moveRecipeEditRow(this, 1)">Move nutrition row down</button>
                <button type="button" class="delete" onclick="removeRecipeEditRow(this)">Delete nutrition row</button>
            </div>
        </div>
    `;
    wrap.appendChild(row);
    bindRecipeEditDragAndDrop(row);
    return row;
}

function recipeNutritionHeaderHtml() {
    return `
        <div class="recipe-edit-nutrition-header" aria-hidden="true">
            <span></span>
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

function recipeReflectionTimestamp(value = "") {
    const parsed = value ? new Date(value) : new Date();

    if (Number.isNaN(parsed.getTime())) {
        return new Date().toISOString();
    }

    return parsed.toISOString();
}

function formatRecipeReflectionTimestamp(value) {
    const parsed = value ? new Date(value) : null;

    if (!parsed || Number.isNaN(parsed.getTime())) {
        return "";
    }

    return parsed.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
    });
}

function recipeReflectionNoteId(value = "") {
    const existing = String(value || "").trim();

    if (existing) {
        return existing;
    }

    return `note-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function addRecipeReflectionNoteRow(note = {}) {
    const wrap = document.getElementById("recipeEditReflectionNotes");

    if (!wrap) {
        return null;
    }

    const createdAt = String(note.created_at || "").trim() || recipeReflectionTimestamp();
    const feedbackCreatedAt = String(note.chatgpt_feedback_created_at || "").trim();
    const feedback = String(note.chatgpt_feedback || "").trim();
    const row = document.createElement("div");

    row.className = "recipe-edit-reflection-note-row";
    row.innerHTML = `
        <span class="recipe-edit-row-handle" aria-hidden="true">${recipeEditSvgIcon("drag")}</span>
        <div class="recipe-edit-reflection-note-main">
            <div class="recipe-edit-reflection-note-meta">
                <span>Added ${escapeHtml(formatRecipeReflectionTimestamp(createdAt) || createdAt)}</span>
                ${feedbackCreatedAt ? `<span data-note-feedback-time>Feedback ${escapeHtml(formatRecipeReflectionTimestamp(feedbackCreatedAt) || feedbackCreatedAt)}</span>` : `<span data-note-feedback-time hidden></span>`}
            </div>
            <textarea data-field="text" rows="3" placeholder="What worked, what changed, or what should be tried next time?">${escapeHtml(note.text || "")}</textarea>
            <input type="hidden" data-field="note_id" value="${escapeAttribute(recipeReflectionNoteId(note.note_id))}">
            <input type="hidden" data-field="created_at" value="${escapeAttribute(createdAt)}">
            <input type="hidden" data-field="chatgpt_feedback_created_at" value="${escapeAttribute(feedbackCreatedAt)}">
            <textarea data-field="chatgpt_feedback" hidden>${escapeHtml(feedback)}</textarea>
            <div class="recipe-edit-note-feedback" data-note-feedback${feedback ? "" : " hidden"}>${escapeHtml(feedback)}</div>
        </div>
        <div class="recipe-edit-reflection-note-actions">
            <button type="button"
                    class="recipe-edit-note-feedback-btn"
                    onclick="return askRecipeNoteFeedback(this)">
                Ask ChatGPT
            </button>
            <div class="recipe-edit-row-menu-wrap">
                <button type="button"
                        class="recipe-edit-row-menu-btn"
                        aria-label="Note actions"
                        title="Note actions"
                        aria-haspopup="true"
                        aria-expanded="false"
                        onclick="return toggleRecipeEditRowMenu(this, event)">
                    <span aria-hidden="true"></span>
                </button>
                <div class="recipe-edit-row-menu" hidden>
                    <button type="button" onclick="moveRecipeEditRow(this, -1)">Move note up</button>
                    <button type="button" onclick="moveRecipeEditRow(this, 1)">Move note down</button>
                    <button type="button" class="delete" onclick="removeRecipeEditRow(this)">Delete note</button>
                </div>
            </div>
        </div>
    `;
    wrap.appendChild(row);
    bindRecipeEditDragAndDrop(row);
    return row;
}

function collectRecipeReflectionNotes() {
    return [...document.querySelectorAll("#recipeEditReflectionNotes .recipe-edit-reflection-note-row")]
        .map(row => {
            const item = fieldValuesFromRow(row);
            const text = String(item.text || "").trim();

            return {
                note_id: recipeReflectionNoteId(item.note_id),
                text,
                created_at: String(item.created_at || "").trim() || recipeReflectionTimestamp(),
                chatgpt_feedback: String(item.chatgpt_feedback || "").trim(),
                chatgpt_feedback_created_at: String(item.chatgpt_feedback_created_at || "").trim(),
            };
        })
        .filter(item => item.text);
}

function applyRecipeNoteFeedbackToRow(row, feedback, createdAt) {
    const feedbackText = String(feedback || "").trim();
    const timestamp = String(createdAt || "").trim() || recipeReflectionTimestamp();
    const feedbackDisplay = row ? row.querySelector("[data-note-feedback]") : null;
    const feedbackInput = row ? row.querySelector('[data-field="chatgpt_feedback"]') : null;
    const feedbackTimeInput = row ? row.querySelector('[data-field="chatgpt_feedback_created_at"]') : null;
    const feedbackTime = row ? row.querySelector("[data-note-feedback-time]") : null;

    if (feedbackInput) {
        feedbackInput.value = feedbackText;
    }

    if (feedbackTimeInput) {
        feedbackTimeInput.value = timestamp;
    }

    if (feedbackDisplay) {
        feedbackDisplay.textContent = feedbackText;
        feedbackDisplay.hidden = !feedbackText;
    }

    if (feedbackTime) {
        feedbackTime.textContent = `Feedback ${formatRecipeReflectionTimestamp(timestamp) || timestamp}`;
        feedbackTime.hidden = !feedbackText;
    }
}

async function askRecipeNoteFeedback(button) {
    const row = button ? button.closest(".recipe-edit-reflection-note-row") : null;
    const noteInput = row ? row.querySelector('[data-field="text"]') : null;
    const note = noteInput ? noteInput.value.trim() : "";

    if (!row || !note) {
        setRecipeEditStatus("Add a recipe note before asking ChatGPT for feedback.", true);
        return false;
    }

    const originalText = button ? button.textContent : "";

    if (button) {
        button.disabled = true;
        button.textContent = "Asking...";
    }

    try {
        setRecipeEditStatus("Asking ChatGPT for note feedback...");
        const payload = collectRecipeEditorPayload();
        const response = await fetch("/api/recipe_note_feedback", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                note,
                recipe: payload.recipe,
            }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error((data && data.error) || "Unable to get note feedback.");
        }

        applyRecipeNoteFeedbackToRow(row, data.feedback || "", data.created_at || "");
        setRecipeEditStatus("ChatGPT feedback added. Save Recipe to keep it.");
    } catch (err) {
        console.warn("Unable to get recipe note feedback.", err);
        setRecipeEditStatus(err.message || "Unable to get note feedback.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Ask ChatGPT";
        }
    }

    return false;
}

function removeRecipeEditRow(button) {
    const row = button ? button.closest(recipeEditMovableRowSelector()) : null;

    if (row) {
        const wasIngredient = row.classList.contains("recipe-edit-ingredient-row");
        const wasEquipment = row.classList.contains("recipe-edit-equipment-row");
        const wasInstruction = row.classList.contains("recipe-edit-instruction-row");
        row.remove();
        closeRecipeEditRowMenus();

        if (wasIngredient) {
            updateRecipeIngredientRowIndexes();
        }
        if (wasEquipment) {
            updateRecipeEquipmentRowNumbers();
        }
        if (wasInstruction) {
            updateRecipeInstructionStepNumbers();
        }
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
            updateRecipeSaveProgressItem(pdfProgressIndex, "running", "Generating...");
            setRecipeEditStatus("Generating PDF...");
            const pdfData = await createRecipePdfForSource(sourceUrl);
            recipeForEditor = {
                ...(recipeForEditor || {}),
                source_url: pdfData.url || sourceUrl,
                pdf_path: pdfData.pdf_path || "",
                pdf_available: true,
                pdf_local_available: Boolean(pdfData.pdf_local_available),
                pdf_public_url: pdfData.pdf_public_url || "",
                pdf_object_key: pdfData.pdf_object_key || "",
                pdf_uploaded_at: pdfData.pdf_uploaded_at || "",
            };
            updateRecipeSaveProgressItem(pdfProgressIndex, "done", pdfData.pdf_public_url ? "Cloud ready" : "Created");
        }

        updateRecipeSaveProgressItem(refreshProgressIndex, "running", "Refreshing...");
        await refreshStoreMarkup();
        if (recipeForEditor) {
            populateRecipeEditor(recipeForEditor, recipeForEditor.source_url || sourceUrl);
        }
        updateRecipeSaveProgressItem(refreshProgressIndex, "done", "Refreshed");
        setRecipeSaveProgressSummary(
            shouldCreatePdf
                ? "Recipe saved, cloud PDF ready, and page values refreshed."
                : "Recipe saved and page values refreshed."
        );
        setRecipeSaveProgressActionsState("done");
        setRecipeEditStatus("");
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe updated.");
    } catch (err) {
        console.warn("Unable to save recipe.", err);
        setRecipeEditStatus("Unable to save recipe.", true);
        setRecipeSaveProgressSummary("Unable to save recipe.");
        updateRecipeSaveProgressFailed();
        setRecipeSaveProgressActionsState("failed");
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
    let statusMessage = "Cloud PDF ready.";
    let finalPdfData = null;

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

        setRecipeEditStatus("Generating PDF...");
        const pdfData = await createRecipePdfForSource(sourceUrl);
        finalPdfData = pdfData;

        if (!pdfData.pdf_public_url) {
            try {
                setRecipeEditStatus("Uploading PDF to Cloudflare...");
                const uploadData = await uploadRecipeEditorPdfToCloudflareWithSource(sourceUrl);
                if (uploadData && uploadData.ok) {
                    finalPdfData = {
                        ...finalPdfData,
                        ...uploadData,
                    };
                    statusMessage = "Cloud PDF ready.";
                } else {
                    statusMessage = "PDF created, but Cloudflare upload was not completed.";
                }
            } catch (uploadError) {
                statusMessage = `PDF created, but automatic Cloudflare upload failed: ${uploadError.message || "Unknown error"}`;
            }
        } else if (pdfData.already_exists) {
            statusMessage = "Cloud PDF ready.";
        } else {
            statusMessage = "Cloud PDF ready.";
        }

        updateRecipeEditorPdfControls({
            source_url: finalPdfData.url || sourceUrl,
            pdf_path: finalPdfData.pdf_path || "",
            pdf_available: true,
            pdf_local_available: Boolean(finalPdfData.pdf_local_available),
            pdf_public_url: finalPdfData.pdf_public_url || "",
            pdf_object_key: finalPdfData.pdf_object_key || "",
            pdf_uploaded_at: finalPdfData.pdf_uploaded_at || "",
        });
        setRecipeEditStatus(statusMessage);
        showRecipeQuantityUpdatedMessage("", "", "", statusMessage);
    } catch (err) {
        console.warn("Unable to create recipe PDF.", err);
        setRecipeEditStatus("Unable to create PDF.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Create recipe PDF";
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

function isShareablePublicPdfUrl(value) {
    if (!isLegitimateWebUrl(value)) {
        return false;
    }

    try {
        const url = new URL(String(value || "").trim());
        const hostname = url.hostname.toLowerCase();

        return !(
            ["127.0.0.1", "localhost", "::1"].includes(hostname)
            || hostname.endsWith(".trycloudflare.com")
        );
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

async function uploadRecipeEditorPdfToCloudflareWithSource(sourceUrl) {
    const sourceUrlValue = String(sourceUrl || "").trim();

    if (!sourceUrlValue) {
        throw new Error("Recipe URL is required before uploading the PDF.");
    }

    const response = await fetch("/api/recipe_pdf/cloudflare_upload", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: sourceUrlValue }),
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
        throw new Error((data && data.error) || "Unable to upload PDF to Cloudflare.");
    }

    updateRecipeEditorPdfControls({
        source_url: data.url || sourceUrlValue,
        pdf_path: data.pdf_path || "",
        pdf_available: data.pdf_available !== false,
        pdf_local_available: Boolean(data.pdf_local_available),
        pdf_public_url: data.pdf_public_url || "",
        pdf_object_key: data.pdf_object_key || "",
        pdf_uploaded_at: data.pdf_uploaded_at || "",
    });

    return data;
}

async function uploadRecipeEditorPdfToCloudflare(button) {
    const originalText = button ? button.textContent : "";
    const sourceInput = document.getElementById("recipeEditSourceUrl");
    const originalInput = document.getElementById("recipeEditOriginalUrl");
    const sourceUrl = (
        (sourceInput ? sourceInput.value.trim() : "")
        || (originalInput ? originalInput.value.trim() : "")
        || ""
    );

    if (!sourceUrl) {
        setRecipeEditStatus("Recipe URL is required before uploading the PDF.", true);
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "Uploading...";
    }

    try {
        setRecipeEditStatus("Uploading PDF to Cloudflare...");
        const data = await uploadRecipeEditorPdfToCloudflareWithSource(sourceUrl);
        setRecipeEditStatus("Cloud PDF ready.");
        showRecipeQuantityUpdatedMessage("", "", "", "Cloud PDF ready.");
        return false;
    } catch (err) {
        console.warn("Unable to upload recipe PDF to Cloudflare.", err);
        setRecipeEditStatus(err.message || "Unable to upload PDF to Cloudflare.", true);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText || "Upload to Cloudflare";
        }
    }

    return false;
}

async function copyRecipeEditorPdfLink(button) {
    const publicUrlInput = document.getElementById("recipeEditPdfPublicUrl");
    const publicUrl = (
        (button && button.dataset.pdfPublicUrl ? button.dataset.pdfPublicUrl : "")
        || (publicUrlInput ? publicUrlInput.value.trim() : "")
    );

    if (!publicUrl) {
        setRecipeEditStatus("Cloud PDF link is not ready yet.", true);
        return false;
    }

    if (!isShareablePublicPdfUrl(publicUrl)) {
        setRecipeEditStatus("Cloudflare PDF link is not ready yet.", true);
        return false;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(publicUrl);
        } else if (publicUrlInput) {
            publicUrlInput.select();
            document.execCommand("copy");
        }

        setRecipeEditStatus("Cloudflare link copied.");
    } catch (err) {
        console.warn("Unable to copy recipe PDF link.", err);
        if (publicUrlInput) {
            publicUrlInput.select();
        }
        setRecipeEditStatus("PDF link selected. Use Ctrl+C to copy.", true);
    }

    return false;
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
        cover_image: normalizeRecipeCoverImageSnapshot(recipe.cover_image || {}),
        rating: String(normalizeRecipeRatingValue(recipe.rating || 0)),
        level: String(recipe.level || "").trim(),
        total_time: String(recipe.total_time || "").trim(),
        prep_time: String(recipe.prep_time || "").trim(),
        inactive_time: String(recipe.inactive_time || "").trim(),
        cook_time: String(recipe.cook_time || "").trim(),
        scaling: normalizeRecipeScalingSnapshot(recipe.scaling || {}),
        ingredients: (recipe.ingredients || []).map(item => ({
            ingredient: String(item.ingredient || "").trim(),
            quantity: String(item.quantity || "").trim(),
            unit: String(item.unit || "").trim(),
            original_text: String(item.original_text || "").trim(),
            purchasable_item: String(item.purchasable_item || item.buy_as || "").trim(),
            preparation: String(item.preparation || "").trim(),
            section: String(item.section || "").trim(),
            store_section: String(item.store_section || "").trim(),
            optional: Boolean(item.optional),
        })),
        equipment: (recipe.equipment || [])
            .map(value => {
                if (typeof value === "object" && value !== null) {
                    return String(value.equipment || value.text || value.name || "").trim();
                }

                return String(value || "").trim();
            })
            .filter(Boolean),
        instructions: (recipe.instructions || [])
            .map((value, index) => normalizeRecipeInstructionSnapshot(value, index))
            .filter(item => item.instruction),
        nutrition: (recipe.nutrition || []).map(item => ({
            key: String(item.key || "").trim(),
            value: String(item.value || "").trim(),
        })),
        reflection_notes: normalizeRecipeReflectionNotesSnapshot(recipe.reflection_notes || []),
        chatgpt_feedback: String(recipe.chatgpt_feedback || "").trim(),
        chatgpt_feedback_created_at: String(recipe.chatgpt_feedback_created_at || "").trim(),
    };
}

function normalizeRecipeReflectionNotesSnapshot(notes) {
    return (Array.isArray(notes) ? notes : [])
        .map(item => ({
            note_id: String(item.note_id || "").trim(),
            text: String(item.text || "").trim(),
            created_at: String(item.created_at || "").trim(),
            chatgpt_feedback: String(item.chatgpt_feedback || "").trim(),
            chatgpt_feedback_created_at: String(item.chatgpt_feedback_created_at || "").trim(),
        }))
        .filter(item => item.text);
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
        ["Rating", "rating"],
        ["Level", "level"],
        ["Total", "total_time"],
        ["Prep", "prep_time"],
        ["Inactive", "inactive_time"],
        ["Cook", "cook_time"],
    ].forEach(([label, key]) => {
        if (previous[key] !== next[key]) {
            detailLines.push(`${label}: ${previous[key] || "(blank)"} -> ${next[key] || "(blank)"}`);
        }
    });

    if (previous.scaling.selected_multiplier !== next.scaling.selected_multiplier) {
        detailLines.push(`Recipe amount: ${previous.scaling.selected_multiplier || "1"}x -> ${next.scaling.selected_multiplier || "1"}x`);
    }

    if (JSON.stringify(previous.cover_image) !== JSON.stringify(next.cover_image)) {
        detailLines.push("Recipe title image updated.");
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
        ["Reflection notes", previous.reflection_notes.length, next.reflection_notes.length],
    ].forEach(([label, beforeCount, afterCount]) => {
        if (beforeCount !== afterCount) {
            detailLines.push(`${label}: ${beforeCount} -> ${afterCount}`);
        }
    });

    if (
        previous.reflection_notes.length === next.reflection_notes.length
        && JSON.stringify(previous.reflection_notes) !== JSON.stringify(next.reflection_notes)
    ) {
        detailLines.push("Reflection notes updated.");
    }

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
        const buyAsChanged = previous.purchasable_item !== item.purchasable_item;
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
        } else if (buyAsChanged) {
            lines.push(`${name} Buy As: ${previous.purchasable_item || "(blank)"} -> ${item.purchasable_item || "(blank)"}`);
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
                <div id="recipeSaveProgressActions" class="recipe-save-progress-actions">
                    <button type="button" id="recipeSaveProgressCloseEditor" class="recipe-save-progress-action primary" onclick="closeRecipeEditorFromSaveProgress()" disabled>Close Edit Recipe</button>
                    <button type="button" class="recipe-save-progress-action secondary" onclick="hideRecipeSaveProgressOverlay()">Hide Progress</button>
                </div>
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
    setRecipeSaveProgressActionsState("running");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
}

function setRecipeSaveProgressActionsState(state) {
    const closeButton = document.getElementById("recipeSaveProgressCloseEditor");

    if (!closeButton) {
        return;
    }

    if (state === "done") {
        closeButton.disabled = false;
        closeButton.textContent = "Close Edit Recipe";
        return;
    }

    closeButton.disabled = true;
    closeButton.textContent = state === "failed"
        ? "Save Failed"
        : "Close Edit Recipe";
}

function closeRecipeEditorFromSaveProgress() {
    hideRecipeSaveProgressOverlay();
    closeRecipeEditor();
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
            cover_image: collectRecipeEditorCoverImage(),
            rating: currentRecipeRating(),
            chatgpt_feedback: recipeEditOriginalSnapshot ? recipeEditOriginalSnapshot.chatgpt_feedback || "" : "",
            chatgpt_feedback_created_at: recipeEditOriginalSnapshot ? recipeEditOriginalSnapshot.chatgpt_feedback_created_at || "" : "",
            level: document.getElementById("recipeEditLevel").value.trim(),
            total_time: document.getElementById("recipeEditTotalTime").value.trim(),
            prep_time: document.getElementById("recipeEditPrepTime").value.trim(),
            inactive_time: document.getElementById("recipeEditInactiveTime").value.trim(),
            cook_time: document.getElementById("recipeEditCookTime").value.trim(),
            scaling: collectRecipeScalingPayload(),
            ingredients: collectRecipeIngredientRows(),
            equipment: collectRecipeEquipmentRows(),
            instructions: collectRecipeInstructionRows(),
            nutrition: collectRecipeNutritionRows(),
            reflection_notes: collectRecipeReflectionNotes(),
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

function recipeEditorSourceUrlForOpen() {
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

function updateRecipeEditSourceUrlLink() {
    const sourceLink = document.getElementById("recipeEditSourceUrlLink");

    if (!sourceLink) {
        return;
    }

    const sourceUrl = recipeEditorSourceUrlForOpen();
    const canOpen = isLegitimateWebUrl(sourceUrl);

    sourceLink.href = canOpen ? sourceUrl : "#";
    sourceLink.hidden = !canOpen;
    sourceLink.setAttribute("aria-disabled", canOpen ? "false" : "true");
    sourceLink.title = canOpen ? "Open source URL" : "No web source URL";
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
            const values = fieldValuesFromRow(row);
            const textInput = row.querySelector('[data-field="text"]');
            const stepInput = row.querySelector('[data-field="step_number"]');
            const stepNumber = Math.max(1, parseFloat(stepInput ? stepInput.value : "") || index + 1);

            return {
                text: textInput ? textInput.value.trim() : "",
                stepNumber,
                originalIndex: index,
                step_image_url: values.step_image_url || "",
                step_image_generated_at: values.step_image_generated_at || "",
            };
        })
        .filter(item => item.text)
        .sort((a, b) => (a.stepNumber - b.stepNumber) || (a.originalIndex - b.originalIndex))
        .map(item => ({
            step_number: item.stepNumber,
            instruction: item.text,
            step_image_url: item.step_image_url,
            step_image_generated_at: item.step_image_generated_at,
        }));
}

function collectRecipeEquipmentRows() {
    return [...document.querySelectorAll("#recipeEditEquipment .recipe-edit-equipment-row")]
        .map(row => {
            const values = fieldValuesFromRow(row);
            const text = String(values.text || "").trim();

            return {
                equipment: text,
                text,
                equipment_image_url: values.equipment_image_url || "",
                equipment_image_generated_at: values.equipment_image_generated_at || "",
            };
        })
        .filter(item => item.equipment);
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

    if (!url) {
        return null;
    }

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
        syncRecipeQuantityInputs(url, quantity, input);
        updateRecipeQuantityDisplays(url, quantity, data);

        if (options.refresh !== false) {
            try {
                await refreshStoreMarkup({ cacheBust: options.cacheBust === true });
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

function syncRecipeQuantityInputs(recipeUrl, quantity, sourceInput = null) {
    if (!recipeUrl) {
        return;
    }

    const normalizedQuantity = String(parseRecipeScaleMultiplier(quantity) || 1);

    document.querySelectorAll(`.recipe-quantity-input[data-recipe-url="${cssEscape(recipeUrl)}"]`).forEach(input => {
        if (input !== sourceInput) {
            input.value = normalizedQuantity;
        }

        input.dataset.lastSavedValue = normalizedQuantity;
        input.classList.add("saved");

        window.setTimeout(() => {
            input.classList.remove("saved");
        }, 700);
    });
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
    const buyAsInput = document.getElementById("itemQtyBuyAsInput");
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
    const buyAs = button.dataset.buyAs || button.dataset.purchaseGroup || itemName;

    keyInput.value = button.dataset.itemKey || "";
    manualInput.value = manualQty;
    if (buyAsInput) {
        buyAsInput.value = buyAs;
    }
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
        quantityInput.dataset.manualQuantitySaveOnly = "1";
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
    const buyAsInput = document.getElementById("itemQtyBuyAsInput");

    if (!sourceButton || !currentDisplay) {
        return;
    }

    const currentQty = sourceButton.dataset.currentQty || "";
    currentDisplay.textContent = currentQty || "No recipe amount found.";
    currentDisplay.classList.toggle("muted", !currentQty);
    if (buyAsInput) {
        buyAsInput.value = sourceButton.dataset.buyAs || sourceButton.dataset.purchaseGroup || sourceButton.dataset.itemName || "";
    }
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
            const rowKey = button.dataset.rowKey || button.dataset.itemKey || "";
            const row = button.closest(".row") || (rowKey
                ? document.querySelector(`.row[data-key="${cssEscape(rowKey)}"]`)
                : null);
            const buttonScope = button.closest(".item-row-menu") || row;
            const itemKey = button.dataset.itemKey || (row ? row.dataset.key : "");
            const storeKey = button.dataset.store || "";
            const wasActive = button.classList.contains("active");
            const wasMenuButton = Boolean(button.closest(".recipe-edit-row-menu"));

            if (buttonScope) {
                buttonScope.querySelectorAll(".store-btn").forEach(scopeButton => {
                    scopeButton.classList.remove("active");
                });
            }

            if (!wasActive) {
                button.classList.add("active");
            }

            if (wasMenuButton) {
                closeRecipeEditRowMenus();
            }

            if (itemKey) {
                await saveItemStoreSelection(itemKey, wasActive ? "" : storeKey);
            }

            if (localStorage.getItem("open-store-urls") === "0") {
                return;
            }

            const itemText = row ? row.querySelector(".item-text") : null;
            const searchBaseUrl = button.dataset.storeUrl || "";
            const ingredient = button.dataset.itemName || (itemText ? itemText.textContent.trim() : "");

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
    document.querySelectorAll("#recipeView .collapsible-header").forEach(header => {
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
    bindRecipeCardToggles();

    document.querySelectorAll(".detail-toggle, .nutrition-toggle").forEach(button => {
        const parts = recipeDetailSectionParts(button);

        if (!parts.content) {
            return;
        }

        const collapsed = localStorage.getItem(parts.storageKey) !== "0";
        setRecipeDetailSectionCollapsed(button, collapsed);

        if (button.dataset.recipeDetailToggleBound === "1") {
            return;
        }

        button.dataset.recipeDetailToggleBound = "1";
        button.addEventListener("click", () => {
            toggleRecipeDetailSection(button);
        });
    });
}

function recipeDetailSectionParts(button) {
    const isNutrition = Boolean(button && button.classList.contains("nutrition-toggle"));
    const key = button
        ? (isNutrition ? button.dataset.nutritionKey : button.dataset.detailKey) || ""
        : "";
    const content = key
        ? document.querySelector(
            isNutrition
                ? `[data-nutrition-content="${cssEscape(key)}"]`
                : `[data-detail-content="${cssEscape(key)}"]`
        )
        : null;
    const header = button ? button.closest(".recipe-detail-header") : null;
    const menuToggle = header ? header.querySelector(".recipe-detail-menu-toggle") : null;

    return {
        key,
        content,
        menuToggle,
        storageKey: `${isNutrition ? "nutrition" : "detail"}-collapsed:${key}`,
    };
}

function setRecipeDetailSectionCollapsed(button, collapsed) {
    const parts = recipeDetailSectionParts(button);

    if (!parts.content) {
        return false;
    }

    parts.content.classList.toggle("collapsed", collapsed);
    button.setAttribute("aria-expanded", collapsed ? "false" : "true");

    if (parts.menuToggle) {
        parts.menuToggle.textContent = collapsed ? "Expand" : "Collapse";
    }

    return true;
}

function toggleRecipeDetailSection(button) {
    const parts = recipeDetailSectionParts(button);

    if (!parts.content) {
        return false;
    }

    const nextCollapsed = !parts.content.classList.contains("collapsed");

    setRecipeDetailSectionCollapsed(button, nextCollapsed);
    localStorage.setItem(parts.storageKey, nextCollapsed ? "1" : "0");
    closeRecipeEditRowMenus();
    return false;
}

function toggleRecipeDetailSectionFromMenu(button) {
    const header = button ? button.closest(".recipe-detail-header") : null;
    const toggle = header ? header.querySelector(".detail-toggle, .nutrition-toggle") : null;

    if (!toggle) {
        return false;
    }

    return toggleRecipeDetailSection(toggle);
}

function resetRecipeTaskCheckbox(checkbox) {
    const key = checkbox ? checkbox.dataset.taskKey || "" : "";
    const taskRow = checkbox ? checkbox.closest(".recipe-task-row") : null;
    const taskText = taskRow ? taskRow.querySelector(".recipe-task-text") : null;

    if (!checkbox) {
        return;
    }

    checkbox.checked = false;
    if (taskText) {
        taskText.classList.remove("checked-item-text");
    }
    if (key) {
        localStorage.removeItem(`recipe-task-checked:${key}`);
    }
}

function resetRecipeTaskCheckboxes(scope = document, selector = ".recipe-task-check") {
    const root = scope || document;

    root.querySelectorAll(selector).forEach(checkbox => {
        resetRecipeTaskCheckbox(checkbox);
    });
}

function resetItemCheckboxRow(row) {
    const checkbox = row ? row.querySelector(".item-check") : null;
    const itemText = row ? row.querySelector(".item-text") : null;

    if (!row) {
        return;
    }

    if (checkbox) {
        checkbox.checked = false;
    }
    row.classList.remove("row-checked");
    if (itemText) {
        itemText.classList.remove("checked-item-text");
    }
    if (row.dataset.key) {
        localStorage.removeItem(`item-checked:${row.dataset.key}`);
    }
}

function resetItemCheckboxRows(scope = document, selector = ".row[data-key]") {
    const root = scope || document;

    root.querySelectorAll(selector).forEach(row => {
        resetItemCheckboxRow(row);
    });
}

function resetRecipeDetailCheckboxesFromMenu(button) {
    const header = button ? button.closest(".recipe-detail-header") : null;
    const toggle = header ? header.querySelector(".detail-toggle") : null;
    const parts = recipeDetailSectionParts(toggle);

    if (!parts.content) {
        closeRecipeEditRowMenus();
        return false;
    }

    resetRecipeTaskCheckboxes(parts.content);
    resetItemCheckboxRows(parts.content);

    closeRecipeEditRowMenus();
    return false;
}

const RECIPE_IMAGE_PROGRESS_CHANNEL = "recipe-image-progress";
const RECIPE_IMAGE_PROGRESS_STORAGE_KEY = "recipe-image-progress-event";
let recipeImageProgressChannel = null;
let recipeImageProgressPollTimer = null;
let recipeImageProgressPollInFlight = false;
const recipeImageProgressItemsByKey = new Map();

function normalizeRecipeImageProgressKind(kind) {
    return String(kind || "").trim().toLowerCase() === "equipment" ? "equipment" : "step";
}

function normalizeRecipeImageProgressTarget(value) {
    const text = String(value || "").trim();
    const number = Number.parseFloat(text);

    return Number.isFinite(number) && Number.isInteger(number) ? String(number) : text;
}

function recipeImageProgressTarget(item, kind) {
    const normalizedKind = normalizeRecipeImageProgressKind(kind || item.kind);

    return normalizeRecipeImageProgressTarget(
        item.target ||
        (normalizedKind === "equipment" ? item.equipment_index : item.step_number)
    );
}

function recipeImageProgressKey(kind, url, target) {
    return [
        normalizeRecipeImageProgressKind(kind),
        String(url || "").trim(),
        normalizeRecipeImageProgressTarget(target),
    ].join("|");
}

function recipeImageProgressItemKey(item) {
    const kind = normalizeRecipeImageProgressKind(item.kind);
    const target = recipeImageProgressTarget(item, kind);

    return item.key || recipeImageProgressKey(kind, item.url, target);
}

function recipeImageProgressItemFromPanel(panel, kind, state, values = {}) {
    const normalizedKind = normalizeRecipeImageProgressKind(kind);
    const target = normalizedKind === "equipment"
        ? panel.dataset.equipmentIndex || ""
        : panel.dataset.stepNumber || "";
    const url = panel.dataset.recipeUrl || "";
    const item = {
        kind: normalizedKind,
        url,
        target,
        state,
        message: values.message || defaultRecipeImageProgressMessage(normalizedKind, state),
        image_url: values.image_url || values.step_image_url || values.equipment_image_url || "",
        generated_at: values.generated_at || values.step_image_generated_at || values.equipment_image_generated_at || "",
        updated_at: Date.now() / 1000,
    };

    if (normalizedKind === "equipment") {
        item.equipment_index = target;
        item.equipment_image_url = values.equipment_image_url || values.image_url || "";
        item.equipment_image_generated_at = values.equipment_image_generated_at || values.generated_at || "";
    } else {
        item.step_number = target;
        item.step_image_url = values.step_image_url || values.image_url || "";
        item.step_image_generated_at = values.step_image_generated_at || values.generated_at || "";
    }

    item.key = recipeImageProgressKey(normalizedKind, url, target);
    return item;
}

function defaultRecipeImageProgressMessage(kind, state) {
    if (state === "running") {
        return kind === "equipment"
            ? "Generating equipment image..."
            : "Generating step image...";
    }

    if (state === "failed") {
        return "Image generation failed. Please try again.";
    }

    return "";
}

function initRecipeImageProgressSync() {
    if (recipeImageProgressChannel) {
        return;
    }

    if ("BroadcastChannel" in window) {
        try {
            recipeImageProgressChannel = new BroadcastChannel(RECIPE_IMAGE_PROGRESS_CHANNEL);
            recipeImageProgressChannel.addEventListener("message", event => {
                applyRecipeImageProgressItem(event.data || {});
            });
        } catch (err) {
            recipeImageProgressChannel = null;
        }
    }

    window.addEventListener("storage", event => {
        if (event.key !== RECIPE_IMAGE_PROGRESS_STORAGE_KEY || !event.newValue) {
            return;
        }

        try {
            applyRecipeImageProgressItem(JSON.parse(event.newValue));
        } catch (err) {
            // Best effort sync between same-origin preview windows.
        }
    });

    startRecipeImageProgressPolling();
}

function publishRecipeImageProgressItem(item) {
    if (!item || !item.url) {
        return;
    }

    rememberRecipeImageProgressItem(item);

    if (recipeImageProgressChannel) {
        try {
            recipeImageProgressChannel.postMessage(item);
        } catch (err) {
            // Keep local state even if BroadcastChannel is unavailable.
        }
    }

    try {
        localStorage.setItem(
            RECIPE_IMAGE_PROGRESS_STORAGE_KEY,
            JSON.stringify({ ...item, nonce: `${Date.now()}-${Math.random()}` })
        );
    } catch (err) {
        // localStorage can be unavailable in private or restricted contexts.
    }
}

function rememberRecipeImageProgressItem(item) {
    const key = recipeImageProgressItemKey(item);

    if (key) {
        recipeImageProgressItemsByKey.set(key, item);
    }
}

function applyKnownRecipeImageProgressItems() {
    recipeImageProgressItemsByKey.forEach(item => applyRecipeImageProgressItem(item));
}

function startRecipeImageProgressPolling() {
    scheduleRecipeImageProgressPoll(300);
}

function scheduleRecipeImageProgressPoll(delay = 5000) {
    window.clearTimeout(recipeImageProgressPollTimer);
    recipeImageProgressPollTimer = window.setTimeout(pollRecipeImageProgress, delay);
}

async function pollRecipeImageProgress() {
    recipeImageProgressPollTimer = null;

    if (recipeImageProgressPollInFlight) {
        scheduleRecipeImageProgressPoll(2000);
        return;
    }

    recipeImageProgressPollInFlight = true;
    let nextDelay = 5000;

    try {
        const response = await fetch("/api/recipe_image_progress", { cache: "no-store" });
        const data = await response.json();

        if (response.ok && data && Array.isArray(data.items)) {
            data.items.forEach(item => applyRecipeImageProgressItem(item));

            if (data.active || data.items.some(item => item.state === "running")) {
                nextDelay = 1500;
            }
        }
    } catch (err) {
        nextDelay = 8000;
    } finally {
        recipeImageProgressPollInFlight = false;
        scheduleRecipeImageProgressPoll(nextDelay);
    }
}

function applyRecipeImageProgressItem(rawItem) {
    if (!rawItem || typeof rawItem !== "object") {
        return;
    }

    const kind = normalizeRecipeImageProgressKind(rawItem.kind);
    const target = recipeImageProgressTarget(rawItem, kind);
    const url = String(rawItem.url || "").trim();

    if (!url || !target) {
        return;
    }

    const item = {
        ...rawItem,
        kind,
        target,
        url,
        key: recipeImageProgressKey(kind, url, target),
    };
    rememberRecipeImageProgressItem(item);

    recipeImageProgressPanelsForItem(item).forEach(panel => {
        if (item.state === "running") {
            setRecipeImagePanelGenerating(panel, item.message || defaultRecipeImageProgressMessage(kind, "running"));
            return;
        }

        if (item.state === "done") {
            setRecipeImagePanelComplete(panel, item);
            return;
        }

        if (item.state === "failed") {
            setRecipeImagePanelFailed(panel, item.message || defaultRecipeImageProgressMessage(kind, "failed"));
        }
    });
}

function recipeImageProgressPanelsForItem(item) {
    const selector = item.kind === "equipment"
        ? "[data-equipment-image-panel]"
        : "[data-step-image-panel]";

    return [...document.querySelectorAll(selector)].filter(panel => {
        const panelTarget = item.kind === "equipment"
            ? panel.dataset.equipmentIndex || ""
            : panel.dataset.stepNumber || "";

        return String(panel.dataset.recipeUrl || "").trim() === item.url &&
            normalizeRecipeImageProgressTarget(panelTarget) === item.target;
    });
}

function recipeImagePanelGenerateButton(panel) {
    if (!panel) {
        return null;
    }

    return panel.querySelector("[data-equipment-image-generate], [data-step-image-generate]");
}

function recipeImagePanelImage(panel, kind) {
    if (!panel) {
        return null;
    }

    return kind === "equipment"
        ? panel.querySelector(".recipe-equipment-image")
        : panel.querySelector(".recipe-step-image");
}

function recipeImagePanelDownload(panel) {
    return panel ? panel.querySelector("[data-equipment-image-download], [data-step-image-download]") : null;
}

function recipeImagePanelKind(panel) {
    return panel && panel.matches("[data-equipment-image-panel]") ? "equipment" : "step";
}

function recipeImagePanelTarget(panel, kind = null) {
    if (!panel) {
        return "";
    }

    const normalizedKind = normalizeRecipeImageProgressKind(kind || recipeImagePanelKind(panel));

    return normalizedKind === "equipment"
        ? panel.dataset.equipmentIndex || ""
        : panel.dataset.stepNumber || "";
}

function recipeImagePanelStatus(panel) {
    return panel ? panel.querySelector("[data-equipment-image-status], [data-step-image-status]") : null;
}

function recipeImagePanelUploadButton(panel) {
    return panel ? panel.querySelector("[data-recipe-image-upload-button]") : null;
}

function recipeImagePanelUploadInput(panel) {
    return panel ? panel.querySelector("[data-recipe-image-upload]") : null;
}

function updateRecipeImagePanelUploadButton(panel, kind = null) {
    const uploadButton = recipeImagePanelUploadButton(panel);
    const uploadInput = recipeImagePanelUploadInput(panel);
    const image = recipeImagePanelImage(panel, kind || recipeImagePanelKind(panel));
    const hasImage = Boolean(image && String(image.getAttribute("src") || "").trim());
    const isGenerating = Boolean(panel && panel.classList.contains("generating"));

    if (uploadButton) {
        uploadButton.textContent = hasImage ? "Replace" : "Upload";
        uploadButton.disabled = isGenerating;
    }

    if (uploadInput) {
        uploadInput.disabled = isGenerating;
    }
}

function setRecipeImagePanelGenerating(panel, message) {
    const status = recipeImagePanelStatus(panel);
    const button = recipeImagePanelGenerateButton(panel);
    const uploadButton = recipeImagePanelUploadButton(panel);
    const uploadInput = recipeImagePanelUploadInput(panel);

    panel.classList.remove("recipe-image-visibility-hidden");
    panel.classList.add("generating");

    if (status) {
        status.textContent = message;
        status.classList.remove("empty");
    }

    if (button) {
        button.disabled = true;
    }

    if (uploadButton) {
        uploadButton.disabled = true;
    }

    if (uploadInput) {
        uploadInput.disabled = true;
    }
}

function setRecipeImagePanelComplete(panel, item) {
    const kind = normalizeRecipeImageProgressKind(item.kind);
    const imageUrl = item.image_url ||
        (kind === "equipment" ? item.equipment_image_url : item.step_image_url) ||
        "";
    const generatedAt = item.generated_at ||
        (kind === "equipment" ? item.equipment_image_generated_at : item.step_image_generated_at) ||
        "";
    const status = recipeImagePanelStatus(panel);
    const image = recipeImagePanelImage(panel, kind);
    const download = recipeImagePanelDownload(panel);
    const button = recipeImagePanelGenerateButton(panel);

    panel.classList.remove("generating");
    panel.classList.remove("recipe-image-visibility-hidden");

    if (imageUrl && image) {
        image.src = imageUrl;
        image.hidden = false;
    }

    if (imageUrl && download) {
        download.href = imageUrl;
        download.hidden = false;
    }

    if (kind === "equipment") {
        setRecipeImagePanelHiddenValue(panel, "equipment_image_url", imageUrl);
        setRecipeImagePanelHiddenValue(panel, "equipment_image_generated_at", generatedAt);
    } else {
        setRecipeImagePanelHiddenValue(panel, "step_image_url", imageUrl);
        setRecipeImagePanelHiddenValue(panel, "step_image_generated_at", generatedAt);
    }

    if (status) {
        status.textContent = imageUrl ? "" : "Image generated. Refresh to view it.";
        status.classList.toggle("empty", Boolean(imageUrl));
    }

    if (button) {
        button.disabled = false;
        button.textContent = "Regenerate";
    }

    updateRecipeImagePanelUploadButton(panel, kind);
    updateRecipeImagePanelRowMenu(panel);
}

function setRecipeImagePanelFailed(panel, message) {
    const status = recipeImagePanelStatus(panel);
    const button = recipeImagePanelGenerateButton(panel);
    const uploadButton = recipeImagePanelUploadButton(panel);
    const uploadInput = recipeImagePanelUploadInput(panel);

    panel.classList.remove("generating");
    panel.classList.remove("recipe-image-visibility-hidden");

    if (status) {
        status.textContent = message;
        status.classList.remove("empty");
    }

    if (button) {
        button.disabled = false;
    }

    if (uploadButton) {
        uploadButton.disabled = false;
    }

    if (uploadInput) {
        uploadInput.disabled = false;
    }

    updateRecipeImagePanelUploadButton(panel);
    updateRecipeImagePanelRowMenu(panel);
}

function updateRecipeImagePanelRowMenu(panel) {
    const row = panel
        ? panel.closest(".recipe-edit-equipment-row, .recipe-edit-instruction-row")
        : null;

    if (row) {
        updateRecipeEditRowImageMenu(row);
    }
}

function openRecipeDetailImageUpload(button) {
    const panel = button ? button.closest("[data-equipment-image-panel], [data-step-image-panel]") : null;
    const input = recipeImagePanelUploadInput(panel);

    if (input) {
        input.click();
    }

    return false;
}

async function uploadRecipeDetailImage(input) {
    const panel = input ? input.closest("[data-equipment-image-panel], [data-step-image-panel]") : null;
    const file = input && input.files ? input.files[0] : null;
    const kind = recipeImagePanelKind(panel);
    const recipeUrl = panel ? panel.dataset.recipeUrl || "" : "";
    const target = recipeImagePanelTarget(panel, kind);
    const status = recipeImagePanelStatus(panel);

    if (!file) {
        return false;
    }

    if (!panel || !recipeUrl || !target) {
        if (status) {
            status.textContent = "This image location could not be found.";
            status.classList.remove("empty");
        }
        input.value = "";
        return false;
    }

    const runningItem = recipeImageProgressItemFromPanel(panel, kind, "running", {
        message: "Uploading image...",
    });
    applyRecipeImageProgressItem(runningItem);
    publishRecipeImageProgressItem(runningItem);

    const formData = new FormData();
    formData.append("url", recipeUrl);
    formData.append("kind", kind);
    formData.append("target", target);
    formData.append(kind === "equipment" ? "equipment_index" : "step_number", target);
    formData.append("image", file);

    try {
        const response = await fetch("/api/recipe_detail_image", {
            method: "POST",
            body: formData,
        });
        let data = {};
        try {
            data = await response.json();
        } catch (err) {
            data = {};
        }

        const imageUrl = data.image_url ||
            (kind === "equipment" ? data.equipment_image_url : data.step_image_url) ||
            "";
        const generatedAt = data.generated_at ||
            (kind === "equipment" ? data.equipment_image_generated_at : data.step_image_generated_at) ||
            "";

        if (!response.ok || !data.ok || !imageUrl) {
            throw new Error((data && data.error) || "Unable to upload this image.");
        }

        const doneItem = recipeImageProgressItemFromPanel(panel, kind, "done", {
            image_url: imageUrl,
            generated_at: generatedAt,
            equipment_image_url: kind === "equipment" ? imageUrl : "",
            equipment_image_generated_at: kind === "equipment" ? generatedAt : "",
            step_image_url: kind === "step" ? imageUrl : "",
            step_image_generated_at: kind === "step" ? generatedAt : "",
        });
        applyRecipeImageProgressItem(doneItem);
        publishRecipeImageProgressItem(doneItem);
        showRecipeQuantityUpdatedMessage("", "", "", "Recipe image updated.");
    } catch (err) {
        const failedItem = recipeImageProgressItemFromPanel(panel, kind, "failed", {
            message: err.message || "Unable to upload this image.",
        });
        applyRecipeImageProgressItem(failedItem);
        publishRecipeImageProgressItem(failedItem);
    } finally {
        if (input) {
            input.value = "";
        }
    }

    return false;
}

async function generateRecipeStepImage(button) {
    const panel = button ? button.closest("[data-step-image-panel]") : null;
    const status = panel ? panel.querySelector("[data-step-image-status]") : null;
    const recipeUrl = panel ? panel.dataset.recipeUrl || "" : "";
    const stepNumber = panel ? panel.dataset.stepNumber || "" : "";
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 120000);

    if (!panel || !button || !recipeUrl || !stepNumber) {
        if (status) {
            status.textContent = "This instruction step could not be found.";
            status.classList.remove("empty");
        }
        return false;
    }

    const runningItem = recipeImageProgressItemFromPanel(panel, "step", "running", {
        message: "Generating step image...",
    });
    applyRecipeImageProgressItem(runningItem);
    publishRecipeImageProgressItem(runningItem);

    try {
        const response = await fetch("/api/recipe_step_image", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url: recipeUrl,
                step_number: stepNumber,
            }),
            signal: controller.signal,
        });
        let data = {};
        try {
            data = await response.json();
        } catch (err) {
            data = {};
        }

        if (!response.ok || !data.ok || !data.step_image_url) {
            throw new Error((data && data.error) || "Unable to generate this step image.");
        }

        const doneItem = recipeImageProgressItemFromPanel(panel, "step", "done", {
            step_image_url: data.step_image_url,
            step_image_generated_at: data.step_image_generated_at || "",
            image_url: data.step_image_url,
            generated_at: data.step_image_generated_at || "",
        });
        applyRecipeImageProgressItem(doneItem);
        publishRecipeImageProgressItem(doneItem);
    } catch (err) {
        const timedOut = err && err.name === "AbortError";
        const message = timedOut
            ? "Image generation timed out. Please try again."
            : (err.message || "Image generation failed. Please try again.");
        const failedItem = recipeImageProgressItemFromPanel(panel, "step", "failed", { message });
        applyRecipeImageProgressItem(failedItem);
        publishRecipeImageProgressItem(failedItem);
    } finally {
        window.clearTimeout(timeout);
        panel.classList.remove("generating");
        button.disabled = false;
    }

    return false;
}

async function generateRecipeEquipmentImage(button) {
    const panel = button ? button.closest("[data-equipment-image-panel]") : null;
    const status = panel ? panel.querySelector("[data-equipment-image-status]") : null;
    const recipeUrl = panel ? panel.dataset.recipeUrl || "" : "";
    const equipmentIndex = panel ? panel.dataset.equipmentIndex || "" : "";
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 120000);

    if (!panel || !button || !recipeUrl || !equipmentIndex) {
        if (status) {
            status.textContent = "This equipment item could not be found.";
            status.classList.remove("empty");
        }
        return false;
    }

    const runningItem = recipeImageProgressItemFromPanel(panel, "equipment", "running", {
        message: "Generating equipment image...",
    });
    applyRecipeImageProgressItem(runningItem);
    publishRecipeImageProgressItem(runningItem);

    try {
        const response = await fetch("/api/recipe_equipment_image", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url: recipeUrl,
                equipment_index: equipmentIndex,
            }),
            signal: controller.signal,
        });
        let data = {};
        try {
            data = await response.json();
        } catch (err) {
            data = {};
        }

        if (!response.ok || !data.ok || !data.equipment_image_url) {
            throw new Error((data && data.error) || "Unable to generate this equipment image.");
        }

        const doneItem = recipeImageProgressItemFromPanel(panel, "equipment", "done", {
            equipment_image_url: data.equipment_image_url,
            equipment_image_generated_at: data.equipment_image_generated_at || "",
            image_url: data.equipment_image_url,
            generated_at: data.equipment_image_generated_at || "",
        });
        applyRecipeImageProgressItem(doneItem);
        publishRecipeImageProgressItem(doneItem);
    } catch (err) {
        const timedOut = err && err.name === "AbortError";
        const message = timedOut
            ? "Image generation timed out. Please try again."
            : (err.message || "Image generation failed. Please try again.");
        const failedItem = recipeImageProgressItemFromPanel(panel, "equipment", "failed", { message });
        applyRecipeImageProgressItem(failedItem);
        publishRecipeImageProgressItem(failedItem);
    } finally {
        window.clearTimeout(timeout);
        panel.classList.remove("generating");
        button.disabled = false;
    }

    return false;
}

function setRecipeImagePanelHiddenValue(panel, field, value) {
    const input = panel ? panel.querySelector(`[data-field="${field}"]`) : null;

    if (input) {
        input.value = value || "";
    }
}

async function generateRecipeEditRowImageFromMenu(button) {
    const row = recipeEditActionRowFromButton(button);
    const imageButton = row
        ? row.querySelector("[data-equipment-image-generate], [data-step-image-generate]")
        : null;

    closeRecipeEditRowMenus();

    if (!imageButton) {
        return false;
    }

    setRecipeEditRowImageVisible(row, true);

    if (imageButton.matches("[data-equipment-image-generate]")) {
        await generateRecipeEquipmentImage(imageButton);
    } else {
        await generateRecipeStepImage(imageButton);
    }

    return false;
}

async function generateRecipeImagesFromEditor(button, options = {}) {
    const modal = document.getElementById("recipeEditModal");
    const allButtons = [...document.querySelectorAll("[data-recipe-editor-image-global-btn]")];
    const originalLabel = button ? button.textContent : "";

    closeRecipeEditRowMenus();

    if (!modal || !modal.classList.contains("open")) {
        return false;
    }

    setRecipeImageContainersVisible(
        modal.querySelectorAll(recipeEditorImagePanelSelector(options)),
        true
    );

    allButtons.forEach(globalButton => {
        globalButton.disabled = true;
    });

    if (button) {
        button.textContent = options.missingOnly ? "Generating Missing..." : "Generating Images...";
    }

    try {
        await generateRecipeImagesInCard(modal, options);
    } finally {
        allButtons.forEach(globalButton => {
            globalButton.disabled = false;
        });

        if (button) {
            button.textContent = originalLabel;
        }
    }

    return false;
}

function setRecipeEditorImagesVisibleFromMenu(button, visible, options = {}) {
    const modal = document.getElementById("recipeEditModal");

    closeRecipeEditRowMenus();

    if (!modal || !modal.classList.contains("open")) {
        return false;
    }

    setRecipeImageContainersVisible(
        modal.querySelectorAll(recipeEditorImagePanelSelector(options)),
        visible
    );

    return false;
}

function recipeEditorImagePanelSelector(options = {}) {
    const scope = options.imageScope || options.scope || "all";

    if (scope === "equipment") {
        return "[data-equipment-image-panel]";
    }

    if (scope === "instructions") {
        return "[data-step-image-panel]";
    }

    return "[data-recipe-edit-title-image-panel], [data-equipment-image-panel], [data-step-image-panel]";
}

function setRecipeEditRowImageVisibleFromMenu(button, visible) {
    const row = recipeEditActionRowFromButton(button);

    closeRecipeEditRowMenus();
    setRecipeEditRowImageVisible(row, visible);
    return false;
}

function setRecipeEditRowImageVisible(row, visible) {
    const panel = row
        ? row.querySelector("[data-equipment-image-panel], [data-step-image-panel]")
        : null;

    if (!panel) {
        return false;
    }

    setRecipeImageContainersVisible([panel], visible);
    updateRecipeEditRowImageMenu(row);
    return true;
}

function updateRecipeEditRowImageMenu(row) {
    const panel = row
        ? row.querySelector("[data-equipment-image-panel], [data-step-image-panel]")
        : null;
    const generateButton = row ? row.querySelector("[data-recipe-edit-row-image-generate]") : null;
    const showButton = row ? row.querySelector("[data-recipe-edit-row-image-show]") : null;
    const hideButton = row ? row.querySelector("[data-recipe-edit-row-image-hide]") : null;
    const image = panel ? panel.querySelector(".recipe-step-image") : null;
    const hasImage = Boolean(image && !image.hidden && String(image.getAttribute("src") || "").trim());
    const isHidden = Boolean(panel && panel.classList.contains("recipe-image-visibility-hidden"));

    if (generateButton) {
        if (row && row.classList.contains("recipe-edit-equipment-row")) {
            generateButton.textContent = hasImage ? "Regenerate equipment image" : "Generate equipment image";
        } else {
            generateButton.textContent = hasImage ? "Regenerate step image" : "Generate step image";
        }
        generateButton.disabled = !panel;
    }

    if (showButton) {
        showButton.textContent = row && row.classList.contains("recipe-edit-equipment-row")
            ? "Show equipment image"
            : "Show step image";
        showButton.hidden = !panel || !isHidden;
    }

    if (hideButton) {
        hideButton.textContent = row && row.classList.contains("recipe-edit-equipment-row")
            ? "Hide equipment image"
            : "Hide step image";
        hideButton.hidden = !panel || isHidden;
    }
}

async function generateAllRecipeInstructionImagesFromMenu(button, options = {}) {
    const header = button ? button.closest(".recipe-detail-header") : null;
    const toggle = header ? header.querySelector(".detail-toggle") : null;
    const parts = recipeDetailSectionParts(toggle);

    if (!parts.content) {
        closeRecipeEditRowMenus();
        return false;
    }

    const stepButtons = [...parts.content.querySelectorAll("[data-step-image-generate]")]
        .filter(stepButton => !options.missingOnly || recipeStepImageIsMissing(stepButton));

    closeRecipeEditRowMenus();

    if (!stepButtons.length) {
        return false;
    }

    if (toggle) {
        setRecipeDetailSectionCollapsed(toggle, false);
        localStorage.setItem(parts.storageKey, "0");
    }

    const firstPanel = stepButtons[0].closest("[data-step-image-panel]");
    if (firstPanel) {
        firstPanel.scrollIntoView({
            behavior: "smooth",
            block: "center",
            inline: "nearest",
        });
    }

    for (const stepButton of stepButtons) {
        if (stepButton.disabled) {
            continue;
        }

        await generateRecipeStepImage(stepButton);
    }

    return false;
}

async function generateAllRecipeEquipmentImagesFromMenu(button, options = {}) {
    const header = button ? button.closest(".recipe-detail-header") : null;
    const toggle = header ? header.querySelector(".detail-toggle") : null;
    const parts = recipeDetailSectionParts(toggle);

    if (!parts.content) {
        closeRecipeEditRowMenus();
        return false;
    }

    const equipmentButtons = [...parts.content.querySelectorAll("[data-equipment-image-generate]")]
        .filter(equipmentButton => !options.missingOnly || recipeEquipmentImageIsMissing(equipmentButton));

    closeRecipeEditRowMenus();

    if (!equipmentButtons.length) {
        return false;
    }

    if (toggle) {
        setRecipeDetailSectionCollapsed(toggle, false);
        localStorage.setItem(parts.storageKey, "0");
    }

    const firstPanel = equipmentButtons[0].closest("[data-equipment-image-panel]");
    if (firstPanel) {
        firstPanel.scrollIntoView({
            behavior: "smooth",
            block: "center",
            inline: "nearest",
        });
    }

    for (const equipmentButton of equipmentButtons) {
        if (equipmentButton.disabled) {
            continue;
        }

        await generateRecipeEquipmentImage(equipmentButton);
    }

    return false;
}

function recipeStepImageIsMissing(button) {
    const panel = button ? button.closest("[data-step-image-panel]") : null;
    const image = panel ? panel.querySelector(".recipe-step-image") : null;
    const src = image ? String(image.getAttribute("src") || "").trim() : "";

    return !src || image.hidden;
}

function recipeEquipmentImageIsMissing(button) {
    const panel = button ? button.closest("[data-equipment-image-panel]") : null;
    const image = panel ? panel.querySelector(".recipe-equipment-image") : null;
    const src = image ? String(image.getAttribute("src") || "").trim() : "";

    return !src || image.hidden;
}

async function generateRecipeImagesFromMenu(button, options = {}) {
    const card = recipeEditActionRowFromButton(button);

    closeRecipeEditRowMenus();

    if (!card) {
        return false;
    }

    await generateRecipeImagesInCard(card, options);
    return false;
}

async function generateAllRecipeImagesFromViewBehavior(button, options = {}) {
    const allButtons = [...document.querySelectorAll("[data-recipe-image-global-btn]")];
    const originalLabel = button ? button.textContent : "";

    if (typeof showView === "function") {
        showView("recipe");
    }

    closeRecipeEditRowMenus();

    allButtons.forEach(globalButton => {
        globalButton.disabled = true;
    });

    if (button) {
        button.textContent = options.missingOnly ? "Generating Missing..." : "Generating Images...";
    }

    try {
        const cards = [...document.querySelectorAll("[data-recipe-view-card]")];

        for (const card of cards) {
            await generateRecipeImagesInCard(card, options);
        }
    } finally {
        allButtons.forEach(globalButton => {
            globalButton.disabled = false;
        });

        if (button) {
            button.textContent = originalLabel;
        }
    }

    return false;
}

async function generateRecipeImagesInCard(card, options = {}) {
    if (!card) {
        return false;
    }

    expandRecipeCardForImageGeneration(card);

    const buttons = recipeImageGenerateButtons(card, options);

    if (!buttons.length) {
        return false;
    }

    const firstPanel = buttons[0].closest("[data-equipment-image-panel], [data-step-image-panel]");
    if (firstPanel) {
        firstPanel.scrollIntoView({
            behavior: "smooth",
            block: "center",
            inline: "nearest",
        });
    }

    for (const imageButton of buttons) {
        if (imageButton.disabled) {
            continue;
        }

        if (imageButton.matches("[data-equipment-image-generate]")) {
            await generateRecipeEquipmentImage(imageButton);
        } else {
            await generateRecipeStepImage(imageButton);
        }
    }

    return false;
}

function recipeImageGenerateButtons(card, options = {}) {
    const scope = options.imageScope || options.scope || "all";

    return [...card.querySelectorAll("[data-equipment-image-generate], [data-step-image-generate]")]
        .filter(imageButton => {
            if (scope === "equipment" && !imageButton.matches("[data-equipment-image-generate]")) {
                return false;
            }

            if (scope === "instructions" && !imageButton.matches("[data-step-image-generate]")) {
                return false;
            }

            if (!options.missingOnly) {
                return true;
            }

            if (imageButton.matches("[data-equipment-image-generate]")) {
                return recipeEquipmentImageIsMissing(imageButton);
            }

            return recipeStepImageIsMissing(imageButton);
        });
}

function expandRecipeCardForImageGeneration(card) {
    if (!card) {
        return;
    }

    const toggle = card.querySelector("[data-recipe-card-toggle]");
    const key = card.dataset.recipeCardKey || (toggle ? toggle.dataset.recipeCardKey : "");

    if (card.classList.contains("recipe-view-collapsed")) {
        setRecipeCardCollapsed(card, toggle, false, { animate: true });

        if (key) {
            localStorage.setItem(`recipe-card-collapsed:${key}`, "0");
        }
    }

    card.querySelectorAll(".detail-toggle").forEach(detailToggle => {
        const detailKey = detailToggle.dataset.detailKey || "";

        if (!detailKey.startsWith("equipment|") && !detailKey.startsWith("instructions|")) {
            return;
        }

        const parts = recipeDetailSectionParts(detailToggle);
        setRecipeDetailSectionCollapsed(detailToggle, false);

        if (parts.storageKey) {
            localStorage.setItem(parts.storageKey, "0");
        }
    });
}

function setRecipeImagesVisibleFromMenu(button, visible) {
    const card = recipeEditActionRowFromButton(button);

    closeRecipeEditRowMenus();

    if (!card) {
        return false;
    }

    if (visible) {
        expandRecipeCardForImageGeneration(card);
    }

    setRecipeImageContainersVisible(recipeImageContainersForCard(card), visible);
    return false;
}

function setAllRecipeImagesVisibleFromMenu(button, visible) {
    if (typeof showView === "function") {
        showView("recipe");
    }

    closeRecipeEditRowMenus();

    document.querySelectorAll("[data-recipe-view-card]").forEach(card => {
        if (visible) {
            expandRecipeCardForImageGeneration(card);
        }

        setRecipeImageContainersVisible(recipeImageContainersForCard(card), visible);
    });

    return false;
}

function setRecipeDetailImagesVisibleFromMenu(button, visible) {
    const header = recipeDetailHeaderFromMenuButton(button);
    const toggle = header ? header.querySelector(".detail-toggle") : null;
    const parts = recipeDetailSectionParts(toggle);

    closeRecipeEditRowMenus();

    if (!parts.content) {
        return false;
    }

    if (visible && toggle) {
        setRecipeDetailSectionCollapsed(toggle, false);
        localStorage.setItem(parts.storageKey, "0");
    }

    setRecipeImageContainersVisible(parts.content.querySelectorAll("[data-equipment-image-panel], [data-step-image-panel]"), visible);
    return false;
}

function setRecipeImageContainersVisible(containers, visible) {
    [...containers].forEach(container => {
        container.classList.toggle("recipe-image-visibility-hidden", !visible);
        container.setAttribute("aria-hidden", visible ? "false" : "true");

        if (container.classList.contains("recipe-view-title-media") || container.classList.contains("recipe-view-body-media")) {
            container.classList.remove("recipe-image-visibility-hidden");
            container.setAttribute("aria-hidden", "false");
            container.querySelectorAll(".recipe-cover-image").forEach(image => {
                image.classList.remove("recipe-image-visibility-hidden");
                image.setAttribute("aria-hidden", "false");
            });
        }
    });
}

function recipeImagesShownByDefault() {
    const savedValue = localStorage.getItem("show-images-by-default");
    return savedValue === null ? true : savedValue === "1";
}

function applyRecipeImageDefaultVisibility(scope = document) {
    if (!scope || !scope.querySelectorAll) {
        return;
    }

    setRecipeImageContainersVisible(
        scope.querySelectorAll("[data-equipment-image-panel], [data-step-image-panel]"),
        recipeImagesShownByDefault()
    );
    keepRecipeCoverImagesVisible(scope);
}

function recipeImageContainersForCard(card) {
    return card
        ? card.querySelectorAll("[data-equipment-image-panel], [data-step-image-panel]")
        : [];
}

function keepRecipeCoverImagesVisible(scope = document) {
    if (!scope || !scope.querySelectorAll) {
        return;
    }

    scope.querySelectorAll(".recipe-view-title-media, .recipe-view-body-media, .recipe-cover-image").forEach(element => {
        element.classList.remove("recipe-image-visibility-hidden");
        element.setAttribute("aria-hidden", "false");
    });
}

function updateRecipeDetailMenuToggleForButton(button) {
    const header = recipeDetailHeaderFromMenuButton(button);
    const toggle = header ? header.querySelector(".detail-toggle, .nutrition-toggle") : null;
    const parts = recipeDetailSectionParts(toggle);

    if (parts.content && parts.menuToggle) {
        parts.menuToggle.textContent = parts.content.classList.contains("collapsed") ? "Expand" : "Collapse";
    }
}

function bindRecipeCardToggles() {
    document.querySelectorAll("[data-recipe-view-card]").forEach(card => {
        const toggle = card.querySelector("[data-recipe-card-toggle]");
        const key = card.dataset.recipeCardKey || (toggle ? toggle.dataset.recipeCardKey : "");

        if (!card || !key || card.dataset.recipeCardToggleBound === "1") {
            return;
        }

        card.dataset.recipeCardToggleBound = "1";
        const collapsed = localStorage.getItem(`recipe-card-collapsed:${key}`) === "1";
        setRecipeCardCollapsed(card, toggle, collapsed);

        if (toggle) {
            toggle.addEventListener("click", () => {
                const shouldCollapse = !card.classList.contains("recipe-view-collapsed");
                setRecipeCardCollapsed(card, toggle, shouldCollapse, { animate: true });
                localStorage.setItem(`recipe-card-collapsed:${key}`, shouldCollapse ? "1" : "0");
            });
        }
    });
}

function toggleRecipeViewCardFromMenu(button) {
    const card = recipeEditActionRowFromButton(button);
    const toggle = card ? card.querySelector("[data-recipe-card-toggle]") : null;
    const key = card ? (card.dataset.recipeCardKey || (toggle ? toggle.dataset.recipeCardKey : "")) : "";

    if (!card || !key) {
        return false;
    }

    const shouldCollapse = !card.classList.contains("recipe-view-collapsed");
    setRecipeCardCollapsed(card, toggle, shouldCollapse, { animate: true });
    localStorage.setItem(`recipe-card-collapsed:${key}`, shouldCollapse ? "1" : "0");
    updateRecipeViewCardCollapseMenuToggle(card);
    closeRecipeEditRowMenus();
    card.scrollIntoView({
        behavior: "auto",
        block: "nearest",
        inline: "nearest",
    });
    return false;
}

function setRecipeViewCardEverythingCollapsed(button, collapsed) {
    const card = recipeEditActionRowFromButton(button);
    const toggle = card ? card.querySelector("[data-recipe-card-toggle]") : null;
    const key = card ? (card.dataset.recipeCardKey || (toggle ? toggle.dataset.recipeCardKey : "")) : "";

    if (!card || !key) {
        closeRecipeEditRowMenus();
        return false;
    }

    if (!collapsed) {
        setRecipeCardCollapsed(card, toggle, false, { animate: true });
        localStorage.setItem(`recipe-card-collapsed:${key}`, "0");
    }

    card.querySelectorAll(".detail-toggle, .nutrition-toggle").forEach(detailToggle => {
        const parts = recipeDetailSectionParts(detailToggle);

        if (!parts.content) {
            return;
        }

        setRecipeDetailSectionCollapsed(detailToggle, collapsed);
        localStorage.setItem(parts.storageKey, collapsed ? "1" : "0");
    });

    card.querySelectorAll('.collapsible-header[data-collapse-scope="recipe-section"]').forEach(header => {
        const title = header.querySelector(".header-title");
        const collapseKey = header.dataset.collapseKey || (title ? normalizeSectionKey(title.textContent) : "");
        const icon = header.querySelector(".header-toggle-icon");

        setSectionCollapsed(header, icon, collapsed);

        if (collapseKey) {
            localStorage.setItem(`section-collapsed:${collapseKey}`, collapsed ? "1" : "0");
        }
    });

    if (collapsed) {
        setRecipeCardCollapsed(card, toggle, true, { animate: true });
        localStorage.setItem(`recipe-card-collapsed:${key}`, "1");
    }

    closeRecipeEditRowMenus();
    card.scrollIntoView({
        behavior: "auto",
        block: "nearest",
        inline: "nearest",
    });
    return false;
}

function setAllRecipeViewCardsCollapsed(collapsed) {
    document.querySelectorAll("[data-recipe-view-card]").forEach(card => {
        const toggle = card.querySelector("[data-recipe-card-toggle]");
        const key = card.dataset.recipeCardKey || (toggle ? toggle.dataset.recipeCardKey : "");

        setRecipeCardCollapsed(card, toggle, collapsed, { animate: true });

        if (key) {
            localStorage.setItem(`recipe-card-collapsed:${key}`, collapsed ? "1" : "0");
        }
    });

    closeRecipeEditRowMenus();
    return false;
}

function setAllRecipeViewEverythingCollapsed(collapsed) {
    if (typeof showView === "function") {
        showView("recipe");
    }

    document.querySelectorAll("[data-recipe-view-card]").forEach(card => {
        const toggle = card.querySelector("[data-recipe-card-toggle]");
        const key = card.dataset.recipeCardKey || (toggle ? toggle.dataset.recipeCardKey : "");

        if (!collapsed) {
            setRecipeCardCollapsed(card, toggle, false, { animate: true });

            if (key) {
                localStorage.setItem(`recipe-card-collapsed:${key}`, "0");
            }
        }

        card.querySelectorAll(".detail-toggle, .nutrition-toggle").forEach(detailToggle => {
            const parts = recipeDetailSectionParts(detailToggle);

            if (!parts.content) {
                return;
            }

            setRecipeDetailSectionCollapsed(detailToggle, collapsed);
            localStorage.setItem(parts.storageKey, collapsed ? "1" : "0");
        });

        card.querySelectorAll('.collapsible-header[data-collapse-scope="recipe-section"]').forEach(header => {
            const title = header.querySelector(".header-title");
            const collapseKey = header.dataset.collapseKey || (title ? normalizeSectionKey(title.textContent) : "");
            const icon = header.querySelector(".header-toggle-icon");

            setSectionCollapsed(header, icon, collapsed);

            if (collapseKey) {
                localStorage.setItem(`section-collapsed:${collapseKey}`, collapsed ? "1" : "0");
            }
        });

        if (collapsed) {
            setRecipeCardCollapsed(card, toggle, true, { animate: true });

            if (key) {
                localStorage.setItem(`recipe-card-collapsed:${key}`, "1");
            }
        }
    });

    closeRecipeEditRowMenus();
    return false;
}

function toggleRecipeViewCardFromTitle(button, event = null) {
    if (eventStartedInNestedInteractive(event, button)) {
        return true;
    }

    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const card = button ? button.closest("[data-recipe-view-card]") : null;
    const toggle = card ? card.querySelector("[data-recipe-card-toggle]") : null;
    const key = card ? (card.dataset.recipeCardKey || button.dataset.recipeCardKey || "") : "";

    if (!card || !key) {
        return false;
    }

    const shouldCollapse = !card.classList.contains("recipe-view-collapsed");

    setRecipeCardCollapsed(card, toggle, shouldCollapse, { animate: true });
    localStorage.setItem(`recipe-card-collapsed:${key}`, shouldCollapse ? "1" : "0");
    closeRecipeEditRowMenus();
    return false;
}

function handleRecipeViewCardTitleKeydown(button, event) {
    if (!event || (event.key !== "Enter" && event.key !== " ")) {
        return true;
    }

    return toggleRecipeViewCardFromTitle(button, event);
}

function setRecipeCardCollapsed(card, button, collapsed, options = {}) {
    const wasCollapsed = card.classList.contains("recipe-view-collapsed");
    card.classList.toggle("recipe-view-collapsed", collapsed);
    keepRecipeCoverImagesVisible(card);

    if (button) {
        button.setAttribute("aria-expanded", collapsed ? "false" : "true");
        button.textContent = collapsed ? "Show v" : "Hide ^";
    }
    const titleToggle = card.querySelector("[data-recipe-card-title-toggle]");
    if (titleToggle) {
        titleToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    updateRecipeViewCardCollapseMenuToggle(card);

    if (options && options.animate && wasCollapsed !== collapsed) {
        pulseRecipeViewCard(card);
    }
}

function pulseRecipeViewCard(card) {
    if (!card) {
        return;
    }

    card.classList.remove("recipe-view-state-pulse");
    void card.offsetWidth;
    card.classList.add("recipe-view-state-pulse");

    window.setTimeout(() => {
        card.classList.remove("recipe-view-state-pulse");
    }, 1000);
}

function bindRecipeTaskChecks() {
    document.querySelectorAll(".recipe-task-check").forEach(checkbox => {
        const key = checkbox.dataset.taskKey;
        const taskRow = checkbox.closest(".recipe-task-row");
        const text = taskRow ? taskRow.querySelector(".recipe-task-text") : null;

        checkbox.checked = localStorage.getItem(`recipe-task-checked:${key}`) === "1";
        syncRecipeTaskCheckedState(checkbox, text);

        if (checkbox.dataset.recipeTaskCheckBound !== "1") {
            checkbox.dataset.recipeTaskCheckBound = "1";
            checkbox.addEventListener("change", () => {
                saveRecipeTaskCheckedState(checkbox, text, key);
            });
        }

        if (text && text.dataset.recipeTaskTextToggleBound !== "1") {
            text.dataset.recipeTaskTextToggleBound = "1";
            text.tabIndex = 0;
            text.setAttribute("role", "button");
            text.setAttribute("aria-label", `Toggle ${text.textContent.trim()}`);
            text.addEventListener("click", () => {
                toggleRecipeTaskCheckbox(checkbox, text, key);
            });
            text.addEventListener("keydown", event => {
                if (event.key !== "Enter" && event.key !== " ") {
                    return;
                }

                event.preventDefault();
                toggleRecipeTaskCheckbox(checkbox, text, key);
            });
        }
    });
}

function syncRecipeTaskCheckedState(checkbox, text) {
    if (text) {
        text.classList.toggle("checked-item-text", checkbox.checked);
        text.setAttribute("aria-pressed", checkbox.checked ? "true" : "false");
    }
}

function saveRecipeTaskCheckedState(checkbox, text, key) {
    localStorage.setItem(`recipe-task-checked:${key}`, checkbox.checked ? "1" : "0");
    syncRecipeTaskCheckedState(checkbox, text);
}

function toggleRecipeTaskCheckbox(checkbox, text, key) {
    if (!checkbox) {
        return;
    }

    checkbox.checked = !checkbox.checked;
    saveRecipeTaskCheckedState(checkbox, text, key);
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
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
    if (event && typeof event.preventDefault === "function") {
        event.preventDefault();
    }

    resetItemCheckboxRows();
    resetRecipeTaskCheckboxes();

    return false;
}

function resetAllCheckboxesFromRecipeViewMenu(button) {
    resetItemChecks();
    closeRecipeEditRowMenus();
    return false;
}

function resetRecipeViewCheckboxesFromMenu(button, scope) {
    if (scope === "equipment") {
        resetRecipeTaskCheckboxes(document, '.recipe-task-check[data-task-key^="equipment|"]');
    } else if (scope === "instructions") {
        resetRecipeTaskCheckboxes(document, '.recipe-task-check[data-task-key^="instruction|"]');
    } else if (scope === "ingredients") {
        resetItemCheckboxRows();
    }

    closeRecipeEditRowMenus();
    return false;
}

async function resetStoresFromRecipeViewMenu(button) {
    const originalDisabled = button ? button.disabled : false;
    let form = document.querySelector('form[action="/reset_stores"]');

    if (!form) {
        form = document.createElement("form");
        form.method = "POST";
        form.action = "/reset_stores";
    }

    if (button) {
        button.disabled = true;
    }

    try {
        await resetStores({
            currentTarget: form,
            preventDefault() {},
        });
    } finally {
        if (button) {
            button.disabled = originalDisabled;
        }
        closeRecipeEditRowMenus();
    }

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

        if (data && data.home_address_history) {
            updateHomeAddressHistory(data.home_address_history);
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
        updateHomeAddressHistory(data.home_address_history || []);
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

function useHomeAddressHistoryEntry(button) {
    const form = document.getElementById("homeAddressForm");

    if (!form || !button) {
        return false;
    }

    setHomeAddressField(form, "address_label", button.dataset.addressLabel || "");
    setHomeAddressField(form, "address_street", button.dataset.addressStreet || "");
    setHomeAddressField(form, "address_apartment", button.dataset.addressApartment || "");
    setHomeAddressField(form, "address_city", button.dataset.addressCity || "");
    setHomeAddressField(form, "address_county", button.dataset.addressCounty || "");
    setHomeAddressField(form, "address_state", button.dataset.addressState || "");
    setHomeAddressField(form, "address_zip", button.dataset.addressZip || "");
    setHomeAddressField(form, "address_country", button.dataset.addressCountry || "");
    updateHomeAddressSummaries(buildAddressSummaryFromForm(form));

    const saveButton = form.querySelector('button[name="action"][value="save"]');

    if (saveButton && typeof saveButton.focus === "function") {
        saveButton.focus({ preventScroll: true });
    }

    return false;
}

function updateHomeAddressHistory(history) {
    const list = document.querySelector("[data-home-address-history-list]");
    const empty = document.querySelector("[data-home-address-history-empty]");
    const count = document.querySelector("[data-home-address-history-count]");

    if (!list || !Array.isArray(history)) {
        return;
    }

    list.replaceChildren(...history.map(createHomeAddressHistoryItem));

    if (empty) {
        empty.hidden = history.length > 0;
    }

    if (count) {
        count.textContent = `${history.length} saved`;
    }

    restoreHomeAddressHistoryCollapseState();
}

function createHomeAddressHistoryItem(entry) {
    const item = document.createElement("li");
    const address = String((entry && entry.full_address) || "").trim();
    const copy = document.createElement("div");
    const time = document.createElement("span");
    const link = document.createElement("a");
    const titleRow = document.createElement("div");
    const titleLabel = document.createElement("label");
    const titleText = document.createElement("span");
    const titleInput = document.createElement("input");
    const titleButton = document.createElement("button");
    const actions = document.createElement("div");
    const useButton = document.createElement("button");
    const removeButton = document.createElement("button");
    const status = document.createElement("div");

    item.className = "home-address-history-item";
    item.dataset.homeAddressHistoryId = (entry && entry.id) || "";
    copy.className = "home-address-history-copy";
    time.className = "home-address-history-time";
    time.textContent = (entry && (entry.saved_at_display || entry.saved_at)) || "Saved";

    link.className = "home-address-history-address home-address-map-link";
    link.textContent = address;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = "Open saved address in Maps";
    link.onclick = event => openStoreAddressMap(link, event);
    updateHomeAddressMapLink(link, address);

    titleRow.className = "home-address-history-title-row";
    titleText.textContent = "Title";
    titleInput.type = "text";
    titleInput.className = "home-address-history-title-input";
    titleInput.value = (entry && entry.label) || "";
    titleInput.placeholder = "Home";
    titleLabel.append(titleText, titleInput);

    titleButton.type = "button";
    titleButton.className = "home-address-history-title-btn";
    titleButton.textContent = "Save Title";
    titleButton.dataset.homeAddressHistoryId = (entry && entry.id) || "";
    titleButton.onclick = () => saveHomeAddressHistoryTitle(titleButton);
    titleRow.append(titleLabel, titleButton);

    actions.className = "home-address-history-actions";

    useButton.type = "button";
    useButton.className = "home-address-history-use-btn";
    useButton.textContent = "Use";
    useButton.dataset.addressLabel = (entry && entry.label) || "";
    useButton.dataset.addressStreet = (entry && entry.street) || "";
    useButton.dataset.addressApartment = (entry && entry.apartment) || "";
    useButton.dataset.addressCity = (entry && entry.city) || "";
    useButton.dataset.addressCounty = (entry && entry.county) || "";
    useButton.dataset.addressState = (entry && entry.state) || "";
    useButton.dataset.addressZip = (entry && entry.zip) || "";
    useButton.dataset.addressCountry = (entry && entry.country) || "";
    useButton.onclick = () => useHomeAddressHistoryEntry(useButton);

    removeButton.type = "button";
    removeButton.className = "home-address-history-remove-btn";
    removeButton.textContent = "Remove";
    removeButton.dataset.homeAddressHistoryId = (entry && entry.id) || "";
    removeButton.onclick = () => removeHomeAddressHistoryEntry(removeButton);
    actions.append(useButton, removeButton);

    status.className = "home-address-history-status";
    status.setAttribute("aria-live", "polite");

    copy.append(time, link);
    item.append(copy, titleRow, actions, status);
    return item;
}

function toggleHomeAddressHistoryCollapse(button) {
    const expanded = button ? button.getAttribute("aria-expanded") === "true" : true;
    setHomeAddressHistoryCollapsed(expanded);
    return false;
}

function restoreHomeAddressHistoryCollapseState() {
    const saved = localStorage.getItem("home-address-history-collapsed");
    setHomeAddressHistoryCollapsed(saved === "1");
}

function setHomeAddressHistoryCollapsed(collapsed) {
    const toggle = document.querySelector("[data-home-address-history-toggle]");
    const body = document.querySelector("[data-home-address-history-body]");

    if (!toggle || !body) {
        return;
    }

    body.classList.toggle("collapsed", collapsed);
    toggle.classList.toggle("collapsed", collapsed);
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    localStorage.setItem("home-address-history-collapsed", collapsed ? "1" : "0");
}

function homeAddressHistoryRowForButton(button) {
    return button ? button.closest(".home-address-history-item") : null;
}

function setHomeAddressHistoryStatus(row, message, isError = false) {
    const status = row ? row.querySelector(".home-address-history-status") : null;

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("error", Boolean(isError));
}

async function saveHomeAddressHistoryTitle(button) {
    const row = homeAddressHistoryRowForButton(button);
    const input = row ? row.querySelector(".home-address-history-title-input") : null;
    const entryId = row
        ? ((button && button.dataset.homeAddressHistoryId) || row.dataset.homeAddressHistoryId || "")
        : "";
    const originalText = button ? button.textContent : "";

    if (!row || !entryId || !input) {
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "Saving...";
    }

    try {
        const response = await fetch(`/api/home_address_history/${encodeURIComponent(entryId)}/label`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
            },
            body: JSON.stringify({ label: input.value.trim() }),
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(data.error || "Unable to save address title.");
        }

        updateHomeAddressHistory(data.home_address_history || []);
        showRecipeQuantityUpdatedMessage("", "", "", "Address title saved.");
    } catch (err) {
        console.warn("Unable to save address title.", err);
        setHomeAddressHistoryStatus(row, err.message || "Unable to save address title.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    return false;
}

async function removeHomeAddressHistoryEntry(button) {
    const row = homeAddressHistoryRowForButton(button);
    const entryId = row
        ? ((button && button.dataset.homeAddressHistoryId) || row.dataset.homeAddressHistoryId || "")
        : "";
    const originalText = button ? button.textContent : "";

    if (!row || !entryId) {
        return false;
    }

    if (!window.confirm("Remove this saved address?")) {
        return false;
    }

    if (button) {
        button.disabled = true;
        button.textContent = "Removing...";
    }

    try {
        const response = await fetch(`/api/home_address_history/${encodeURIComponent(entryId)}/delete`, {
            method: "POST",
            headers: {
                "X-Requested-With": "fetch",
            },
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(data.error || "Unable to remove saved address.");
        }

        updateHomeAddressHistory(data.home_address_history || []);
        showRecipeQuantityUpdatedMessage("", "", "", "Saved address removed.");
    } catch (err) {
        console.warn("Unable to remove saved address.", err);
        setHomeAddressHistoryStatus(row, err.message || "Unable to remove saved address.", true);
    } finally {
        if (button && button.isConnected) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    return false;
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
    if (!canToggleStores()) {
        return false;
    }

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

const STORE_REQUEST_FEEDBACK_DESCRIPTION = [
    "Store name:",
    "Store website:",
    "Store selector/location URL:",
    "Why this store should be added:",
    "Notes:"
].join("\n");

function openStoreRequestFeedback(button) {
    closeRecipeEditRowMenus();

    const section = document.getElementById("feedbackSupportSection");
    const content = document.querySelector('[data-collapse-content="feedback-support"]');

    if (!section || !content) {
        return false;
    }

    if (content.classList.contains("collapsed")) {
        toggleCardCollapse("feedback-support");
    }

    window.setTimeout(() => {
        const form = document.getElementById("feedbackForm");

        if (form) {
            prefillStoreRequestFeedback(form);
        }

        section.scrollIntoView({ behavior: "smooth", block: "start" });

        const focusTarget = form
            ? (form.querySelector("#feedbackSubjectInput") || form.querySelector("[name=\"subject\"]"))
            : section.querySelector(".feedback-sign-in-panel");

        if (focusTarget && typeof focusTarget.focus === "function") {
            focusTarget.focus({ preventScroll: true });
        }
    }, 0);

    return false;
}

function prefillStoreRequestFeedback(form) {
    const typeInput = form.querySelector("#feedbackTypeInput, [name=\"feedback_type\"]");
    const subjectInput = form.querySelector("#feedbackSubjectInput, [name=\"subject\"]");
    const descriptionInput = form.querySelector("#feedbackDescriptionInput, [name=\"description\"]");

    if (typeInput) {
        const storeRequestOption = Array.from(typeInput.options || []).find(option => option.value === "Store Request");
        typeInput.value = storeRequestOption ? "Store Request" : "Store Issue";
    }

    if (subjectInput && !subjectInput.value.trim()) {
        subjectInput.value = "Request store: ";
    }

    if (descriptionInput && !descriptionInput.value.trim()) {
        descriptionInput.value = STORE_REQUEST_FEEDBACK_DESCRIPTION;
    }
}

let addStoreReturnFocus = null;

function expandStoreOptionsForAddStoreModal() {
    const content = document.querySelector('[data-collapse-content="store-options"]');

    if (content && content.classList.contains("collapsed")) {
        toggleCardCollapse("store-options");
    }
}

function openAddStoreModalFromMenu(button) {
    if (!canManageStores()) {
        closeRecipeEditRowMenus();
        return false;
    }

    closeRecipeEditRowMenus();
    expandStoreOptionsForAddStoreModal();
    openAddStoreModal();
    return false;
}

function openAddStoreModal() {
    if (!canManageStores()) {
        return false;
    }

    const modal = document.getElementById("addStoreModal");

    if (!modal) {
        return false;
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

    return false;
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
    const inlineAction = document.querySelector(".store-add-inline-action");
    const modal = document.getElementById("addStoreModal");

    if (!section || !content || !action) {
        return;
    }

    const sectionRect = section.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const expanded = !content.classList.contains("collapsed");
    const actionHeight = action.offsetHeight || 68;
    const inlineRect = inlineAction ? inlineAction.getBoundingClientRect() : null;
    const sectionStarted = sectionRect.top < viewportHeight - actionHeight;
    const inlineCanTakeOver = inlineRect
        ? inlineRect.top <= viewportHeight - actionHeight && inlineRect.bottom > 0
        : false;
    const sectionStillVisible = sectionRect.bottom > actionHeight;
    const modalOpen = modal && modal.classList.contains("open");
    const shouldShow = expanded && sectionStarted && sectionStillVisible && !inlineCanTakeOver && !modalOpen;

    action.classList.toggle("is-visible", shouldShow);
    action.setAttribute("aria-hidden", shouldShow ? "false" : "true");

    if (!shouldShow) {
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
        const cookbookOverwriteModal = document.getElementById("cookbookOverwriteModal");

        if (cookbookOverwriteModal && cookbookOverwriteModal.classList.contains("open")) {
            resolveCookbookOverwritePrompt(false);
            return;
        }

        const cookbookNameModal = document.getElementById("cookbookNameEditorModal");

        if (cookbookNameModal && cookbookNameModal.classList.contains("open")) {
            closeCookbookNameEditor();
            return;
        }

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

    if (!labelInput && !searchUrlInput && !selectorUrlInput) {
        return;
    }

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
    replaceSectionFromPage(nextPage, "#aiPantrySection");
    replaceSectionFromPage(nextPage, "#editItemsSection");
    replaceSectionFromPage(nextPage, "#home-address-section");
    replaceSectionFromPage(nextPage, "#storeOptionsSection");
    const recipeLogWasRefreshed = replaceSectionFromPage(nextPage, "#currentRecipeUrlLogCard");
    replaceSectionFromPage(nextPage, "#cookbooksCard");
    replaceSectionFromPage(nextPage, "#foodRestrictionsCard");
    replaceSectionFromPage(nextPage, "#rulesCard");
    replaceSectionFromPage(nextPage, "#sectionView");
    replaceSectionFromPage(nextPage, "#storeView");
    replaceSectionFromPage(nextPage, "#recipeView");

    if (options.requireRecipeLog && !recipeLogWasRefreshed) {
        throw new Error("Recipe log refresh target was not found.");
    }

    restoreCardCollapseState();
    restoreHomeAddressHistoryCollapseState();
    restoreOpenStorePanels();
    restoreViewBehaviorSettings();
    restoreItemCheckState();
    initPhoneCountryInputs();
    bindRecipeUrlLogDragAndDrop();
    bindRecipeViewDragAndDrop();
    bindCurrentRecipeUrlSummaryToggles();
    bindRecipeQuantityInputs();
    bindRecipeNameInputs();
    bindCookbooks();
    bindStoreButtons();
    bindSectionHeaderToggles();
    bindRecipeDetailToggles();
    bindRecipeTaskChecks();
    decorateRecipeCoverImages();
    applyKnownRecipeImageProgressItems();
    updateViewSwitcherStickyOffset();
    restoreStoreOptionsDisplaySettings();
    restoreActiveStoreIconMode();
    restoreStoreOptionsListSort();
    initStoreLocationMaps();
    restoreWindowScroll(scrollX, scrollY);
    scheduleRecipeImageProgressPoll(250);
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

function ensureRecipeImageLightbox() {
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
            <button type="button"
                    class="recipe-image-lightbox-close"
                    onclick="closeRecipeImageLightbox()">Close</button>
            <img id="recipeImageLightboxImage" alt="">
        </div>
    `;
    lightbox.addEventListener("click", event => {
        if (
            event.target === lightbox ||
            event.target.classList.contains("recipe-image-lightbox-content")
        ) {
            closeRecipeImageLightbox();
        }
    });
    document.body.appendChild(lightbox);

    return lightbox;
}

function openRecipeImageLightbox(image) {
    if (!image || !image.src) {
        return;
    }

    const lightbox = ensureRecipeImageLightbox();
    const lightboxImage = document.getElementById("recipeImageLightboxImage");

    if (!lightboxImage) {
        return;
    }

    lightboxImage.src = image.currentSrc || image.src;
    lightboxImage.alt = image.alt || "Recipe image";
    lightbox.classList.add("open");
    lightbox.setAttribute("aria-hidden", "false");
    document.body.classList.add("image-lightbox-open");

    const closeButton = lightbox.querySelector(".recipe-image-lightbox-close");
    if (closeButton) {
        closeButton.focus({ preventScroll: true });
    }
}

function closeRecipeImageLightbox() {
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

function handleRecipeCoverImageClick(event) {
    const image = event.target.closest ? event.target.closest(".recipe-cover-image") : null;

    if (!image) {
        return;
    }

    event.preventDefault();
    openRecipeImageLightbox(image);
}

function handleRecipeCoverImageKeydown(event) {
    const image = event.target.closest ? event.target.closest(".recipe-cover-image") : null;

    if (!image || (event.key !== "Enter" && event.key !== " ")) {
        return;
    }

    event.preventDefault();
    openRecipeImageLightbox(image);
}

function closeRecipeImageLightboxOnEscape(event) {
    if (event.key === "Escape") {
        closeRecipeImageLightbox();
    }
}

function decorateRecipeCoverImages() {
    document.querySelectorAll(".recipe-cover-image").forEach(image => {
        image.tabIndex = 0;
        image.setAttribute("role", "button");
        image.setAttribute("aria-label", `Enlarge ${image.alt || "recipe image"}`);
    });
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
    restoreScreenSettings();
    restoreCardCollapseState();
    restoreHomeAddressHistoryCollapseState();
    restoreOpenStorePanels();
    restoreViewBehaviorSettings();
    restoreItemCheckState();
    initPhoneCountryInputs();
    bindRecipeUrlLogDragAndDrop();
    bindRecipeViewDragAndDrop();
    bindCurrentRecipeUrlSummaryToggles();
    bindRecipeQuantityInputs();
    bindRecipeNameInputs();
    bindCookbooks();
    bindStoreButtons();
    bindSectionHeaderToggles();
    bindRecipeDetailToggles();
    bindRecipeTaskChecks();
    keepRecipeCoverImagesVisible();
    initRecipeImageProgressSync();
    updateRecipeEditStickyOffsets();
    updateViewSwitcherStickyOffset();
    restoreStoreOptionsDisplaySettings();
    restoreActiveStoreIconMode();
    restoreStoreOptionsListSort();
    initStoreLocationMaps();
    startExtractionProgressPolling();
    document.addEventListener("click", handleRecipeCoverImageClick);
    document.addEventListener("click", handleRecipeEditRowMenuOutsideClick);
    document.addEventListener("scroll", handleRecipeEditRowMenuScrollOrResize, true);
    document.addEventListener("wheel", handleRecipeEditRowMenuScrollOrResize, { passive: true, capture: true });
    document.addEventListener("touchmove", handleRecipeEditRowMenuScrollOrResize, { passive: true, capture: true });
    document.addEventListener("keydown", handleRecipeCoverImageKeydown);
    document.addEventListener("keydown", closeAddStoreModalOnEscape);
    document.addEventListener("keydown", closeRecipeImageLightboxOnEscape);
    updateAddStoreStickyVisibility();
});

window.addEventListener("resize", updateRecipeEditStickyOffsets);
window.addEventListener("resize", updateViewSwitcherStickyOffset);
window.addEventListener("resize", invalidateStoreLocationMaps);
window.addEventListener("resize", handleRecipeEditRowMenuScrollOrResize);
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
