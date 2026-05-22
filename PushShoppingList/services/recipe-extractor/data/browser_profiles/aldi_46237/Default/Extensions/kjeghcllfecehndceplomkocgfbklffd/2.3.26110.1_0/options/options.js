/****************************************************************************************
  Module:		options
  Description:	- Initializes the strings on the options page
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		melsaie@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		08/13/2018 (mm/dd/yyyy)
*****************************************************************************************/

var DialogEnum = {
	STANDALONE: 1,
	INTEGRATED: 2,
	PRIVACY: 3,
	DECLINED: 4,
	FFV3: 5
};

//Additional permissions required for FF Manifest V3
const permissionsToRequestFfMv3 = {
	origins: ["http://*/*", "https://*/*"]
};

var kcExpiryDate = null;
var sKC = null;
var iMode = 0;
var privacyAccepted = 0;
var permissionsAccepted = 0;
var isBusiness = 0;

function init()
{
	chrome.storage.local.get(['AutoOpenDisabled', 'PrivacyAccepted', 'Auth', 'KC', 'Mode', 'Settings', 'PI'], function (result) {

		if (result.AutoOpenDisabled) {
			document.getElementById("AutoOpenDisabledDiv1").style.display = "none";
			document.getElementById("AutoOpenDisabledDiv2").style.display = "none";
			document.getElementById("AutoOpenDisabledDivFf").style.display = "none";
		}
		else {
			document.getElementById("AutoOpenDisabled1").checked = false;
			document.getElementById("AutoOpenDisabled2").checked = false;
			document.getElementById("AutoOpenDisabledDivFf").checked = false;
		}

		if (result.Auth) kcExpiryDate = result.Auth.KCEXPIRYDATE;
		if (result.KC) sKC = result.KC;
		if (result.Mode) iMode = result.Mode;
		if (result.PrivacyAccepted) privacyAccepted = result.PrivacyAccepted;
		if (result.Settings && result.Settings.Flg && (result.Settings.Flg == 6)) isBusiness = 1;

		const elm1 = document.getElementById("standalonePII");
		const elm2 = document.getElementById("integratedPII");

		if (elm1) elm1.checked = false;
		if (elm2) elm2.checked = false;

		if (((iMode == 1) && result.Settings && ((result.Settings.Flg & (1 << 1)) == 0)) || (iMode == 2)) {
			document.getElementById("standaloneExperimentalHeadline").style.display = "block";
			document.getElementById("standaloneExperimental").style.display = "block";
			document.getElementById("integratedExperimentalHeadline").style.display = "block";
			document.getElementById("integratedExperimental").style.display = "block";


			if (result.PI == undefined) {
				chrome.storage.local.set({ "PI": 1 }, function () { });
			}
			if ((result.PI == 1) || (result.PI == undefined)) {
				if (elm1) elm1.checked = true;
				if (elm2) elm2.checked = true;	
			}
		}

		// Initialize the strings
		initLocale();
		// Initialize Safari specific elements
		initSafari();

		// Add onClick event listener to elements
		document.getElementById("allowButton").addEventListener("click", onAllowButtonClick);
		document.getElementById("declineButton").addEventListener("click", onPermissionsDeclineButtonClick);
		document.getElementById("privacyBackButton").addEventListener("click", onPrivacyBackButtonClick);
		document.getElementById("removeButton").addEventListener("click", onRemoveButtonClick);
		document.getElementById("newkeycodeinput").addEventListener("keyup", onKeyCodeChange);
		document.getElementById("validatebutton").addEventListener("click", onValidateButtonClick);
		document.getElementById("notificationButton").addEventListener("click", onNotificationButtonClick);
		document.getElementById("needhelplink").addEventListener("click", onNeedHelpLinkClick);
		document.getElementById("AutoOpenDisabled1").addEventListener("click", onAutoOpenDisabledChange);
		document.getElementById("AutoOpenDisabled2").addEventListener("click", onAutoOpenDisabledChange);
		document.getElementById("AutoOpenDisabledFf").addEventListener("click", onAutoOpenDisabledChange);
		document.getElementById("allowButtonFfV3").addEventListener("click", onAllowButtonFfV3Click);
		document.getElementById("declineButtonFfV3").addEventListener("click", onPermissionsDeclineButtonClick);
		document.getElementById("standalonePII").addEventListener("click", onPIIClick);
		document.getElementById("integratedPII").addEventListener("click", onPIIClick);

		// Check if Standalone mode
		chrome.runtime.sendMessage({ msg: "is_standalone_mode" }, function (response) {

			if (!response) return;

			if (response.INITIALIZED == 0) {
				document.getElementById("integratedmode").innerText = chrome.i18n.getMessage("BA_ERROR_HDR");
				selectDialog(DialogEnum.INTEGRATED);

				// Update BrowserAction (Case: WSA UNREACHABLE)
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "COMPONENT_ERROR" }, function (response) { });
				return;
			}

			chrome.storage.local.set({ "lastOptionsPage": Math.floor(Date.now() / 1000) }, function () { });

			if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) {

				if (privacyAccepted != 1) {
					chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_EXPIRED" }, function (response) { });
					selectDialog(DialogEnum.PRIVACY);
					return;
				}

				//Check if additional permissions are enabled
				browser.permissions.contains(permissionsToRequestFfMv3).then(function (response) {
					if (!response) {
						chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_EXPIRED" }, function (response) { });
						selectDialog(DialogEnum.FFV3);
						return;
					}
					else {
						selectModeDialog(iMode);
					}
				});
			}
			else {
				selectModeDialog(iMode);
			}
		});

		// Redirect 'Enter' key in newkeycodeinput to validatebutton
		document.onkeydown = function onKeydown(event) {
			if (event.which == 13) { //Enter keycode
				document.getElementById("validatebutton").click();
			}
		};

	});

}

