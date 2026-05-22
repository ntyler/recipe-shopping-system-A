/****************************************************************************************
  Module:		chat.js
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pkulkarni@opentext.com
  Manager:		pblaimschein@opentext.com
  Created:		11/18/2025 (mm/dd/yyyy)
*****************************************************************************************/

var chat = {
	// ==================== Configuration ====================
	ERROR_STRING_CONTEXTLOST: chrome.i18n.getMessage('PII_ERROR_LOSTCONTEXT'),
	DEBOUNCE_MS: 500,
	MIN_CONFIDENCE_SCORE: 0.7,
	editableSelectors: 'input[type="text"], textarea, [contenteditable="true"]',
	PLATFORM_CONFIGS: [
		{
			hosts: ["chatgpt.com", "chat.openai.com"],
			textarea: "#prompt-textarea",
			submitBtn: ".composer-submit-button, #composer-submit-button",
			// Stable container that doesn't resize when textarea grows
			composerContainer: "form, div.bg-token-main-surface-tertiary",
			requiresTextareaCheck: false,
			charLimit: 8000
		},
		{
			hosts: ["gemini.google.com"],
			textarea: ".ql-editor.textarea.new-input-ui,.ql-editor.ql-blank.textarea.new-input-ui",
			submitBtn: ".send-button",
			composerContainer: "div.text-input-field",
			requiresTextareaCheck: false,
			charLimit: 8000
		},
		{
			hosts: ["google.com", "www.google.com"],
			textarea: ".ITIRGe",
			submitBtn: ".uMMzHc.OEueve",
			composerContainer: "div.AgWCw",
			requiresTextareaCheck: true,
			charLimit: 8000
		}
	],
	isAISite: function () {
		this.currentConfig = this.getPlatformConfig();
		if (!this.currentConfig) {
			return false;
		}
		if (!this.currentConfig.textarea || typeof this.currentConfig.textarea !== 'string' || this.currentConfig.textarea.trim() === '') {
			this.sendPIIException(1);
			return false;
		}
		// Some platforms need textarea check to avoid false positives (e.g., google.com)
		if (this.currentConfig.requiresTextareaCheck) {
			return document.querySelector(this.currentConfig.textarea) !== null;
		}
		return true;
	},
	// ==================== State Management ====================
	contextLost: false,
	ctxPopup: null,
	ctxIndicator: null,
	currentConfig: null,
	currentProviderType: null,
	elementObservers: new WeakMap(),
	observedElements: new WeakMap(),
	scanningInProgress: new WeakSet(),
	ignoredPII: new WeakMap(),

	// Redaction-related state
	autoRedactMode: false, // set to true to auto-redact on send/enter
	isSynthetic: false,
	isActivated: false,

	isContextLost: function () {
		if (!chrome?.runtime?.id) {
			console.log('Extension context lost! Either because the extension was stopped or restarted; please refresh the page!');
			if (!this.contextLost) {
				this.contextLost = true;
				this.shutdownPII(true);
			}
			return true;
		}
		return false;
	},
	shutdownPII: function (showContextWarning) {
		const el = this.ctxIndicator?._el;

		this.hidePIIPopup();
		this.hidePIIIndicator();
		if (el) {
			if (showContextWarning) this.showContextWarning(el);
			this.removeOverlays(el);
			if (el._piiParentObserver) { el._piiParentObserver.disconnect(); delete el._piiParentObserver; }
			delete el._piiParentObserverTarget;
			clearTimeout(el._overlayRefreshTimer);
			delete el.piiMatches;
			delete el.lastScannedText;
			delete el.piiOverlayId;
			delete el.reportedPII;
			this.ignoredPII.delete(el);
		}

		try {
			localStorage.setItem("WTS_IsContextLost", "1");
		} catch (e) {
			console.log("WTS: Error writing 'IsContextLost' to localStorage - error:", e);
		}
	},
	// ==================== Initialization ====================
	identifyText: function() {
		if (window !== window.top) return; // only run in top-level window
		Webroot_Extension.Log("chat PII script loaded and starting...");
		if (!this.isAISite()) {
			Webroot_Extension.Log("Not an AI site — PII Detetction and Redaction disabled");
			return;
		}
		chrome.storage.local.get(['Settings', 'Mode'], (r) => {
			if (r?.Settings?.VERSION == 1 && r.Mode && r.Mode != 0 && r.Settings.ERR != 51) {
				this.isActivated = true;
				Webroot_Extension.Log("AI site detected — PII Detetction and Redaction enabled");
				this.createPIIPopup();
				this.createPIIIndicator();
				this.startListeners();
				this.setupOverlayRepositioning();
				this.setupOverlayHover();
				let wasContextLost = localStorage.getItem("WTS_IsContextLost") === "1";
				if (wasContextLost) {
					this.sendFeedbackCounter('US_SSN', true);  //Use SSN positive fb counter to indicate context lost
					this.incrementPIISDKCalls();  //To cope with counter api (SDK-Calls field is mandatory)
					localStorage.removeItem("WTS_IsContextLost");
				}
			} else Webroot_Extension.Log("PII Detection disabled - no valid keycode");
		});
	},
	createPIIPopup: function () {
		if (document.getElementById('wts-pii-ctx-popup')) return;

		const popup = document.createElement('div');
		popup.id = 'wts-pii-ctx-popup';
		popup.className = 'wts-ctx-popup';
		popup.setAttribute('role', 'status');
		popup.setAttribute('aria-hidden', 'true');

		const popup2 = document.createElement('div');

		// ****************************** head line section ******************************
		const popupHeadline = document.createElement('div');
		popupHeadline.className = 'wts-ctx-popupHead';
		popup._popupDivHeadline = popupHeadline;
		// img red exclamation mark
		const imgHeadline = document.createElement('img');
		imgHeadline.src = chrome.runtime.getURL('images/chat/bad.svg');
		// span for detect Information
		const spanHeadline = document.createElement('span');
		spanHeadline.textContent = chrome.i18n.getMessage('PII_POPUP_HEADLINE'); //"Detect Information"

		popupHeadline.appendChild(imgHeadline);
		popupHeadline.appendChild(spanHeadline);
		popup2.appendChild(popupHeadline);

		// ******************************* PII section *******************************
		const popupPII = document.createElement('div');
		popupPII.className = 'wts-ctx-popupPII';
		// span PII type
		const spanPIIType = document.createElement('span');
		spanPIIType.textContent = "";
		popup._popupSpanPIIType = spanPIIType;
		// span for PII item found
		const spanPIIValue = document.createElement('span');
		spanPIIValue.textContent = "";
		popup._popupSpanPIIValue = spanPIIValue;
		// button redact
		const buttonRedact = document.createElement('button');
		buttonRedact.textContent = chrome.i18n.getMessage('PII_POPUP_REDACT');
		popup._popupButtonRedact = buttonRedact;
		popup._pendingRedactAction = false;
		popup._pendingUnmarkAction = false;
		buttonRedact.addEventListener('click', this.onPIIPopupRedactButton.bind(this));

		popupPII.appendChild(spanPIIType);
		popupPII.appendChild(spanPIIValue);
		popupPII.appendChild(buttonRedact);
		popup2.appendChild(popupPII);
		popup.appendChild(popup2);

		// **************************** accurate section ****************************
		const popupAcc = document.createElement('div');
		popupAcc.className = 'wts-ctx-popupAccurate';
		const popupAcc2 = document.createElement('span');
		// span for text
		const spanAcc = document.createElement('span');
		spanAcc.textContent = chrome.i18n.getMessage('PII_POPUP_ACCURATE'); //"Is this information accurate?"
		spanAcc.id = "wts-ctx-popupAccurateText";
		const spanAccDone = document.createElement('span');
		spanAccDone.id = "wts-ctx-popupAccurateDoneText";
		spanAccDone.className = 'AccurateHide';
		spanAccDone.textContent = chrome.i18n.getMessage('PII_POPUP_ACCURATE_DONE'); //"Thank you for your feedback."
		// img thumbs up
		const imgAcc1 = document.createElement('img');
		imgAcc1.id = "wts-ctx-popupAccurateThumbUpImg";
		imgAcc1.className = 'thumb';
		imgAcc1.src = chrome.runtime.getURL('images/chat/thup.svg');
		imgAcc1.addEventListener('click', this.onPIIPopupThumbs.bind(this));
		// img thumbs down
		const imgAcc2 = document.createElement('img');
		imgAcc2.id = "wts-ctx-popupAccurateThumbDownImg";
		imgAcc2.className = 'thumb';
		imgAcc2.src = chrome.runtime.getURL('images/chat/thdn.svg');
		imgAcc2.addEventListener('click', this.onPIIPopupThumbs.bind(this));
		// img thumbsUp done
		const imgAccDoneUp = document.createElement('img');
		imgAccDoneUp.id = "wts-ctx-popupAccurateThumbUpDoneImg";
		imgAccDoneUp.classList.add('thumb', 'AccurateHide');
		imgAccDoneUp.src = chrome.runtime.getURL('images/chat/thupdone.svg');
		imgAccDoneUp.addEventListener('click', this.onPIIPopupThumbs.bind(this));
		// img thumbsDn done
		const imgAccDoneDn = document.createElement('img');
		imgAccDoneDn.id = "wts-ctx-popupAccurateThumbDownDoneImg";
		imgAccDoneDn.classList.add('thumb', 'AccurateHide');
		imgAccDoneDn.src = chrome.runtime.getURL('images/chat/thdndone.svg');
		imgAccDoneDn.addEventListener('click', this.onPIIPopupThumbs.bind(this));
		popupAcc2.appendChild(spanAcc);
		popupAcc2.appendChild(spanAccDone);
		popupAcc2.appendChild(imgAcc1);
		popupAcc2.appendChild(imgAcc2);
		popupAcc2.appendChild(imgAccDoneUp);
		popupAcc2.appendChild(imgAccDoneDn);
		popupAcc.appendChild(popupAcc2);
		// img logo
		const imgAccLogo = document.createElement('img');
		imgAccLogo.src = chrome.runtime.getURL('images/Webroot.svg');
		imgAccLogo.height = '18';
		popupAcc.appendChild(imgAccLogo);
		popup.appendChild(popupAcc);

		// **************************** RedactAll section ****************************
		const popupAll = document.createElement('div');
		popupAll.className = 'wts-ctx-popupAll';
		popup._popupSpanAll = popupAll;
		const popupAll2 = document.createElement('span');
		// img arrow left
		const imgArrowLeft = document.createElement('img');
		imgArrowLeft.src = chrome.runtime.getURL('images/chat/aleft.svg');
		imgArrowLeft.id = "wts-ctx-popupArrowLeftImg";
		imgArrowLeft.addEventListener('click', this.onPIIPopupArrows.bind(this));
		const imgArrowRight = document.createElement('img');
		imgArrowRight.id = "wts-ctx-popupArrowRightImg";
		imgArrowRight.src = chrome.runtime.getURL('images/chat/aright.svg');
		imgArrowRight.addEventListener('click', this.onPIIPopupArrows.bind(this));
		const spanItemNumbers = document.createElement('span');
		spanItemNumbers.textContent = '1/1';
		popup._popupSpanAllNumbers = spanItemNumbers;
		popupAll2.appendChild(imgArrowLeft);
		popupAll2.appendChild(imgArrowRight);
		popupAll2.appendChild(spanItemNumbers);
		popupAll.appendChild(popupAll2);
		const buttonRedactAll = document.createElement('button');
		buttonRedactAll.textContent = "Redact all"; //chrome.i18n.getMessage('PII_POPUP_REDACT');
		buttonRedactAll.addEventListener('click', this.onPIIPopupRedactAllButton.bind(this));
		popupAll.appendChild(buttonRedactAll);
		popup.appendChild(popupAll);

		// finalize
		popup._undoInfo = {};
		popup._el = null;
		popup._matchRef = null;
		document.body.appendChild(popup);
		this.ctxPopup = popup;

		// Hide menu if clicking outside or pressing Escape
		document.addEventListener('click', (e) => {
			if (this.ctxIndicator && this.ctxIndicator.contains(e.target)) {
				if (popup.style.visibility === 'visible') this.hidePIIPopup();
				else this.showPIIPopupFromIndicator();
			}
			else if (!popup.contains(e.target)) {
				if ((popup.style.visibility === 'visible') &&
					(popup._popupSpanAll.style.display != 'none')) {
					this.hidePIIPopup();
				}
			}
		});
		document.addEventListener('keyup', (e) => {
			if (e.key === 'Escape') this.hidePIIPopup();
		});
	},
	createPIIIndicator: function() {
		if (document.getElementById('wts-pii-ctx-indicator')) return;

		const divIndicator = document.createElement('div');
		divIndicator.id = 'wts-pii-ctx-indicator';
		divIndicator.className = 'wts-ctx-indicator';
		divIndicator.setAttribute('role', 'status');
		divIndicator.setAttribute('aria-hidden', 'true');
		const divIndicatorSub = document.createElement('div');
		const imgLogo = document.createElement('img');
		imgLogo.src = chrome.runtime.getURL('images/Webroot.svg');
		const spanPIIType = document.createElement('span');
		spanPIIType.textContent = "";
		divIndicator._spanPIIType = spanPIIType;
		const imgBad = document.createElement('img');
		imgBad.src = chrome.runtime.getURL('images/chat/bad.svg');
		const spanCount = document.createElement('span');
		spanCount.textContent = "";
		divIndicator._spanPlusCount = spanCount;
		divIndicatorSub.appendChild(imgLogo);
		divIndicatorSub.appendChild(spanPIIType);
		divIndicatorSub.appendChild(imgBad);
		divIndicatorSub.appendChild(spanCount);

		divIndicator._el = null;
		divIndicator._SelectedPIIIndex = 0;
		divIndicator._PopupOpen = false;
		divIndicator.appendChild(divIndicatorSub);
		document.body.appendChild(divIndicator);
		this.ctxIndicator = divIndicator;
	},
	setupOverlayRepositioning: function() {
		let rafId;
		const reposition = (evnt) => {
			if (rafId) cancelAnimationFrame(rafId);
			rafId = requestAnimationFrame(() => {
				const charLimit = this.currentConfig?.charLimit || 8000;
				document.querySelectorAll(this.editableSelectors).forEach(el => {
					if (el.piiMatches?.length) {
						if (!el.offsetParent) {
							this.removeOverlays(el);
						} else {
							// Cap overlay text to charLimit to avoid expensive DOM walks on huge content
							const raw = el.lastScannedText || '';
							const overlayText = raw.length > charLimit ? raw.substring(0, charLimit) : raw;
							this.createOrUpdateOverlay(el, overlayText, el.piiMatches);
						}
					}
				});
			});
			this.hidePIIPopup(evnt);
			this.updatePIIIndicator(true);
		};
		window.addEventListener('scroll', reposition, true);
		window.addEventListener('resize', reposition);

		const redrawOverlaysForThemeChange = () => {
			// Small delay to allow page styles to update after theme change
			setTimeout(() => {
				document.querySelectorAll(this.editableSelectors).forEach(el => {
					if (el.piiMatches?.length && el.offsetParent) {
						// Clear cached segment rects so isDark is re-evaluated from scratch
						el.piiMatches.forEach(m => { delete m._segCachedRects; delete m.cachedRects; delete m.cacheKey; });
						// Remove and recreate overlays to force full redraw
						this.removeOverlays(el);
						this.createOrUpdateOverlay(el, el.lastScannedText || '', el.piiMatches);
					}
				});
			}, 100);
		};

		// Listen for system color scheme changes
		const colorSchemeQuery = window.matchMedia('(prefers-color-scheme: dark)');
		colorSchemeQuery.addEventListener('change', redrawOverlaysForThemeChange);

		const themeObserver = new MutationObserver((mutations) => {
			for (const mutation of mutations) {
				if (mutation.type === 'attributes' && 
					(mutation.attributeName === 'class' || 
					 mutation.attributeName === 'data-theme' || 
					 mutation.attributeName === 'data-color-mode' ||
					 mutation.attributeName === 'style')) {
					redrawOverlaysForThemeChange();
					break;
				}
			}
		});
		
		if (document.documentElement) {
			themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'data-color-mode', 'style'] });
		}
		if (document.body) {
			themeObserver.observe(document.body, { attributes: true, attributeFilter: ['class', 'data-theme', 'data-color-mode', 'style'] });
		}

		let textareaCheckPending = false;
		const checkTextareaOverlays = () => {
			if (textareaCheckPending) return;
			textareaCheckPending = true;
			requestAnimationFrame(() => {
				textareaCheckPending = false;
				if (!this.currentConfig?.textarea) return;
				const textarea = document.querySelector(this.currentConfig.textarea);
				if (textarea && textarea.offsetParent) {
					const text = this.getPlainText(textarea);
					if (text && text.length >= 3 && !textarea.piiMatches?.length && !textarea._piiOverlayHost?.parentNode) {
						this.scheduleIdleCheck(textarea);
					}
					else if (textarea.piiMatches?.length && (!textarea._piiOverlayHost || !textarea._piiOverlayHost.parentNode)) {
						this.createOrUpdateOverlay(textarea, textarea.lastScannedText || text, textarea.piiMatches);
						this.showPIIIndicator(textarea, textarea.piiMatches.length);
					}
				}
			});
		};
		const setupTextareaContainerObserver = () => {
			if (!this.currentConfig?.composerContainer) return;
			const containers = document.querySelectorAll(this.currentConfig.composerContainer);
			containers.forEach(container => {
				if (container._wtsContainerObserver) return;
				const containerObs = new MutationObserver(checkTextareaOverlays);
				containerObs.observe(container, { childList: true, subtree: true });
				container._wtsContainerObserver = containerObs;
			});
		};
		setupTextareaContainerObserver();
		setInterval(setupTextareaContainerObserver, 500);

		let lastUrl = location.href;
		setInterval(() => {
			if (location.href !== lastUrl) {
				lastUrl = location.href;
				document.querySelectorAll('.wts-pii-overlay-host').forEach(el => el.remove());
				document.querySelectorAll('.wts-pii-underline-individual').forEach(el => { if (el._invertDiv) el._invertDiv.remove(); el.remove(); });
				document.querySelectorAll('.wts-pii-invert').forEach(el => el.remove());
				document.querySelectorAll(this.currentConfig.textarea).forEach(el => {
					if (el._piiParentObserver) { el._piiParentObserver.disconnect(); delete el._piiParentObserver; }
					delete el._piiParentObserverTarget;
					clearTimeout(el._overlayRefreshTimer);
					delete el.piiMatches; delete el.lastScannedText; delete el.piiOverlayId; delete el.piiOverlayNodes;
					delete el.cachedClippingParents; delete el._piiOverlayHost;
				});
			}
			const activeIds = new Set();
			document.querySelectorAll(this.editableSelectors).forEach(el => {
				if (el.piiMatches?.length && el.offsetParent) {
					if (el.piiOverlayId) activeIds.add(el.piiOverlayId);
				} else {
					this.removeOverlays(el);
					if (el._piiParentObserver) { el._piiParentObserver.disconnect(); delete el._piiParentObserver; }
					delete el._piiParentObserverTarget;
					clearTimeout(el._overlayRefreshTimer);
					el.piiMatches = [];
					el.lastScannedText = '';
					delete el.cachedClippingParents;
				}
			});
			document.querySelectorAll('.wts-pii-underline-individual').forEach(u => {
				if (!activeIds.has(u.dataset.piiElementId)) { if (u._invertDiv) u._invertDiv.remove(); u.remove(); }
			});
		}, 500);
	},
	setupOverlayHover: function() {
		document.addEventListener('click', (e) => {
			// While popup is open (not from indicator), don't switch entities
			if (this.ctxPopup && this.ctxPopup.style.visibility === 'visible' && this.ctxPopup._popupSpanAll.style.display === 'none') {
				// Check if mouse is on the popup
				const popupRect = this.ctxPopup.getBoundingClientRect();
				if (e.clientX >= popupRect.left && e.clientX <= popupRect.right && e.clientY >= popupRect.top && e.clientY <= popupRect.bottom) {
					return;
				}
				// Mouse left both the popup and the source entity — hide and allow re-hover
				this.hidePIIPopup();
			}
			else {
				// Skip if a page UI element (menu, popover) is covering the overlays
				if (this.ctxPopup?.contains(e.target)) return;

				const topEl = document.elementFromPoint(e.clientX, e.clientY);
				if (topEl && !topEl.closest('.wts-pii-overlay-host') && !topEl.closest('.wts-ctx-popup') && !topEl.matches(this.editableSelectors) && !topEl.closest(this.editableSelectors)) {
					return;
				}
				const overlays = document.querySelectorAll('.wts-pii-underline-individual');
				let hit = null;
				for (const div of overlays) {
					if (div.style.display === 'none' || !div._matchRef) continue;
					const rect = div.getBoundingClientRect();
					if (e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom) {
						hit = div;
						break;
					}
				}
				if (hit && hit._sourceEl) {
					if (this.ctxPopup?.style.visibility === 'visible') this.hidePIIPopup();
					else this.showPIIPopup(hit._matchRef, hit._sourceEl, false);
				}
			}
		});
	},
	// ==================== Platform Config ====================
	getPlatformConfig: function() {
		var configObject = null;
		const hostname = location.hostname;
		if (hostname.includes("chatgpt.com") || hostname.includes("chat.openai.com")) {
			this.currentProviderType = "chatgpt.com";
			configObject = this.PLATFORM_CONFIGS[0];
		}
		else if (hostname.includes("gemini.google.com")) {
			this.currentProviderType = "gemini.google.com";
			configObject = this.PLATFORM_CONFIGS[1];
		}
		else if (hostname.includes("google.com") || hostname.includes("www.google.com")) {
			this.currentProviderType = "google.com";
			configObject = this.PLATFORM_CONFIGS[2];
		}
		return configObject;
	},
	// ==================== Event Listeners ====================
	startListeners: function() {
		const handlers = {
			keydown: [this.handleCtrlKeys.bind(this), this.handleShiftKeys.bind(this), this.handleBackspace.bind(this)],
			input: [this.handleInput.bind(this)],
			compositionend: [(e) => {
				let target = e.target;
				if (!this.isEditable(target)) {
					target = target.closest?.(this.editableSelectors);
				}
				if (target) {
					setTimeout(() => this.scheduleIdleCheck(target), 100);
				}
			}],
			focusin: [(e) => {
				if (e.target.matches?.(this.editableSelectors)) {
					this.scheduleIdleCheck(e.target);
				}
			}],
			drop: [this.handleDrop.bind(this)]
		};

		Object.entries(handlers).forEach(([event, fns]) => {
			fns.forEach(fn => document.addEventListener(event, fn));
		});

		// Intercept Enter before the page sees it (for auto-redact)
		document.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				this.interceptEnter(e);
			}
		}, true);

		// Intercept Send / Submit button clicks - polling for button
		const attachedButtons = new WeakSet();
		const attachSendHandler = () => {
			if (this.currentConfig) document.querySelectorAll(this.currentConfig.submitBtn).forEach(btn => {
				if (attachedButtons.has(btn)) return;
				btn.addEventListener("click", (e) => !this.isSynthetic && this.interceptSendClick(e), true);
				attachedButtons.add(btn);
			});
		};
		attachSendHandler();
		setInterval(attachSendHandler, 500);
	},

	// Intercept Send / Submit button click and redact BEFORE sending
	interceptSendClick: async function(e) {
		if (this.isSynthetic || !this.isActivated) return;
		e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
		if (!this.currentConfig) return;
		const submitBtn = e.currentTarget || document.querySelector(this.currentConfig.submitBtn);
		const textarea = Array.from(document.querySelectorAll(this.currentConfig.textarea)).find(el => el.offsetParent && (el.value || el.innerText?.trim())) || document.querySelector(this.currentConfig.textarea);
		if (!textarea || !submitBtn) return;
		const text = textarea.value ?? textarea.innerText ?? textarea.textContent;
		let finalText = text;
		if (this.autoRedactMode && text) {
			try {
				const sendRedact = new Promise((resolve) => {
					try {
						chrome.runtime.sendMessage(
							{ msg: "RedactAndSend", data: text, ignoredPII: Array.from(this.ignoredPII.get(textarea) || []) },
							(response) => resolve(response)
						);
					} catch (err) {
						resolve(null);
					}
				});
				const timeout = new Promise(resolve => setTimeout(() => resolve(null), 4000));
				const response = await Promise.race([sendRedact, timeout]);
				if (response?.redactedText) {
					Webroot_Extension.Log("Redacted:", response.redactedText);
					finalText = response.redactedText;
				} else {
					Webroot_Extension.Log("Timeout/No response - sending original");
				}
			} catch (err) {
				Webroot_Extension.Log("Error - sending original");
			}
		}
		// Set the redacted text
		if (textarea.value !== undefined) textarea.value = finalText;
		else textarea.innerText = finalText;
		textarea.dispatchEvent(new Event('input', { bubbles: true }));
		textarea.dispatchEvent(new Event('change', { bubbles: true }));
		textarea.focus();
		// Re-scan PII on the redacted text before submitting
		this.scheduleIdleCheck(textarea);
		// Submit the form/message
		setTimeout(() => {
			this.isSynthetic = true;
			submitBtn.click();
			this.isSynthetic = false;
			// Clear overlays and reset state after submission
			setTimeout(() => {
				this.removeOverlays(textarea);
				delete textarea.piiMatches;
				delete textarea.lastScannedText;
				delete textarea.piiOverlayId;
				delete textarea.reportedPII;
				this.ignoredPII.delete(textarea);
			}, 100);
		}, 150);
	},
	handleCtrlKeys: function (e) {
		if (!e.ctrlKey && !e.metaKey) return;
		const key = e.key.toLowerCase();
		if (!['v', 'x', 'a'].includes(key)) return;
		const target = e.target;
		if (!this.isEditable(target)) return;
		Webroot_Extension.Log('cut and paste / ctrl-key detected');
		this.scheduleIdleCheck(target);
	},

	handleShiftKeys: function (e) {
		if (!e.shiftKey) return;
		const key = e.key.toLowerCase();
		if (!['arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'enter'].includes(key)) return;
		const target = e.target;
		if (!this.isEditable(target)) return;
		this.scheduleIdleCheck(target);
	},

	handleBackspace: function(e) {
		if (e.key.toLowerCase() === 'backspace' && this.isEditable(e.target)) {
			setTimeout(() => this.scheduleIdleCheck(e.target), 20);
		}
	},

	handleInput: function (e) {
		const target = e.target;
		if (!this.isEditable(target)) return;
		this.scheduleIdleCheck(target);
	},
	// ============ Extra listeners from redact snippet ============
	handleDrop: function (e) {
		e.preventDefault();
		const target = e.target;
		const active = document.activeElement;
		const editable = this.isEditable(target) ? target : (this.isEditable(active) ? active : null);
		if (!editable) return;
		this.scheduleIdleCheck(editable);
	},
	// Intercept Enter and redact BEFORE sending
	interceptEnter: async function(e) {
		const target = e.target;
		if (!this.isEditable(target) || this.isSynthetic || !this.isActivated) return;

		// Allow Shift+Enter for new line (don't intercept)
		if (e.shiftKey) {
			this.scheduleIdleCheck(target);
			return;
		}
		// We are handling Enter ourselves
		e.preventDefault();
		e.stopImmediatePropagation();
		const text = target.value ?? target.innerText;
		let finalText = text;
		if (this.autoRedactMode) {
			try {
				// Wrap chrome.runtime.sendMessage in a Promise
				const sendRedact = new Promise((resolve) => {
					try {
						chrome.runtime.sendMessage(
							{ msg: "RedactAndSend", data: text, ignoredPII: Array.from(this.ignoredPII.get(target) || []) },
							(response) => resolve(response)
						);
					} catch (err) {
						resolve(null);
					}
				});
				const timeout = new Promise(resolve => setTimeout(() => resolve(null), 4000));
				const response = await Promise.race([sendRedact, timeout]);
				if (response?.redactedText) {
					Webroot_Extension.Log("Redacted:", response.redactedText);
					finalText = response.redactedText;
				} else {
					Webroot_Extension.Log("Timeout/No response - sending original");
					finalText = text;
				}
			} catch (err) {
				Webroot_Extension.Log("Error - sending original");
				finalText = text;
			}
		} else {
			Webroot_Extension.Log("autoRedactMode OFF - sending original");
		}

		if (target.value !== undefined) target.value = finalText;
		else target.innerText = finalText;
		// Re-scan PII on the redacted text
		this.scheduleIdleCheck(target);
		// Let the page see a synthetic Enter after redaction
		setTimeout(() => {
			this.isSynthetic = true;
			target.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
			this.isSynthetic = false;

			// Treat Enter-submit like a send: clear ignored PII for the next message
			setTimeout(() => {
				this.removeOverlays(target);
				delete target.piiMatches;
				delete target.lastScannedText;
				delete target.piiOverlayId;
				delete target.reportedPII;
				this.ignoredPII.delete(target);
			}, 100);
		}, 100);
	},
	// ==================== PII Scanning ====================
	scheduleIdleCheck: function(el) {
		if (!this.isActivated) return;
		clearTimeout(el.piiTimer);
		el.piiRequested = true;

		el.piiTimer = setTimeout(() => {
			el.piiRequested = false;
			const text = this.getPlainText(el);

			if (!text || text.length < 3) {
				this.removeOverlays(el);
				this.hidePIIIndicator();
				el.lastScannedText = text;
				el.piiMatches = [];
				return;
			}

			if (this.scanningInProgress.has(el)) {
				el.piiQueued = true;
				Webroot_Extension.Log('scan in progress, queueing another scan for element');
				return;
			}

			this.runPIIScan(el, text);
		}, this.DEBOUNCE_MS);
	},
	ProcessMultiByteChars: function (results, text) {
		let nMatches = (results.matches || []).map(m => {
			return Object.assign({}, m, {
				start: (m.start ?? m.startIndex ?? m.begin ?? null),
				end: (m.end ?? m.endIndex ?? m.finish ?? null),
				score: (m.score ?? m.confidenceScore ?? null)
			});
		}).filter(m => {
			// Filter by confidence score first
			const score = m.score;
			const meetsConfidence = score == null || score >= this.MIN_CONFIDENCE_SCORE;
			const hasValidIndices = Number.isInteger(m.start) && Number.isInteger(m.end) && m.end > m.start;

			if (!meetsConfidence) {
				Webroot_Extension.Log(`Filtering out low confidence PII: ${m.entityType || m.type} (score: ${score?.toFixed(2) || 'N/A'})`);
			}

			return meetsConfidence && hasValidIndices;
		}).sort((a, b) => a.start - b.start);

		// Deduplicate: when the same span+entity has multiple scores, keep only the highest
		nMatches = this.deduplicateByHighestScore(nMatches);

		if (nMatches.length === 0)
			return nMatches;

		// Build a byte-offset → char-offset lookup table.
		// byteToChar[byteIndex] = characterIndex
		// This correctly handles multi-byte characters (emoji, non-breaking hyphens, CJK, etc.)
		const encoder = new TextEncoder();
		const byteToChar = [];
		let byteIndex = 0;
		for (let charIndex = 0; charIndex < text.length; charIndex++) {
			const bytes = encoder.encode(text[charIndex]);
			for (let b = 0; b < bytes.length; b++) {
				byteToChar[byteIndex] = charIndex;
				byteIndex++;
			}
		}
		// Allow end indices that land exactly at the end
		byteToChar[byteIndex] = text.length;

		// Convert byte-based indices to character-based indices for each match
		for (let i = 0; i < nMatches.length; i++) {
			const m = nMatches[i];
			// PERSON and ADDRESS already use character-based indices from the backend
			if (m.entityType === "PERSON") {
				continue;
			}

			const charStart = byteToChar[m.start];
			const charEnd = byteToChar[m.end];

			if (charStart == null || charEnd == null) {
				Webroot_Extension.Log(
					'Multi-byte mapping failed for ' + (m.entityType || m.type) +
					' byte[' + m.start + ',' + m.end + '] — skipping adjustment'
				);
				continue;
			}

			Webroot_Extension.Log(
				'Multi-byte adjust: ' + (m.entityType || m.type) +
				' byte[' + m.start + ',' + m.end + '] → char[' + charStart + ',' + charEnd + ']' +
				' text="' + text.substring(charStart, charEnd) + '"'
			);

			m.start = charStart;
			m.end = charEnd;
			if (m.startIndex != null) m.startIndex = charStart;
			if (m.endIndex != null) m.endIndex = charEnd;
		}

		Webroot_Extension.Log("from method: ", nMatches);
		return nMatches;
	},

	/**
	* Deduplicates PII matches that share the same span (start/end) and entity type,
	* keeping only the entry with the highest confidence score.
	* @param {Array} matches - Sorted, normalized PII matches
	* @returns {Array} Deduplicated matches
	*/
	deduplicateByHighestScore: function (matches) {
		if (!matches || matches.length <= 1) return matches;

		// Group by composite key: start|end|entityType
		const bestByKey = new Map();

		for (const m of matches) {
			const entityType = m.entityType || m.type || 'PII';
			const key = m.start + '|' + m.end;
			const existing = bestByKey.get(key);

			if (!existing) {
				bestByKey.set(key, m);
			} else {
				const existingScore = existing.score ?? 0;
				const currentScore = m.score ?? 0;

				if (currentScore > existingScore) {
					Webroot_Extension.Log(
						'Dedup: ' + entityType + ' [' + m.start + ',' + m.end + '] ' +
						'score ' + existingScore.toFixed(2) + ' -> ' + currentScore.toFixed(2)
					);
					bestByKey.set(key, m);
				}
			}
		}

		const deduplicated = Array.from(bestByKey.values()).sort((a, b) => a.start - b.start);

		if (deduplicated.length < matches.length) {
			Webroot_Extension.Log(
				'Dedup: reduced ' + matches.length + ' matches to ' + deduplicated.length +
				' (kept highest score per span+entity)'
			);
		}

		return deduplicated;
	},

	runPIIScan: function (el, text) {
		if (!Webroot_Extension.PIIDetectionEnabled) {
			Webroot_Extension.Log("PII detection has been disabled");
			return;
		}

		if (this.isContextLost()) {
			Webroot_Extension.Log('chrome.runtime.id not available — cannot send ScanPII');
			return;
		}

		let scannedText = text;
		let isTruncated = false;
		if (this.currentConfig?.charLimit && text.length > this.currentConfig.charLimit) {
			scannedText = text.substring(0, this.currentConfig.charLimit);
			isTruncated = true;
			this.sendPIIException(2); // LengthExceeded exception
		}

		this.scanningInProgress.add(el);
		el.piiQueued = false;

		// Record start time for latency measurement
		const scanStartTime = performance.now();

		this.incrementPIISDKCalls();

		chrome.runtime.sendMessage({ msg: 'ScanPII', data: scannedText }, (response) => {
			// Calculate and send latency
			const latencyMs = performance.now() - scanStartTime;
			this.sendPIILatency(latencyMs);

			this.scanningInProgress.delete(el);

			const currentText = this.getPlainText(el);
			if (currentText !== text) {
				if (el.piiQueued) {
					el.piiQueued = false;
					this.scheduleIdleCheck(el);
				}
				if (!currentText || currentText.length < 3) {
				this.removeOverlays(el);
					this.hidePIIIndicator();
					el.piiMatches = [];
					el.lastScannedText = currentText;
				}
				return;
			}

			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('chrome.runtime.lastError:', chrome.runtime.lastError);
				if (el.piiQueued || el.piiRequested) {
					clearTimeout(el.piiTimer);
					el.piiTimer = setTimeout(() => this.scheduleIdleCheck(el), 50);
				}
				return;
			}

			const results = this.parseResults(response);
			if (!results) {
				Webroot_Extension.Log('No results from parseResults');
				return;
			}

			// Use only the scanned portion for multi-byte mapping to avoid
			// building a huge byteToChar[] array for text beyond the char limit
			let normalizedMatches = this.ProcessMultiByteChars(results, scannedText);
			if (isTruncated) {
				const brokenBoundary = scannedText.length;
				normalizedMatches = normalizedMatches.filter(m => m.end < brokenBoundary);
			}

			if (normalizedMatches.length) {
				const filteredMatches = this.filterIgnoredPII(el, text, normalizedMatches);
				this.logPIIResults(filteredMatches);
				const newMatches = this.getNewPIIMatches(el, text, filteredMatches);
				if (newMatches.length > 0) {
					this.sendPIICounters(newMatches);
				}
				el.piiMatches = filteredMatches;
				// Pass scannedText (capped) to overlay creation so DOM walking
				// and rect computation are bounded to the char limit region
				this.applyPIIMarkers(el, scannedText, filteredMatches);
				el.lastScannedText = text;
			} else {
				Webroot_Extension.Log('No PII detected');
				this.removeOverlays(el);
				this.hidePIIIndicator();
				el.piiMatches = [];
				el.reportedPII = new Set();
				el.lastScannedText = text;
			}

			if (el.piiQueued) {
				el.piiQueued = false;
				setTimeout(() => {
					const newText = this.getPlainText(el);
					if (newText !== el.lastScannedText) this.runPIIScan(el, newText);
				}, 50);
			}
		});
	},
	getNewPIIMatches: function (el, text, matches) {
		if (!el.reportedPII) {
			el.reportedPII = new Set();
		}

		const newMatches = [];
		matches.forEach(m => {
			// Create a unique key for this PII instance: "entityType:actualText"
			const entityType = m.entityType || m.type || 'UNKNOWN';
			const key = `${entityType}:${m.start}:${m.end}`;

			if (!el.reportedPII.has(key)) {
				el.reportedPII.add(key);
				newMatches.push(m);
			}
		});

		return newMatches;
	},

	sendPIICounters: function (matches) {
		if (!matches || !matches.length || !this.currentProviderType) return;

		const foundEntities = {};
		matches.forEach(m => {
			const entityType = m.entityType || m.type || 'UNKNOWN';
			foundEntities[entityType] = (foundEntities[entityType] || 0) + 1;
		});

		Webroot_Extension.Log('Sending PII Counters:', {
			providerType: this.currentProviderType,
			foundEntities: foundEntities
		});

		chrome.runtime.sendMessage({
			msg: 'UpdatePIICounter',
			providerType: this.currentProviderType,
			foundEntities: foundEntities,
			sdkCalls: 0
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error sending PII Counters:', chrome.runtime.lastError);
			}
		});
	},

	sendRedactedCounter: function (entityType) {
		if (!entityType || !this.currentProviderType) return;

		const redactedEntities = {};
		redactedEntities[entityType] = 1;

		Webroot_Extension.Log('Sending Redacted Counter:', {
			providerType: this.currentProviderType,
			redactedEntities: redactedEntities
		});

		if (this.isContextLost()) return;

		chrome.runtime.sendMessage({
			msg: 'UpdateRedactedCounter',
			providerType: this.currentProviderType,
			redactedEntities: redactedEntities
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error sending Redacted Counter:', chrome.runtime.lastError);
			}
		});
	},
	sendRedactedCounterBatch: function (matches) {
		if (!matches || !matches.length || !this.currentProviderType) return;

		// Build entity counts from all matches
		const redactedEntities = {};
		matches.forEach(m => {
			const entityType = m.entityType || m.type || 'UNKNOWN';
			redactedEntities[entityType] = (redactedEntities[entityType] || 0) + 1;
		});

		Webroot_Extension.Log('Sending Redacted Counter Batch:', {
			providerType: this.currentProviderType,
			redactedEntities: redactedEntities
		});

		if (!chrome?.runtime?.id) return;

		chrome.runtime.sendMessage({
			msg: 'UpdateRedactedCounter',
			providerType: this.currentProviderType,
			redactedEntities: redactedEntities
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error sending Redacted Counter Batch:', chrome.runtime.lastError);
			}
		});
	},
	decrementRedactedCounter: function (entityType) {
		if (!entityType || !this.currentProviderType) return;

		const redactedEntities = {};
		redactedEntities[entityType] = 1;

		Webroot_Extension.Log('Decrementing Redacted Counter:', {
			providerType: this.currentProviderType,
			redactedEntities: redactedEntities
		});

		if (!chrome?.runtime?.id) return;

		chrome.runtime.sendMessage({
			msg: 'DecrementRedactedCounter',
			providerType: this.currentProviderType,
			redactedEntities: redactedEntities
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error decrementing Redacted Counter:', chrome.runtime.lastError);
			}
		});
	},
	sendFeedbackCounter: function (entityType, isPositive) {
		if (!entityType || !this.currentProviderType) return;

		Webroot_Extension.Log('Sending Feedback Counter:', {
			providerType: this.currentProviderType,
			entityType: entityType,
			isPositive: isPositive
		});

		chrome.runtime.sendMessage({
			msg: 'UpdateFeedbackCounter',
			providerType: this.currentProviderType,
			entityType: entityType,
			isPositive: isPositive
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error sending Feedback Counter:', chrome.runtime.lastError);
			}
		});
	},
	decrementFeedbackCounter: function (entityType, isPositive) {
		if (!entityType || !this.currentProviderType) return;

		Webroot_Extension.Log('Decrementing Feedback Counter:', {
			providerType: this.currentProviderType,
			entityType: entityType,
			isPositive: isPositive
		});

		chrome.runtime.sendMessage({
			msg: 'DecrementFeedbackCounter',
			providerType: this.currentProviderType,
			entityType: entityType,
			isPositive: isPositive
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error decrementing Feedback Counter:', chrome.runtime.lastError);
			}
		});
	},

	sendPIILatency: function (latencyMs) {
		if (latencyMs == null || latencyMs < 0 || !this.currentProviderType) return;

		Webroot_Extension.Log('Sending PII Latency:', latencyMs.toFixed(2) + 'ms');

		chrome.runtime.sendMessage({
			msg: 'UpdatePIILatency',
			providerType: this.currentProviderType,
			latencyMs: latencyMs
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error sending PII Latency:', chrome.runtime.lastError);
			}
		});
	},

	incrementPIISDKCalls: function () {
		if (!this.currentProviderType) return;
		chrome.runtime.sendMessage({ msg: 'IncrementPIISDKCalls', providerType: this.currentProviderType }, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error incrementing SDK calls:', chrome.runtime.lastError);
			}
		});	
	},

	parseResults: function(response) {
		try {
			const arr = response?.piiResults;
			if (!arr) return null;
			const matches = typeof arr === 'string' ? JSON.parse(arr) : arr;
			return { success: matches.length > 0, matches };
		} catch (e) {
			Webroot_Extension.Log('PII parse error:', e);
			return null;
		}
	},

	filterIgnoredPII: function(el, text, matches) {
		const ignoredSet = this.ignoredPII.get(el) || new Set();
		return matches.filter(m => !ignoredSet.has(text.slice(m.start, m.end)));
	},

	ignorePIIText: function(el, piiText) {
		if (!el || !piiText) return;
		let ignoredSet = this.ignoredPII.get(el);
		if (!ignoredSet) {
			ignoredSet = new Set();
			this.ignoredPII.set(el, ignoredSet);
		}
		ignoredSet.add(piiText);
	},
	unignorePIIText: function (el, piiText) {
		if (!el || !piiText) return;
		const ignoredSet = this.ignoredPII.get(el);
		if (ignoredSet) {
			ignoredSet.delete(piiText);
		}
	},
	logPIIResults: function(matches) {
		if (Webroot_Extension.logLevel >= 3) {
			const counts = matches.reduce((acc, m) => ({ ...acc, [m.type || m.entityType || 'PII']: (acc[m.type || m.entityType || 'PII'] || 0) + 1 }), {});
			const summary = Object.entries(counts).map(([type, count]) => `${count} ${type}${count > 1 ? 's' : ''}`).join(', ');
			Webroot_Extension.Log(`PII matches found: ${matches.length} (${summary})`);
		}
	},

	// ==================== Observer Management ====================
	setupObserver: function(element) {
		if (!this.elementObservers.has(element)) {
			const observer = new MutationObserver(() => {
				const currentText = this.getPlainText(element);
				if (element.lastScannedText !== currentText) {
					this.scheduleIdleCheck(element);
				}
			});

			observer.observe(element, { childList: true, subtree: true, characterData: true });
			this.elementObservers.set(element, observer);
			
			// Stabilize scrollbar gutter on scrollable ancestors to prevent
			// layout shifts when content changes cause scrollbar to appear/disappear
			for (var node = element; node && node !== document.body; node = node.parentElement) {
				var ov = getComputedStyle(node).overflowY;
				if ((ov === 'auto' || ov === 'scroll') && !node._piiGutterSet) {
					node._piiGutterSet = true;
					node.style.scrollbarGutter = 'stable';
				}
			}
		}

		// Watch parent for overlay host removal by framework re-renders (e.g., React/ProseMirror)
		// Re-check every call in case the parent element was replaced by the framework
		const currentParent = element.parentElement;
		if (currentParent && (!element._piiParentObserver || element._piiParentObserverTarget !== currentParent)) {
			if (element._piiParentObserver) element._piiParentObserver.disconnect();
			const parentObs = new MutationObserver(() => {
				if (element.piiMatches?.length && element._piiOverlayHost &&
					!element._piiOverlayHost.parentNode) {
					clearTimeout(element._overlayRefreshTimer);
					element._overlayRefreshTimer = setTimeout(() => {
						if (element.piiMatches?.length) {
							this.createOrUpdateOverlay(element, element.lastScannedText || '', element.piiMatches);
						}
					}, 50);
				}
			});
			parentObs.observe(currentParent, { childList: true });
			element._piiParentObserver = parentObs;
			element._piiParentObserverTarget = currentParent;
		}
	},

	// ==================== Overlay Management ====================
	applyPIIMarkers: function(element, text, matches) {
		if (!matches?.length) {
			this.hidePIIIndicator();
			this.hidePIIPopup();
			return;
		}
		this.setupObserver(element);
		this.createOrUpdateOverlay(element, text, matches);
		element.piiMatches = matches;
		this.showPIIIndicator(element, matches.length);

		if (!this.observedElements.get(element)) {
			this.observedElements.set(element, true);
		}
	},

	createOrUpdateOverlay: function(el, text, matches) {
		if (!matches?.length) return this.removeOverlays(el);
		try {
			el.piiOverlayId = el.piiOverlayId || 'pii-' + Math.random().toString(36).slice(2);

			// Get or create overlay host inside the textarea's parent
			if (!el._piiOverlayHost || !el._piiOverlayHost.parentNode || el._piiOverlayHost.parentNode !== el.parentElement) {
				if (el._piiOverlayHost) el._piiOverlayHost.remove();
				el.piiOverlayNodes = [];
				const host = document.createElement('div');
				host.className = 'wts-pii-overlay-host';
				const parent = el.parentElement;
				if (parent && getComputedStyle(parent).position === 'static') {
					parent.style.position = 'relative';
				}
				if (parent) parent.appendChild(host);
				el._piiOverlayHost = host;
			}
			const host = el._piiOverlayHost;
			const hostRect = host.getBoundingClientRect();

			const isInput = ['TEXTAREA', 'INPUT'].includes(el.tagName), cacheKey = el.offsetWidth,
				elRect = el.getBoundingClientRect(), allRects = [], pool = (el.piiOverlayNodes = el.piiOverlayNodes || []);
			let clip = { top: elRect.top, bottom: elRect.bottom, left: elRect.left, right: elRect.right }, mirror;

			// Detect dark/light background for blend mode
			let isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
			try {
				let node = el;
				let foundBg = false;
				while (node && node !== document.documentElement) {
					const bg = getComputedStyle(node).backgroundColor;
					const m = bg.match(/\d+/g);
					if (m && m.length >= 4 && Number(m[3]) === 0) { node = node.parentElement; continue; }
					if (m && m.length >= 3) { 
						isDark = (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) < 128; 
						foundBg = true;
						break; 
					}
					node = node.parentElement;
				}
			} catch (_) { }

			if (isInput) clip = { top: elRect.top + el.clientTop, bottom: elRect.top + el.clientTop + el.clientHeight, left: elRect.left + el.clientLeft, right: elRect.left + el.clientLeft + el.clientWidth };
			for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
				const s = getComputedStyle(p), pr = p.getBoundingClientRect();
				if (s.overflow !== 'visible') clip = { top: Math.max(clip.top, pr.top), bottom: Math.min(clip.bottom, pr.bottom), left: Math.max(clip.left, pr.left), right: Math.min(clip.right, pr.right) };
			}

			if (isInput && matches.some(m => !m.cachedRects || m.cacheKey !== cacheKey)) {
				mirror = document.body.appendChild(document.createElement('div'));
				const s = getComputedStyle(el);
				['font', 'lineHeight', 'padding', 'border', 'boxSizing', 'width', 'height', 'whiteSpace', 'wordBreak', 'overflowWrap', 'letterSpacing'].forEach(p => mirror.style[p] = s[p]);
				// Reduce mirror width by the scrollbar width so text wraps identically
				var scrollbarW = el.offsetWidth - el.clientWidth - parseFloat(s.borderLeftWidth || 0) - parseFloat(s.borderRightWidth || 0);
				if (scrollbarW > 0) mirror.style.width = (parseFloat(s.width) - scrollbarW) + 'px';
				Object.assign(mirror.style, { position: 'absolute', top: '-9999px', visibility: 'hidden', whiteSpace: 'pre-wrap' });
			}

			// Build visual segments: for ADDRESS matches containing newlines,
			// split into per-line sub-ranges so underlines skip '\n' characters.
			// All other match types render as a single segment.
			const visualSegments = [];
			matches.forEach(m => {
				if (m.entityType === 'ADDRESS' && text.substring(m.start, m.end).includes('\n')) {
					const span = text.substring(m.start, m.end);
					let offset = m.start;
					const lines = span.split('\n');
					for (let i = 0; i < lines.length; i++) {
						if (lines[i].length > 0) {
							visualSegments.push({ start: offset, end: offset + lines[i].length, match: m });
						}
						offset += lines[i].length + 1; // +1 for '\n'
					}
				} else {
					visualSegments.push({ start: m.start, end: m.end, match: m });
				}
			});

			visualSegments.forEach(seg => {
				const m = seg.match;
				let rs = [];
				if (isInput) {
					// For input/textarea, use segment boundaries for mirror measurement
					const segCacheKey = seg.start + '|' + seg.end + '|' + cacheKey;
					if (!m._segCachedRects || !m._segCachedRects[segCacheKey]) {
						mirror.textContent = el.value.substring(0, seg.start);
						const span = document.createElement('span'); span.textContent = el.value.substring(seg.start, seg.end);
						mirror.append(span, el.value.substring(seg.end));
						const mr = mirror.getBoundingClientRect();
						if (!m._segCachedRects) m._segCachedRects = {};
						m._segCachedRects[segCacheKey] = Array.from(span.getClientRects()).map(r => ({ left: r.left - mr.left, top: r.top - mr.top, width: r.width, height: r.height }));
					}
					rs = m._segCachedRects[segCacheKey].map(r => ({ left: r.left + elRect.left - el.scrollLeft, top: r.top + elRect.top - el.scrollTop, width: r.width, height: r.height }));
				} else {
					let r = document.createRange(), s = null, e = null, c = 0;
					const walk = (n) => {
						if (s && e) return;
						if (n.nodeType === 3) {
							if (!s && c + n.length > seg.start) s = { n, o: seg.start - c };
							if (!e && c + n.length >= seg.end) e = { n, o: seg.end - c };
							c += n.length;
						} else if (n.tagName === 'BR') c++; else { for (let k = n.firstChild; k; k = k.nextSibling) walk(k); if (n.tagName === 'P') c += 2; }
					};
					walk(el);
					if (s && e) { r.setStart(s.n, s.o); r.setEnd(e.n, e.o); rs = Array.from(r.getClientRects()); }
				}
				for (const r of rs) {
					const [it, ib, il, ir] = [Math.max(0, clip.top - r.top), Math.max(0, r.top + r.height - clip.bottom), Math.max(0, clip.left - r.left), Math.max(0, r.left + r.width - clip.right)];
					if (r.height - it - ib > 0 && r.width - il - ir > 0) allRects.push({ left: r.left, top: r.top, width: r.width, height: r.height, clipPath: `inset(${it}px ${ir}px ${ib}px ${il}px)`, match: m });
				}
			});
			mirror?.remove();

			for (let i = 0; i < Math.max(pool.length, allRects.length); i++) {
				if (i >= allRects.length) { pool[i].style.display = 'none'; if (pool[i]._invertDiv) pool[i]._invertDiv.style.display = 'none'; continue; }
				let div = pool[i] || (pool[i] = document.createElement('div')), inner = div.firstElementChild || div.appendChild(document.createElement('div')), r = allRects[i], m = r.match;
				if (!div.parentNode) {
					inner.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;box-sizing:border-box';
					div.className = 'wts-pii-underline-individual';
					host.appendChild(div);
				}
				if (isDark) {
					if (!div._invertDiv) { div._invertDiv = document.createElement('div'); div._invertDiv.className = 'wts-pii-invert'; }
					if (!div._invertDiv.parentNode) host.insertBefore(div._invertDiv, div);
					Object.assign(div._invertDiv.style, { left: (r.left - hostRect.left) + 'px', top: (r.top - hostRect.top) + 'px', width: r.width + 'px', height: r.height + 'px', display: 'block', clipPath: r.clipPath });
				} else if (div._invertDiv) { div._invertDiv.style.display = 'none'; }
				Object.assign(div.style, { left: (r.left - hostRect.left) + 'px', top: (r.top - hostRect.top) + 'px', width: r.width + 'px', height: r.height + 'px', display: 'block', clipPath: r.clipPath });
				div._matchRef = m;
				div._sourceEl = el;
				const titles = [...new Set(matches.filter(om => Math.max(om.start, m.start) < Math.min(om.end, m.end)).map(om => {
					const entityType = om.entityType || om.type;
					const showScore = Webroot_Extension.logLevel >= 3 && om.score;
					return showScore ? `${entityType}(${Number(om.score).toFixed(2)})` : entityType;
				}))];
				Object.assign(div.dataset, { piiTitle: titles.join(', '), piiElementId: el.piiOverlayId, start: m.start, end: m.end });
			}
		}
		catch (err) {
			// Exception occurred while marking underlines
			Webroot_Extension.Log('Error in createOrUpdateOverlay:', err);
			this.sendPIIException(0); // MarkingRelated exception
		}
	},

	removeOverlays: function(element) {
		if (element.piiOverlayNodes) {
			element.piiOverlayNodes.forEach(el => {
				// Null back-references so match objects and source element refs can be GC'd
				el._matchRef = null;
				el._sourceEl = null;
				if (el._invertDiv) {
					el._invertDiv.remove();
					el._invertDiv = null;
				}
				el.remove();
			});
			element.piiOverlayNodes = [];
		}
		if (element._piiOverlayHost) { element._piiOverlayHost.remove(); delete element._piiOverlayHost; }
		document.querySelectorAll(`[data-pii-element-id="${element.piiOverlayId || ''}"]`).forEach(el => {
			el._matchRef = null;
			el._sourceEl = null;
			if (el._invertDiv) { el._invertDiv.remove(); el._invertDiv = null; }
			el.remove();
		});
	},

	// ==================== PII Indicator Management ====================

	/**
	 * Gets the stable container element for positioning the indicator.
	 * The container is the form/composer area that doesn't resize when textarea grows.
	 * Falls back to textarea's parent if no container selector is configured.
	 */
	getIndicatorAnchor: function(textareaElement) {
		if (!textareaElement) return null;
		const config = this.currentConfig;
		if (!config) return textareaElement;

		// Try to find the configured container
		if (config.composerContainer) {
			const container = textareaElement.closest(config.composerContainer);
			if (container) return container;
		}

		// Fallback: find closest positioned ancestor or parent
		return textareaElement.parentElement || textareaElement;
	},
	// Clamps left/top so the element stays fully within the viewport.
	_clampToViewport: function(left, top, w, h) {
		const margin = 4;
		const vw = window.innerWidth;
		const vh = window.innerHeight;
		left = Math.max(margin, Math.min(left, vw - w - margin));
		top  = Math.max(margin, Math.min(top,  vh - h - margin));
		return { left, top };
	},

	/**
	 * Shows the PII warning indicator above the textarea.
	 * Uses a stable anchor point so indicator doesn't move when textarea grows.
	 * @param {HTMLElement} element - The textarea element
	 * @param {number} count - Number of PII items detected
	 */
	showPIIIndicator: function(element, count = 1) {
		if (!this.ctxIndicator || !element || !count) return;
		if (this.isContextLost()) return;

		if (this.ctxIndicator._PopupOpen) {
			if (this.ctxIndicator._el !== element) this.hidePIIPopup();
		}
		else this.ctxIndicator._SelectedPIIIndex = 0;

		if (count > 1) this.ctxIndicator._spanPlusCount.textContent = "+" + (count - 1);
		else this.ctxIndicator._spanPlusCount.textContent = "";
		if (!this.isPopupInUndoMode() && !this.isPopupInUnmarkMode()) this.ctxIndicator._spanPIIType.textContent = chrome.i18n.getMessage("PII_POPUP_DETECTED", this.mapPIITypeToResource(element.piiMatches[this.ctxIndicator._SelectedPIIIndex].entityType));

		const anchor1 = this.getIndicatorAnchor(element);
		const anchorRect = anchor1.getBoundingClientRect();
		const indW = this.ctxIndicator.offsetWidth;
		const indH = this.ctxIndicator.offsetHeight;
		const indTop = anchorRect.top - indH - 5;
		// Hide indicator if anchor scrolled out of viewport vertically
		if (anchorRect.bottom < 0 || anchorRect.top > window.innerHeight) {
			this.ctxIndicator.style.visibility = 'hidden';
			return;
		}
		// Position above anchor, right-aligned, clamped to viewport
		const rawTop = anchorRect.top - indH - 5;
		const rawLeft = anchorRect.right - indW;
		const clamped = this._clampToViewport(rawLeft, rawTop, indW, indH);
		this.ctxIndicator.style.left = clamped.left + 'px';
		this.ctxIndicator.style.top  = indTop + 'px';
		this.ctxIndicator.style.visibility = 'visible';
		this.ctxIndicator.setAttribute('aria-hidden', 'false');
		this.ctxIndicator._el = element;

		// update popup if displayed including ALL section
		if (this.ctxIndicator._PopupOpen) {

			const idx = Math.min(this.ctxIndicator._SelectedPIIIndex || 0, this.ctxIndicator._el.piiMatches.length - 1);
			if (idx != this.ctxIndicator._SelectedPIIIndex) this.ctxIndicator._SelectedPIIIndex = idx;
			this.ctxPopup._popupSpanAllNumbers.textContent = (idx + 1) + "/" + this.ctxIndicator._el.piiMatches.length;
		}
	},
	/**
	 * Hides and cleans up the PII indicator and all associated observers.
	 */
	hidePIIIndicator: function() {
		if (!this.ctxIndicator) return;

		this.ctxIndicator.style.visibility = 'hidden';
		this.ctxIndicator.setAttribute('aria-hidden', 'true');
		this.ctxIndicator.style.left = '-300px';
		this.ctxIndicator.style.top = '0px';

	},
	updatePIIIndicator: function (fromResize) {
		if (!this.ctxIndicator) return;
		if (this.isContextLost()) return;

		// content update
		const el = this.ctxIndicator._el;
		if (!el) return;
		if (!el.piiMatches || !el.piiMatches.length) {
			this.hidePIIIndicator();
			return;
		}

		const idxNew = this.ctxIndicator._SelectedPIIIndex;
		const spanPIIType = (el.piiMatches && el.piiMatches.length > idxNew) ? chrome.i18n.getMessage("PII_POPUP_DETECTED", this.mapPIITypeToResource(el.piiMatches[idxNew]?.entityType)) : chrome.i18n.getMessage("PII_POPUP_DETECTED", this.mapPIITypeToResource('none'));
		if (this.ctxIndicator._spanPIIType.textContent !== spanPIIType) this.ctxIndicator._spanPIIType.textContent = spanPIIType;

		// position update
		const anchor1 = this.getIndicatorAnchor(el);
		if (!anchor1) return;
		const anchorRect = anchor1.getBoundingClientRect();
		const indW = this.ctxIndicator.offsetWidth;
		const indH = this.ctxIndicator.offsetHeight;
		const indTop = anchorRect.top - indH - 5;
		// Hide indicator if anchor scrolled out of viewport vertically
		if (anchorRect.bottom < 0 || anchorRect.top > window.innerHeight) {
			this.ctxIndicator.style.visibility = 'hidden';
			return;
		}
		// Position above anchor, right-aligned, clamped to viewport
		const rawTop = anchorRect.top - indH - 5;
		const rawLeft = anchorRect.right - indW;
		const clamped = this._clampToViewport(rawLeft, rawTop, indW, indH);
		if (this.ctxIndicator.style.visibility == 'visible' && Math.round(parseFloat(this.ctxIndicator.style.left)) == Math.round(clamped.left) && Math.round(parseFloat(this.ctxIndicator.style.top)) == Math.round(clamped.top)) return;

		this.ctxIndicator.style.left = clamped.left + 'px';
		this.ctxIndicator.style.top  = indTop + 'px';
		this.ctxIndicator.style.visibility = 'visible';

		
		if (fromResize) {
			// redo after resize since not all resize msgs are triggering
			setTimeout(() => { this.updatePIIIndicator(); }, 500);
		}

	},
	showPIIPopupFromIndicator: function(evnt) {
		if (!this.ctxIndicator) return;
		if (!this.ctxPopup) return;
		if (this.isContextLost()) return;

		this.ctxIndicator._PopupOpen = true;
		this.ctxIndicator.classList.add('wts-indicator-selected');
		const idx = Math.min(this.ctxIndicator._SelectedPIIIndex || 0, Math.max(0, this.ctxIndicator._el.piiMatches.length - 1));
		if (idx != this.ctxIndicator._SelectedPIIIndex) this.ctxIndicator._SelectedPIIIndex = idx;
		this.ctxPopup._popupSpanAllNumbers.textContent = (idx + 1) + "/" + this.ctxIndicator._el.piiMatches.length;
		this.showPIIPopup(this.ctxIndicator._el.piiMatches[idx], this.ctxIndicator._el, true);
	},
	showPIIPopup: function (matchRef, el, fromIndicator) {
		if (!this.ctxPopup) return;
		if (!matchRef) return;
		if (!el) return;
		if (this.isContextLost()) return;

		const allText = this.getPlainText(el);
		const maxEnd = matchRef.start + Math.min(matchRef.end - matchRef.start, 50);
		const postDots = (matchRef.end - matchRef.start) > 50 ? "..." : "";
		const piiText = allText.substring(matchRef.start, maxEnd) + postDots;
		const piiTextForUndo = allText.substring(matchRef.start, matchRef.end);

		this.ctxPopup._popupSpanPIIType.textContent = this.mapPIITypeToResource(matchRef.entityType);
		this.ctxPopup._popupSpanPIIValue.textContent = piiText;
		this.ctxPopup._popupDivHeadline.getElementsByTagName('img')[0].src = chrome.runtime.getURL('images/chat/bad.svg');
		this.ctxPopup._popupDivHeadline.getElementsByTagName('span')[0].textContent = chrome.i18n.getMessage('PII_POPUP_HEADLINE'); //"Detect Information"
		this.ctxPopup._popupButtonRedact.textContent = chrome.i18n.getMessage('PII_POPUP_REDACT');
		this.ctxPopup._popupButtonRedact.classList.remove('undo');
		this.toggleAccurateItems(true, false);
		this.ctxPopup._undoInfo = { txt: piiTextForUndo, matchRef: matchRef };
		this.ctxPopup._pendingRedactAction = false;
		this.ctxPopup._pendingUnmarkAction = false;
		this.ctxPopup._el = el;
		this.ctxPopup._matchRef = matchRef;
		if (!fromIndicator) {
			const divPIIUnderLineIndividual = this.findUnderlineIndividual(el, matchRef);
			const pos = divPIIUnderLineIndividual.getBoundingClientRect();
			let popTop, popLeft = pos.left;
			if (window.innerHeight > pos.bottom + this.ctxPopup.offsetHeight + 2) {
				popTop = pos.bottom + 2;
			}
			else {
				popTop = pos.top - this.ctxPopup.offsetHeight - 2;
			}
			const c1 = this._clampToViewport(popLeft, popTop, this.ctxPopup.offsetWidth, this.ctxPopup.offsetHeight);
			this.ctxPopup.style.top  = c1.top + 'px';
			this.ctxPopup.style.left = c1.left + 'px';
			this.ctxPopup._popupSpanAll.style.display = 'none';
			if (this.ctxIndicator) {
				this.ctxIndicator.classList.remove('wts-indicator-selected');
			}
		}
		else if (this.ctxIndicator) {
			this.ctxPopup._popupSpanAll.style.display = 'flex';
			const pos = this.ctxIndicator.getBoundingClientRect();
			let popLeft = pos.right - this.ctxPopup.offsetWidth;
			let popTop  = pos.top - this.ctxPopup.offsetHeight - 5;
			const c2 = this._clampToViewport(popLeft, popTop, this.ctxPopup.offsetWidth, this.ctxPopup.offsetHeight);
			this.ctxPopup.style.left = c2.left + 'px';
			this.ctxPopup.style.top  = c2.top + 'px';
		}

		this.ctxPopup.style.visibility = 'visible';
		this.ctxPopup.setAttribute('aria-hidden', 'false');

		if (Webroot_Extension.logLevel >= 3) {
			const divPIIUnderLineIndividual = this.findUnderlineIndividual(el, matchRef);
			const tooltip = document.createElement('span');
			tooltip.textContent = divPIIUnderLineIndividual?.dataset?.piiTitle;
			tooltip.className = 'wts-ctx-popupPII-tooltip';
			this.ctxPopup._popupSpanPIIType.appendChild(tooltip);
		}
	},
	hidePIIPopup: function (evnt) {
		if (!this.ctxPopup) return;
		if (this.ctxPopup.style.visibility !== 'visible') return;
		if (evnt && evnt.type === 'scroll' && this.ctxPopup._popupSpanAll?.style.display !== 'none') return; //Do not hide if scrolling in edit field

		if (!this.isContextLost()) {
			this.ctxPopup._popupDivHeadline.getElementsByTagName('img')[0].src = chrome.runtime.getURL('images/chat/bad.svg');
			this.ctxPopup._popupDivHeadline.getElementsByTagName('span')[0].textContent = chrome.i18n.getMessage('PII_POPUP_HEADLINE'); //"Detect Information"
			this.ctxPopup._popupButtonRedact.textContent = chrome.i18n.getMessage('PII_POPUP_REDACT');
		}
		this.toggleAccurateItems(true, false);

		this.ctxPopup.style.visibility = 'hidden';
		this.ctxPopup.setAttribute('aria-hidden', 'false');
		this.ctxPopup.style.left = '-500px';
		this.ctxPopup.style.top = '0';
		this.ctxPopup._el = null;
		this.ctxPopup._matchRef = null;
		this.ctxPopup._undoInfo = {};  // release match object reference
		this.ctxPopup._pendingRedactAction = false;
		this.ctxPopup._pendingUnmarkAction = false;

		if (this.ctxIndicator) {
			this.ctxIndicator.classList.remove('wts-indicator-selected');
			this.ctxIndicator._PopupOpen = false;
		}

		// remove tooltip child (dbg)
		if (this.ctxPopup._popupSpanPIIType.childNodes.length > 0) this.ctxPopup._popupSpanPIIType.removeChild(this.ctxPopup._popupSpanPIIType.childNodes[this.ctxPopup._popupSpanPIIType.childNodes.length - 1]);
	},
	isPopupInUndoMode: function () {
		if (!this.ctxPopup) return false;
		if (!this.ctxPopup._pendingRedactAction) return false;
		return true;
	},
	isPopupInUnmarkMode: function () {
		if (!this.ctxPopup) return false;
		if (!this.ctxPopup._pendingUnmarkAction) return false;
		return true;
	},
	onPIIPopupRedactButton: function () {
		if (!this.ctxPopup) return;
		if (this.isContextLost()) return;

		if (!this.ctxPopup._pendingRedactAction) {
			this.handleRedactPII(this.ctxPopup._el, this.ctxPopup._matchRef, true);

			this.ctxPopup._popupDivHeadline.getElementsByTagName('img')[0].src = chrome.runtime.getURL('images/chat/good.svg');
			this.ctxPopup._popupDivHeadline.getElementsByTagName('span')[0].textContent = chrome.i18n.getMessage('PII_POPUP_HEADLINE2'); //"Information protected"
			this.ctxPopup._popupButtonRedact.textContent = chrome.i18n.getMessage('PII_POPUP_UNDO');
			this.ctxPopup._popupButtonRedact.classList.add('undo');
			this.ctxPopup._pendingRedactAction = true;
		}
		else {
			// Decrement redacted counter when undo is clicked
			const entityType = this.ctxPopup._undoInfo.matchRef?.entityType || this.ctxPopup._undoInfo.matchRef?.type || 'UNKNOWN';
			this.decrementRedactedCounter(entityType);			
			this.handleUndoRedactPII(this.ctxPopup._el, this.ctxPopup._undoInfo.matchRef, this.ctxPopup._undoInfo.txt);
			this.ctxPopup._popupDivHeadline.getElementsByTagName('img')[0].src = chrome.runtime.getURL('images/chat/bad.svg');
			this.ctxPopup._popupDivHeadline.getElementsByTagName('span')[0].textContent = chrome.i18n.getMessage('PII_POPUP_HEADLINE'); //"Information protected"
			this.ctxPopup._popupButtonRedact.textContent = chrome.i18n.getMessage('PII_POPUP_REDACT');
			this.ctxPopup._popupButtonRedact.classList.remove('undo');
			this.ctxPopup._pendingRedactAction = false;
		}
	},
	onPIIPopupRedactAllButton: function (evnt) {
		if (!this.ctxIndicator) return;
		if (!this.ctxPopup) return;
		if (this.isContextLost()) return;

		this.handleRedactAllPII(this.ctxIndicator._el);
	},
	onPIIPopupThumbs: function (evnt) {
		if (!this.ctxPopup) return;
		if (!evnt || !evnt.currentTarget) return;
		if (this.isContextLost()) return;

		const id = evnt.currentTarget.id;
		const entityType = this.ctxPopup._matchRef?.entityType || this.ctxPopup._matchRef?.type ||
			'UNKNOWN';

		switch (id) {
			case 'wts-ctx-popupAccurateThumbUpImg':
				this.toggleAccurateItems(true, true);
				break;
			case 'wts-ctx-popupAccurateThumbUpDoneImg':
				this.toggleAccurateItems(true, false);
				break;
			case 'wts-ctx-popupAccurateThumbDownImg':
				// Send negative feedback counter
				this.sendFeedbackCounter(entityType, false);
				this.toggleAccurateItems(false, true);
				this.ctxPopup._pendingUnmarkAction = true;
				this.handleUnmarkPII(this.ctxPopup._el, this.ctxPopup._matchRef);
				break;
			case 'wts-ctx-popupAccurateThumbDownDoneImg':
				// Decrement negative feedback counter (undo thumbs down)
				this.decrementFeedbackCounter(entityType, false);
				this.toggleAccurateItems(false, false);
				this.ctxPopup._pendingUnmarkAction = false;
				this.handleUnmarkUndoPII(this.ctxPopup._el, this.ctxPopup._undoInfo.txt);
				break;
		}

	},
	onPIIPopupArrows: function(evnt) {
		if (!this.ctxIndicator) return;
		if (!this.ctxPopup) return;
		if (this.isContextLost()) return;

		if (this.ctxPopup._pendingRedactAction || this.ctxPopup._pendingUnmarkAction) {
			this.showPIIPopupFromIndicator();
			this.updatePIIIndicator();
			return;
		}

		const id = evnt.currentTarget.id;
		const count = this.ctxIndicator._el.piiMatches.length || 0;
		const idx = this.ctxIndicator._SelectedPIIIndex || 0;
		if (id === 'wts-ctx-popupArrowRightImg') {
			if (idx + 1 >= count) return;
			this.ctxIndicator._SelectedPIIIndex++;
		}
		else if (id === 'wts-ctx-popupArrowLeftImg') {
			if (idx - 1 < 0) return;
			this.ctxIndicator._SelectedPIIIndex--;
		}
		this.showPIIPopupFromIndicator();
		this.updatePIIIndicator();
	},
	toggleAccurateItems: function (thumbUp, setToFeedback) {
		if (typeof thumbUp != "boolean") return;
		if (typeof setToFeedback != "boolean") return;
		if (!this.ctxPopup) return;

		if (setToFeedback) {
			document.getElementById('wts-ctx-popupAccurateText').classList.add('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateDoneText').classList.remove('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateThumbUpImg').classList.add('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateThumbDownImg').classList.add('AccurateHide');
			if (!thumbUp) {
				document.getElementById('wts-ctx-popupAccurateThumbUpDoneImg').classList.add('AccurateHide');
				document.getElementById('wts-ctx-popupAccurateThumbDownDoneImg').classList.remove('AccurateHide');
			}
			else {
				document.getElementById('wts-ctx-popupAccurateThumbUpDoneImg').classList.remove('AccurateHide');
				document.getElementById('wts-ctx-popupAccurateThumbDownDoneImg').classList.add('AccurateHide');
			}
		} else {
			document.getElementById('wts-ctx-popupAccurateText').classList?.remove('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateDoneText').classList?.add('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateThumbUpImg').classList?.remove('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateThumbUpDoneImg').classList?.add('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateThumbDownImg').classList?.remove('AccurateHide');
			document.getElementById('wts-ctx-popupAccurateThumbDownDoneImg').classList?.add('AccurateHide');
		}
	},
	handleUnmarkPII: function(element, match) {
		if (!element || !match) return this.hidePIIPopup();

		const text = this.getPlainText(element);
		const piiText = text.slice(match.start, match.end);
		if (piiText) this.ignorePIIText(element, piiText);

		// Immediately remove underlines for any occurrences of the same PII string
		const currentMatches = element.piiMatches || [];
		const filteredMatches = this.filterIgnoredPII(element, text, currentMatches);
		element.piiMatches = filteredMatches;
		element.lastScannedText = text;
		this.createOrUpdateOverlay(element, text, filteredMatches);

		// Hide PII indicator if no PII remains after unmarking
		if (!filteredMatches.length) {
			this.hidePIIIndicator();
		}

		// Re-scan immediately so UI updates even if there are other matches not in the current overlay
		if (this.scanningInProgress.has(element)) {
			element.piiQueued = true;
		} else {
			this.runPIIScan(element, text);
		}
	},
	handleUnmarkUndoPII: function (element, undoText) {
		if (!element || !undoText) return this.hidePIIPopup();

		this.unignorePIIText(element, undoText);

		// Re-scan immediately so UI updates even if there are other matches not in the current overlay
		if (this.scanningInProgress.has(element)) {
			element.piiQueued = true;
		} else {
			this.runPIIScan(element, this.getPlainText(element));
		}
	},
	handleUndoRedactPII: function(element, match, originalText) {
		if (!element || !match || !originalText) return this.hidePIIPopup();

		this.setPlainText(element, originalText, match.start, match.end);
		this.restoreCursor(element, match.start + originalText.length);

		setTimeout(() => this.runPIIScan(element, this.getPlainText(element)), 100);
	},

	handleRedactPII: function(element, match, reScan) {
		if (!element || !match) return this.hidePIIPopup();

		const text = this.getPlainText(element);
		const piiText = text.slice(match.start, match.end);

		// Send redacted counter for this entity type
		const entityType = match.entityType || 'UNKNOWN';
		this.sendRedactedCounter(entityType);

		// For single-item redaction, apply directly using the already-detected entity type
		// instead of re-analyzing which may fail due to lack of context
		const redactedText = piiText.replace(/\S/g, '#');

		this.setPlainText(element, redactedText, match.start, match.end);
		this.restoreCursor(element, match.start + redactedText.length);
		// Notify React of the DOM change so its internal state stays in sync (edit-mode fix)
		element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));

		if (reScan) setTimeout(() => this.runPIIScan(element, this.getPlainText(element)), 100);
	},

	handleRedactAllPII: async function(element) {
		if (!element) return this.hidePIIPopup();

		const matches = element.piiMatches;
		if (!matches?.length) return this.hidePIIPopup();

		try {
			// Send redacted counter for all entities at once (with proper counts per entity type)
			this.sendRedactedCounterBatch(matches);

			// Process in reverse so earlier offsets stay valid (replacements are same-length but be safe)
			for (let i = matches.length - 1; i >= 0; i--) {
				const piiText = this.getPlainText(element).slice(matches[i].start, matches[i].end);
				const redactedText = piiText.replace(/\S/g, '#');
				this.setPlainText(element, redactedText, matches[i].start, matches[i].end);
			}
			// Notify React of the DOM change so its internal state stays in sync (edit-mode fix)
			element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));

			// Eagerly free the overlay and match state before the re-scan completes
			this.removeOverlays(element);
			element.piiMatches = [];
			element.reportedPII = null;   // allow GC of the Set and its strings
			delete element.piiOverlayId;

			setTimeout(() => this.runPIIScan(element, this.getPlainText(element)), 100);

		} catch (e) {
			Webroot_Extension.Log('Redact all error:', e);
		}
		this.hidePIIPopup();

		return; //TODO - currently we just re-scan and redact on backend to ensure consistent redaction and handle edge cases like overlapping matches, dynamic content, etc. Frontend redaction can be added later if needed for performance.
		/*
		const text = this.getPlainText(element);

		try {
			const timeout = new Promise(resolve => setTimeout(() => resolve(null), 2000));
			const response = await Promise.race([
				chrome.runtime.sendMessage({ msg: "RedactAndSend", data: text, ignoredPII: Array.from(this.ignoredPII.get(element) || []) }),
				timeout
			]);

			const redactedText = response?.redactedText || text;
			element.value !== undefined ? element.value = redactedText : element.textContent = redactedText;
			this.restoreCursor(element, redactedText.length);

			// Immediately clear old underlines/state and re-scan to refresh overlays
			this.removeOverlays(element);
			element.piiMatches = [];
			element.lastScannedText = redactedText;
			delete element.piiOverlayId;

			element.dispatchEvent(new Event('input', { bubbles: true }));
			element.dispatchEvent(new Event('change', { bubbles: true }));
			this.scheduleIdleCheck(element);
		} catch (e) {
			Webroot_Extension.Log('Redact all error:', e);
		}*/
	},

	restoreCursor: function(element, offset) {
		try {
			// place caret at given text offset in the element
			const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null);
			let current = walker.nextNode();
			let charCount = 0;
			let foundNode = null;
			let foundOffset = 0;
			while (current) {
				const nodeLen = current.textContent.length;
				if (charCount + nodeLen >= offset) {
					foundNode = current;
					foundOffset = Math.max(0, offset - charCount);
					break;
				}
				charCount += nodeLen;
				current = walker.nextNode();
			}

			const range = document.createRange();
			const sel = window.getSelection();
			if (foundNode) {
				range.setStart(foundNode, Math.min(foundOffset, foundNode.length || 0));
				range.collapse(true);
				sel.removeAllRanges();
				sel.addRange(range);
			} else {
				// fallback: place caret at end
				element.focus?.();
				Webroot_Extension.Log('Cursor restore fallback: focused element');
			}
		} catch (e) {
			Webroot_Extension.Log('Could not restore cursor:', e);
		}
	},
	sendPIIException: function (index) {
		if (![0, 1, 2].includes(index)) return;

		Webroot_Extension.Log('Sending PII Exception at index:', index);

		chrome.runtime.sendMessage({
			msg: 'IncrementPIIException',
			index: index
		}, () => {
			if (chrome.runtime.lastError) {
				Webroot_Extension.Log('Error sending PII Exception:', chrome.runtime.lastError);
			}
		});
	},
	showContextWarning: function (element) {
		if (!element) return;

		const divWarning = document.createElement('div');
		divWarning.id = 'wts-pii-ctx-warning';
		divWarning.className = 'wts-ctx-indicator';
		divWarning.setAttribute('role', 'status');
		const spanText = document.createElement('span');
		spanText.textContent = this.ERROR_STRING_CONTEXTLOST;
		divWarning.appendChild(spanText);
		document.body.appendChild(divWarning);
		const anchor1 = this.getIndicatorAnchor(element);
		const anchorRect = anchor1.getBoundingClientRect();
		divWarning.style.left = (anchorRect.right - divWarning.offsetWidth) + 'px';
		divWarning.style.top = (anchorRect.top - divWarning.offsetHeight - 5) + 'px';
		divWarning.style.visibility = 'visible';
		divWarning._el = element;

		window.addEventListener('resize', () => {
			const anchor1 = this.getIndicatorAnchor(divWarning._el);
			const anchorRect = anchor1.getBoundingClientRect();
			divWarning.style.left = (anchorRect.right - divWarning.offsetWidth) + 'px';
			divWarning.style.top = (anchorRect.top - divWarning.offsetHeight - 5) + 'px';
		});

	},
	// ==================== Utilities ====================
	isEditable: function(el) { return el?.matches?.(this.editableSelectors); },
	getPlainText: function (el) {
		if (el?.value !== undefined) return el.value;
		const text = el?.innerText ?? el?.textContent ?? '';
		return text;
	},
	setPlainText: function (el, text, start, end) {
		if (el?.value !== undefined) {
			const v = el.value;
			const s = start ?? 0;
			const e = end ?? v.length;
			el.value = v.slice(0, s) + text + v.slice(e);
			return;
		}
		const lo = start ?? 0;
		const hi = end ?? this.getPlainText(el).length;
		// Same-length replacement: edit each text node in-place so BR/P structure is preserved
		if (text.length === (hi - lo)) {
			let c = 0;
			const editNodes = (n) => {
				if (n.nodeType === 3) {
					const nodeStart = c;
					c += n.length;
					const overlapStart = Math.max(nodeStart, lo);
					const overlapEnd = Math.min(nodeStart + n.length, hi);
					if (overlapStart < overlapEnd) {
						const localStart = overlapStart - nodeStart;
						const localEnd = overlapEnd - nodeStart;
						n.data = n.data.slice(0, localStart) + text.slice(overlapStart - lo, overlapEnd - lo) + n.data.slice(localEnd);
					}
				} else if (n.tagName === 'BR') {
					c++;
				} else {
					for (let k = n.firstChild; k; k = k.nextSibling) editNodes(k);
					if (n.tagName === 'P') c += 2;
				}
			};
			editNodes(el);
			el.normalize();
			return;
		}
		// Different-length fallback: find start/end nodes and use Range API
		let s = null, e = null, c = 0;
		const walk = (n) => {
			if (s && e) return;
			if (n.nodeType === 3) {
				if (!s && c + n.length > lo) s = { n, o: lo - c };
				if (!e && c + n.length >= hi) e = { n, o: hi - c };
				c += n.length;
			} else if (n.tagName === 'BR') {
				c++;
			} else {
				for (let k = n.firstChild; k; k = k.nextSibling) walk(k);
				if (n.tagName === 'P') c += 2;
			}
		};
		walk(el);
		if (!s || !e) return;
		if (s.n === e.n) {
			s.n.data = s.n.data.slice(0, s.o) + text + s.n.data.slice(e.o);
		} else {
			const r = document.createRange();
			r.setStart(s.n, s.o);
			r.setEnd(e.n, e.o);
			r.deleteContents();
			r.insertNode(document.createTextNode(text));
		}
		el.normalize();
	},
	findUnderlineIndividual: function (element, matchRef) {
		if (!element) return null;

		const nodes = document.querySelectorAll(`[data-pii-element-id="${element.piiOverlayId || ''}"][data-start="${matchRef.start}"][data-end="${matchRef.end}"]`);
		if (!nodes?.length) return null;
		return nodes[0]
	},
	getEditableElement: function() {
		const active = document.activeElement;
		return (active && this.isEditable(active)) ? active : null;
	},
	mapPIITypeToResource: function (type) {
		if (this.isContextLost()) return '';
		if (!chrome.i18n) return '';
		if (!type) return '';

		switch (type) {
			case 'CREDIT_CARD': return chrome.i18n.getMessage('PIITYPE_CREDIT_CARD'); //'Credit Card';
			case 'CRYPTO': return chrome.i18n.getMessage('PIITYPE_CRYPTO'); //'Crypto Key';
			case 'US_BANK_NUMBER': return chrome.i18n.getMessage('PIITYPE_BANK_NUMBER'); //'Bank Account';
			case 'US_DRIVER_LICENSE': return chrome.i18n.getMessage('PIITYPE_DRIVER_LICENSE'); //'Driver License';
			case 'EMAIL_ADDRESS': return chrome.i18n.getMessage('PIITYPE_EMAIL_ADDRESS'); //'Email';
			case 'IP_ADDRESS': return chrome.i18n.getMessage('PIITYPE_IP_ADDRESS'); //'IP Address';
			case 'US_ITIN': return chrome.i18n.getMessage('PIITYPE_ITIN'); //'ITIN';
			case 'US_PASSPORT': return chrome.i18n.getMessage('PIITYPE_PASSPORT'); //'Passport No';
			case 'PHONE_NUMBER': return chrome.i18n.getMessage('PIITYPE_PHONE_NUMBER'); //'Phone';
			case 'US_SSN': return chrome.i18n.getMessage('PIITYPE_SSN'); //'SSN';
			case 'US_SWIFT_CODE': return chrome.i18n.getMessage('PIITYPE_SWIFT_CODE'); //'Swift Code';
			case 'PERSON': return chrome.i18n.getMessage('PIITYPE_PERSON'); //'Person';
			case 'ADDRESS': return chrome.i18n.getMessage('PIITYPE_ADDRESS'); //'Address';
			default: return chrome.i18n.getMessage('PIITYPE_UNKNOWN'); //'Unspecified PII';
		}
	}
};
chat.identifyText();