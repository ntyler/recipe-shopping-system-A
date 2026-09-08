(() => {
    'use strict';

    const root = document.querySelector('.ingredient-master-page');
    if (!root) return;
    const phoneLayout = window.matchMedia('(max-width: 760px)');
    const rowSelector = '[data-ingredient-master-row]';
    const detailSelector = '.ingredient-name-field, .ingredient-order-cell, .ingredient-aliases-cell, .ingredient-section-cell, .ingredient-action-cell';
    // Keep an expanded row open when saving or filtering replaces its element.
    const rowState = new Map();
    const aliasManager = document.getElementById('ingredientAliasManager');

    function rowHasPendingWork(row) {
        return row.matches('.is-dirty, .is-saving, .is-deleting, [aria-busy="true"]')
            || (row.classList.contains('is-editing') && aliasManager?.getAttribute('aria-busy') === 'true');
    }

    function setAttribute(element, name, value) {
        if (element.getAttribute(name) !== value) element.setAttribute(name, value);
    }

    function syncRow(row) {
        const toggle = row.querySelector('[data-ingredient-mobile-toggle]');
        if (!toggle) return;
        const recordId = row.dataset.masterRecordId;
        let state = rowState.get(recordId);
        if (!state) {
            state = {expanded: false};
            rowState.set(recordId, state);
        }
        if (!toggle.hasAttribute('aria-controls')) {
            const controls = Array.from(row.querySelectorAll(detailSelector)).map((cell, index) => {
                if (!cell.id) cell.id = `ingredientMobileDetails-${row.dataset.masterRecordId}-${index}`;
                return cell.id;
            });
            toggle.setAttribute('aria-controls', controls.join(' '));
        }
        const pending = rowHasPendingWork(row);
        if (pending && phoneLayout.matches) state.expanded = true;
        const expanded = !phoneLayout.matches || state.expanded;
        if (row.classList.contains('is-mobile-expanded') !== expanded) {
            row.classList.toggle('is-mobile-expanded', expanded);
        }
        const name = row.dataset.recordName || 'ingredient';
        const label = toggle.querySelector('[data-ingredient-mobile-name]');
        if (label && label.textContent !== name) label.textContent = name;
        setAttribute(toggle, 'aria-expanded', String(expanded));
        setAttribute(toggle, 'aria-disabled', String(pending));
        setAttribute(toggle, 'aria-label', pending
            ? `Save or cancel changes to ${name} before collapsing details`
            : `${expanded ? 'Collapse' : 'Expand'} details for ${name}`);
        setAttribute(toggle, 'title', pending ? 'Save or cancel before collapsing details' : expanded ? 'Collapse details' : 'Expand details');
    }

    function syncRows() {
        root.querySelectorAll(rowSelector).forEach(syncRow);
    }

    root.addEventListener('click', event => {
        const toggle = event.target.closest('[data-ingredient-mobile-toggle]');
        if (!toggle || !phoneLayout.matches) return;
        const row = toggle.closest(rowSelector);
        if (!row) return;
        event.preventDefault();
        syncRow(row);
        if (rowHasPendingWork(row)) return;
        const state = rowState.get(row.dataset.masterRecordId);
        state.expanded = !state.expanded;
        syncRow(row);
        toggle.focus({preventScroll: true});
    });

    // A programmatically focused editor must remain visible, including when a
    // save validation error or a desktop-to-phone resize restores field focus.
    root.addEventListener('focusin', event => {
        if (!phoneLayout.matches || !event.target.closest(detailSelector)) return;
        const row = event.target.closest(rowSelector);
        if (!row) return;
        syncRow(row);
        rowState.get(row.dataset.masterRecordId).expanded = true;
        syncRow(row);
    });

    phoneLayout.addEventListener('change', () => {
        if (phoneLayout.matches) {
            const active = document.activeElement;
            const row = active?.closest(rowSelector);
            if (row && active.closest(detailSelector)) {
                syncRow(row);
                rowState.get(row.dataset.masterRecordId).expanded = true;
            }
        }
        syncRows();
    });

    // Filtering, grouping, saving and ordering can replace or move table rows.
    // Observe the stable page container so new rows gain the same disclosure.
    let syncFrame = 0;
    const observer = new MutationObserver(() => {
        if (syncFrame) return;
        syncFrame = window.requestAnimationFrame(() => {
            syncFrame = 0;
            syncRows();
        });
    });
    observer.observe(root, {
        subtree: true, childList: true, attributes: true,
        attributeFilter: ['class', 'aria-busy', 'data-record-name'],
    });
    if (aliasManager && !root.contains(aliasManager)) {
        observer.observe(aliasManager, {attributes: true, attributeFilter: ['aria-busy']});
    }
    syncRows();
    root.classList.add('has-mobile-ingredient-rows');
})();