function initSafari() {

	if (Webroot_Browser.SAFARI != Webroot_Browser.identify_browser()) return;

	document.getElementById("howtoUninstall").style.display = "none";

	checkPermissionOnSafari();

	if (!sKC) {
		const integratedModeDetails = document.getElementById("integratedModeDetails");
		integratedModeDetails.innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_MODE_SAFARI_SETUPINCOMPLETE");
		integratedModeDetails.style = "color: red;";
	}	
}

function checkPermissionOnSafari() {
	chrome.permissions.contains(
		{ origins: ["https://*/*","http://*/*"] },
		(hasAllUrls) => {
			if (!hasAllUrls) {
				const integratedModeDetails = document.getElementById("integratedModeDetails");
				integratedModeDetails.innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_MODE_SAFARI_PERMISSION");
				integratedModeDetails.style = "color: red;";
			}
		}
	);
}

// Sets the strings on the screen in the proper locale
function initLocale()
{
	optionsTitle = chrome.i18n.getMessage("OPTIONS_TITLE");
	document.getElementById("optionstitleSA").innerText = optionsTitle;
	document.getElementById("optionstitleIN").innerText = optionsTitle;
	if (isBusiness) document.getElementById("integratedmode").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_MODE_OT");
	else document.getElementById("integratedmode").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_MODE");
	if (isBusiness) document.getElementById("integratedModeDetails").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_MODE_DETAILS_OT");
	else document.getElementById("integratedModeDetails").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_MODE_DETAILS");
	document.getElementById("integratedSettingsHeadline").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_SETTINGS_HEADLINE");
	document.getElementById("integratedExperimentalHeadline").innerText = chrome.i18n.getMessage("OPTIONS_EXPERIMENTAL_SETTINGS");
	document.getElementById("integratedLabelPII").innerText = chrome.i18n.getMessage("OPTIONS_EXPERIMENTAL_LABELPII");
	document.getElementById("integratedPIILearnMore").innerText = chrome.i18n.getMessage("OPTIONS_EXPERIMENTAL_LEARNMOREPII");

	document.getElementById("standaloneExperimentalHeadline").innerText = chrome.i18n.getMessage("OPTIONS_EXPERIMENTAL_SETTINGS");
	document.getElementById("standaloneLabelPII").innerText = chrome.i18n.getMessage("OPTIONS_EXPERIMENTAL_LABELPII");
	document.getElementById("standalonePIILearnMore").innerText = chrome.i18n.getMessage("OPTIONS_EXPERIMENTAL_LEARNMOREPII");
	document.getElementById("subscriptiontext").innerText = chrome.i18n.getMessage("OPTIONS_SUBSCRIPTION_LABEL");

	document.getElementById("labelActive").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_ACTIVE");
	document.getElementById("labelURLBlocking").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_URLBLOCKING");
	document.getElementById("labelPhishBlocking").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_PHISHBLOCKING");
	document.getElementById("labelSearchAnnotation").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_SEARCHANNOTATION");
	document.getElementById("refreshNote").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_REFRESHNOTE");
	document.getElementById("howtoModify").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_HOWTOMODIFY");
	document.getElementById("howtoUninstall").innerText = chrome.i18n.getMessage("OPTIONS_INTEGRATED_HOWTOUNINSTALL");

	addInnerHTMLFromLocale("eulatext", "OPTIONS_STANDALONE_EULATEXT")

	//document.getElementById("notificationoptionlabel").innerText = chrome.i18n.getMessage("OPTIONS_NOTIFICATION_LABEL");
	//document.getElementById("notificationoption1").innerText = chrome.i18n.getMessage("OPTIONS_NOTIFICATION_VALUE_1");
	//document.getElementById("notificationoption2").innerText = chrome.i18n.getMessage("OPTIONS_NOTIFICATION_VALUE_2");
	//document.getElementById("notificationoption3").innerText = chrome.i18n.getMessage("OPTIONS_NOTIFICATION_VALUE_3");

	document.getElementById("keycodelabel").innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_KC_LABEL");
	document.getElementById("newkeycodelabel").innerText = chrome.i18n.getMessage("OPTIONS_NEW_KEYCODE");

	document.getElementById("validatebutton").value = chrome.i18n.getMessage("OPTIONS_VALIDATE_BUTTON");
	document.getElementById("validatebutton").title = chrome.i18n.getMessage("OPTIONS_VALIDATE_BUTTON");
	document.getElementById("needhelplink").innerText = chrome.i18n.getMessage("OPTIONS_FORGOT_BUTTON");

	document.getElementById("AutoOpenDisabledText1").innerText = chrome.i18n.getMessage("OPTIONS_DONTSHOW");
	document.getElementById("AutoOpenDisabledText2").innerText = chrome.i18n.getMessage("OPTIONS_DONTSHOW");

	document.getElementById("privacyheadline").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_HEADLINE1");
	document.getElementById("allowButton").value = chrome.i18n.getMessage("OPTIONS_PRIVACY_ALLOW_BUTTON");
	document.getElementById("allowButton").title = document.getElementById("allowButton").value;
	document.getElementById("declineButton").value = chrome.i18n.getMessage("OPTIONS_PRIVACY_DECLINE_BUTTON");
	document.getElementById("declineButton").title = document.getElementById("declineButton").value

	if (isBusiness) document.getElementById("privacyDesciption1").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_DESCRIPTION1_OT");
	else document.getElementById("privacyDesciption1").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_DESCRIPTION1");

	if (isBusiness) document.getElementById("privacyDesciption2").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_DESCRIPTION2_OT");
	else document.getElementById("privacyDesciption2").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_DESCRIPTION2");

	addInnerHTMLFromLocale("privacyDesciption3", "OPTIONS_PRIVACY_DESCRIPTION3")

	//FF Manifest V3 additional permissions
	document.getElementById("permissionHeadlineFf").innerText = chrome.i18n.getMessage("PERMISSION_HEADLINE_FF");
	document.getElementById("permissionDescriptionFf-1").innerText = chrome.i18n.getMessage("PERMISSION_DESC_FF_1");
	document.getElementById("permissionDescriptionFf-2").innerText = chrome.i18n.getMessage("PERMISSION_DESC_FF_2");
	document.getElementById("AutoOpenDisabledTextFf").innerText = chrome.i18n.getMessage("OPTIONS_DONTSHOW");
	document.getElementById("declineButtonFfV3").value = chrome.i18n.getMessage("OPTIONS_PRIVACY_DECLINE_BUTTON");
	document.getElementById("declineButtonFfV3").title = document.getElementById("declineButtonFfV3").value
	document.getElementById("allowButtonFfV3").value = chrome.i18n.getMessage("OPTIONS_PRIVACY_ALLOW_BUTTON");
	document.getElementById("allowButtonFfV3").title = document.getElementById("allowButtonFfV3").value;

	document.getElementById("declineheadline").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_HEADLINE2");
	document.getElementById("removeButton").value = chrome.i18n.getMessage("OPTIONS_PRIVACY_REMOVE_BUTTON");
	document.getElementById("removeButton").title = document.getElementById("removeButton").value;
	document.getElementById("privacyBackButton").value = chrome.i18n.getMessage("OPTIONS_PRIVACY_BACK_BUTTON");
	document.getElementById("privacyBackButton").title = document.getElementById("privacyBackButton").value;
	document.getElementById("privacyDeclineText1").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_DECLINE_TEXT1");
	document.getElementById("privacyDeclineText2").innerText = chrome.i18n.getMessage("OPTIONS_PRIVACY_DECLINE_TEXT2");
}

