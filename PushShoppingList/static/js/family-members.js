/* Manage the same scoped member records used by the Meal Planner. */
(function (root) {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
    const clean = value => String(value ?? '').trim().replace(/\s+/g, ' ');

    class FamilyMembersPage {
        constructor(page, members) {
            this.page = page;
            this.members = Array.isArray(members) ? members : [];
            this.drafts = new Map();
            this.errors = new Map();
            this.pending = new Set();
            this.loading = false;
            this.creating = false;
            this.search = '';
            this.filter = 'active';
            page.addEventListener('click', event => this.click(event));
            page.addEventListener('input', event => this.input(event));
            page.addEventListener('change', event => {
                if (event.target.matches('[data-family-filter]')) {
                    this.filter = event.target.value;
                    this.render();
                }
            });
            page.addEventListener('keydown', event => this.keydown(event));
            page.querySelector('[data-family-create]').addEventListener('submit', event => {
                event.preventDefault();
                this.create();
            });
            this.render();
        }

        visibleMembers() {
            const query = clean(this.search).toLocaleLowerCase();
            return this.members.filter(member => (this.filter === 'all' || !!member.archived === (this.filter === 'archived'))
                && String(member.name).toLocaleLowerCase().includes(query));
        }

        dirty(member) { return this.drafts.has(member.id) && clean(this.drafts.get(member.id)) !== member.name; }

        setStatus(message, error = false) {
            const status = this.page.querySelector('[data-family-status]');
            status.textContent = message;
            status.hidden = !message;
            status.classList.toggle('is-error', error);
        }

        focusState() {
            const element = document.activeElement;
            const row = element?.closest?.('[data-family-member-id]');
            if (!row) return null;
            const control = ['name', 'save', 'cancel', 'archive'].find(key => element.matches(`[data-family-${key}]`));
            return control ? {memberId:row.dataset.familyMemberId, control, start:element.selectionStart, end:element.selectionEnd} : null;
        }

        restoreFocus(state) {
            if (!state) return false;
            const row = [...this.page.querySelectorAll('[data-family-member-id]')].find(node => node.dataset.familyMemberId === state.memberId);
            const control = row?.querySelector(`[data-family-${state.control}]`);
            if (!control || control.disabled || control.hidden) return false;
            control.focus({preventScroll:true});
            if (state.control === 'name' && state.start != null) control.setSelectionRange?.(state.start, state.end);
            return true;
        }

        mayReturnFocus(memberId) {
            const active = document.activeElement;
            return !active || active === document.body || this.focusState()?.memberId === memberId;
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
                return `<tr data-family-member-id="${esc(member.id)}" aria-busy="${busy}">
                    <td data-mobile-label="Name"><label class="family-members-name"><span class="sr-only">Name for ${esc(member.name)}</span>
                        <input type="text" value="${esc(this.drafts.get(member.id) ?? member.name)}" maxlength="100" required autocomplete="off" data-family-name aria-describedby="familyMemberError${index}"${error ? ' aria-invalid="true"' : ''}${disabled}>
                    </label><p id="familyMemberError${index}" class="family-members-error" role="alert"${error ? '' : ' hidden'}>${esc(error)}</p></td>
                    <td data-mobile-label="Status"><span class="family-members-badge${member.archived ? ' is-archived' : ''}">${member.archived ? 'Archived' : 'Active'}</span></td>
                    <td data-mobile-label="Used in meal plans">${Number(member.meal_count) || 0} scheduled ${(Number(member.meal_count) || 0) === 1 ? 'meal' : 'meals'}</td>
                    <td data-mobile-label="Actions"><div class="family-members-row-actions">
                        <button type="button" data-family-save aria-label="Save name for ${esc(member.name)}"${busy || !this.dirty(member) || !clean(this.drafts.get(member.id)) ? ' disabled' : ''}>Save</button>
                        <button type="button" data-family-cancel aria-label="Cancel changes to ${esc(member.name)}"${this.dirty(member) ? '' : ' hidden'}${disabled}>Cancel</button>
                        <button type="button" data-family-archive aria-label="${member.archived ? 'Restore' : 'Archive'} ${esc(member.name)}"${disabled}>${member.archived ? 'Restore' : 'Archive'}</button>
                    </div></td></tr>`;
            }).join('');
            const empty = this.page.querySelector('[data-family-empty]');
            empty.hidden = visible.length > 0;
            empty.textContent = this.loading ? 'Loading family members…' : this.search.trim() ? 'No members match your search.' : this.filter === 'archived' ? 'No archived members.' : this.members.length ? 'No active family members. Add a member or restore one from Archived.' : 'No family members yet. Add your first member to start planning individual portions.';
            this.page.querySelector('[data-family-refresh]').disabled = this.loading || this.creating || this.pending.size > 0;
            this.page.querySelector('[data-family-add]').disabled = this.loading || this.creating;
            this.page.querySelector('[data-family-create]').querySelectorAll('input, button').forEach(node => { node.disabled = this.loading || this.creating; });
            this.page.querySelector('[data-family-rows]').setAttribute('aria-busy', String(this.loading));
            this.restoreFocus(focused);
        }

        async request(suffix, options = {}) {
            const raw = this.page.dataset.apiUrl + suffix;
            const url = typeof root.withCanonicalViewerUserId === 'function' ? root.withCanonicalViewerUserId(raw) : raw;
            const response = await root.fetch(url, {credentials:'same-origin', ...options});
            let data;
            try { data = await response.json(); } catch (_error) { throw new Error('Unable to read the response. Please try again.'); }
            if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to save family members. Please try again.');
            return data;
        }

        async load() {
            if (this.loading || this.creating || this.pending.size) return;
            const focused = this.focusState();
            this.loading = true;
            this.setStatus('Loading family members…');
            this.render();
            try {
                const data = await this.request('?include_archived=true');
                if (!Array.isArray(data.members)) throw new Error('Unable to load family members. Please try again.');
                this.members = data.members;
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
            const errorNode = form.querySelector('[data-family-create-error]');
            const mayReturnFocus = () => !document.activeElement || document.activeElement === document.body || form.contains?.(document.activeElement);
            errorNode.hidden = true;
            if (!name) { errorNode.textContent = 'Enter a family member name.'; errorNode.hidden = false; input.focus(); return; }
            this.creating = true;
            form.querySelectorAll('input, button').forEach(node => { node.disabled = true; });
            form.setAttribute('aria-busy', 'true');
            this.page.querySelector('[data-family-refresh]').disabled = true;
            this.page.querySelector('[data-family-add]').disabled = true;
            try {
                const data = await this.request('', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
                this.members.push(data.member);
                input.value = '';
                this.search = '';
                this.filter = 'active';
                this.page.querySelector('[data-family-search]').value = '';
                this.page.querySelector('[data-family-filter]').value = 'active';
                this.setStatus(`${data.member.name} added.`);
                this.creating = false;
                this.openCreate(false, mayReturnFocus());
            } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
            finally {
                this.creating = false;
                form.querySelectorAll('input, button').forEach(node => { node.disabled = false; });
                form.setAttribute('aria-busy', 'false');
                this.render();
                if (!errorNode.hidden && mayReturnFocus()) input.focus();
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
                this.setStatus(Object.hasOwn(patch, 'archived') ? `${data.member.name} ${patch.archived ? 'archived. Existing meal plans are preserved.' : 'restored.'}` : `Name saved: ${data.member.name}.`);
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
            if (!target.matches('[data-family-name]')) return;
            const row = target.closest('[data-family-member-id]');
            const member = this.members.find(item => item.id === row.dataset.familyMemberId);
            if (!member) return;
            this.drafts.set(member.id, target.value);
            row.querySelector('[data-family-save]').disabled = !this.dirty(member) || !clean(target.value);
            row.querySelector('[data-family-cancel]').hidden = !this.dirty(member);
        }

        saveRow(row, member) {
            const input = row.querySelector('[data-family-name]');
            if (!input.reportValidity() || !clean(input.value) || !this.dirty(member)) return;
            return this.update(member, {name:clean(input.value)});
        }

        click(event) {
            const button = event.target.closest('button');
            if (!button || button.disabled) return;
            if (button.matches('[data-family-add]')) return this.openCreate(true);
            if (button.matches('[data-family-cancel-create]')) return this.openCreate(false);
            if (button.matches('[data-family-refresh]')) return this.load();
            const row = button.closest('[data-family-member-id]');
            const member = row && this.members.find(item => item.id === row.dataset.familyMemberId);
            if (!member) return;
            if (button.matches('[data-family-save]')) return this.saveRow(row, member);
            if (button.matches('[data-family-archive]')) return this.update(member, {archived:!member.archived});
            if (button.matches('[data-family-cancel]')) this.cancelRow(member.id);
        }

        cancelRow(id) {
            this.drafts.delete(id);
            this.errors.delete(id);
            this.render();
            [...this.page.querySelectorAll('[data-family-member-id]')].find(row => row.dataset.familyMemberId === id)?.querySelector('[data-family-name]').focus();
        }

        keydown(event) {
            if (!event.target.matches('[data-family-name]')) return;
            const row = event.target.closest('[data-family-member-id]');
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
        let members = [];
        try { members = JSON.parse(document.getElementById('familyMembersData').textContent); } catch (_error) { /* Refresh can recover missing initial data. */ }
        const controller = new FamilyMembersPage(page, members);
        controller.load();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})(typeof window !== 'undefined' ? window : globalThis);
