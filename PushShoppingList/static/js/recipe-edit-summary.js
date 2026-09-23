/* A projection of the canonical editor fields; saving still uses the original controls. */
function recipeEditCompactSummaryValues() {
    const read = id => String(document.getElementById(id)?.value || "").trim();
    const categories = collectRecipeEditorCategoryValues();
    const tags = [categories.meal_type, ...recipeEditCuisineTagValues(),
        ...recipeEditDietaryPreferenceValues(), categories.main_ingredient,
        categories.cooking_method, categories.occasion, ...recipeEditCustomCategoryValues()];
    const seen = new Set();
    return {
        title: read("recipeEditDisplayName"),
        description: read("recipeEditDescription"),
        servings: read("recipeEditServings").replace(/\s+servings?$/i, ""),
        scale: formatRecipeScaleMultiplierLabel(currentRecipeEditScaleMultiplier()),
        time: read("recipeEditTotalTime"),
        difficulty: read("recipeEditLevel"),
        tags: tags.filter(value => {
            const key = String(value || "").trim().toLowerCase();
            if (!key || seen.has(key)) return false;
            seen.add(key);
            return true;
        }),
    };
}

function openRecipeEditSummaryField(tab, fieldId) {
    if (tab === "recipeimage") return openRecipeEditCoverDialog();
    setRecipeEditActiveTab(tab);
    const field = document.getElementById(fieldId);
    if (field) {
        field.focus({ preventScroll: true });
        field.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    if (fieldId === "recipeEditCustomAdd") openRecipeEditMultiselect("custom");
}

function addRecipeEditSummaryNote() {
    setRecipeEditActiveTab("notes");
    const row = addRecipeReflectionNoteRow();
    const field = row?.querySelector('[data-field="text"]');
    field?.focus();
}

function syncRecipeEditCompactSummary() {
    const summary = document.getElementById("recipeEditCompactSummary");
    if (!summary) return;
    const values = recipeEditCompactSummaryValues();
    for (const key of ["title", "description", "servings", "scale", "time", "difficulty"]) {
        const target = summary.querySelector(`[data-summary-value="${key}"]`);
        const value = values[key] || (key === "title" ? "Untitled recipe"
            : key === "description" ? "Add a description" : "Not set");
        if (target.textContent !== value) target.textContent = value;
        target.title = value;
        target.classList.toggle("is-unspecified", !values[key]);
        const metric = target.closest(".recipe-edit-summary-metric");
        if (metric) {
            const label = { servings: "Servings", scale: "Scale", time: "Total time", difficulty: "Difficulty" }[key];
            metric.setAttribute("aria-label", `${label}: ${value}. Edit ${label.toLowerCase()}.`);
        }
    }
    const tags = summary.querySelector("[data-summary-tags]");
    const tagKey = JSON.stringify(values.tags);
    if (tags.dataset.values !== tagKey) {
        tags.dataset.values = tagKey;
        tags.setAttribute("aria-label", `Edit recipe tags${values.tags.length ? `: ${values.tags.join(", ")}` : ""}`);
        tags.replaceChildren(...values.tags.slice(0, 4).map(value => {
            const chip = document.createElement("span");
            chip.className = "recipe-edit-summary-chip";
            chip.textContent = value;
            return chip;
        }));
        if (values.tags.length > 4) {
            const more = document.createElement("span");
            more.className = "recipe-edit-summary-chip";
            more.textContent = `+${values.tags.length - 4}`;
            more.title = values.tags.slice(4).join(", ");
            tags.appendChild(more);
        }
    }
}

function organizeRecipeEditCompactSummary() {
    if (!recipeEditorStandalonePageIsActive() || document.getElementById("recipeEditCompactSummary")) return;
    const workspace = document.querySelector(".recipe-edit-main-workspace");
    if (!workspace) return;
    const summary = document.createElement("section");
    summary.id = "recipeEditCompactSummary";
    summary.className = "recipe-edit-compact-summary";
    summary.setAttribute("aria-label", "Recipe summary");
    summary.innerHTML = `
        <div class="recipe-edit-summary-media">
            <button type="button" class="recipe-edit-summary-photo" data-recipe-edit-cover-view
                data-summary-cover-dialog aria-label="Edit recipe image" aria-haspopup="dialog" aria-controls="recipeEditCoverDialog">
                <img data-recipe-edit-cover-image alt="Recipe image" hidden>
                <span data-recipe-edit-cover-empty>Add recipe image</span>
            </button>
        </div>
        <div class="recipe-edit-summary-content">
            <h1 class="recipe-edit-summary-title"><button type="button" data-summary-tab="recipeinformation"
                data-summary-field="recipeEditDisplayName" data-summary-value="title">Recipe</button></h1>
            <div class="recipe-edit-summary-rating-row"><button type="button" class="recipe-edit-summary-note"
                data-summary-add-note><span aria-hidden="true">＋</span> Add Note</button></div>
            <div class="recipe-edit-summary-tags-row">
                <button type="button" class="recipe-edit-summary-tags" data-summary-tags data-summary-tab="recipeinformation"
                    data-summary-field="recipeEditCategoryMealType" aria-label="Edit recipe tags"></button>
                <button type="button" class="recipe-edit-summary-add-tags" data-summary-tab="recipeinformation"
                    data-summary-field="recipeEditCustomAdd">＋ Add Tags</button>
            </div>
            <button type="button" class="recipe-edit-summary-description" data-summary-value="description"
                data-summary-tab="recipeinformation" data-summary-field="recipeEditDescription"></button>
        </div>
        <div class="recipe-edit-summary-metrics"></div>`;
    const metrics = [
        ["servings", "Servings", "servings", "recipeEditServingsCount"],
        ["scale", "Scale", "scale", "recipeEditScaleMultiplier"],
        ["time", "Total Time", "inactive", "recipeEditTotalTime"],
        ["difficulty", "Difficulty", "difficulty", "recipeEditLevel"],
    ];
    metrics.forEach(([key, label, icon, field]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "recipe-edit-summary-metric";
        button.dataset.summaryTab = "recipeinformation";
        button.dataset.summaryField = field;
        button.setAttribute("aria-label", `Edit ${label.toLowerCase()}`);
        button.innerHTML = `${recipeEditMetadataIcon(icon)}<span><strong data-summary-value="${key}"></strong><span>${label}</span></span>`;
        summary.querySelector(".recipe-edit-summary-metrics").appendChild(button);
    });
    const rating = document.getElementById("recipeEditRating")?.closest(".recipe-edit-rating-field");
    if (rating) summary.querySelector(".recipe-edit-summary-rating-row").prepend(rating);
    const favorite = document.getElementById("recipeEditFavoriteButton");
    if (favorite) summary.querySelector(".recipe-edit-summary-media").appendChild(favorite);
    const image = summary.querySelector("img");
    image.addEventListener("load", () => handleRecipeEditorCoverImageLoad(image));
    image.addEventListener("error", () => handleRecipeEditorCoverImageError(image));
    summary.addEventListener("click", event => {
        const target = event.target.closest("[data-summary-tab], [data-summary-add-note], [data-summary-cover-dialog]");
        if (target?.hasAttribute("data-summary-cover-dialog")) return openRecipeEditCoverDialog(target);
        if (target?.hasAttribute("data-summary-add-note")) addRecipeEditSummaryNote();
        else if (target) openRecipeEditSummaryField(target.dataset.summaryTab, target.dataset.summaryField);
    });
    workspace.prepend(summary);
    document.body.dataset.recipeEditCompact = "true";
    syncRecipeEditCompactSummary();
}
