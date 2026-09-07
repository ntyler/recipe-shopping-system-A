(function () {
    'use strict';

    // A menu button with radio items keeps category choices and commands accessible
    // without putting commands in a native select or inside listbox options.
    window.createUnitCategoryUI = function ({root, getRegistry, applyRegistry, announce}) {
        const editor = root.querySelector('[data-category-editor]');
        const manager = root.querySelector('[data-category-manager]');
        const form = editor.querySelector('form');
        const name = form.elements.name, description = form.elements.description;
        const submit = form.querySelector('[data-category-submit]');
        const error = form.querySelector('#unitCategoryMutationError');
        const reassign = form.querySelector('#unitCategoryReassign');
        const managerList = manager.querySelector('[data-category-manager-list]');
        const managerStatus = manager.querySelector('[data-category-manager-status]');
        const menu = document.createElement('div');
        menu.id = 'unitCategoryMenu'; menu.className = 'unit-category-menu';
        menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', 'Category');
        menu.setAttribute('popover', 'manual');
        root.append(menu);
        let trigger = null, origin = null, editorReturn = null, managerReturn = null;
        let mode = 'add', editingId = '', pending = false, typeahead = '', typedAt = 0;
        for (const dialog of [editor, manager]) {
            dialog.addEventListener('keydown', event => {
                if (event.key !== 'Tab') return;
                const controls = [...dialog.querySelectorAll('button, input, textarea, select, [tabindex="0"]')]
                    .filter(control => !control.disabled && control.getClientRects().length);
                const first = controls[0], last = controls.at(-1);
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            });
        }
        const categories = () => getRegistry().categories;
        const button = (label, action, aria = label) => {
            const control = document.createElement('button');
            control.type = 'button'; control.textContent = label; control.setAttribute('aria-label', aria);
            control.addEventListener('click', action);
            return control;
        };
        const refresh = control => {
            control.textContent = categories().find(c => c.key === control.value)?.label || 'Choose category';
            control.title = control.textContent;
            control.setAttribute('aria-label', `${control.dataset.categoryLabel}: ${control.textContent}`);
        };
        const closeMenu = (restore = true) => {
            if (!trigger) return;
            const previous = trigger;
            menu.hidePopover(); previous.setAttribute('aria-expanded', 'false'); trigger = null;
            if (restore) previous.focus({preventScroll: true});
        };
        const choose = (control, value) => {
            control.value = value; refresh(control);
            control.dispatchEvent(new Event('change', {bubbles: true}));
        };
        const focusMenuItem = item => {
            item.focus({preventScroll: true});
            // Reveal keyboard focus inside a long menu without scrolling the unit draft.
            const bounds = menu.getBoundingClientRect(), rect = item.getBoundingClientRect();
            const top = bounds.top + menu.clientTop, bottom = top + menu.clientHeight;
            if (rect.top < top) menu.scrollTop -= top - rect.top;
            else if (rect.bottom > bottom) menu.scrollTop += rect.bottom - bottom;
        };
        const openMenu = control => {
            if (control.disabled || pending) return;
            if (trigger === control) { closeMenu(); return; }
            closeMenu(false); trigger = control; origin = control; typeahead = ''; typedAt = 0;
            menu.replaceChildren();
            categories().forEach(category => {
                const item = button(category.label, () => { choose(control, category.key); closeMenu(); });
                item.setAttribute('role', 'menuitemradio');
                item.setAttribute('aria-checked', String(category.key === control.value));
                item.dataset.categoryId = category.key;
                item.tabIndex = -1; menu.append(item);
            });
            const separator = document.createElement('div'); separator.setAttribute('role', 'separator'); menu.append(separator);
            for (const [label, action] of [['+ Add category', () => openEditor('add')], ['Manage categories…', openManager]]) {
                const item = button(label, () => { closeMenu(); action(); });
                item.setAttribute('role', 'menuitem'); item.setAttribute('aria-haspopup', 'dialog');
                item.tabIndex = -1; menu.append(item);
            }
            control.setAttribute('aria-expanded', 'true');
            menu.showPopover();
            const rect = control.getBoundingClientRect();
            menu.style.maxHeight = `${Math.max(160, Math.min(400, innerHeight - 24))}px`;
            const bounds = menu.getBoundingClientRect();
            menu.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - bounds.width - 12))}px`;
            menu.style.top = `${Math.max(12, Math.min(rect.bottom + 4, innerHeight - bounds.height - 12))}px`;
            focusMenuItem(menu.querySelector('[aria-checked="true"]') || menu.querySelector('button'));
        };
        const enhance = control => {
            if (control.tagName === 'SELECT') {
                const replacement = document.createElement('button');
                for (const attr of control.attributes) replacement.setAttribute(attr.name, attr.value);
                replacement.value = control.value; control.replaceWith(replacement); control = replacement;
            }
            if (control.dataset.categoryPicker !== undefined) { refresh(control); return control; }
            control.type = 'button'; control.dataset.categoryPicker = '';
            control.dataset.categoryLabel = control.getAttribute('aria-label') ||
                (control.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.textContent || '').join(' ').trim() || 'Category';
            control.removeAttribute('aria-labelledby');
            control.classList.add('unit-category-picker');
            control.setAttribute('aria-haspopup', 'menu'); control.setAttribute('aria-expanded', 'false');
            control.setAttribute('aria-controls', menu.id);
            control.addEventListener('click', () => openMenu(control));
            control.addEventListener('keydown', event => {
                if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
                    event.preventDefault(); event.stopPropagation(); openMenu(control);
                }
            });
            refresh(control); return control;
        };
        menu.addEventListener('keydown', event => {
            const items = [...menu.querySelectorAll('button')], index = items.indexOf(document.activeElement);
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(); return; }
            if (event.key === 'Tab') { closeMenu(); return; }
            let next;
            if (event.key === 'Home') next = 0;
            else if (event.key === 'End') next = items.length - 1;
            else if (event.key === 'ArrowDown') next = (index + 1) % items.length;
            else if (event.key === 'ArrowUp') next = (index - 1 + items.length) % items.length;
            else if (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey) {
                typeahead = Date.now() - typedAt > 700 ? event.key : typeahead + event.key; typedAt = Date.now();
                next = items.findIndex(item => item.textContent.toLocaleLowerCase().startsWith(typeahead.toLocaleLowerCase()));
            }
            if (next !== undefined) {
                event.preventDefault(); event.stopPropagation();
                if (next >= 0) focusMenuItem(items[next]);
            }
        });
        document.addEventListener('pointerdown', event => {
            if (trigger && !menu.contains(event.target) && event.target !== trigger) closeMenu(false);
        });
        document.addEventListener('focusin', event => {
            if (trigger && !menu.contains(event.target) && event.target !== trigger) closeMenu(false);
        });
        window.addEventListener('resize', () => closeMenu());

        const fieldError = (field, message) => {
            const output = form.querySelector(field === name ? '#unitCategoryNameError' : '#unitCategoryDescriptionError');
            output.textContent = message || ''; output.hidden = !message;
            field.setAttribute('aria-invalid', String(Boolean(message)));
        };
        const closeEditor = () => { if (!pending) editor.close(); };
        const openEditor = (nextMode, category = null, returnTo = document.activeElement) => {
            if (pending) return;
            mode = nextMode; editingId = category?.key || ''; editorReturn = returnTo;
            form.reset(); error.hidden = true; fieldError(name, ''); fieldError(description, '');
            form.querySelector('[data-category-fields]').hidden = mode === 'delete';
            form.querySelector('[data-category-delete-fields]').hidden = mode !== 'delete';
            name.value = category?.label || ''; description.value = category?.description || '';
            const title = mode === 'delete' ? 'Delete category' : mode === 'edit' ? 'Edit category' : 'Add category';
            form.querySelector('h2').textContent = title;
            submit.textContent = mode === 'delete' ? category.unit_count ? 'Reassign & Delete' : 'Delete Category'
                : mode === 'edit' ? 'Save Category' : 'Add Category';
            if (mode === 'delete') {
                const draftUsesCategory = origin?.value === category.key;
                form.querySelector('[data-category-delete-context]').textContent = category.unit_count
                    ? `${category.label} is used by ${category.unit_count} unit${category.unit_count === 1 ? '' : 's'}. Choose where to move them before deleting.`
                    : draftUsesCategory ? `Your unsaved unit uses ${category.label}. Choose a replacement for its draft before deleting.`
                        : `Delete ${category.label}? No saved units use it.`;
                reassign.replaceChildren(new Option('Choose a category', ''), ...categories().filter(c => c.key !== category.key).map(c => new Option(c.label, c.key)));
                reassign.required = Boolean(category.unit_count || draftUsesCategory);
                reassign.hidden = !reassign.required;
                form.querySelector('label[for="unitCategoryReassign"]').hidden = !reassign.required;
            }
            editor.showModal();
            (mode === 'delete' ? reassign.hidden ? form.querySelector('[data-category-editor-cancel]') : reassign : name).focus({preventScroll: true});
        };
        const restoreEditorFocus = () => {
            if (editorReturn?.isConnected) editorReturn.focus({preventScroll: true});
            else if (manager.open && editorReturn?.dataset.categoryFocus) managerList.querySelector(`[data-category-focus="${CSS.escape(editorReturn.dataset.categoryFocus)}"]`)?.focus({preventScroll: true});
            else if (manager.open) manager.querySelector('[data-category-manager-close]').focus({preventScroll: true});
            else origin?.focus({preventScroll: true});
        };
        editor.addEventListener('close', restoreEditorFocus);
        editor.addEventListener('cancel', event => { event.preventDefault(); closeEditor(); });
        form.querySelector('[data-category-editor-cancel]').addEventListener('click', closeEditor);
        name.addEventListener('input', () => fieldError(name, ''));
        description.addEventListener('input', () => fieldError(description, ''));

        const request = async (id, method, values) => {
            if (pending) return null;
            const focused = document.activeElement;
            pending = true; editor.setAttribute('aria-busy', 'true'); manager.setAttribute('aria-busy', 'true');
            const controls = [...editor.querySelectorAll('button, input, textarea, select'), ...manager.querySelectorAll('button')];
            const disabled = controls.map(control => control.disabled);
            controls.forEach(control => { control.disabled = true; });
            try {
                const response = await fetch(root.dataset.categoriesUrl + (id ? '/' + encodeURIComponent(id) : ''), {
                    method, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'}, body: JSON.stringify(values),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) {
                    const failure = new Error(result.error || 'Categories could not be saved. Try again.');
                    failure.fields = result.errors; throw failure;
                }
                applyRegistry(result.registry, result);
                announce(result.message);
                return result;
            } finally {
                pending = false; controls.forEach((control, index) => { control.disabled = disabled[index]; });
                editor.setAttribute('aria-busy', 'false'); manager.setAttribute('aria-busy', 'false');
                focused?.focus({preventScroll: true});
            }
        };
        form.addEventListener('submit', async event => {
            event.preventDefault(); if (pending) return;
            error.hidden = true;
            if (mode !== 'delete') {
                // The server performs Unicode case folding and the authoritative duplicate check.
                const cleaned = name.value.normalize('NFKC').trim().replace(/\s+/g, ' ');
                const invalid = !cleaned ? 'Enter a category name.' : categories().some(c => c.key !== editingId && c.label.toLowerCase() === cleaned.toLowerCase())
                    ? 'A category with this name already exists.' : '';
                fieldError(name, invalid);
                if (invalid) { name.focus(); return; }
            } else if (reassign.required && !reassign.value) {
                error.textContent = 'Choose a category to reassign the units before deleting.'; error.hidden = false; reassign.focus(); return;
            }
            try {
                const result = await request(editingId, mode === 'delete' ? 'DELETE' : editingId ? 'PUT' : 'POST',
                    mode === 'delete' ? {reassign_to: reassign.value} : {name: name.value, description: description.value});
                if (!result) return;
                if (mode === 'add' && origin?.isConnected) choose(origin, result.category_id);
                if (manager.open) renderManager();
                editor.close();
            } catch (failure) {
                error.textContent = failure.message; error.hidden = false;
                fieldError(name, failure.fields?.name); fieldError(description, failure.fields?.description);
                if (failure.fields?.name) name.focus();
            }
        });

        const renderManager = () => {
            const previous = document.activeElement;
            const focusKey = previous?.dataset.categoryFocus;
            const oldScroll = manager.scrollTop;
            managerList.replaceChildren();
            categories().forEach((category, index, all) => {
                const row = document.createElement('section'); row.className = 'unit-category-management-row'; row.dataset.categoryId = category.key;
                row.setAttribute('aria-label', category.label);
                const info = document.createElement('div'), title = document.createElement('strong'); title.textContent = category.label;
                const detail = document.createElement('p'); detail.textContent = category.description || 'No description';
                const usage = document.createElement('small');
                usage.textContent = `${category.unit_count} unit${category.unit_count === 1 ? '' : 's'}${category.required ? ' · Required' : ''}`;
                info.append(title, detail, usage);
                const actions = document.createElement('div'); actions.className = 'unit-category-management-actions';
                const order = document.createElement('span'); order.textContent = String(index + 1); order.setAttribute('aria-label', `Position ${index + 1} of ${all.length}`);
                actions.append(order);
                for (const [direction, label, offset] of [['up', '↑', -1], ['down', '↓', 1]]) {
                    const move = button(label, async () => {
                        try {
                            await request(category.key, 'PATCH', {action: 'move_to', position: index + offset + 1});
                            renderManager(); managerStatus.textContent = `${category.label} moved to position ${index + offset + 1}.`;
                        } catch (failure) { managerStatus.textContent = failure.message; move.focus({preventScroll: true}); }
                    }, `Move ${category.label} ${direction}`);
                    move.disabled = index + offset < 0 || index + offset >= all.length;
                    move.dataset.categoryFocus = `${category.key}-${direction}`; actions.append(move);
                }
                const edit = button('Edit', () => openEditor('edit', category, edit), `Edit ${category.label}`);
                edit.dataset.categoryFocus = `${category.key}-edit`; actions.append(edit);
                if (!category.required) {
                    const remove = button('Delete', () => openEditor('delete', category, remove), `Delete ${category.label}`);
                    actions.append(remove);
                }
                row.append(info, actions); managerList.append(row);
            });
            if (!editor.open && focusKey) {
                const next = managerList.querySelector(`[data-category-focus="${CSS.escape(focusKey)}"]`);
                (next?.disabled ? next.closest('section').querySelector('[data-category-focus$="-edit"]') : next)?.focus({preventScroll: true});
            }
            manager.scrollTop = oldScroll;
        };
        function openManager() {
            managerReturn = origin; managerStatus.textContent = ''; renderManager(); manager.showModal();
            manager.querySelector('[data-category-manager-close]').focus({preventScroll: true});
        }
        manager.querySelector('[data-category-manager-close]').addEventListener('click', () => { if (!pending) manager.close(); });
        manager.addEventListener('cancel', event => { if (pending) event.preventDefault(); });
        manager.addEventListener('close', () => managerReturn?.focus({preventScroll: true}));
        manager.querySelector('[data-category-manager-add]').addEventListener('click', () => openEditor('add'));
        return {enhance, refresh, openMenu, refreshAll: () => root.querySelectorAll('[data-category-picker]').forEach(refresh)};
    };
}());
