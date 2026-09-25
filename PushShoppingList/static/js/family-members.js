/* Manage the same scoped member records used by the Meal Planner. */
(function (root) {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
    const clean = value => String(value ?? '').trim().replace(/\s+/g, ' ');
    const ids = values => [...new Set((Array.isArray(values) ? values : []).map(String))];
    const profile = member => ({first_name:member.first_name || '', last_name:member.last_name || '', default_portion:member.default_portion ?? 1, group_ids:ids(member.group_ids)});
    const positive = value => Number.isFinite(Number(value)) && Number(value) > 0;
    const json = value => ({method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(value)});

    class FamilyMembersPage {
        constructor(page, members, groups = []) {
            this.page = page;
            this.members = Array.isArray(members) ? members : [];
            this.drafts = new Map();
            this.profiles = new Map();
            this.groupEditorMemberId = '';
            this.groupEditor = page.querySelector('[data-family-group-editor]');
            if (this.groupEditor) this.groupEditor.hidden = true;
            this.groups = Array.isArray(groups) ? groups : [];
            this.groupDrafts = new Map();
            this.groupErrors = new Map();
            this.groupPending = new Set();
            this.groupCreating = false;
            this.groupFilter = 'all';
            this.createGroups = [];
            this.bulkGroups = [];
            this.bulkRows = [];
            this.nextBulkId = 1;
            this.bulkBusy = false;
            this.addBulkRow();
            this.addBulkRow();
            this.errors = new Map();
            this.pending = new Set();
            this.loading = false;
            this.creating = false;
            this.search = '';
            const initialStatus = new URLSearchParams(root.location?.search || '').get('status');
            this.filter = ['active', 'all', 'archived'].includes(initialStatus) ? initialStatus : 'active';
            page.querySelector('[data-family-filter]').value = this.filter;
            page.addEventListener('click', event => this.click(event));
            page.addEventListener('input', event => this.input(event));
            page.addEventListener('change', event => this.change(event));
            page.addEventListener('keydown', event => this.keydown(event));
            document.addEventListener?.('pointerdown', event => {
                if (!this.groupEditorMemberId || this.groupEditor?.contains(event.target) || event.target.closest?.('[data-family-edit-groups]')) return;
                this.closeGroupEditor(!event.target.closest?.('button, input, select, textarea, a[href], [tabindex]'));
            });
            document.addEventListener?.('focusin', event => {
                if (!this.groupEditorMemberId || this.groupEditor?.contains(event.target) || event.target.closest?.('[data-family-edit-groups]')) return;
                this.closeGroupEditor(false);
            });
            const positionGroups = () => this.positionGroupEditor();
            root.addEventListener?.('resize', positionGroups);
            document.addEventListener?.('scroll', positionGroups, true);
            root.visualViewport?.addEventListener('resize', positionGroups);
            root.visualViewport?.addEventListener('scroll', positionGroups);
            if (this.groupEditor && root.ResizeObserver) new root.ResizeObserver(positionGroups).observe(this.groupEditor);
            page.querySelector('[data-family-create]').addEventListener('submit', event => {
                event.preventDefault();
                this.create();
            });
            page.querySelector('[data-family-bulk]')?.addEventListener('submit', event => { event.preventDefault(); this.createBulk(); });
            page.querySelector('[data-family-group-create]')?.addEventListener('submit', event => { event.preventDefault(); this.createGroup(); });
            this.render();
        }

        visibleMembers() {
            const query = clean(this.search).toLocaleLowerCase();
            return this.members.filter(member => (this.filter === 'all' || !!member.archived === (this.filter === 'archived'))
                && [member.name, member.first_name, member.last_name].filter(Boolean).join(' ').toLocaleLowerCase().includes(query)
                && (this.groupFilter === 'all' || (this.groupFilter === 'ungrouped' ? !ids(member.group_ids).length : ids(member.group_ids).includes(this.groupFilter))));
        }

        memberProfile(member) { return this.profiles.get(member.id) || profile(member); }

        dirty(member) {
            if (this.drafts.has(member.id) && clean(this.drafts.get(member.id)) !== member.name) return true;
            if (!this.profiles.has(member.id)) return false;
            const saved = profile(member), current = this.memberProfile(member);
            return clean(current.first_name) !== saved.first_name || clean(current.last_name) !== saved.last_name
                || Number(current.default_portion) !== Number(saved.default_portion)
                || JSON.stringify(ids(current.group_ids).sort()) !== JSON.stringify(saved.group_ids.sort());
        }

        addBulkRow() { this.bulkRows.push({key:String(this.nextBulkId++), name:'', first_name:'', last_name:'', default_portion:1}); }

        groupChoices(selected, attribute, busy = false) {
            const chosen = ids(selected);
            const groups = this.groups.filter(group => !group.archived || chosen.includes(group.id));
            if (!groups.length) return '<span class="family-members-help">No groups yet. Use Manage groups to add one.</span>';
            return groups.map(group => `<label class="family-members-check"><input type="checkbox" ${attribute} data-family-focus="${esc(attribute + ':' + group.id)}" value="${esc(group.id)}"${chosen.includes(group.id) ? ' checked' : ''}${busy ? ' disabled' : ''}>${esc(group.name)}${group.archived ? ' (Archived)' : ''}</label>`).join('');
        }

        setStatus(message, error = false) {
            const status = this.page.querySelector('[data-family-status]');
            status.textContent = message;
            status.hidden = !message;
            status.classList.toggle('is-error', error);
        }

        focusState() {
            const element = document.activeElement;
            if (element?.dataset?.familyFocus) return {key:element.dataset.familyFocus, memberId:element.closest('[data-family-member-id]')?.dataset.familyMemberId || (this.groupEditor?.contains(element) ? this.groupEditorMemberId : undefined), start:element.selectionStart, end:element.selectionEnd};
            const row = element?.closest?.('[data-family-member-id]');
            if (!row) return null;
            const control = ['name', 'save', 'cancel', 'archive', 'edit-groups'].find(key => element.matches(`[data-family-${key}]`));
            return control ? {memberId:row.dataset.familyMemberId, control, start:element.selectionStart, end:element.selectionEnd} : null;
        }

        restoreFocus(state) {
            if (!state) return false;
            const row = [...this.page.querySelectorAll('[data-family-member-id]')].find(node => node.dataset.familyMemberId === state.memberId);
            const control = state.key ? [...this.page.querySelectorAll('[data-family-focus]')].find(node => node.dataset.familyFocus === state.key) : row?.querySelector(`[data-family-${state.control}]`);
            if (!control || control.disabled || control.hidden) return false;
            control.focus({preventScroll:true});
            if (state.start != null && (!control.type || ['text', 'search'].includes(control.type))) control.setSelectionRange?.(state.start, state.end);
            return true;
        }

        mayReturnFocus(memberId) {
            const active = document.activeElement;
            return !active || active === document.body || this.focusState()?.memberId === memberId;
        }

        memberRow(id) {
            return [...this.page.querySelectorAll('[data-family-member-id]')].find(row => row.dataset.familyMemberId === id);
        }

        positionGroupEditor() {
            if (!this.groupEditorMemberId || !this.groupEditor || this.groupEditor.hidden) return;
            const anchor = this.memberRow(this.groupEditorMemberId)?.querySelector('[data-family-edit-groups]');
            root.MasterDataAliasEditor?.positionPopover(this.groupEditor, anchor);
        }

        syncGroupEditor() {
            if (!this.groupEditorMemberId || !this.groupEditor) return;
            const member = this.visibleMembers().find(item => item.id === this.groupEditorMemberId);
            if (!member) { this.closeGroupEditor(false); return; }
            const busy = this.loading || this.pending.has(member.id);
            this.page.querySelector('[data-family-group-editor-title]').textContent = `Groups for ${this.drafts.get(member.id) ?? member.name}`;
            this.page.querySelector('[data-family-group-editor-choices]').innerHTML = this.groupChoices(this.memberProfile(member).group_ids, `data-family-member-group data-family-member="${esc(member.id)}"`, busy);
            this.groupEditor.hidden = false;
            if (this.groupEditor.showPopover && !this.groupEditor.matches(':popover-open')) this.groupEditor.showPopover();
            this.positionGroupEditor();
        }

        openGroupEditor(member) {
            if (!this.groupEditor || this.loading || this.pending.has(member.id)) return;
            this.groupEditorMemberId = member.id;
            this.render();
            (this.groupEditor.querySelector('input:not(:disabled)') || this.groupEditor).focus({preventScroll:true});
        }

        closeGroupEditor(restoreFocus = true) {
            const id = this.groupEditorMemberId;
            if (!id) return;
            this.groupEditorMemberId = '';
            if (this.groupEditor?.hidePopover && this.groupEditor.matches(':popover-open')) this.groupEditor.hidePopover();
            if (this.groupEditor) this.groupEditor.hidden = true;
            const row = this.memberRow(id);
            row?.classList.remove('is-group-editing');
            row?.querySelector('[data-family-edit-groups]')?.setAttribute('aria-expanded', 'false');
            if (restoreFocus) this.restoreFocus({memberId:id, control:'edit-groups'});
        }

        render() {
            const focused = this.focusState();
            const visible = this.visibleMembers();
            const active = this.members.filter(member => !member.archived).length;
            for (const [key, value] of Object.entries({total:this.members.length, active, archived:this.members.length - active, used:this.members.filter(member => member.meal_count > 0).length})) {
                this.page.querySelector(`[data-family-${key}]`).textContent = value;
            }
            this.page.querySelector('[data-family-visible-count]').textContent = `Showing ${visible.length} of ${this.members.length} family members.`;
            this.page.querySelector('[data-family-rows]').innerHTML = visible.map((member, index) => {
                const busy = this.loading || this.pending.has(member.id);
                const error = this.errors.get(member.id) || '';
                const disabled = busy ? ' disabled' : '';
                const values = this.memberProfile(member);
                const groupLabels = ids(values.group_ids).map(id => this.groups.find(group => group.id === id)).filter(Boolean);
                const invalidPortion = !!error && !positive(values.default_portion);
                const groupsOpen = this.groupEditorMemberId === member.id;
                return `<tr data-family-member-id="${esc(member.id)}" aria-busy="${busy}" class="${this.dirty(member) ? 'is-dirty' : ''}${groupsOpen ? ' is-group-editing' : ''}">
                    <td data-mobile-label="Display name"><label class="family-members-name"><span class="sr-only">Display name for ${esc(member.name)}</span>
                        <input type="text" value="${esc(this.drafts.get(member.id) ?? member.name)}" maxlength="100" required autocomplete="off" data-family-name aria-describedby="familyMemberError${index}"${error && !invalidPortion ? ' aria-invalid="true"' : ''}${disabled}>
                    </label><p id="familyMemberError${index}" class="family-members-error" role="alert"${error ? '' : ' hidden'}>${esc(error)}</p></td>
                    ${[['first_name','First name'],['last_name','Last name']].map(([field,label]) => `<td data-mobile-label="${label}"><input type="text" maxlength="100" value="${esc(values[field])}" placeholder="Optional" autocomplete="off" aria-label="${label} for ${esc(member.name)}" data-family-profile="${field}" data-family-focus="${esc(member.id)}:${field}"${disabled}></td>`).join('')}
                    <td data-mobile-label="Groups"><div class="family-members-group-badges"><span class="family-members-group-chip-list">${groupLabels.length ? groupLabels.map(group => `<span class="family-members-group-chip${group.archived ? ' is-archived' : ''}">${esc(group.name)}${group.archived ? ' (Archived)' : ''}</span>`).join('') : '<span class="family-members-help">Ungrouped</span>'}</span>
                        <button type="button" class="family-members-edit-groups" data-family-edit-groups aria-expanded="${groupsOpen}" aria-controls="familyMemberGroupEditor" aria-haspopup="dialog" aria-label="Edit groups for ${esc(member.name)}" title="Edit groups for ${esc(member.name)}"${disabled}>+</button></div></td>
                    <td data-mobile-label="Default portion"><input type="number" min="0" step="any" required value="${esc(values.default_portion)}" aria-label="Default portion for ${esc(member.name)}" aria-describedby="familyMemberError${index}"${invalidPortion ? ' aria-invalid="true"' : ''} data-family-profile="default_portion" data-family-focus="${esc(member.id)}:default_portion"${disabled}></td>
                    <td data-mobile-label="Status"><span class="family-members-badge${member.archived ? ' is-archived' : ''}">${member.archived ? 'Archived' : 'Active'}</span></td>
                    <td data-mobile-label="Used in meal plans">${Number(member.meal_count) || 0} scheduled ${(Number(member.meal_count) || 0) === 1 ? 'meal' : 'meals'}</td>
                    <td data-mobile-label="Actions"><div class="family-members-row-actions">
                        <button type="button" data-family-save aria-label="Save ${esc(member.name)}"${busy || !this.dirty(member) || !clean(this.drafts.get(member.id) ?? member.name) ? ' disabled' : ''}>Save</button>
                        <button type="button" data-family-cancel aria-label="Cancel changes to ${esc(member.name)}"${this.dirty(member) ? '' : ' hidden'}${disabled}>Cancel</button>
                        <button type="button" data-family-archive aria-label="${member.archived ? 'Restore' : 'Archive'} ${esc(member.name)}"${disabled}>${member.archived ? 'Restore' : 'Archive'}</button>
                    </div></td></tr>`;
            }).join('');
            const empty = this.page.querySelector('[data-family-empty]');
            empty.hidden = visible.length > 0;
            empty.textContent = this.loading ? 'Loading family members…' : this.search.trim() || this.groupFilter !== 'all' ? 'No members match your filters.' : this.filter === 'archived' ? 'No archived members.' : this.members.length ? 'No active family members. Add a member or restore one from Archived.' : 'No family members yet. Add your first member to start planning individual portions.';
            this.page.querySelector('[data-family-refresh]').disabled = this.loading || this.creating || this.bulkBusy || this.groupCreating || this.pending.size > 0 || this.groupPending.size > 0;
            this.page.querySelector('[data-family-add]').disabled = this.loading || this.creating;
            this.page.querySelector('[data-family-create]').querySelectorAll('input, button').forEach(node => { node.disabled = this.loading || this.creating; });
            this.page.querySelector('[data-family-rows]').setAttribute('aria-busy', String(this.loading));
            this.renderExtras();
            this.syncGroupEditor();
            this.restoreFocus(focused);
        }

        renderExtras() {
            const filter = this.page.querySelector('[data-family-group-filter]');
            filter.innerHTML = '<option value="all">All groups</option><option value="ungrouped">Ungrouped</option>'
                + this.groups.map(group => `<option value="${esc(group.id)}">${esc(group.name)}${group.archived ? ' (Archived)' : ''}</option>`).join('');
            filter.value = this.groupFilter;
            this.page.querySelector('[data-family-create-groups]').innerHTML = this.groupChoices(this.createGroups, 'data-family-create-group', this.loading || this.creating);
            this.page.querySelector('[data-family-bulk-groups]').innerHTML = this.groupChoices(this.bulkGroups, 'data-family-bulk-group', this.loading || this.bulkBusy);
            this.page.querySelector('[data-family-group-count]').textContent = this.groups.length;
            this.page.querySelector('[data-family-groups]').innerHTML = this.groups.length ? this.groups.map(group => {
                const busy = this.loading || this.groupPending.has(group.id), disabled = busy ? ' disabled' : '';
                const name = this.groupDrafts.get(group.id) ?? group.name;
                return `<div class="family-members-group-row" data-family-group-id="${esc(group.id)}">
                    <label><span class="sr-only">Group name for ${esc(group.name)}</span><input type="text" value="${esc(name)}" maxlength="100" required data-family-group-name data-family-focus="group:${esc(group.id)}"${disabled}></label>
                    <span class="family-members-badge${group.archived ? ' is-archived' : ''}">${group.archived ? 'Archived' : 'Active'}</span>
                    <div class="family-members-row-actions"><button type="button" data-family-group-save${busy || clean(name) === group.name || !clean(name) ? ' disabled' : ''}>Save group</button><button type="button" data-family-group-archive${disabled}>${group.archived ? 'Restore' : 'Archive'}</button></div>
                    <p class="family-members-error" role="alert"${this.groupErrors.has(group.id) ? '' : ' hidden'}>${esc(this.groupErrors.get(group.id) || '')}</p></div>`;
            }).join('') : '<p class="family-members-help">No groups yet.</p>';
            this.page.querySelector('[data-family-group-create]').querySelectorAll('input, button').forEach(node => { node.disabled = this.loading || this.groupCreating; });
            const bulkDisabled = this.loading || this.bulkBusy ? ' disabled' : '';
            this.page.querySelector('[data-family-bulk-rows]').innerHTML = this.bulkRows.map((row, index) => `<div class="family-members-bulk-person" data-family-bulk-row="${row.key}">
                <strong>Person ${index + 1}</strong><div class="family-members-profile-fields">${[['name','Display name'],['first_name','First name (optional)'],['last_name','Last name (optional)'],['default_portion','Default portion']].map(([field,label]) => `<label>${label}<input type="${field === 'default_portion' ? 'number' : 'text'}" ${field === 'default_portion' ? 'min="0" step="any"' : 'maxlength="100"'}${['name','default_portion'].includes(field) ? ' required' : ''} value="${esc(row[field])}" data-family-bulk-field="${field}" data-family-focus="bulk:${row.key}:${field}"${bulkDisabled}></label>`).join('')}</div><button type="button" data-family-bulk-remove="${row.key}" aria-label="Remove person ${index + 1}"${this.bulkRows.length === 1 ? ' disabled' : bulkDisabled}>Remove</button></div>`).join('');
            this.page.querySelector('[data-family-bulk-submit]').textContent = `Add ${this.bulkRows.length} ${this.bulkRows.length === 1 ? 'person' : 'people'}`;
            this.page.querySelector('[data-family-bulk]').querySelectorAll('button').forEach(node => { node.disabled = this.loading || this.bulkBusy || (node.matches('[data-family-bulk-remove]') && this.bulkRows.length === 1) || (node.matches('[data-family-bulk-add-row]') && this.bulkRows.length >= 100); });
            this.page.querySelector('[data-family-add-bulk]').disabled = this.loading || this.bulkBusy;
        }

        async request(suffix, options = {}, groups = false) {
            const raw = (groups ? this.page.dataset.groupsApiUrl : this.page.dataset.apiUrl) + suffix;
            const url = typeof root.withCanonicalViewerUserId === 'function' ? root.withCanonicalViewerUserId(raw) : raw;
            const response = await root.fetch(url, {credentials:'same-origin', ...options});
            let data;
            try { data = await response.json(); } catch (_error) { throw new Error('Unable to read the response. Please try again.'); }
            if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to save family members. Please try again.');
            return data;
        }

        async load() {
            if (this.loading || this.creating || this.bulkBusy || this.pending.size || this.groupPending.size || this.groupCreating) return;
            const focused = this.focusState();
            this.loading = true;
            this.setStatus('Loading family members…');
            this.render();
            try {
                const data = await this.request('?include_archived=true');
                if (!Array.isArray(data.members)) throw new Error('Unable to load family members. Please try again.');
                this.members = data.members;
                if (Array.isArray(data.groups)) this.groups = data.groups;
                this.setStatus('Family members refreshed.');
            } catch (error) { this.setStatus(error.message, true); }
            finally {
                const returnFocus = focused && this.mayReturnFocus(focused.memberId);
                this.loading = false;
                this.render();
                if (returnFocus) this.restoreFocus(focused);
            }
        }

        openCreate(open, focus = true) {
            if (this.creating) return;
            const form = this.page.querySelector('[data-family-create]');
            form.hidden = !open;
            this.page.querySelector('[data-family-add]').setAttribute('aria-expanded', String(open));
            if (focus) {
                if (open) form.querySelector('input').focus();
                else this.page.querySelector('[data-family-add]').focus();
            }
        }

        async create() {
            if (this.creating || this.loading) return;
            const form = this.page.querySelector('[data-family-create]');
            if (!form.reportValidity()) return;
            const input = form.querySelector('input');
            const name = clean(input.value);
            const fields = {name, first_name:clean(form.querySelector('[name="first_name"]')?.value), last_name:clean(form.querySelector('[name="last_name"]')?.value), default_portion:Number(form.querySelector('[name="default_portion"]')?.value ?? 1), group_ids:ids(this.createGroups)};
            const errorNode = form.querySelector('[data-family-create-error]');
            const mayReturnFocus = () => !document.activeElement || document.activeElement === document.body || form.contains?.(document.activeElement);
            errorNode.hidden = true;
            if (!name) { errorNode.textContent = 'Enter a family member name.'; errorNode.hidden = false; input.focus(); return; }
            if (!positive(fields.default_portion)) { errorNode.textContent = 'Default portion must be greater than zero.'; errorNode.hidden = false; return; }
            this.creating = true;
            form.querySelectorAll('input, button').forEach(node => { node.disabled = true; });
            form.setAttribute('aria-busy', 'true');
            this.page.querySelector('[data-family-refresh]').disabled = true;
            this.page.querySelector('[data-family-add]').disabled = true;
            let returnToAdd = false;
            try {
                const data = await this.request('', json(fields));
                this.members.push(data.member);
                input.value = '';
                form.querySelector('[name="first_name"]').value = '';
                form.querySelector('[name="last_name"]').value = '';
                form.querySelector('[name="default_portion"]').value = 1;
                this.createGroups = [];
                this.search = '';
                this.filter = 'active';
                this.groupFilter = 'all';
                this.page.querySelector('[data-family-search]').value = '';
                this.page.querySelector('[data-family-filter]').value = 'active';
                this.setStatus(`${data.member.name} added.`);
                this.creating = false;
                returnToAdd = mayReturnFocus();
                this.openCreate(false, false);
            } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
            finally {
                this.creating = false;
                form.querySelectorAll('input, button').forEach(node => { node.disabled = false; });
                form.setAttribute('aria-busy', 'false');
                this.render();
                if (returnToAdd) this.page.querySelector('[data-family-add]').focus();
                if (!errorNode.hidden && mayReturnFocus()) input.focus();
            }
        }

        openBulk(open, focus = true) {
            if (this.bulkBusy) return;
            this.page.querySelector('[data-family-bulk]').hidden = !open;
            this.page.querySelector('[data-family-add-bulk]').setAttribute('aria-expanded', String(open));
            if (focus) {
                if (open) this.restoreFocus({key:`bulk:${this.bulkRows[0].key}:name`});
                else this.page.querySelector('[data-family-add-bulk]').focus();
            }
        }

        async createBulk() {
            if (this.bulkBusy || this.loading) return;
            const form = this.page.querySelector('[data-family-bulk]');
            const errorNode = this.page.querySelector('[data-family-bulk-error]');
            errorNode.hidden = true;
            if (!form.reportValidity()) return;
            const invalid = this.bulkRows.findIndex(row => !clean(row.name) || !positive(row.default_portion));
            if (invalid >= 0) { errorNode.textContent = `Person ${invalid + 1} needs a display name and a portion greater than zero.`; errorNode.hidden = false; return; }
            const payload = {members:this.bulkRows.map(row => ({name:clean(row.name), first_name:clean(row.first_name), last_name:clean(row.last_name), default_portion:Number(row.default_portion)})), group_ids:ids(this.bulkGroups)};
            this.bulkBusy = true;
            form.setAttribute('aria-busy', 'true');
            this.render();
            let returnToAdd = false;
            try {
                const data = await this.request('/bulk', json(payload));
                this.members.push(...data.members);
                const added = data.members.length;
                this.bulkRows = []; this.addBulkRow(); this.addBulkRow(); this.bulkGroups = [];
                this.filter = 'active'; this.groupFilter = 'all'; this.search = '';
                this.page.querySelector('[data-family-filter]').value = 'active';
                this.page.querySelector('[data-family-search]').value = '';
                this.setStatus(`${added} ${added === 1 ? 'person' : 'people'} added.`);
                this.bulkBusy = false;
                returnToAdd = !document.activeElement || document.activeElement === document.body || form.contains?.(document.activeElement);
                this.openBulk(false, false);
            } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
            finally {
                this.bulkBusy = false; form.setAttribute('aria-busy', 'false'); this.render();
                if (returnToAdd) this.page.querySelector('[data-family-add-bulk]').focus();
            }
        }

        async createGroup() {
            if (this.groupCreating || this.loading) return;
            const form = this.page.querySelector('[data-family-group-create]');
            const input = form.querySelector('input');
            const errorNode = this.page.querySelector('[data-family-group-create-error]');
            errorNode.hidden = true;
            if (!form.reportValidity()) return;
            const name = clean(input.value);
            if (!name) { errorNode.textContent = 'Enter a group name.'; errorNode.hidden = false; return; }
            this.groupCreating = true; this.render();
            try {
                const data = await this.request('', json({name}), true);
                this.groups.push(data.group); input.value = '';
                this.setStatus(`Group added: ${data.group.name}.`);
            } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
            finally { this.groupCreating = false; this.render(); }
        }

        async updateGroup(group, patch) {
            if (this.loading || this.groupPending.has(group.id)) return;
            this.groupPending.add(group.id); this.groupErrors.delete(group.id); this.render();
            try {
                const data = await this.request('/' + encodeURIComponent(group.id), {...json(patch), method:'PATCH'}, true);
                this.groups = this.groups.map(item => item.id === group.id ? {...item, ...data.group} : item);
                if (Object.hasOwn(patch, 'name')) this.groupDrafts.delete(group.id);
                this.setStatus(Object.hasOwn(patch, 'archived') ? `${data.group.name} ${patch.archived ? 'archived. Existing members stay associated.' : 'restored.'}` : `Group saved: ${data.group.name}.`);
            } catch (error) { this.groupErrors.set(group.id, error.message); this.setStatus(error.message, true); }
            finally {
                const mayFocus = !document.activeElement || document.activeElement === document.body || this.focusState()?.key === `group:${group.id}`;
                this.groupPending.delete(group.id); this.render();
                if (mayFocus) this.restoreFocus({key:`group:${group.id}`});
            }
        }

        async update(member, patch) {
            if (this.loading || this.pending.has(member.id)) return;
            this.pending.add(member.id);
            this.errors.delete(member.id);
            this.render();
            try {
                const data = await this.request('/' + encodeURIComponent(member.id), {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch)});
                this.members = this.members.map(item => item.id === member.id ? {...item, ...data.member} : item);
                if (Object.hasOwn(patch, 'name')) this.drafts.delete(member.id);
                if (Object.hasOwn(patch, 'default_portion')) this.profiles.delete(member.id);
                this.setStatus(Object.hasOwn(patch, 'archived') ? `${data.member.name} ${patch.archived ? 'archived. Existing meal plans are preserved.' : 'restored.'}` : `Member saved: ${data.member.name}.`);
            } catch (error) { this.errors.set(member.id, error.message); this.setStatus(error.message, true); }
            finally {
                this.pending.delete(member.id);
                const returnFocus = this.mayReturnFocus(member.id);
                this.render();
                if (returnFocus) {
                    const control = this.errors.has(member.id) || Object.hasOwn(patch, 'name') ? 'name' : 'archive';
                    if (!this.restoreFocus({memberId:member.id, control})) this.page.querySelector('[data-family-filter]').focus();
                }
            }
        }

        input(event) {
            const target = event.target;
            if (target.matches('[data-family-search]')) { this.search = target.value; this.render(); return; }
            if (target.matches('[data-family-bulk-field]')) {
                const row = this.bulkRows.find(item => item.key === target.closest('[data-family-bulk-row]').dataset.familyBulkRow);
                if (row) row[target.dataset.familyBulkField] = target.value;
                return;
            }
            if (target.matches('[data-family-group-name]')) {
                const id = target.closest('[data-family-group-id]').dataset.familyGroupId;
                this.groupDrafts.set(id, target.value);
                target.closest('[data-family-group-id]').querySelector('[data-family-group-save]').disabled = !clean(target.value) || clean(target.value) === this.groups.find(group => group.id === id)?.name;
                return;
            }
            if (target.matches('[data-family-profile]')) {
                const id = target.closest('[data-family-member-id]')?.dataset.familyMemberId;
                const member = this.members.find(item => item.id === id);
                if (!member || this.loading || this.pending.has(id)) return;
                this.profiles.set(id, {...this.memberProfile(member), [target.dataset.familyProfile]:target.value});
                this.syncMemberActions(member);
                return;
            }
            if (!target.matches('[data-family-name]')) return;
            const row = target.closest('[data-family-member-id]');
            const member = this.members.find(item => item.id === row.dataset.familyMemberId);
            if (!member) return;
            this.drafts.set(member.id, target.value);
            this.syncMemberActions(member);
        }

        syncMemberActions(member) {
            const row = [...this.page.querySelectorAll('[data-family-member-id]')].find(node => node.dataset.familyMemberId === member.id);
            if (!row) return;
            row.querySelector('[data-family-save]').disabled = !this.dirty(member) || !clean(this.drafts.get(member.id) ?? member.name);
            row.querySelector('[data-family-cancel]').hidden = !this.dirty(member);
            row.classList.toggle('is-dirty', this.dirty(member));
        }

        change(event) {
            const target = event.target;
            if (target.matches('[data-family-filter]')) { this.filter = target.value; this.render(); return; }
            if (target.matches('[data-family-group-filter]')) { this.groupFilter = target.value; this.render(); return; }
            const toggle = values => target.checked ? ids([...values, target.value]) : values.filter(id => id !== target.value);
            if (target.matches('[data-family-create-group]')) this.createGroups = toggle(this.createGroups);
            if (target.matches('[data-family-bulk-group]')) this.bulkGroups = toggle(this.bulkGroups);
            if (target.matches('[data-family-member-group]')) {
                const member = this.members.find(item => item.id === target.dataset.familyMember);
                if (!member || this.loading || this.pending.has(member.id)) return;
                const values = this.memberProfile(member);
                this.profiles.set(member.id, {...values, group_ids:toggle(values.group_ids)});
                this.render();
            }
        }

        saveRow(row, member) {
            const input = row.querySelector('[data-family-name]');
            if (!input.reportValidity() || !clean(input.value) || !this.dirty(member)) return;
            const patch = {name:clean(input.value)};
            if (this.profiles.has(member.id)) {
                const values = this.memberProfile(member);
                if (!positive(values.default_portion)) {
                    this.errors.set(member.id, 'Default portion must be greater than zero.');
                    this.render();
                    this.restoreFocus({key:`${member.id}:default_portion`});
                    return;
                }
                Object.assign(patch, {first_name:clean(values.first_name), last_name:clean(values.last_name), default_portion:Number(values.default_portion), group_ids:ids(values.group_ids)});
            }
            return this.update(member, patch);
        }

        click(event) {
            const button = event.target.closest('button');
            if (!button || button.disabled) return;
            if (button.matches('[data-family-close-groups]')) return this.closeGroupEditor();
            if (button.matches('[data-family-manage-groups]')) {
                this.closeGroupEditor(false);
                this.page.querySelector('[data-family-groups-section]').open = true;
                this.page.querySelector('[data-family-group-create]').querySelector('input').focus();
                return;
            }
            if (button.matches('[data-family-add]')) return this.openCreate(true);
            if (button.matches('[data-family-cancel-create]')) return this.openCreate(false);
            if (button.matches('[data-family-refresh]')) return this.load();
            if (button.matches('[data-family-add-bulk]')) return this.openBulk(true);
            if (button.matches('[data-family-cancel-bulk]')) return this.openBulk(false);
            if (button.matches('[data-family-bulk-add-row]')) {
                if (this.bulkBusy || this.bulkRows.length >= 100) return;
                this.addBulkRow(); this.render();
                this.restoreFocus({key:`bulk:${this.bulkRows.at(-1).key}:name`});
                return;
            }
            if (button.matches('[data-family-bulk-remove]')) {
                if (this.bulkBusy || this.bulkRows.length < 2) return;
                this.bulkRows = this.bulkRows.filter(row => row.key !== button.dataset.familyBulkRemove);
                this.render(); this.page.querySelector('[data-family-bulk-add-row]').focus(); return;
            }
            const groupRow = button.closest('[data-family-group-id]');
            if (groupRow) {
                const group = this.groups.find(item => item.id === groupRow.dataset.familyGroupId);
                if (!group) return;
                if (button.matches('[data-family-group-archive]')) return this.updateGroup(group, {archived:!group.archived});
                if (button.matches('[data-family-group-save]')) {
                    const input = groupRow.querySelector('[data-family-group-name]');
                    if (input.reportValidity() && clean(input.value)) return this.updateGroup(group, {name:clean(input.value)});
                }
                return;
            }
            const row = button.closest('[data-family-member-id]');
            const member = row && this.members.find(item => item.id === row.dataset.familyMemberId);
            if (!member) return;
            if (button.matches('[data-family-edit-groups]')) {
                return this.openGroupEditor(member);
            }
            if (button.matches('[data-family-save]')) return this.saveRow(row, member);
            if (button.matches('[data-family-archive]')) return this.update(member, {archived:!member.archived});
            if (button.matches('[data-family-cancel]')) this.cancelRow(member.id);
        }

        cancelRow(id) {
            this.drafts.delete(id);
            this.profiles.delete(id);
            this.errors.delete(id);
            this.render();
            [...this.page.querySelectorAll('[data-family-member-id]')].find(row => row.dataset.familyMemberId === id)?.querySelector('[data-family-name]').focus();
        }

        keydown(event) {
            if (this.groupEditorMemberId && event.key === 'Escape') {
                event.preventDefault(); event.stopPropagation(); this.closeGroupEditor(); return;
            }
            if (this.groupEditorMemberId && event.key === 'Tab' && this.groupEditor?.contains(event.target)) {
                const controls = [...this.groupEditor.querySelectorAll('button:not(:disabled), input:not(:disabled)')];
                if ((event.shiftKey && event.target === controls[0]) || (!event.shiftKey && event.target === controls.at(-1))) {
                    event.preventDefault();
                    const id = this.groupEditorMemberId;
                    this.closeGroupEditor(event.shiftKey);
                    if (!event.shiftKey) {
                        const row = this.memberRow(id);
                        const save = row?.querySelector('[data-family-save]');
                        (save && !save.disabled ? save : row?.querySelector('[data-family-profile="default_portion"]'))?.focus({preventScroll:true});
                    }
                    return;
                }
            }
            if (event.target.matches('[data-family-group-name]')) {
                const id = event.target.closest('[data-family-group-id]').dataset.familyGroupId;
                const group = this.groups.find(item => item.id === id);
                if (event.key === 'Enter' && group && clean(event.target.value) && event.target.reportValidity()) { event.preventDefault(); this.updateGroup(group, {name:clean(event.target.value)}); }
                if (event.key === 'Escape') { event.preventDefault(); this.groupDrafts.delete(id); this.groupErrors.delete(id); this.render(); }
                return;
            }
            if (!event.target.matches('[data-family-name]') && !event.target.matches('[data-family-profile]')) return;
            const row = event.target.closest('[data-family-member-id]');
            if (!row) return;
            const member = this.members.find(item => item.id === row.dataset.familyMemberId);
            if (!member || this.pending.has(member.id) || this.loading) return;
            if (event.key === 'Enter') { event.preventDefault(); this.saveRow(row, member); }
            if (event.key === 'Escape') { event.preventDefault(); this.cancelRow(member.id); }
        }
    }

    root.FamilyMembersPage = FamilyMembersPage;
    function init() {
        const page = document.querySelector('[data-family-members-page]');
        if (!page) return;
        let members = [], groups = [];
        try { members = JSON.parse(document.getElementById('familyMembersData').textContent); } catch (_error) { /* Refresh can recover missing initial data. */ }
        try { groups = JSON.parse(document.getElementById('familyGroupsData').textContent); } catch (_error) { /* Refresh also returns groups. */ }
        const controller = new FamilyMembersPage(page, members, groups);
        controller.load();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})(typeof window !== 'undefined' ? window : globalThis);