function selectModeDialog(mode)
{
	// If Integrated mode
	if ((mode == 1) || (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser())) {
		chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "DEFAULT" }, function (response) { });
		selectDialog(DialogEnum.INTEGRATED);
		setIntegratedSettings();
		return;
	}

	selectDialog(DialogEnum.STANDALONE);
	setStandaloneSettings();
}

function addInnerHTMLFromLocale(elementId, localeString)
{
	var element = document.getElementById(elementId);
	var translatedStringWithElements = chrome.i18n.getMessage(localeString);

	if (!element || !translatedStringWithElements) return;

	element.innerText = "";
	const template = document.createElement('template');
	template.innerHTML = translatedStringWithElements;
	element.appendChild(template.content);
}

function displayExpireDays(expiresInDays)
{
	if (expiresInDays == undefined) return;
	if (expiresInDays < 0) expiresInDays = 0;

	var subscriptionValue = document.getElementById("subscriptionvalue");
	if (expiresInDays == 1) subscriptionValue.innerText = expiresInDays + chrome.i18n.getMessage("OPTIONS_SUBSCRIPTION_VALUE_1");
	else subscriptionValue.innerText = expiresInDays + chrome.i18n.getMessage("OPTIONS_SUBSCRIPTION_VALUE");
	if (expiresInDays <= 30) {
		subscriptionValue.style.fontWeight = "bold";
		subscriptionValue.style.color = "red";
	}
	else {
		subscriptionValue.style.fontWeight = "normal";
		subscriptionValue.style.color = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
			? "white" : "black";
	}
}

