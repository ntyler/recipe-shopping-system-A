/****************************************************************************************
  Module:		Keycode_ui
  Description:	- Initializes and handles events on browser_actions/Keycode_ui.
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		melsaie@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		08/13/2018 (mm/dd/yyyy)
*****************************************************************************************/

// Initialize the page on load
function init() {
	// Localize page strings
	initLocale();

	// Check if Standalone mode
	chrome.runtime.sendMessage({ msg: "is_standalone_mode" }, function (response) {
		if (!response) return;

		if (response.INITIALIZED == 0) {

			// Update BrowserAction (Case: WSA UNREACHABLE)
			//chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "COMPONENT_ERROR" }, function (response) { });
			return;
		}

		chrome.storage.local.get(['Mode', 'Auth'], function (result) {

			if (result.Mode && (result.Mode == 1)) {
				//if (response.NONTABBEDERROR) chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "DEFAULT" }, function (response) { });

				if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) {
					chrome.storage.local.get(['PrivacyAccepted'], function (result) {
						if (!result.PrivacyAccepted) {
							chrome.runtime.sendMessage({ msg: "displayOptionsDlg" }, function (r) {
								window.close();
							});
						}
					});
				}
				return;
			}
			// If Standalone mode

			// Add onClick event listener to elements
			if (document.getElementById("renewbutton")) document.getElementById("renewbutton").addEventListener('click', onRenewButtonClick);
			if (document.getElementById("remindmelaterbutton")) document.getElementById("remindmelaterbutton").addEventListener('click', onRemindMeLaterLinkClick);

			if (response.STATUS == 52) {
				// Update BrowserAction (Case: connection error)
				//chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
				return;
			}

			// Check expiry
			checkKCExpiry(result.Auth);
		});
	});
}

function checkKCExpiry(auth)
{
	if (!auth) {
		// Update BrowserAction (Case: Missing Keycode)
		chrome.runtime.sendMessage({ msg: "displayOptionsDlg" }, function (r) {
			window.close();
		});
		return;
	}

	if (auth.KCEXPIRYDATE) {

		var sKCExpDate = auth.KCEXPIRYDATE;
		if (!sKCExpDate) {
			chrome.runtime.sendMessage({ msg: "displayOptionsDlg" }, function (r) {
				window.close();
			});

			return;
		}
		const iKCExpDate = Date.parse(sKCExpDate);
		const iTNow = Date.now();
		const dTDays = (iKCExpDate - iTNow) / (1000 * 3600 * 24);
		const dTiDays = Math.ceil(dTDays);

		// Expires in > 30 days
		if (dTiDays > 30) return;

		// Expires in >0 and  <=30 days
		if (dTiDays > 0) {
			displayExpiresInPopup(dTiDays);
			return;
		}

		// Is expired
		chrome.runtime.sendMessage({ msg: "displayOptionsDlg" }, function (r) {
			window.close();
		});
	}
}

// Displays the <EXPIRESIN> popup flyout
function displayExpiresInPopup(expiresIn)
{
	removeElement("webrootlogo");
	removeElement("features");

	// Add text to flyout
	if (expiresIn == 1)
		document.getElementById("warningtext_1").innerText = chrome.i18n.getMessage("BA_KEYCODE_WARNING_TEXT_1a");
	else
		document.getElementById("warningtext_1").innerText = chrome.i18n.getMessage("BA_KEYCODE_WARNING_TEXT_1b", expiresIn.toString());

	document.getElementById("warningtext_2").innerText = chrome.i18n.getMessage("BA_KEYCODE_WARNING_TEXT_2");

	document.getElementById("webrootwarninglogo").setAttribute("style", "display:block");
	document.getElementById("expirewarning").setAttribute("style", "display:block");

	// Update BrowserAction (Case: Missing Keycode)
	//chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_EXPIRED" }, function (response) { });
}

// Adds txt strings to page in appropriate locale
function initLocale()
{
	document.getElementById("title").innerText = chrome.i18n.getMessage("BA_KEYCODE_HEADER");
	document.getElementById("featuresheader").innerText = chrome.i18n.getMessage("BA_KEYCODE_FEATURES");
	addInnerHTMLFromLocale("featurebullet1", "BA_KEYCODE_FEATURE_1");
	addInnerHTMLFromLocale("featurebullet2", "BA_KEYCODE_FEATURE_2");
	addInnerHTMLFromLocale("featurebullet3", "BA_KEYCODE_FEATURE_3");
	
	document.getElementById("renewbutton").value = chrome.i18n.getMessage("BA_KEYCODE_RENEW_BUTTON");
	document.getElementById("renewbutton").title = chrome.i18n.getMessage("BA_KEYCODE_RENEW_BUTTON");
	document.getElementById("remindmelaterbutton").innerText = chrome.i18n.getMessage("BA_KEYCODE_REMINDMELATER_BUTTON");
}

function addInnerHTMLFromLocale(elementId, localeString) {
	var element = document.getElementById(elementId);
	var translatedStringWithElements = chrome.i18n.getMessage(localeString);

	if (!element || !translatedStringWithElements) return;

	element.innerText = "";
	const template = document.createElement('template');
	template.innerHTML = translatedStringWithElements;
	element.appendChild(template.content);
}

// Triggered when user clicks on the <RENEW LICENSE> button
function onRenewButtonClick()
{
	// Send message to background script to open options page
	chrome.runtime.sendMessage({ msg: "open_purchase_page" }, function (response) {
		// Close browser action
		window.close();
	});
}

// Triggers when user clicks on the <REMIND ME LATER> link
function onRemindMeLaterLinkClick()
{
	window.close();
}

function removeElement(id) {
	var elem = document.getElementById(id);
	if (elem) elem.remove();
}

document.addEventListener("DOMContentLoaded", init);