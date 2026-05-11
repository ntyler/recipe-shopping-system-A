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

function showView(viewName) {
    const sectionView = document.getElementById("sectionView");
    const storeView = document.getElementById("storeView");
    const recipeView = document.getElementById("recipeView");

    const sectionBtn = document.getElementById("sectionViewBtn");
    const storeBtn = document.getElementById("storeViewBtn");
    const recipeBtn = document.getElementById("recipeViewBtn");

    if (sectionView) sectionView.style.display = "none";
    if (storeView) storeView.style.display = "none";
    if (recipeView) recipeView.style.display = "none";

    if (sectionBtn) sectionBtn.classList.remove("active");
    if (storeBtn) storeBtn.classList.remove("active");
    if (recipeBtn) recipeBtn.classList.remove("active");

    if (viewName === "store") {
        if (storeView) storeView.style.display = "block";
        if (storeBtn) storeBtn.classList.add("active");
    } else if (viewName === "recipe") {
        if (recipeView) recipeView.style.display = "block";
        if (recipeBtn) recipeBtn.classList.add("active");
    } else {
        if (sectionView) sectionView.style.display = "block";
        if (sectionBtn) sectionBtn.classList.add("active");
    }

    localStorage.setItem("shopping_view", viewName);
}

function restoreView() {
    showView(localStorage.getItem("shopping_view") || "section");
}

function toggleCardCollapse(key) {
    const content = document.querySelector('[data-collapse-content="' + key + '"]');
    const icon = document.querySelector('[data-collapse-icon="' + key + '"]');

    if (!content) return;

    const collapsed = content.classList.toggle("collapsed");

    if (icon) {
        icon.textContent = collapsed ? "Show ▾" : "Hide ▴";
    }

    localStorage.setItem("card_collapsed|" + key, collapsed ? "closed" : "open");
}

function setupCardCollapseToggles() {
    document.querySelectorAll("[data-collapse-content]").forEach(content => {
        const key = content.dataset.collapseContent;
        const icon = document.querySelector('[data-collapse-icon="' + key + '"]');
        const saved = localStorage.getItem("card_collapsed|" + key);

        if (saved === "open") {
            content.classList.remove("collapsed");
            if (icon) icon.textContent = "Hide ▴";
        } else {
            content.classList.add("collapsed");
            if (icon) icon.textContent = "Show ▾";
        }
    });
}

function togglePasswordVisibility(inputId, button) {
    const input = document.getElementById(inputId);

    if (!input) return;

    const showing = input.type === "text";
    input.type = showing ? "password" : "text";

    if (button) {
        button.textContent = showing ? "👁" : "🙈";
    }
}

function saveOpenStoreUrlsSetting() {}
function saveShowItemButtonsSetting() {}
function saveShowBestProductSetting() {}
function saveHideCheckedItemsSetting() {}
function saveCompactModeSetting() {}

document.addEventListener("DOMContentLoaded", function () {
    restoreScroll();
    restoreView();
    setupCardCollapseToggles();
});