// Formats the Keycode by adding '-' to it for better readability
function formatKeycode(keycode)
{
	var formattedKeycode = '';

	if (!keycode) return formatKeycode;

	for (var index = 0; index < keycode.length; index++) {
		if (index != 0 && index % 4 == 0) formattedKeycode += '-';
		formattedKeycode += keycode[index];
	}

	return formattedKeycode;
}

// Triggers when user clicks on the <Privacy->Permissions->Permit> button
function onAllowButtonClick()
{
	chrome.storage.local.set({ "PrivacyAccepted": 1 }, function () { });
	privacyAccepted = 1;

	if (iMode == 1) {
		chrome.runtime.sendMessage({ msg: "CONFIG", skipresponse: 0 }, function (response) { }); // unlock "Enabled"
	}
	selectDialog(DialogEnum.FFV3);
}


function onAllowButtonFfV3Click() {
	//Display a user consent popup that allows additional permissions to be enabled
	browser.permissions.request(permissionsToRequestFfMv3).then(function (response) {
		if (response) {
			permissionsAccepted = 1;
			selectModeDialog(iMode);
		}
		else {
			selectDialog(DialogEnum.DECLINED);
		}
	});
}

// Triggers when user clicks on the <Privacy->Permissions->Decline> button
function onPermissionsDeclineButtonClick()
{
	selectDialog(DialogEnum.DECLINED);
}

