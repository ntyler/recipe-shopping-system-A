/* Standalone editor sections reuse the existing controls and their listeners. */
function revealRecipeEditControlPanel(control) {
    if (!recipeEditorStandalonePageIsActive()) return;
    const panel = control?.closest?.("[data-recipe-edit-tab-panel]");
    if (panel) setRecipeEditActiveTab(panel.dataset.recipeEditTabPanel);
}

function organizeRecipeEditCompactSections() {
    if (!recipeEditorStandalonePageIsActive()
        || document.body.dataset.recipeEditCompactSectionsOrganized === "1") return false;

    const tabsRoot = document.querySelector("[data-recipe-edit-tabs]");
    const tabList = tabsRoot?.querySelector('[role="tablist"]');
    const panelsRoot = tabsRoot?.querySelector(".recipe-edit-tab-panels");
    if (!tabsRoot || !tabList || !panelsRoot) return false;

    const definitions = [
        ["recipeinformation", "RecipeInformation", "Recipe Information"],
        ["cookbookassignment", "CookbookAssignment", "Cookbook Assignment"],
        ["sourceinformation", "SourceInformation", "Source Information"],
    ];
    const sections = {};
    definitions.forEach(([key, suffix, title]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.id = `recipeEditTab${suffix}`;
        button.className = "recipe-edit-tab";
        button.setAttribute("role", "tab");
        button.setAttribute("aria-selected", "false");
        button.setAttribute("aria-controls", `recipeEditPanel${suffix}`);
        button.tabIndex = -1;
        button.dataset.recipeEditTab = key;
        button.textContent = title;
        tabList.appendChild(button);

        const panel = document.createElement("section");
        panel.id = `recipeEditPanel${suffix}`;
        panel.className = "recipe-edit-section recipe-edit-secondary-panel";
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", button.id);
        panel.dataset.recipeEditTabPanel = key;
        panel.hidden = true;
        const heading = document.createElement("h2");
        heading.className = "recipe-edit-secondary-panel-title";
        heading.textContent = title;
        const body = document.createElement("div");
        body.className = "recipe-edit-secondary-panel-body";
        panel.append(heading, body);
        panelsRoot.appendChild(panel);
        sections[key] = body;
    });

    const move = (target, selector) => {
        const element = document.querySelector(selector);
        if (element) target.appendChild(element);
        return element;
    };

    // The canonical information panel keeps all detailed fields, including
    // classification and hidden source metadata used by existing save flows.
    move(sections.recipeinformation, ".recipe-edit-info-panel:not(.recipe-edit-categories-panel)");
    [
        ".recipe-edit-ai-assistant-card",
        ".recipe-edit-health-card",
        ".recipe-edit-confidence-card",
    ].forEach(selector => {
        const card = move(sections.recipeinformation, selector);
        card?.classList.remove("recipe-edit-sticky-action-footer");
    });

    const assignment = document.createElement("div");
    assignment.className = "recipe-edit-grid recipe-edit-compact-assignment-grid";
    sections.cookbookassignment.appendChild(assignment);
    move(assignment, "#recipeEditCookbookField");
    move(assignment, "#recipeEditCategoryMenuSectionField");
    const priceField = recipeEditFieldContainer("recipeEditMenuPrice");
    if (priceField) assignment.appendChild(priceField);

    // Preserve the canonical image inputs inside the recipe form. The cover
    // dialog will move the desktop card out of this storage when initialized.
    const coverControls = document.createElement("div");
    coverControls.id = "recipeEditCoverControls";
    coverControls.hidden = true;
    tabsRoot.appendChild(coverControls);
    move(coverControls, ".recipe-edit-image-card");
    move(coverControls, "[data-recipe-edit-mobile-image-slot]");
    document.querySelector(".recipe-edit-ingredient-gallery-card")?.remove();

    [".recipe-edit-source-documents-card", ".recipe-edit-restaurant-card"].forEach(selector => {
        const card = move(sections.sourceinformation, selector);
        if (card?.tagName === "DETAILS") card.open = true;
    });

    const sidebar = document.querySelector(".recipe-edit-context-sidebar");
    if (sidebar) {
        // Source/restaurant dialogs live alongside the old sidebar cards.
        // Keep their original nodes outside tab panels so opening a dialog is
        // never blocked by a hidden ancestor when another tab is active.
        Array.from(sidebar.children).forEach(child => {
            if (child.matches('[role="dialog"], [class*="modal"], [class*="backdrop"]')) {
                tabsRoot.appendChild(child);
            } else {
                sections.recipeinformation.appendChild(child);
            }
        });
        sidebar.hidden = true;
    }
    document.body.dataset.recipeEditCompactSectionsOrganized = "1";
    initRecipeEditTabs();
    return true;
}
