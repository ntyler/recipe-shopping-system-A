/* Shared top-layer placement for compact master-data alias editors. */
window.MasterDataAliasEditor = {
    positionPopover(form, anchor) {
        if (form.hidden || !anchor?.isConnected) return;
        const rect = anchor.getBoundingClientRect(), viewport = window.visualViewport;
        const left = (viewport?.offsetLeft || 0) + 12, top = (viewport?.offsetTop || 0) + 12;
        const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
        const right = left + width - 24, bottom = top + height - 24;
        form.style.width = `${Math.min(360, width - 24)}px`;
        form.style.maxHeight = `${height - 24}px`;
        const panel = form.getBoundingClientRect();
        const below = bottom - rect.bottom - 6, above = rect.top - top - 6;
        let y = rect.bottom + 6;
        if (panel.height > below && above > below) y = rect.top - panel.height - 6;
        form.style.left = `${Math.max(left, Math.min(rect.left, right - panel.width))}px`;
        form.style.top = `${Math.max(top, Math.min(y, bottom - panel.height))}px`;
    },
};