// Triggers when user clicks on the <PrivacyDeclined->Privacy> button
function onPrivacyBackButtonClick()
{
	//If Privacy not accepted display Privacy Dialog
	if (privacyAccepted != 1)
		selectDialog(DialogEnum.PRIVACY);
	//If Additional Permissions not accepted display Permissions Dialog
	else if (permissionsAccepted != 1)
		selectDialog(DialogEnum.FFV3);
}

// Triggers when user clicks on the <PrivacyDeclined->Remove> button
function onRemoveButtonClick()
{
	chrome.management.uninstallSelf({ showConfirmDialog: true }, function () { var err = chrome.runtime.lastError } );
}

function onKeyCodeChange()
{
	var elm = document.getElementById('newkeycodeinput');
	if (elm.value != "")
		document.getElementById('validatebutton').removeAttribute("disabled");
	else
		document.getElementById('validatebutton').setAttribute("disabled", null);
}

// Triggers when user clicks on the <Validate Kecode> button
async function onValidateButtonClick()
{
	// unsuspend BK if suspended
	var x = await chrome.runtime.sendMessage({ msg: "SuspendWakeup" });
	while (x.responseText != 0) {
		x = await chrome.runtime.sendMessage({ msg: "SuspendWakeup" });
	}

	var kc = validateInputKeycode();
	if (!kc) return;

	sendValidationRequest(kc);
}


function onNotificationButtonClick()
{
	var Url = document.getElementById('notificationButton').getAttribute('data-Url');
	chrome.runtime.sendMessage({ msg: "open_page", url: Url }, function (response) { });
}

// Triggers when user clicks on the <Purchase Keycode> link
function onPurchaseButtonClick()
{
	// Send message to background script to open options page
	chrome.runtime.sendMessage({ msg: "open_purchase_page" }, function (response) { });
}

// Triggers when user clicks on the <Forgot Kecode> button
function onNeedHelpLinkClick()
{
	// Send message to background script to open options page
	chrome.runtime.sendMessage({ msg: "open_forgot_page" }, function (response) { });
}

function onPIIClick(evnt)
{
	if (!evnt || !evnt.target) return;

	var isChecked = evnt.target.checked;
	chrome.storage.local.set({ "PI": isChecked ? 1 : 0 }, function () { });
	chrome.runtime.sendMessage({ msg: "UpdatePIIStatus", data: isChecked ? 1 : 0 }, function (response) { });
}

function selectDialog(dialogId) {

	var permissionsDialog = document.getElementById("permissions");
	var permissionDeclineDialog = document.getElementById("permissiondecline");
	var settingsStandaloneDialog = document.getElementById("settingsStandalone");
	var settingsIntegratedDialog = document.getElementById("settingsIntegrated");
	var permissionFfV3Dialog = document.getElementById("permissionsFf");

	var on = "display:block";
	var off = "display:none";

	settingsStandaloneDialog.setAttribute("style", off);
	settingsIntegratedDialog.setAttribute("style", off);

	if (isBusiness) {

		var source = settingsIntegratedDialog.getElementsByTagName("source");
		source[0].srcset = "../images/logoOT-dark.svg";    //darkmode
		source[1].srcset = "../images/logoOT.svg";

		source = permissionsDialog.getElementsByTagName("source");
		source[0].srcset = "../images/logoOT-dark.svg";    //darkmode
		source[1].srcset = "../images/logoOT.svg";

		source = permissionFfV3Dialog.getElementsByTagName("source");
		source[0].srcset = "../images/logoOT-dark.svg";    //darkmode
		source[1].srcset = "../images/logoOT.svg";

		source = permissionDeclineDialog.getElementsByTagName("source");
		source[0].srcset = "../images/logoOT-dark.svg";    //darkmode
		source[1].srcset = "../images/logoOT.svg";
	}

	permissionsDialog.setAttribute("style", off);
	permissionDeclineDialog.setAttribute("style", off);
	permissionFfV3Dialog.setAttribute("style", off);

	switch (dialogId) {
		case DialogEnum.STANDALONE:
			settingsStandaloneDialog.setAttribute("style", on);
			break;
		case DialogEnum.INTEGRATED:
			settingsIntegratedDialog.setAttribute("style", on);
			break;
		case DialogEnum.PRIVACY:
			permissionsDialog.setAttribute("style", on);
			break;
		case DialogEnum.DECLINED:
			permissionDeclineDialog.setAttribute("style", on);
			break;
		case DialogEnum.FFV3:
			permissionFfV3Dialog.setAttribute("style", on);
			break;
		default:
			settingsStandaloneDialog.setAttribute("style", on);
			break;
	}
}

