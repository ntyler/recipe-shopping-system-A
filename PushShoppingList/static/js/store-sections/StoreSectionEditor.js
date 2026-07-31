(function initializeStoreSectionEditor(global) {
    "use strict";

    let activeEditor = null;

    function unmount(options = {}) {
        const editor = activeEditor;
        if (!editor) {
            return null;
        }
        activeEditor = null;
        editor.container.classList.remove("is-store-section-editing");
        if (editor.control && editor.control.isConnected) {
            editor.control.remove();
        }
        if (typeof editor.onUnmount === "function") {
            editor.onUnmount(options);
        }
        return editor;
    }

    function mount(options = {}) {
        if (!options.container || typeof options.createControl !== "function") {
            return null;
        }
        unmount();
        const control = options.createControl();
        if (!control) {
            return null;
        }
        control.classList.add("store-section-editor-control", "is-entering");
        control.dataset.storeSectionEditor = "true";
        options.container.classList.add("is-store-section-editing");
        options.container.appendChild(control);
        activeEditor = {
            container: options.container,
            control,
            display: options.display || null,
            source: options.source || null,
            onUnmount: options.onUnmount,
        };
        window.requestAnimationFrame(() => {
            if (control.isConnected) {
                control.classList.remove("is-entering");
            }
        });
        return control;
    }

    function current() {
        return activeEditor;
    }

    function isActiveControl(control) {
        return Boolean(activeEditor && activeEditor.control === control);
    }

    global.StoreSectionEditor = Object.freeze({
        mount,
        unmount,
        current,
        isActiveControl,
    });
}(window));
