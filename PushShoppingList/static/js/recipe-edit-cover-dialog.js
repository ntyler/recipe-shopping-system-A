/* Move the existing cover controls into a native modal. They remain in the form,
 * so upload/removal, prompt editing and recipe saving keep their existing state. */
function syncRecipeEditCoverDialog() {
    const dialog = document.getElementById("recipeEditCoverDialog");
    if (!dialog) return;
    const image = document.getElementById("recipeEditCoverImage");
    const trigger = document.querySelector("[data-summary-cover-dialog]");
    const hasImage = Boolean(image?.getAttribute("src"));
    trigger?.setAttribute("aria-label", hasImage ? "Edit recipe image" : "Add recipe image");
    if (dialog.open && image?.dataset.fullSrc) {
        // The shared setter normally chooses a card-sized source. Use its saved
        // full-size URL inside the enlarged preview without changing cover data.
        if (image.getAttribute("src") !== image.dataset.fullSrc) image.src = image.dataset.fullSrc;
        if (image.hasAttribute("srcset")) image.removeAttribute("srcset");
    }
    const sourceStatus = document.getElementById("recipeEditStatus");
    const status = dialog.querySelector("[data-cover-dialog-status]");
    const message = sourceStatus?.textContent || "";
    if (status.textContent !== message) status.textContent = message;
    status.hidden = !message;
    status.classList.toggle("error", Boolean(sourceStatus?.classList.contains("error")));
}

function closeRecipeEditCoverDialog() {
    const dialog = document.getElementById("recipeEditCoverDialog");
    if (!dialog?.open) return false;
    closeRecipeImageChangeActions();
    closeRecipeImagePromptModal({ restoreFocus: false });
    dialog.close();
    return false;
}

function handleRecipeEditCoverDialogKeydown(event) {
    if (event.key !== "Tab") return;
    const prompt = recipeImagePromptModal();
    if (prompt && !prompt.hidden) return; // The existing prompt editor owns its focus trap.
    const dialog = event.currentTarget;
    const controls = Array.from(dialog.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(control => !control.hidden && control.getClientRects().length);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!first) return;
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function openRecipeEditCoverDialog(trigger = null) {
    if (!recipeEditorStandalonePageIsActive()) return false;
    organizeRecipeEditCoverDialog();
    const dialog = document.getElementById("recipeEditCoverDialog");
    if (!dialog || dialog.open) return false;
    dialog.recipeEditCoverTrigger = trigger || document.querySelector("[data-summary-cover-dialog]");
    closeRecipeImageChangeActions();
    dialog.showModal();
    document.body.classList.add("recipe-edit-cover-dialog-open");
    syncRecipeEditCoverDialog();
    dialog.querySelector("[data-cover-dialog-close]").focus({ preventScroll: true });
    return false;
}

function organizeRecipeEditCoverDialog() {
    if (!recipeEditorStandalonePageIsActive() || document.getElementById("recipeEditCoverDialog")) return;
    const form = document.getElementById("recipeEditForm");
    const card = document.querySelector(".recipe-edit-image-card");
    if (!form || !card) return;
    const dialog = document.createElement("dialog");
    dialog.id = "recipeEditCoverDialog";
    dialog.dataset.recipeEditCoverDialog = "";
    dialog.setAttribute("aria-labelledby", "recipeEditCoverDialogTitle");
    dialog.innerHTML = `<header class="recipe-edit-cover-dialog-heading">
        <h2 id="recipeEditCoverDialogTitle">Recipe Image</h2>
        <button type="button" data-cover-dialog-close aria-label="Close recipe image">×</button>
        </header><div class="recipe-edit-cover-dialog-body"></div>
        <p data-cover-dialog-status role="status" aria-live="polite" hidden></p>`;
    dialog.querySelector(".recipe-edit-cover-dialog-body").appendChild(card);
    // Reuse the prompt dialog inside the native modal's top layer. Its existing
    // focus trap and Escape handler continue to operate, including focus return.
    const prompt = recipeImagePromptModal();
    if (prompt) dialog.appendChild(prompt);
    const image = card.querySelector("#recipeEditCoverImage");
    if (image) {
        image.classList.remove("recipe-cover-image");
        image.removeAttribute("role");
        image.removeAttribute("tabindex");
        image.removeAttribute("title");
        image.removeAttribute("aria-label");
    }
    dialog.querySelector("[data-cover-dialog-close]").addEventListener("click", closeRecipeEditCoverDialog);
    dialog.addEventListener("keydown", handleRecipeEditCoverDialogKeydown);
    dialog.addEventListener("cancel", event => {
        event.preventDefault();
        const prompt = recipeImagePromptModal();
        if (prompt && !prompt.hidden) closeRecipeImagePromptModal();
        else if (dialog.querySelector("[data-recipe-image-change-actions]")) closeRecipeImageChangeActions({ restoreFocus: true });
        else closeRecipeEditCoverDialog();
    });
    dialog.addEventListener("click", event => {
        if (event.target !== dialog) return;
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right
            || event.clientY < bounds.top || event.clientY > bounds.bottom) closeRecipeEditCoverDialog();
    });
    dialog.addEventListener("close", () => {
        closeRecipeImageChangeActions();
        closeRecipeImagePromptModal({ restoreFocus: false });
        document.body.classList.remove("recipe-edit-cover-dialog-open");
        const trigger = dialog.recipeEditCoverTrigger;
        delete dialog.recipeEditCoverTrigger;
        if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    });
    form.appendChild(dialog);
    const observer = new MutationObserver(syncRecipeEditCoverDialog);
    if (image) observer.observe(image, { attributes: true, attributeFilter: ["src", "srcset", "data-full-src"] });
    const status = document.getElementById("recipeEditStatus");
    if (status) observer.observe(status, { attributes: true, attributeFilter: ["class"], childList: true, subtree: true, characterData: true });
    syncRecipeEditCoverDialog();
}