// Triggers when user changes AutoOpenDisabled checkbox
function onAutoOpenDisabledChange(event)
{
	var isAutoOpenDisabledChecked = event.target.checked;
	chrome.storage.local.set({ AutoOpenDisabled: isAutoOpenDisabledChecked }, function () { });

	if (event.target.id == "AutoOpenDisabled1" || event.target.id == "AutoOpenDisabledFf") {
		if (isAutoOpenDisabledChecked) document.getElementById("AutoOpenDisabledDiv2").style.display = "none";
		else document.getElementById("AutoOpenDisabledDiv2").style.display = "block";
	}
}

function setStandaloneSettings() {

	// If no Keycode available
	if (!sKC) {
		document.getElementById("keycodelabel").style.visibility = "hidden";
		document.getElementById("subscriptiontext").style.visibility = "hidden";
		// Update BrowserAction (Case: Missing KC)
		chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_MISSING" }, function (response) { });
	}
	else {
		document.getElementById("AutoOpenDisabledDiv2").style.display = "none";
		removeElement("eulatext");
		// Update <Input> field
		document.getElementById('keycodevalue').innerText = formatKeycode(sKC);

		// Update BrowserAction (Case: Default)
		chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "DEFAULT" }, function (response) { });

		chrome.runtime.sendMessage({ msg: "IPM", data: "DEFAULT" });

		// Check if Keycode about to expire
		if (kcExpiryDate) {
			const ichrKCExpDate = Date.parse(kcExpiryDate);
			const iTNow = Date.now();
			const dTDays = (ichrKCExpDate - iTNow) / (1000 * 3600 * 24);
			const dTiDays = Math.ceil(dTDays);

			displayExpireDays(dTiDays);

			// If Keycode not about to expire
			if ((dTiDays != undefined) && dTiDays <= 30) {

				// Display <EXPIRESIN> flyout
				var iErr; // expired
				if (dTiDays > 0) iErr = 54;
				else iErr = 53;
				updateKeycodeValidator('warning', iErr, dTiDays);
			}

		}
	};

	// if mode changes -> reload the page
	chrome.storage.onChanged.addListener(function (changes, namespace) {
		if (namespace == "local" && changes["Mode"]) {
			if ((changes["Mode"].oldValue > 1) && (changes["Mode"].newValue == 1)) {
				location.reload();
			}
		}
	});

	if (Webroot_Browser.identify_os() == OS_INFO.WINDOWS) {
		// trigger check for integrated mode
		chrome.runtime.sendMessage({ msg: "CONFIG", skipresponse: 1, integratedCheck: 1 }, function (response) { });
	}
}

function setIntegratedSettings() {

	if (!sKC && (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser()))
		// Update BrowserAction (Case: Missing KC)
		chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_MISSING" }, function (response) { });

	chrome.storage.local.get(['Settings'], function (result) {

		if (chrome.runtime.lastError) return;
		if (!result["Settings"]) return;

		setIntegratedValues(result["Settings"]);
	});

	// trigger for settings changes
	chrome.storage.onChanged.addListener(function (changes, namespace) {
		if (namespace == "local" && changes["Settings"]) {
			setIntegratedValues(changes["Settings"].newValue);
		}
		if (namespace == "local" && changes["KC"]) {
			if (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser()) {
				if ((changes["KC"].oldValue == "") && (changes["KC"].newValue != "")) {
					location.reload();
				}
			}
		}
	});

	var extUrl = "";
	var brwsr = Webroot_Browser.identify_browser();
	switch (brwsr) {
		case Webroot_Browser.CHROME:
			extUrl = "chrome://extensions/";
			break;
		case Webroot_Browser.EDGE_CHROMIUM:
			extUrl = "edge://extensions";
			break;
		case Webroot_Browser.FIREFOX:
			extUrl = "about:addons";
			break;
		case Webroot_Browser.SAFARI:
			extUrl = "";
			return;
		default:
			console.warn("WTS: Unsupported Browser!");
			return;
	}

	document.getElementById('howtoUninstall').addEventListener('click', function () {
		onRemoveButtonClick();
		//chrome.tabs.update(null, { active:true, highlighted:true, url: extUrl });
	});
}

