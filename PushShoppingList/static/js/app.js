function saveScroll() {
    localStorage.setItem("scrollY", window.scrollY);
}

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
        modal.style.display = "flex";
    }
}

function hideExtractProgressModal() {
    const modal = document.getElementById("extractProgressModalBackdrop");

    if (modal) {
        modal.style.display = "none";
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

document.addEventListener("DOMContentLoaded", function () {
    restoreScroll();
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

    showExtractionOverlay();

    const list = document.getElementById("extractUrlList");
    const status = document.getElementById("extractStatusText");
    const summary = document.getElementById("extractSummary");
    const bar = document.getElementById("extractProgressBar");

    list.innerHTML = "";

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

    for (let i = 0; i < urls.length; i++) {
        const url = urls[i];
        const row = document.getElementById(`extract-url-${i}`);
        const checkbox = row.querySelector(".bulk-progress-check");
        const text = row.querySelector(".bulk-progress-text");
        const reason = row.querySelector(".bulk-skip-reason");

        status.textContent = `Downloading recipe ${i + 1} of ${urls.length}...`;
        summary.textContent = "Fetching recipe page and extracting ingredients.";
        reason.textContent = "extracting • Running recipe extractor...";
        text.classList.add("active");

        bar.style.width = `${Math.max(10, Math.round((i / urls.length) * 100))}%`;

        try {
            const response = await fetch("/api/extract_recipe", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    url: url,
                }),
            });

            const data = await response.json();

            if (data.ok) {
                checkbox.checked = true;
                text.classList.remove("active");
                text.classList.add("done");
                reason.textContent = `done • ${data.ingredients.length} ingredients extracted`;
            } else {
                text.classList.remove("active");
                reason.textContent = `failed • ${data.error || "unknown error"}`;
            }
        } catch (err) {
            text.classList.remove("active");
            reason.textContent = `failed • ${err}`;
        }

        bar.style.width = `${Math.round(((i + 1) / urls.length) * 100)}%`;
    }

    status.textContent = "Extraction complete.";
    summary.textContent = "Refreshing shopping list...";
    bar.style.width = "100%";

    setTimeout(() => {
        window.location.href = "/";
    }, 800);
}