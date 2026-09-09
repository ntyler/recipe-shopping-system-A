(() => {
    'use strict';
    const root = document.querySelector('.equipment-master-page');
    if (!root) return;
    const rowSelector = '[data-equipment-master-row]';
    const phone = matchMedia('(max-width: 760px)');
    const clean = value => value.trim().replace(/\s+/g, ' ');
    const field = row => row.querySelector('[data-equipment-row-name]');
    const dirty = row => Boolean(field(row) && clean(field(row).value) !== row.dataset.currentName);
    const busy = row => row.getAttribute('aria-busy') === 'true';

    function status(row, message = '', error = false) {
        const output = row.querySelector('[data-equipment-row-status]');
        if (!output) return;
        output.textContent = message;
        output.classList.toggle('is-error', error);
    }

    function sync(row) {
        const input = field(row);
        if (!input) return;
        const changed = dirty(row), saving = busy(row);
        const name = clean(input.value);
        const error = !name ? 'Enter a display name.' : name.length > 160 ? 'Display name must be 160 characters or fewer.' : '';
        const output = row.querySelector('[data-equipment-name-error]');
        output.textContent = error;
        output.hidden = !error;
        if (error) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
        row.classList.toggle('is-dirty', changed);
        row.classList.toggle('is-saving', saving);
        const save = row.querySelector('[data-equipment-row-save]');
        // Invalid drafts have a Cancel action, never a disabled resting Save.
        save.hidden = !changed || Boolean(error);
        save.disabled = saving;
        save.textContent = saving ? 'Saving…' : 'Save';
        const cancel = row.querySelector('[data-equipment-row-cancel]');
        cancel.hidden = !changed;
        cancel.disabled = saving;
        const reset = row.querySelector('[data-equipment-row-reset]');
        reset.hidden = changed || row.dataset.currentName === row.dataset.detectedName;
        reset.disabled = saving;
        input.disabled = saving;
    }

    function select(row) {
        root.querySelectorAll(`${rowSelector}.is-selected`).forEach(other => {
            if (other !== row) other.classList.remove('is-selected');
        });
        row.classList.add('is-selected');
    }

    function setExpanded(row, expanded) {
        row.classList.toggle('is-mobile-expanded', expanded);
        const toggle = row.querySelector('[data-equipment-mobile-toggle]');
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.setAttribute('aria-label', `${expanded ? 'Collapse' : 'Expand'} details for ${row.dataset.recordName}`);
    }

    function cancel(row) {
        if (busy(row)) return;
        field(row).value = row.dataset.currentName;
        status(row, 'Changes canceled.');
        sync(row);
        field(row).focus({preventScroll: true});
    }

    async function save(row) {
        sync(row);
        if (!dirty(row) || busy(row) || field(row).getAttribute('aria-invalid') === 'true') return;
        const name = clean(field(row).value);
        row.setAttribute('aria-busy', 'true');
        status(row, 'Saving display name…');
        sync(row);
        try {
            const response = await fetch(row.dataset.updateUrl, {
                method: 'PATCH',
                headers: {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
                body: JSON.stringify({display_name: name, reset: name === row.dataset.detectedName}),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || 'Display name could not be saved.');
            const savedName = result.record.name;
            row.dataset.currentName = savedName;
            row.dataset.recordName = savedName;
            row.dataset.detectedName = result.record.detected_name;
            field(row).value = savedName;
            field(row).setAttribute('aria-label', `Display name for ${savedName}`);
            row.querySelector('[data-equipment-master-display-name]').textContent = savedName;
            setExpanded(row, row.classList.contains('is-mobile-expanded'));
            const image = row.querySelector('img.master-data-thumbnail');
            if (image) {
                image.alt = `${savedName} image`;
                image.setAttribute('aria-label', `View image: ${savedName} image`);
            }
            const usage = row.querySelector('[data-master-usage-button]');
            if (usage) {
                usage.dataset.recordName = savedName;
                const count = usage.querySelector('strong').textContent.trim();
                usage.setAttribute('aria-label', `Show ${count} recipe${count === '1' ? '' : 's'} referencing ${savedName}`);
                usage.title = `Show recipes referencing ${savedName}`;
            } else {
                row.querySelector('.master-data-usage-empty').setAttribute('aria-label', `${savedName} is unused; no recipes currently reference it`);
            }
            const time = row.querySelector('.master-data-updated-cell time');
            if (result.record.updated_at) {
                time.dateTime = result.record.updated_at;
                time.title = result.record.updated_at;
                time.textContent = result.record.updated_at_label;
            }
            status(row, 'Saved.');
        } catch (error) {
            // Keep the draft available for retry after a rejected or failed write.
            status(row, error.message || 'Display name could not be saved.', true);
        } finally {
            row.setAttribute('aria-busy', 'false');
            sync(row);
            if (!document.activeElement || document.activeElement === document.body || row.contains(document.activeElement)) {
                field(row).focus({preventScroll: true});
            }
        }
    }

    root.addEventListener('input', event => {
        if (!event.target.matches('[data-equipment-row-name]')) return;
        const row = event.target.closest(rowSelector);
        status(row);
        sync(row);
    });
    root.addEventListener('focusin', event => {
        const row = event.target.closest(rowSelector);
        if (row) select(row);
    });
    root.addEventListener('click', event => {
        const row = event.target.closest(rowSelector);
        if (!row) return;
        select(row);
        const button = event.target.closest('button');
        if (!button) return;
        if (button.matches('[data-equipment-mobile-toggle]')) setExpanded(row, !row.classList.contains('is-mobile-expanded'));
        else if (button.matches('[data-equipment-row-save]')) void save(row);
        else if (button.matches('[data-equipment-row-cancel]')) cancel(row);
        else if (button.matches('[data-equipment-row-reset]') && !busy(row)) {
            field(row).value = row.dataset.detectedName;
            status(row);
            sync(row);
            field(row).focus({preventScroll: true});
        }
    });
    root.addEventListener('keydown', event => {
        const row = event.target.closest(rowSelector);
        if (!row || !field(row)) return;
        if (event.key === 'Escape' && dirty(row)) {
            event.preventDefault();
            cancel(row);
        } else if (event.key === 'Enter' && event.target.matches('[data-equipment-row-name]')) {
            event.preventDefault();
            void save(row);
        }
    });
    window.addEventListener('beforeunload', event => {
        if ([...root.querySelectorAll(rowSelector)].some(row => dirty(row) || busy(row))) {
            event.preventDefault();
            event.returnValue = '';
        }
    });
    // Resizing must not hide a focused control or unsaved draft on a phone.
    phone.addEventListener('change', () => {
        if (phone.matches) root.querySelectorAll(rowSelector).forEach(row => {
            if (dirty(row) || row.contains(document.activeElement)) setExpanded(row, true);
        });
    });
    root.querySelectorAll(rowSelector).forEach(sync);
})();