function setIntegratedValues(settings) {
	if (!settings) return;
	if (settings["VERSION"] != 1) return;

	if (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser()) {
		if (settings["Mode"] != 2) return;
	}
	else if (settings["Mode"] != 1) return;

	var ActiveChkBox = document.getElementById("Active");
	var UrlBlockingChkBox = document.getElementById("URLBlocking");
	var PhishBlockingChkBox = document.getElementById("PhishBlocking");
	var SearchAnnotationChkBox = document.getElementById("SearchAnnotation");

	if (ActiveChkBox) ActiveChkBox.checked = (settings["URLBlocking"] == 1) || (settings["PhishBlocking"] == 1) || (settings["SearchAnnotation"] == 1);
	if (UrlBlockingChkBox) UrlBlockingChkBox.checked = (settings["URLBlocking"] == 1);
	if (PhishBlockingChkBox) PhishBlockingChkBox.checked = (settings["PhishBlocking"] == 1);
	if (SearchAnnotationChkBox) SearchAnnotationChkBox.checked = (settings["SearchAnnotation"] == 1);

}

// Send validation message to background script
function sendValidationRequest(kc)
{
	// Display page overlay with spinning icon
	enableSpinner(true);

	// Send VALIDATE message to background scripts
	chrome.runtime.sendMessage({ msg: "VALIDATE", data: kc });
}

// Checks if the input keycode matches the required keycode specs.
function validateInputKeycode()
{
	// Extract value from input field
	var kc = document.getElementById('newkeycodeinput').value;
	if (!kc) { updateKeycodeValidator('warning', 51); return; }

	// Remove any input '-' & spaces from keycode
	kc = kc.replace(/-/g, '');
	kc = kc.replace(/ /g, '');

	// Check length of keyc ode
	if (kc.length != 20) { updateKeycodeValidator('warning', 51); return; }

	return kc;
}

// Updates the text & icon of the validator
function updateKeycodeValidator(className, responseErr, expiresIn)
{
	switch (className) {
		case 'success':
			displayExpireDays(expiresIn);
			document.getElementById("validateOk").innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_VALIDATOR_SUCCESS");

			// Display the validator
			document.getElementById("keycodevalidator").style.visibility = "hidden";
			document.getElementById("newkeycodeinput").style.borderColor = "#E7E8EA";
			break;
		case 'warning':
			document.getElementById("newkeycodeinput").style.borderColor = "#DB3030";
			document.getElementById("keycodevalidator").style.visibility = "visible";

			document.getElementById('validateOk').innerText = "";

			if (!responseErr) 
				document.getElementById('keycodevalidatortext').innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_VALIDATOR_WARNING_2");
			else {
				switch (responseErr) {
					// Invalid Keycode
					case 51:
						document.getElementById('keycodevalidatortext').innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_VALIDATOR_WARNING_1");
						break;

					// Failed to connect to server
					case 52:
						document.getElementById('keycodevalidatortext').innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_VALIDATOR_WARNING_2");

						chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
						break;

					// Keycode expired
					case 53:
						document.getElementById('keycodevalidatortext').innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_VALIDATOR_WARNING_3");

						chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_EXPIRED" }, function (response) { });
						break;

					// Keycode expires in {expiresIn} days
					case 54:
						displayExpireDays(expiresIn);

						document.getElementById("newkeycodeinput").style.borderColor = "#E7E8EA";
						document.getElementById("keycodevalidator").style.visibility = "hidden";
						chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_EXPIRED" }, function (response) { });
						break;
					default:
						document.getElementById('keycodevalidatortext').innerText = chrome.i18n.getMessage("OPTIONS_KEYCODE_VALIDATOR_WARNING_2") + ' {' + responseErr + '}';
						break;
				}
			}
		  
			break;
	}
	return;
}

