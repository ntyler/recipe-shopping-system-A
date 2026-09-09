(() => {
    'use strict';
    const root = document.querySelector('.equipment-master-page');
    if (!root) return;
    const rowSelector = '[data-equipment-master-row]';
    const detailSelector = '.equipment-name-field, .equipment-order-cell, .equipment-aliases-cell, .equipment-type-cell, .equipment-master-action-cell';
    const phone = matchMedia('(max-width: 760px)');
    const manager = document.getElementById('equipmentAliasManager');
    const clean = value => String(value || '').trim().replace(/\s+/g, ' ');
    const key = value => clean(value).toLowerCase();
    const rows = () => [...root.querySelectorAll(rowSelector)];
    const field = row => row?.querySelector('[data-equipment-row-name]');
    const typeField = row => row?.querySelector('[data-equipment-row-type]');
    const editable = row => Boolean(row?.querySelector('[data-equipment-row-save]'));
    const editor = name => manager?.querySelector(`[data-equipment-editor-${name}]`);
    const rowStates = new Map();
    let editingRow = null, deletingRow = null, aliasAnchor = null, mutationPending = false;
    let orderOriginal = null, orderChange = null;
    let imageRequestToken = 0;

    // Enhance the existing selects without changing their values or save contract.
    // Labels and SVGs come from the same server-rendered mapping as group headings.
    const typeTemplates = new Map([...root.querySelectorAll('[data-equipment-type-template]')]
        .map(template => [template.dataset.equipmentTypeTemplate, template]));
    const typeMenu = document.createElement('div');
    typeMenu.id = 'equipmentTypeMenu';
    typeMenu.className = 'equipment-type-menu';
    typeMenu.setAttribute('popover', 'manual');
    typeMenu.setAttribute('role', 'listbox');
    typeMenu.tabIndex = -1;
    typeMenu.hidden = true;
    document.body.append(typeMenu);
    let activeTypePicker = null, activeTypeIndex = 0, typeSearch = '', typeSearchAt = 0;

    function typeLabel(value, text) {
        const label = (typeTemplates.get(value) || typeTemplates.get('')).content.firstElementChild.cloneNode(true);
        label.dataset.equipmentTypeLabel = value;
        label.querySelector('.equipment-type-text').textContent = text;
        return label;
    }
    function closeTypeMenu(restoreFocus = false) {
        const picker = activeTypePicker;
        activeTypePicker = null;
        if (typeMenu.matches(':popover-open')) typeMenu.hidePopover();
        typeMenu.hidden = true;
        typeMenu.removeAttribute('aria-activedescendant');
        if (picker) {
            picker.trigger.setAttribute('aria-expanded', 'false');
            if (restoreFocus && picker.trigger.isConnected) picker.trigger.focus({preventScroll: true});
        }
    }
    function positionTypeMenu() {
        if (!activeTypePicker) return;
        const rect = activeTypePicker.trigger.getBoundingClientRect();
        if (!activeTypePicker.trigger.isConnected || !rect.height) { closeTypeMenu(); return; }
        const viewport = window.visualViewport;
        const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
        const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
        const menuWidth = Math.min(Math.max(240, rect.width), width - 16);
        const below = top + height - rect.bottom - 8, above = rect.top - top - 8;
        const upward = below < Math.min(typeMenu.scrollHeight, 360) && above > below;
        typeMenu.style.width = `${menuWidth}px`;
        typeMenu.style.maxHeight = `${Math.max(44, Math.min(360, upward ? above : below))}px`;
        typeMenu.style.left = `${Math.max(left + 8, Math.min(rect.left, left + width - menuWidth - 8))}px`;
        typeMenu.style.top = `${upward ? rect.top - typeMenu.offsetHeight - 4 : rect.bottom + 4}px`;
    }
    function highlightType(index) {
        const options = [...typeMenu.children];
        activeTypeIndex = Math.max(0, Math.min(options.length - 1, index));
        options.forEach((option, i) => option.classList.toggle('is-active', i === activeTypeIndex));
        const active = options[activeTypeIndex];
        if (active) { typeMenu.setAttribute('aria-activedescendant', active.id); active.scrollIntoView({block: 'nearest'}); }
    }
    function chooseType(index) {
        const picker = activeTypePicker, option = picker?.select.options[index];
        if (!option || option.disabled || picker.select.disabled) return;
        picker.select.value = option.value;
        picker.select.dispatchEvent(new Event('change', {bubbles: true}));
        syncTypePicker(picker);
        closeTypeMenu(true);
    }
    function openTypeMenu(picker) {
        if (picker.select.disabled) return false;
        if (picker.row && !edit(picker.row)) return false;
        closeTypeMenu();
        activeTypePicker = picker;
        typeSearch = ''; typeSearchAt = 0;
        typeMenu.setAttribute('aria-label', picker.select.getAttribute('aria-label'));
        typeMenu.replaceChildren(...[...picker.select.options].map((option, index) => {
            const item = document.createElement('div');
            item.id = `equipmentTypeOption-${index}`;
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', String(option.selected));
            item.setAttribute('aria-disabled', String(option.disabled));
            item.append(typeLabel(option.value, option.textContent.trim()));
            item.addEventListener('click', () => chooseType(index));
            return item;
        }));
        picker.trigger.setAttribute('aria-expanded', 'true');
        typeMenu.hidden = false;
        typeMenu.showPopover();
        positionTypeMenu();
        highlightType(picker.select.selectedIndex);
        typeMenu.focus({preventScroll: true});
        return true;
    }
    function typeMenuKey(event) {
        if (!activeTypePicker) return;
        const last = typeMenu.children.length - 1;
        if (event.key === 'Escape') closeTypeMenu(true);
        else if (event.key === 'Tab') { closeTypeMenu(true); return; }
        else if (event.key === 'ArrowDown') highlightType(activeTypeIndex === last ? 0 : activeTypeIndex + 1);
        else if (event.key === 'ArrowUp') highlightType(activeTypeIndex === 0 ? last : activeTypeIndex - 1);
        else if (event.key === 'Home') highlightType(0);
        else if (event.key === 'End') highlightType(last);
        else if (event.key === 'Enter' || event.key === ' ') chooseType(activeTypeIndex);
        else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
            const now = Date.now();
            typeSearch = (now - typeSearchAt < 700 ? typeSearch : '') + event.key.toLowerCase();
            typeSearchAt = now;
            const options = [...activeTypePicker.select.options];
            const repeated = [...typeSearch].every(char => char === typeSearch[0]);
            const search = repeated ? typeSearch[0] : typeSearch;
            const start = repeated ? activeTypeIndex + 1 : activeTypeIndex;
            const index = options.map((_, i) => (start + i) % options.length)
                .find(i => !options[i].disabled && options[i].textContent.trim().toLowerCase().startsWith(search));
            if (index !== undefined) highlightType(index);
        } else return;
        event.preventDefault(); event.stopPropagation();
    }
    function syncTypePicker(picker) {
        const {select, trigger} = picker;
        const option = select.selectedOptions[0];
        if (trigger.dataset.value !== select.value) {
            trigger.replaceChildren(typeLabel(select.value, option?.textContent.trim() || select.value));
            trigger.dataset.value = select.value;
        }
        trigger.disabled = select.disabled;
        trigger.setAttribute('aria-label', `${select.getAttribute('aria-label')}: ${option?.textContent.trim() || select.value}`);
        trigger.setAttribute('aria-invalid', select.getAttribute('aria-invalid') || 'false');
        if (select.getAttribute('aria-describedby')) trigger.setAttribute('aria-describedby', select.getAttribute('aria-describedby'));
        if (activeTypePicker === picker && select.disabled) closeTypeMenu();
    }
    function syncTypePickers() {
        root.querySelectorAll('[data-equipment-type-picker]').forEach(wrapper => {
            const select = wrapper.querySelector('select');
            if (!select.equipmentTypePicker) {
                const trigger = document.createElement('button');
                trigger.type = 'button';
                trigger.className = 'equipment-type-trigger';
                if (select.matches('[data-equipment-row-type]')) trigger.classList.add('ingredient-row-section');
                trigger.dataset.equipmentTypeTrigger = '';
                trigger.setAttribute('aria-haspopup', 'listbox');
                trigger.setAttribute('aria-expanded', 'false');
                trigger.setAttribute('aria-controls', typeMenu.id);
                const picker = {select, trigger, row: select.closest(rowSelector)};
                select.equipmentTypePicker = picker;
                trigger.addEventListener('click', () => activeTypePicker === picker ? closeTypeMenu(true) : openTypeMenu(picker));
                trigger.addEventListener('keydown', event => {
                    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) ||
                        (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey)) {
                        event.preventDefault();
                        if (openTypeMenu(picker) && !['ArrowDown', 'ArrowUp'].includes(event.key)) typeMenuKey(event);
                    }
                });
                select.addEventListener('change', () => syncTypePicker(picker));
                wrapper.querySelector(':scope > .equipment-type-label')?.remove();
                select.hidden = true;
                wrapper.prepend(trigger);
            }
            syncTypePicker(select.equipmentTypePicker);
        });
        if (activeTypePicker && !activeTypePicker.trigger.isConnected) closeTypeMenu();
    }
    typeMenu.addEventListener('keydown', typeMenuKey);
    document.addEventListener('pointerdown', event => {
        if (activeTypePicker && !typeMenu.contains(event.target) && !activeTypePicker.trigger.contains(event.target)) closeTypeMenu();
    });
    document.addEventListener('focusin', event => {
        if (activeTypePicker && !typeMenu.contains(event.target) && event.target !== activeTypePicker.trigger) closeTypeMenu();
    });
    window.addEventListener('resize', positionTypeMenu);
    window.visualViewport?.addEventListener('resize', positionTypeMenu);
    document.addEventListener('scroll', event => { if (event.target !== typeMenu) positionTypeMenu(); }, true);

    function state(row) {
        if (!row.equipmentOriginal) {
            row.equipmentAliases = [...row.querySelectorAll('[data-equipment-alias]')].map(chip => chip.dataset.equipmentAlias);
            row.equipmentImageUrl = row.dataset.imageSrc || '';
            row.equipmentImageChange = null; row.equipmentImageError = ''; row.equipmentImagePending = false;
            row.equipmentOriginal = {name: row.dataset.currentName, equipment_type: typeField(row)?.value || row.dataset.equipmentType || '', aliases: [...row.equipmentAliases], image_url: row.equipmentImageUrl};
            row.equipmentPendingAlias = '';
        }
        return row.equipmentOriginal;
    }
    function values(row) {
        state(row);
        return {name: clean(field(row)?.value ?? row.dataset.currentName), equipment_type: typeField(row)?.value || row.dataset.equipmentType || '', aliases: [...row.equipmentAliases], image_url: row.equipmentImageUrl};
    }
    function signature(value) {
        return JSON.stringify({...value, name: clean(value.name), aliases: value.aliases.map(clean).sort()});
    }
    function dirty(row) {
        return Boolean(row && editable(row) && (signature(values(row)) !== signature(state(row)) || clean(row.equipmentPendingAlias) || (row === editingRow && orderChange)));
    }
    function status(row, message = '', error = false) {
        const output = row?.querySelector('[data-equipment-row-status]') || root.querySelector('[data-equipment-registry-status]');
        if (output) { output.textContent = message; output.classList.toggle('is-error', error); }
        if (row && row === editingRow && editor('feedback')) {
            editor('feedback').textContent = message;
            editor('feedback').hidden = !message;
            editor('feedback').dataset.status = error ? 'error' : 'success';
        }
    }
    function validation(row) {
        const draft = values(row), errors = {aliases: {}};
        if (row.equipmentImageError) errors.image = row.equipmentImageError;
        if (!draft.name) errors.name = 'Enter a display name.';
        else if (draft.name.length > 160) errors.name = 'Display name must be 160 characters or fewer.';
        const type = typeField(row);
        if (type && ![...type.options].some(option => option.value === draft.equipment_type)) errors.type = 'Choose a valid Equipment Type.';
        const aliases = [...draft.aliases, ...(clean(row.equipmentPendingAlias) ? [clean(row.equipmentPendingAlias)] : [])];
        const seen = new Set();
        aliases.forEach((alias, index) => {
            const normalized = key(alias);
            if (!normalized || clean(alias).length > 160) errors.aliases[index] = 'Use an alias of 1–160 characters.';
            else if (index >= 100) errors.aliases[index] = 'Use at most 100 aliases.';
            else if (seen.has(normalized)) errors.aliases[index] = `“${clean(alias)}” is already in this equipment.`;
            seen.add(normalized);
        });
        return errors;
    }
    function fieldError(input, output, message = '') {
        if (input) {
            if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
        }
        if (output) { output.textContent = message; output.hidden = !message; }
    }
    function pending(row) { return dirty(row) || row.equipmentImagePending || row.equipmentImageError || row === deletingRow || mutationPending && row === editingRow; }
    function syncMobile(row) {
        const toggle = row.querySelector('[data-equipment-mobile-toggle]');
        if (!toggle) return;
        let saved = rowStates.get(row.dataset.masterRecordId);
        if (!saved) { saved = {expanded: false}; rowStates.set(row.dataset.masterRecordId, saved); }
        if (!toggle.hasAttribute('aria-controls')) {
            const controls = [...row.querySelectorAll(detailSelector)].map((cell, index) => {
                if (!cell.id) cell.id = `equipmentMobileDetails-${row.dataset.masterRecordId}-${index}`;
                return cell.id;
            });
            toggle.setAttribute('aria-controls', controls.join(' '));
        }
        const hasWork = pending(row);
        if (hasWork && phone.matches) saved.expanded = true;
        const expanded = !phone.matches || saved.expanded;
        row.classList.toggle('is-mobile-expanded', expanded);
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.setAttribute('aria-disabled', String(hasWork));
        const action = row === deletingRow ? 'Confirm or cancel deletion' : 'Save or cancel changes';
        toggle.setAttribute('aria-label', hasWork ? `${action} for ${row.dataset.recordName} before collapsing details` : `${expanded ? 'Collapse' : 'Expand'} details for ${row.dataset.recordName}`);
        toggle.title = hasWork ? `${action} before collapsing details` : expanded ? 'Collapse details' : 'Expand details';
        const label = toggle.querySelector('[data-equipment-master-display-name], [data-equipment-mobile-name]');
        if (label) label.textContent = row.dataset.recordName;
    }
    function sync() {
        const anyDirty = dirty(editingRow);
        rows().forEach(row => {
            state(row);
            if (!editable(row)) { syncMobile(row); return; }
            const changed = dirty(row), confirming = row === deletingRow;
            const errors = validation(row), aliasError = Object.values(errors.aliases).join(' ');
            const invalid = Boolean(errors.name || errors.type || aliasError || errors.image);
            fieldError(field(row), row.querySelector('[data-equipment-name-error], [data-equipment-row-name-error]'), errors.name);
            fieldError(typeField(row), row.querySelector('[data-equipment-type-error], [data-equipment-row-type-error]'), errors.type);
            row.classList.toggle('is-editing', row === editingRow);
            row.classList.toggle('is-dirty', changed);
            row.classList.toggle('is-saving', mutationPending && row === editingRow && !confirming);
            row.classList.toggle('is-confirming-delete', confirming);
            row.querySelectorAll('button, input, select').forEach(control => { control.disabled = mutationPending; });
            const save = row.querySelector('[data-equipment-row-save]');
            if (save) { save.hidden = !changed || confirming; save.disabled = mutationPending || row.equipmentImagePending || !changed || invalid; save.textContent = mutationPending && row === editingRow ? 'Saving…' : 'Save'; }
            const cancel = row.querySelector('[data-equipment-row-cancel]');
            if (cancel) { cancel.hidden = !changed && !confirming && !row.equipmentImagePending && !row.equipmentImageError; cancel.setAttribute('aria-label', confirming ? `Cancel deleting ${row.dataset.recordName}` : `Cancel changes to ${row.dataset.recordName}`); }
            const remove = row.querySelector('[data-equipment-row-delete]');
            if (remove) { remove.hidden = confirming || changed; remove.disabled = mutationPending || anyDirty || Boolean(editingRow?.equipmentImagePending); }
            const confirm = row.querySelector('[data-equipment-row-confirm-delete]');
            if (confirm) { confirm.hidden = !confirming; confirm.disabled = mutationPending || anyDirty; confirm.textContent = mutationPending && confirming ? 'Deleting…' : 'Confirm delete'; }
            const merge = row.querySelector('[data-master-merge-open]');
            if (merge) {
                if (!merge.dataset.mergeTitle) merge.dataset.mergeTitle = merge.title;
                merge.hidden = confirming || changed && invalid;
                merge.disabled = Boolean(merge.dataset.mergeBlockedReason) || mutationPending || anyDirty || Boolean(editingRow?.equipmentImagePending);
                merge.title = merge.dataset.mergeBlockedReason || (anyDirty ? 'Save or cancel the current changes before merging.' : merge.dataset.mergeTitle);
            }
            const blocked = mutationPending || row.dataset.orderEnabled !== 'true';
            const handle = row.querySelector('[data-equipment-order-handle]');
            if (handle) { handle.disabled = false; handle.draggable = !blocked; handle.setAttribute('aria-disabled', String(blocked)); }
            const up = row.querySelector('[data-equipment-order-action="up"]'), down = row.querySelector('[data-equipment-order-action="down"]');
            if (up) up.disabled = blocked || Number(row.dataset.sortOrder) === 0;
            if (down) down.disabled = blocked || Number(row.dataset.sortOrder) >= Number(row.dataset.sectionCount) - 1;
            if (row === editingRow && manager) {
                manager.setAttribute('aria-busy', String(mutationPending));
                manager.classList.toggle('is-dirty', changed);
                manager.querySelectorAll('input, button').forEach(control => { control.disabled = mutationPending; });
                if (editor('close-aliases')) editor('close-aliases').disabled = false;
                fieldError(editor('alias-input'), editor('alias-error'), aliasError);
                if (editor('title')) editor('title').textContent = `Aliases for ${values(row).name || row.dataset.recordName}`;
                if (editor('alias-preview')) editor('alias-preview').textContent = 'Alias changes stay pending until you save the row.';
                [...(editor('alias-chips')?.children || [])].forEach((chip, index) => { chip.classList.toggle('has-error', Boolean(errors.aliases[index])); chip.title = errors.aliases[index] || ''; });
            }
            syncMobile(row);
        });
        syncTypePickers();
        window.MasterDataImageLightbox?.sync();
        if (aliasAnchor) window.MasterDataAliasEditor?.positionPopover(manager, aliasAnchor);
    }
    function select(row) {
        rows().forEach(other => other.classList.toggle('is-selected', other === row));
    }
    function closeAliases({restoreFocus = true} = {}) {
        if (!aliasAnchor) return;
        const anchor = aliasAnchor; aliasAnchor = null;
        if (manager.matches(':popover-open')) manager.hidePopover();
        manager.hidden = true; manager.removeAttribute('style');
        anchor.setAttribute('aria-expanded', 'false');
        if (restoreFocus && anchor.isConnected) anchor.focus({preventScroll: true});
    }
    function captureScroll(row) {
        const top = row.getBoundingClientRect().top, scrollers = [];
        for (let element = row.parentElement; element; element = element.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) scrollers.push([element, element.scrollTop]);
        }
        const documentScroll = document.scrollingElement || document.documentElement;
        scrollers.push([documentScroll, documentScroll.scrollTop]);
        return () => {
            scrollers.forEach(([element, position]) => { element.scrollTop = position; });
            const anchor = row.isConnected ? row : rows().find(item => item.dataset.masterRecordId === row.dataset.masterRecordId);
            if (anchor?.getClientRects().length) scrollers[0][0].scrollTop += anchor.getBoundingClientRect().top - top;
        };
    }
    function groupRows(row) {
        return rows().filter(other => other.dataset.userId === row.dataset.userId && other.dataset.equipmentType === row.dataset.equipmentType);
    }
    function placeRows(previous, ordered) {
        if (!previous.length) return;
        const anchor = document.createComment('equipment order'); previous[0].before(anchor);
        ordered.forEach((row, index) => {
            anchor.before(row); row.dataset.sortOrder = String(index);
            const number = row.querySelector('[data-equipment-order-number]');
            if (number) { number.textContent = String(index + 1); number.setAttribute('aria-label', `Position ${index + 1}`); }
        });
        anchor.remove();
    }
    function renderRowAliases(row, aliases) {
        const list = row.querySelector('[data-equipment-alias-list]');
        if (!list) return;
        list.replaceChildren(...aliases.map(alias => {
            const chip = document.createElement('code'); chip.dataset.equipmentAlias = alias; chip.textContent = alias; chip.title = alias; return chip;
        }));
        if (!aliases.length) { const empty = document.createElement('span'); empty.className = 'unit-master-no-aliases'; empty.textContent = 'No aliases'; list.append(empty); }
    }
    function cancel(row, {restoreFocus = true, discard = true} = {}) {
        if (!row) return true;
        if (mutationPending) return false;
        if (!discard && dirty(row) && !window.confirm('Discard unsaved changes to this equipment?')) return false;
        const restore = captureScroll(row), original = state(row);
        imageRequestToken++;
        row.equipmentImageUrl = original.image_url; row.equipmentImageChange = null;
        row.equipmentImagePending = false; row.equipmentImageError = '';
        field(row).value = original.name;
        if (typeField(row)) typeField(row).value = original.equipment_type;
        row.equipmentAliases = [...original.aliases]; row.equipmentPendingAlias = '';
        renderRowAliases(row, original.aliases);
        closeAliases({restoreFocus: false});
        if (orderOriginal) placeRows(groupRows(row), orderOriginal);
        orderOriginal = null; orderChange = null; editingRow = null; deletingRow = null;
        status(row, 'Changes canceled.'); sync();
        if (restoreFocus) row.focus({preventScroll: true});
        restore(); return true;
    }
    function edit(row) {
        if (mutationPending || !editable(row)) return false;
        if (editingRow === row) return true;
        if (editingRow && !cancel(editingRow, {restoreFocus: false, discard: false})) return false;
        deletingRow = null; editingRow = row; state(row); select(row); sync(); return true;
    }
    function renderAliases() {
        const row = editingRow, container = editor('alias-chips');
        if (!row || !container) return;
        container.replaceChildren(...row.equipmentAliases.map((alias, index) => {
            const chip = document.createElement('span'); chip.className = 'unit-master-alias-chip';
            const text = document.createElement('span'); text.textContent = alias;
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', `Remove alias ${alias}`);
            remove.addEventListener('click', () => {
                if (mutationPending) return;
                row.equipmentAliases.splice(index, 1); renderAliases(); renderRowAliases(row, row.equipmentAliases); status(row); sync(); editor('alias-input').focus({preventScroll: true});
            });
            chip.append(text, remove); return chip;
        }));
    }
    function openAliases(row, anchor) {
        if (!manager || !edit(row)) return;
        closeAliases({restoreFocus: false}); aliasAnchor = anchor;
        editor('alias-input').value = row.equipmentPendingAlias;
        renderAliases(); manager.hidden = false; manager.showPopover(); anchor.setAttribute('aria-expanded', 'true'); sync();
        editor('alias-input').focus({preventScroll: true});
    }
    function addAlias() {
        if (!editingRow || mutationPending) return false;
        const value = clean(editingRow.equipmentPendingAlias);
        if (!value) return true;
        if (validation(editingRow).aliases[editingRow.equipmentAliases.length]) { sync(); editor('alias-input')?.focus({preventScroll: true}); return false; }
        editingRow.equipmentAliases.push(value); editingRow.equipmentPendingAlias = '';
        if (editor('alias-input')) editor('alias-input').value = '';
        renderAliases(); renderRowAliases(editingRow, editingRow.equipmentAliases); sync(); return true;
    }
    function applySaved(row, record) {
        row.dataset.currentName = record.name; row.dataset.recordName = record.name;
        row.dataset.detectedName = record.detected_name || row.dataset.detectedName;
        row.dataset.equipmentType = record.equipment_type || record.equipment_section || typeField(row)?.value || '';
        row.dataset.currentType = row.dataset.equipmentType;
        row.dataset.sortOrder = String(record.sort_order ?? row.dataset.sortOrder);
        row.dataset.sectionCount = String(record.section_count ?? row.dataset.sectionCount);
        field(row).value = record.name; field(row).setAttribute('aria-label', `Display name for ${record.name}`);
        if (typeField(row)) { typeField(row).value = row.dataset.equipmentType; typeField(row).setAttribute('aria-label', `Equipment Type for ${record.name}`); }
        row.equipmentAliases = [...(record.aliases || row.equipmentAliases)]; row.equipmentPendingAlias = '';
        row.dataset.imageSrc = record.image_url || '';
        row.equipmentImageUrl = row.dataset.imageSrc; row.equipmentImageChange = null; row.equipmentImageError = '';
        row.equipmentOriginal = values(row); renderRowAliases(row, row.equipmentAliases);
        const trigger = row.querySelector('[data-master-image-trigger]');
        const image = document.createElement(record.image_url ? 'img' : 'span');
        image.className = record.image_url ? 'master-data-thumbnail' : 'master-data-no-image';
        if (record.image_url) { image.src = record.image_url; image.dataset.fullSrc = record.image_url; image.alt = `${record.name} image`; }
        else image.textContent = 'No image';
        trigger.replaceChildren(image);
        trigger.setAttribute('aria-label', `${record.image_url ? 'Manage' : 'Add'} image for ${record.name}`);
        const usage = row.querySelector('[data-master-usage-button]');
        if (usage) {
            usage.dataset.recordName = record.name;
            const count = usage.querySelector('strong')?.textContent.trim();
            usage.setAttribute('aria-label', `Show ${count} recipe${count === '1' ? '' : 's'} referencing ${record.name}`); usage.title = `Show recipes referencing ${record.name}`;
        } else row.querySelector('.master-data-usage-empty')?.setAttribute('aria-label', `${record.name} is unused; no recipes currently reference it`);
        const merge = row.querySelector('[data-master-merge-open]');
        if (merge) merge.dataset.sourceName = record.name;
        if (record.can_delete === false) row.querySelectorAll('[data-equipment-row-delete], [data-equipment-row-confirm-delete]').forEach(control => control.remove());
    }
    async function save(row) {
        if (!edit(row) || !dirty(row) || !addAlias()) return;
        sync(); if (row.querySelector('[data-equipment-row-save]')?.disabled) return;
        const draft = values(row), restore = captureScroll(row);
        const payload = {display_name: draft.name, reset: draft.name === row.dataset.detectedName, equipment_type: draft.equipment_type, aliases: draft.aliases};
        if (row.equipmentImageChange) payload.image = row.equipmentImageChange;
        if (orderChange) payload.order = orderChange;
        mutationPending = true; row.setAttribute('aria-busy', 'true'); status(row, 'Saving changes…'); sync();
        let saved = false;
        try {
            const response = await fetch(row.dataset.updateUrl, {method: 'PATCH', headers: {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-Requested-With': 'fetch'}, body: JSON.stringify(payload)});
            const result = await response.json();
            if (!response.ok || !result.ok) {
                row.equipmentImageError = result.errors?.image || '';
                throw new Error(result.message || result.error || 'Equipment could not be saved.');
            }
            applySaved(row, result.record || result.result); saved = true;
            orderOriginal = null; orderChange = null; editingRow = null; closeAliases({restoreFocus: false});
            await window.MasterDataRegistryRefresh();
            status(null, `${draft.name} saved.`);
        } catch (error) {
            if (saved) rows().forEach(item => { item.dataset.orderEnabled = 'false'; });
            status(saved ? null : row, saved ? 'Saved. The table could not refresh; reload the page to see the updated group.' : error.message || 'Equipment could not be saved.', true);
        } finally {
            mutationPending = false; row.setAttribute('aria-busy', 'false'); sync();
            const current = rows().find(item => item.dataset.masterRecordId === row.dataset.masterRecordId);
            (saved ? current || root.querySelector('[name="search"]') : field(row))?.focus({preventScroll: true}); restore();
        }
    }
    // The shared Ingredient/Equipment lightbox delegates draft ownership to this row editor.
    async function prepareImage(row, file = null) {
        if (row !== editingRow || mutationPending || row.equipmentImagePending) return;
        const token = ++imageRequestToken;
        row.equipmentImagePending = true; row.equipmentImageError = '';
        row.equipmentImageStatus = file ? 'Preparing image preview…' : 'Generating an image preview…';
        status(row); sync();
        try {
            let body, headers = {'X-Requested-With': 'fetch'};
            if (file) { body = new FormData(); body.append('image', file); }
            else { body = JSON.stringify({action: 'generate', name: values(row).name}); headers['Content-Type'] = 'application/json'; }
            const response = await fetch(row.dataset.imageUrl, {method: 'POST', headers, body});
            const result = await response.json();
            if (token !== imageRequestToken || row !== editingRow) return;
            if (!response.ok || !result.ok || !result.token || !result.image_url) throw new Error(result.error || 'Image preview could not be prepared.');
            row.equipmentImageUrl = result.image_url;
            row.equipmentImageChange = {action: 'replace', token: result.token};
        } catch (error) {
            if (token === imageRequestToken && row === editingRow) {
                row.equipmentImageError = error.message || 'Image preview could not be prepared.';
                status(row, row.equipmentImageError, true);
            }
        } finally {
            if (token === imageRequestToken && row === editingRow) {
                row.equipmentImagePending = false; sync();
                const lightbox = document.getElementById('recipeImageLightbox');
                if (lightbox?.classList.contains('open') && lightbox.equipmentRow === row) {
                    lightbox.querySelector(`[data-master-image-action="${file ? 'replace' : 'generate'}"]`).focus({preventScroll: true});
                }
            }
        }
    }
    function removeImage(row) {
        if (row !== editingRow || mutationPending || row.equipmentImagePending || !row.equipmentImageUrl) return;
        if (!window.confirm('Remove this equipment image? The change stays pending until you save.')) return;
        row.equipmentImageUrl = ''; row.equipmentImageChange = state(row).image_url ? {action: 'remove'} : null;
        row.equipmentImageError = ''; status(row); sync();
        document.querySelector('#recipeImageLightbox [data-master-image-action="replace"]')?.focus({preventScroll: true});
    }
    function confirmDelete(row) {
        const button = row.querySelector('[data-equipment-row-delete]');
        if (!button || button.disabled || mutationPending || dirty(editingRow)) return;
        if (editingRow) cancel(editingRow, {restoreFocus: false});
        deletingRow = row; status(row); sync(); row.querySelector('[data-equipment-row-cancel]')?.focus({preventScroll: true});
    }
    async function deleteRow(row) {
        const button = row.querySelector('[data-equipment-row-delete]');
        if (deletingRow !== row || !button || mutationPending || dirty(editingRow)) return;
        mutationPending = true; row.setAttribute('aria-busy', 'true'); sync();
        const nextId = rows().find(item => item !== row)?.dataset.masterRecordId;
        let deleted = false;
        try {
            const response = await fetch(button.dataset.deleteUrl, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'}, body: JSON.stringify({confirm: true, redirect_url: window.location.href})});
            const result = await response.json();
            if (!response.ok || !result.ok) {
                if (result.result?.can_delete === false || result.record?.can_delete === false) { row.querySelectorAll('[data-equipment-row-delete], [data-equipment-row-confirm-delete]').forEach(control => control.remove()); deletingRow = null; }
                throw new Error(result.result?.delete_blocked_reason || result.message || result.error || 'Equipment could not be deleted.');
            }
            deleted = true; deletingRow = null; row.remove();
            await window.MasterDataRegistryRefresh(); status(null, `${row.dataset.recordName} deleted.`);
        } catch (error) {
            if (deleted) rows().forEach(item => { item.dataset.orderEnabled = 'false'; });
            status(deleted ? null : row, deleted ? 'Deleted. The table could not refresh; reload the page to see the updated group.' : error.message || 'Equipment could not be deleted.', true);
        } finally {
            mutationPending = false; row.setAttribute('aria-busy', 'false'); sync();
            (deleted ? rows().find(item => item.dataset.masterRecordId === nextId) || root.querySelector('[name="search"]') : row)?.focus({preventScroll: true});
        }
    }
    function move(row, targetIndex, trigger) {
        if (mutationPending || row.dataset.orderEnabled !== 'true' || !edit(row)) return;
        const previous = groupRows(row), current = previous.indexOf(row);
        const target = Math.max(0, Math.min(previous.length - 1, targetIndex));
        if (current === target) return;
        const restore = captureScroll(row);
        if (!orderOriginal) orderOriginal = [...previous];
        const ordered = [...previous]; ordered.splice(target, 0, ordered.splice(current, 1)[0]);
        orderChange = ordered.every((item, index) => item === orderOriginal[index]) ? null : {position: target + 1, expected_ids: orderOriginal.map(item => Number(item.dataset.masterRecordId))};
        placeRows(previous, ordered); status(row); sync();
        (trigger?.disabled ? row.querySelector('[data-equipment-order-handle]') : trigger)?.focus({preventScroll: true}); restore();
    }

    const update = event => {
        if (!event.target.matches('[data-equipment-row-name], [data-equipment-row-type]')) return;
        const row = event.target.closest(rowSelector), value = event.target.value;
        if (!edit(row)) { event.target.value = state(row)[event.target === field(row) ? 'name' : 'equipment_type']; syncTypePickers(); return; }
        event.target.value = value; status(row); sync();
    };
    root.addEventListener('input', update); root.addEventListener('change', update);
    root.addEventListener('focusin', event => {
        const row = event.target.closest(rowSelector); if (!row) return;
        select(row);
        if (event.target.matches('[data-equipment-row-name], [data-equipment-row-type]') && !edit(row)) { field(editingRow)?.focus({preventScroll: true}); return; }
        if (phone.matches && event.target.closest(detailSelector)) { syncMobile(row); rowStates.get(row.dataset.masterRecordId).expanded = true; syncMobile(row); }
    });
    root.addEventListener('click', event => {
        const row = event.target.closest(rowSelector); if (!row) return;
        select(row); const button = event.target.closest('button'); if (!button) return;
        if (button.matches('[data-equipment-mobile-toggle]')) {
            if (!phone.matches || pending(row)) return;
            const saved = rowStates.get(row.dataset.masterRecordId); saved.expanded = !saved.expanded; syncMobile(row); button.focus({preventScroll: true});
        } else if (button.matches('[data-equipment-row-save]')) void save(row);
        else if (button.matches('[data-equipment-row-cancel]')) {
            if (row === deletingRow) { deletingRow = null; status(row); sync(); row.querySelector('[data-equipment-row-delete]')?.focus({preventScroll: true}); }
            else cancel(row);
        } else if (button.matches('[data-equipment-row-alias]')) openAliases(row, button);
        else if (button.matches('[data-equipment-row-delete]')) confirmDelete(row);
        else if (button.matches('[data-equipment-row-confirm-delete]')) void deleteRow(row);
        else if (button.matches('[data-equipment-order-action]')) move(row, groupRows(row).indexOf(row) + (button.dataset.equipmentOrderAction === 'up' ? -1 : 1), button);
        else if (button.matches('[data-master-merge-open]') && !dirty(editingRow) && !mutationPending) { if (editingRow) cancel(editingRow, {restoreFocus: false}); deletingRow = null; sync(); }
    });
    root.addEventListener('keydown', event => {
        if (event.defaultPrevented) return;
        const row = event.target.closest(rowSelector); if (!row) return;
        if (event.key === 'Escape' && row === deletingRow && !mutationPending) { event.preventDefault(); deletingRow = null; sync(); row.querySelector('[data-equipment-row-delete]')?.focus({preventScroll: true}); }
        else if (event.key === 'Escape' && row === editingRow) { event.preventDefault(); cancel(row); }
        else if (event.key === 'Enter' && event.target.matches('[data-equipment-row-name]')) { event.preventDefault(); void save(row); }
        else if (event.target.matches('[data-equipment-order-handle]') && ['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
            event.preventDefault(); const group = groupRows(row);
            move(row, event.key === 'Home' ? 0 : event.key === 'End' ? group.length - 1 : group.indexOf(row) + (event.key === 'ArrowUp' ? -1 : 1), event.target);
        }
    });
    root.addEventListener('submit', event => {
        if (event.target.matches('.master-data-filter-form') && dirty(editingRow) && !cancel(editingRow, {restoreFocus: false, discard: false})) { event.preventDefault(); event.stopImmediatePropagation(); }
    }, true);
    if (manager) {
        editor('alias-input').addEventListener('input', event => { if (editingRow) { editingRow.equipmentPendingAlias = event.target.value; status(editingRow); sync(); } });
        editor('alias-add').addEventListener('click', () => { addAlias(); editor('alias-input').focus({preventScroll: true}); });
        editor('close-aliases').addEventListener('click', () => { closeAliases(); sync(); });
        manager.addEventListener('submit', event => event.preventDefault());
        manager.addEventListener('keydown', event => {
            if (event.target === editor('alias-input') && ['Enter', ','].includes(event.key)) { event.preventDefault(); addAlias(); }
            else if (event.key === 'Escape') { event.preventDefault(); closeAliases(); sync(); }
        });
        document.addEventListener('pointerdown', event => { if (aliasAnchor && !manager.contains(event.target) && !aliasAnchor.contains(event.target)) { closeAliases({restoreFocus: false}); sync(); } });
        const position = () => { if (aliasAnchor) window.MasterDataAliasEditor?.positionPopover(manager, aliasAnchor); };
        window.addEventListener('resize', position); document.addEventListener('scroll', position, true);
    }
    let dragged = null, dropTarget = null, dropAfter = false;
    const clearDrag = () => { rows().forEach(row => row.classList.remove('is-row-dragging', 'is-row-drop-before', 'is-row-drop-after')); dropTarget = null; };
    root.addEventListener('dragstart', event => {
        const handle = event.target.closest('[data-equipment-order-handle]');
        if (!handle || handle.getAttribute('aria-disabled') === 'true') { event.preventDefault(); return; }
        dragged = handle.closest(rowSelector); dragged.classList.add('is-row-dragging'); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', dragged.dataset.masterRecordId);
    });
    root.addEventListener('dragover', event => {
        if (!dragged) return;
        event.preventDefault(); clearDrag(); const target = event.target.closest(rowSelector);
        if (mutationPending || !target || target === dragged || target.dataset.userId !== dragged.dataset.userId || target.dataset.equipmentType !== dragged.dataset.equipmentType) { event.dataTransfer.dropEffect = 'none'; return; }
        dropTarget = target; const rect = target.getBoundingClientRect(); dropAfter = event.clientY > rect.top + rect.height / 2;
        dragged.classList.add('is-row-dragging'); target.classList.add(dropAfter ? 'is-row-drop-after' : 'is-row-drop-before'); event.dataTransfer.dropEffect = 'move';
    });
    root.addEventListener('drop', event => {
        if (!dragged) return; event.preventDefault();
        if (dropTarget) { const group = groupRows(dragged); let target = group.indexOf(dropTarget) + (dropAfter ? 1 : 0); if (group.indexOf(dragged) < target) target--; move(dragged, target, dragged.querySelector('[data-equipment-order-handle]')); }
        clearDrag(); dragged = null;
    });
    root.addEventListener('dragend', () => { clearDrag(); dragged = null; });
    window.addEventListener('beforeunload', event => { if (dirty(editingRow) || mutationPending || editingRow?.equipmentImagePending) { event.preventDefault(); event.returnValue = ''; } });
    phone.addEventListener('change', () => {
        const row = document.activeElement?.closest(rowSelector);
        if (phone.matches && row && document.activeElement.closest(detailSelector)) { syncMobile(row); rowStates.get(row.dataset.masterRecordId).expanded = true; }
        rows().forEach(syncMobile);
    });
    // Shared refresh and merge workflows can replace the results without reloading the page.
    let frame = 0;
    new MutationObserver(changes => {
        if (frame || !changes.some(change => [...change.addedNodes].some(node => node.nodeType === 1 && (node.matches?.(rowSelector) || node.querySelector?.(rowSelector))))) return;
        frame = requestAnimationFrame(() => { frame = 0; sync(); });
    }).observe(root, {subtree: true, childList: true});
    window.EquipmentRegistry = {
        hasPendingWork: () => dirty(editingRow) || mutationPending || Boolean(editingRow?.equipmentImagePending), sync,
        imageEditor: {
            open(row) { if (editable(row) && !edit(row)) return false; closeAliases({restoreFocus: false}); return true; },
            prepare: prepareImage, remove: removeImage,
            state(row) {
                if (row !== editingRow || !editable(row)) return null;
                return {
                    url: row.equipmentImageUrl, name: values(row).name,
                    busy: mutationPending || row.equipmentImagePending,
                    feedback: Boolean(row.equipmentImageError || row.equipmentImagePending),
                    status: row.equipmentImageError || (row.equipmentImagePending ? row.equipmentImageStatus
                        : row.equipmentImageChange ? 'Unsaved image change · Save the row to keep it.' : 'Use the row’s Save to keep image changes.'),
                };
            },
        },
    };
    sync(); root.classList.add('has-mobile-equipment-rows', 'has-mobile-ingredient-rows');
})();