// Checks the return response of the VALIDATE message
function analyseValidateResponse(response)
{
	if (!response)
	{
		updateKeycodeValidator('warning', 52 /*connction failed*/);
	}
	else if (response.ERR == 0)
	{
		// Update the validator
		updateKeycodeValidator('success', 0, response.EXPIRES);

		// Update <Input> field
		var kc = response.KC;
		if (!kc) kc = validateInputKeycode();
		removeElement("eulatext");
		document.getElementById("AutoOpenDisabledDiv2").style.display = "none";
		document.getElementById("keycodelabel").style.visibility = "visible";
		document.getElementById("subscriptiontext").style.visibility = "visible";
		document.getElementById('keycodevalue').innerText = formatKeycode(kc);

		// Update <NewKeycode> field
		document.getElementById('newkeycodeinput').value = "";
		document.getElementById('validatebutton').setAttribute("disabled", null);

		document.getElementById("standaloneExperimentalHeadline").style.display = "block";
		document.getElementById("standaloneExperimental").style.display = "block";

		// Update BrowserAction (Case: Default)
		chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "DEFAULT" }, function (response) { });

		chrome.runtime.sendMessage({ msg: "IPM", data: "DEFAULT" });
	}
	else {
		// Update the validator
		updateKeycodeValidator('warning', response.ERR, response.EXPIRES);

		if (response.ERR == 54)
		{
			// Update <Input> field
			var kc = response.KC;
			if (!kc) kc = validateInputKeycode();
			removeElement("eulatext");
			document.getElementById("keycodelabel").style.visibility = "visible";
			document.getElementById("subscriptiontext").style.visibility = "visible";
			document.getElementById('keycodevalue').innerText = formatKeycode(kc);

			// Update <NewKeycode> field
			document.getElementById('newkeycodeinput').value = "";
			document.getElementById('validatebutton').setAttribute("disabled", null);

			chrome.runtime.sendMessage({ msg: "IPM", data: "DEFAULT" });
		}
	}

	// Remove the overlay
	enableSpinner(false);
}

function ProcessIPMResponse(request)
{
	if (!request || request.msg != "IPM")
	{
		document.getElementById("notification").style.visibility = "hidden";
		return;
	}
	if (!request.response.IPM)
	{
		document.getElementById("notification").style.visibility = "hidden";
		return;
	}

	var IPM = request.response.IPM;
	var str = "";
	if (IPM.MessageHeadline) str += IPM.MessageHeadline;
	if (IPM.MessageBody) str = str + "<br \>" + IPM.MessageBody;

	var element = document.getElementById('notificationtext');
	element.innerText = "";
	const template = document.createElement('template');
	template.innerHTML = str;
	element.appendChild(template.content);

	var notificationButton = document.getElementById('notificationButton');
	notificationButton.title = IPM.ButtonText;
	notificationButton.value = IPM.ButtonText;
	notificationButton.setAttribute('data-Url', IPM.LinkUrl);

	document.getElementById("notification").style.visibility = "visible";
}

function removeElement(id) {
	var elem = document.getElementById(id);
	if (elem) elem.remove();
}

function enableSpinner(enable) {

	if (enable)
		document.getElementById("spinneroverlay").style.width = "100%";
	else
		document.getElementById("spinneroverlay").style.width = "0%";
}

// Triggers when background script replies to VALIDATE message
chrome.runtime.onMessage.addListener(function (request, sender, sendResponse)
{
	if (!request) return;
	if (request.data) return; // request from other options instance or keycode_ui

	if (request.msg == "VALIDATE")
		analyseValidateResponse(request.response);
	else if (request.msg == "IPM")
		ProcessIPMResponse(request);
	else if (request.msg == "BKINITIALIZED")
		location.reload();
});

document.addEventListener("DOMContentLoaded", init);
