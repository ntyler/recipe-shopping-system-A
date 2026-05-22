/*******************************************************************************************
  Module:		main
  Description:	- Main contentScript for directly interacting with the page's DOM.
				- Every tab has its own instance of this script.
				- Page content (DOM) can only be modified/accessed from within the content script
/*******************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/*******************************************************************************************
  Creator:		melsaie@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		02/10/2017 (mm/dd/yyyy)
********************************************************************************************/

// IFDEF EDGE_LEGACY
if (Webroot_Browser.identify_browser() == Webroot_Browser.EDGE_LEGACY) chrome = browser;
else if (Webroot_Browser.identify_browser() == Webroot_Browser.SAFARI) chrome = browser;


var isBusiness = 0;
var initDateTime = new Date();

// ---------------------------- //
//   Webroot_Extension Object   //
// ---------------------------- //
var Webroot_Extension = 
{
	// Initialize User Preferences
	mode: 0,
	urlBlocking: 0,
	phishBlocking: 0,
	searchAnnotation: 0,
	agentPwd: 0,
	Flg: 0,
	unsuspendLatency: null,

	// Define PP limit (1MB)
	RTAP_BYTE_SIZE: 1000000,

	isIframe: false,
	currentUri: null,
	frameRef: 1,
	cfgReceivedAt: 0,
	lastConfigRefresh: 0,
	isContentObservingSet: false,
	currentChksum: 0,
	isRTAPpending: false,
	PIIDetectionEnabled: false,

	//Event handler for whitelist requests sent from blockpage to FF Extension
	whiteListListener: function (event) {
		if (event?.source === window) {
			if (Webroot_Helper.isWTSHost(new Uri(event.origin))) {
				if (event?.data?.msg === "WHITELIST")
					Webroot_Extension.whiteList({ msg: "WHITELIST", q: event.data.q, hash: event.data.hash });
				else
					console.info("Unexpected message on whiteListListener");
			}
		}
	},

	// ---------------------------------- //
	//     Initialization function        //
	// ---------------------------------- //
	init: function()
	{
		Webroot_Extension.isIframe = (window.top != window.self) ? true : false;
		SRA.SRA_DATE = SRA.SRA_DATE_DEFAULT;
		SRA.SRA_CONFIG = SRA.SRA_CONFIG_DEFAULT;

		//Listen to whitelist requests sent by blockpage (FireFox only)
		if ((Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) || (Webroot_Browser.identify_browser() == Webroot_Browser.SAFARI))
		  window.addEventListener("message", event => Webroot_Extension.whiteListListener(event));

		Webroot_Extension.checkBkSuspended().then(() => { 

			//Capture unsuspend latency
			Webroot_Extension.unsuspendLatency = new Date() - initDateTime;

			chrome.storage.local.get(['ConfigRules', 'Settings', 'LogSettings', 'Mode', 'PI'], function (result) {
				if (!chrome.runtime.lastError) {
					if (result["ConfigRules"] && (result["ConfigRules"]["VERSION"] == 4)) {
						var serverSRADate = new Date(result["ConfigRules"]["DATE"]);
						var defaultSRADate = new Date(SRA.SRA_DATE);
						if (serverSRADate > defaultSRADate) {
							SRA.SRA_CONFIG = result["ConfigRules"]["CONFIG"];
							SRA.SRA_DATE = result["ConfigRules"]["DATE"];
						}
					}

					if (result["LogSettings"] && result["LogSettings"]["LOGLEVEL"]) Webroot_Extension.logLevel = result["LogSettings"]["LOGLEVEL"];
					else Webroot_Extension.logLevel = 0;

					if (result.Settings && result.Settings.Flg && (result.Settings.Flg == 6)) isBusiness = 1;

					if (result.PI != undefined) {
						Webroot_Extension.PIIDetectionEnabled = result.PI == 1 ? true : false;
					}

					Webroot_Extension.initConfig(result);
				}
			})
			
		});

		if (Webroot_Browser.identify_browser() != Webroot_Browser.FIREFOX) {
			// keep extension unsuspended while content script is active
			setInterval( () => {
				if (chrome.runtime.id !== undefined) chrome.runtime.sendMessage({ msg: "is_standalone_mode" }, function (response) { });
			}, 25 /*seconds*/ * 1000);
		}

	},	

	connectWithPromise: function (name) {
		if (Webroot_Browser.identify_browser() == Webroot_Browser.SAFARI) {

			return new Promise((resolve, reject) => {
				let port = chrome.runtime.connect({ name: name });
				let timeoutId = null;
				let done = false;

				timeoutId = setTimeout(() => {
					if (!done) {

						port.disconnect();
						console.log("no answer from bk");						
						reject(new Error('Connection timeout after 300ms'));
					}
				}, 1000);

				port.onMessage.addListener(function (msg) {
					if (!done) {

						console.log("answer from bk");

						done = true;
						clearTimeout(timeoutId);
						port.disconnect();

						if (msg.responseText == 0) resolve(msg);
						else reject(new Error('Invalid response'));
					}
				});

				port.onDisconnect.addListener(function () {
					if (!done) {

						done = true;
						clearTimeout(timeoutId);
						reject(new Error('Port disconnected'));
					}
				});

				port.postMessage({ name: name });
			});

		}

	},

	checkBkSuspended: async function () {
		if (Webroot_Browser.identify_browser() == Webroot_Browser.SAFARI) {
			var noSucc = 1;
			var retries = 0;

			do {
				try {
					var x = Webroot_Extension.connectWithPromise("SuspendWakeup");
					var msg = await x;
					noSucc = 0;
				}
				catch (err) {
					retries = retries + 1;
				}
			} while (noSucc && (retries < 200));

			if (retries >= 100) {

				return Promise.reject();
			}
		}
		else {
			var x = await chrome.runtime.sendMessage({ msg: "SuspendWakeup" });
			while (x.responseText != 0) {
				x = await chrome.runtime.sendMessage({ msg: "SuspendWakeup" });
			}
			return x;
		}
	},

	initConfig: function (config) {

		if (!config || !config["Settings"] || (config["Settings"]["VERSION"] != 1)) {
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "COMPONENT_ERROR" }, function (response) { });
			return;
		}

		if (config["Mode"]) Webroot_Extension.mode = config["Mode"];
		if (config["Settings"]["URLBlocking"]) Webroot_Extension.urlBlocking = config["Settings"]["URLBlocking"];
		else Webroot_Extension.urlBlocking = 0;
		if (config["Settings"]["PhishBlocking"]) Webroot_Extension.phishBlocking = config["Settings"]["PhishBlocking"];
		else Webroot_Extension.phishBlocking = 0;
		if (config["Settings"]["SearchAnnotation"]) Webroot_Extension.searchAnnotation = config["Settings"]["SearchAnnotation"];
		else Webroot_Extension.searchAnnotation = 0;
		if (config["Settings"]["AgentPwd"]) Webroot_Extension.agentPwd = config["Settings"]["AgentPwd"];
		else Webroot_Extension.agentPwd = 0;
		if (config["Settings"]["Flg"]) Webroot_Extension.Flg = config["Settings"]["Flg"];
		else Webroot_Extension.Flg = 0;

		if (Webroot_Extension.mode == 0 || config["Settings"]["ERR"] == 51) {
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_MISSING" }, function (response) { var err = chrome.runtime.lastError });
			Webroot_Extension.updateConfig();
			return;
		}

		Webroot_Extension.runScript();
	},

	// ----------------------------------------- //
	// Sends log entry to background             //
	// ----------------------------------------- //
	Log: function (logVal1, logVal2, logVal3) {

		if (Webroot_Extension.logLevel >= 3) {

			var logObj = {
				msg: "LOG",
				headline: logVal1
			};

			if (logVal2 || logVal3) {
				logObj.details = {
					logVal2: logVal2,
					logVal3: logVal3
				}
			};
			try {
				if (chrome?.runtime?.id)
					chrome.runtime.sendMessage(logObj, function (response) { });
			}
			catch (e) {
				console.log("Background unavailable", e);
			}
		}
		return true;
	},

	// ----------------------------------------- //
	// Sends a BCAP request                      //
	// Returns True --> If BCAP is switched ON   //
	// Returns False --> If BCAP is switched OFF //
	// ----------------------------------------- //
	processBCAP: function (url)
	{
		if ((Webroot_Extension.urlBlocking != 1) && (Webroot_Extension.phishBlocking != 1)) {
			if (Webroot_Extension.mode == 1) Webroot_Extension.updateConfig();
			return false;
		}

		if (Webroot_Extension.isIframe) {
			Webroot_Extension.frameRef = Webroot_Extension.CreateREF(url);
		}

		chrome.runtime.sendMessage({ msg: "BCAP", ppURL: url, ref: Webroot_Extension.frameRef }, function (response)
		{
			if (!response || (response.responseText == undefined))
			{ 
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
				return;
			}
			// Check for errors
			var error = response.responseText;
			if (error != 0)
			{
				// Log error
				console.info("WTS_Extension [processBCAP]: " + JSON.stringify(error));

				// Update BrowserAction (Case: WSA UNREACHABLE)
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
			}
		});
		return true;
	},

	CreateREF: function(str)
	{
		var chkSum = parseInt(Math.random() * 10000000);
		if (str) {
			for (i = 0; i < Math.min(str.length, 250); i++) {
				chkSum += str.charCodeAt(i);
			}
		}
		return chkSum;
	},

	// ----------------------------------------- //
	// Sends a RTAP request                      //
	// Returns True --> If RTAP is switched ON   //
	// Returns False --> If RTAP is switched OFF //
	// ----------------------------------------- //
	processRTAP: function (url, isDynRTAP)
	{
		if (Webroot_Extension.phishBlocking != 1) return false;

		// Get Root Document HTML
		var htmlContent = Webroot_Helper.extractPageHtml(document);

		// Check size of extracted document
		if (htmlContent.length <= 0) return true;
		if (Webroot_Helper.getByteLen(htmlContent) > Webroot_Extension.RTAP_BYTE_SIZE) return true;

		Webroot_Extension.isRTAPpending = true;

		chrome.runtime.sendMessage({ msg: "RTAP", isDynRTAP: isDynRTAP, ppURL: url, RootHTML: htmlContent, ref: Webroot_Extension.frameRef.toString() }, function (response)
		{
			if (!response || (response.responseText == undefined) ) 
			{
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
				return;
			}
			// Check for errors
			var error = response.responseText;
			if (error != 0)
			{
				// Log error
				console.info("WTS_Extension [processRTAP]: " + JSON.stringify(error));

				// Update BrowserAction (Case: WSA UNREACHABLE)
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
			}
		});
		return true;
	},

	whiteList: function (jsnWhiteListMessage)
	{
		chrome.runtime.sendMessage( jsnWhiteListMessage, function (response) {
			if (!response || (response.responseText == undefined)) {
				console.info("WTS_Extension [processWhiteList]");
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
			}
			// Check for errors
			var error = response.responseText;
			if (error != 0) {
				// Log error
				console.info("WTS_Extension [processWhiteList]: " + JSON.stringify(error));

				// Update BrowserAction (Case: WSA UNREACHABLE)
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
			}
		});
	},

	// ----------------------------------------- //
	// Sends a WHITELIST request                 //
	// Returns True --> If Whitelisting url      //
	// Returns False --> otherwise               //
	// ----------------------------------------- //
	processWhiteList: function (uri)
	{
		const urlId = Webroot_Helper.isWTSUrl(uri);

		if (urlId == WTSURLID.BLOCKPAGE || urlId == WTSURLID.IFRAMEBLOCKPAGE)
		{
			Webroot_Extension.whiteList({ msg: "WHITELIST", ppURL: url });
			return true;
		}
		return false;
	},

	getContentHash: function (string) {
		var hash = 0, i, chr;
		if (string.length === 0) return hash;
		for (i = 0; i < string.length; i++) {
			chr = string.charCodeAt(i);
			hash = ((hash << 5) - hash) + chr;
			hash |= 0; // Convert to 32bit integer
		}
		return hash;
	},

	// ---------------------------------- //
	// OnDocumentComplete event listener  //
	// ---------------------------------- //
	runScript: function ()
	{
		// Check if extension is disabled
		if (!Webroot_Extension.urlBlocking && !Webroot_Extension.phishBlocking && !Webroot_Extension.searchAnnotation) {
			if (Webroot_Extension.mode == 1) Webroot_Extension.updateConfig();
			return;
		}

		const uri = new Uri(document.URL);
		if (!uri || uri?.raw == '') return;
		
		if (Webroot_Extension.currentUri?.raw == uri.raw) return;
		Webroot_Extension.currentUri = uri;

		// Check for WTS URL
		const urlId = Webroot_Helper.isWTSUrl(Webroot_Extension.currentUri);
		if (urlId == WTSURLID.IWHITELISTPAGE) {
			Webroot_Extension.handleIframeWhitePage(Webroot_Extension.currentUri.raw);
			return;
		}
		else if (urlId == WTSURLID.WHITELISTPAGE) {
			if (Webroot_Extension.processWhiteList(Webroot_Extension.currentUri)) {
				chrome.runtime.sendMessage({ msg: "PAGE-SYNC-LATENCY", value: new Date() - initDateTime }, function (response) { });
			}
			return;
		}
		else if (urlId != WTSURLID.NONE) {
			// Update BrowserAction if BlockPage
			if (((urlId == WTSURLID.BLOCKPAGE || urlId == WTSURLID.IFRAMEBLOCKPAGE)) && (Webroot_Extension.isIframe == false)) {
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "BLOCK_PAGE" }, function (response) { });
			}
			return;
		}

		// Perform SRA
		if (SRA.processSRA(Webroot_Extension.currentUri)) return;

		// Perform BCAP
		if (Webroot_Extension.processBCAP(Webroot_Extension.currentUri?.raw)) {

			//Report PAGE-SYNC-LATENCY
			chrome.runtime.sendMessage({ msg: "PAGE-SYNC-LATENCY", value: new Date() - initDateTime }, function (response) { });
			//Report PAGE-UNSUSPEND-LATENCY
			chrome.runtime.sendMessage({ msg: "PAGE-UNSUSPEND-LATENCY", value: Webroot_Extension.unsuspendLatency }, function (response) { });
		
			return;
		};
	},
	// -------------------------------------------------- //
	// Update page elements and display main document URL //
	// -------------------------------------------------- //
	handleIframeWhitePage: function (url) {

		// Extract tabId
		var tabId = url.substring(url.toLowerCase().indexOf("tabid") + 6);

		chrome.runtime.sendMessage({ msg: "getTabUrl", tabId: tabId }, function (response) {
			// Update page HTML
			var blockedURL = document.getElementById("blockedURL");
			blockedURL.href = response.responseText;

			// Update style attribute of URL element
			document.getElementById("urlBlock").style.display = "block";

			// Break down URL if long enough
			if (response.responseText.length >= 40) {
				blockedURL.innerText = response.responseText.substring(0, 40) + "...";
				blockedURL.title = response.responseText;
			}
			else { blockedURL.innerText = response.responseText; }

			return 0;
		});
		return 0;
	},

// -------------------------------------------------------- //
	// Check received response for errors        
	// return: -1 -> error; 0 -> stop processing; 1 -> success/proceed
	// -------------------------------------------------------- //
	checkResponseError: function (response)
	{
		if (!response || (response.responseText == undefined)) return -1;
		var obj = response.responseText;

		if (obj.ERR == 0) {
			return 1;
		}
		else if (obj.ERR == 51) { //ERR=51 -> missing KC
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_MISSING" }, function (response) { });
			return 0;
		}
		else if (obj.ERR == 52) { //ERR=52 -> KC failed to validate
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
		}
		else if (obj.ERR == 55) { //ERR=55 -> "Privacy not accepted" (FF)
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_MISSING" }, function (response) { var err = chrome.runtime.lastError });
		}
		else if (obj.ERR == 200) { //ERR=200 -> "Invalid Password"
			var str = chrome.i18n.getMessage("Password");
			alert(str);
			return 1;
		}
		else if (obj.ERR == 503) {
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "WSA_UNREACHABLE" }, function (response) { });
		}
		else if (obj.ERR == 1062) { // ERROR_SERVICE_NOT_ACTIVE returned if "Enable Web Shield" disabled (WSA GUI)
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "DEFAULT" }, function (response) { });
			//not an error; just stop processing
			return 0;
		}
		else if (obj.ERR > 0) { 
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "ERROR" }, function (response) { });
		}

		return -1;
	},

	// --------------------------------------------------------- //
	// Extracts the BLK URL from QueryParams and navigates to it //
	// --------------------------------------------------------- //
	processWhiteListResponse: function (url,msg) {

		var q;
		var blkURL;
		var extra;
		var tabId;
		var isV2 = (msg.responseText.DATA && msg.responseText.DATA[0] && msg.responseText.DATA[0]["BURL"]) ? true : false;

		//Report PAGE-ASYNC-LATENCY
		chrome.runtime.sendMessage({ msg: "PAGE-ASYNC-LATENCY", value: new Date() - initDateTime }, function (response) { });

		if (isV2) {

			if (msg.responseText.ERR == 200) return;

			blkURL = msg.responseText.DATA[0]["BURL"];
			extra = msg.responseText.DATA[0]["EXTRA"];
			tabId = extra.substring(extra.indexOf(":") + 1);
		}
		else {

			// Split URL
			var uri = new Uri(url);
			if (uri.host.toLowerCase() != "wf.webrootanywhere.com") return;
			q = uri.query();
			blkURL = q["burl"];
			extra = q["extra"];
			tabId = extra.substring(extra.indexOf(":") + 1);
		}

		// Navigate to WhiteListed URL
		if (tabId == '')
		{
			if (!isV2) window.location = Webroot_Helper.decodeBase64(blkURL);
			else window.location = blkURL;
		}
		else {
			if (msg.responseText.ERR == 0) {
				var tabID = extra.substring(extra.indexOf(":") + 1);
				if (/^\d+$/.test(tabID)) {
					window.location = "https://" + BLOCKPAGEHOST + IWHITELISTPATH + "?" + "tabId=" + tabID + "&flg=" + Webroot_Extension.Flg;
				}
				else {
					console.info("Unexpected TabId");
				}
			}
		}
	},

	// ---------------------------------------- //
	// BCAP --> if page classified as malicious --> Navigates to BlockPage
	// BCAP --> If page not malicious --> Performs RTAP
	// ---------------------------------------- //
	processBCAPResponse: function (jsonResponse)
	{
		// BCAP
		if (jsonResponse.DATA[0].REF != Webroot_Extension.frameRef) return;

		//hidden BCAP
		Webroot_Extension.updateSettingsFromWSA(jsonResponse);

		//Report PAGE-ASYNC-LATENCY
		chrome.runtime.sendMessage({ msg: "PAGE-ASYNC-LATENCY", value: new Date() - initDateTime }, function (response) { });

		if ((Webroot_Extension.urlBlocking == 1) ||
			((Webroot_Extension.phishBlocking == 1) && (jsonResponse.DATA[0].RTAP == -1)))
		{
			if (jsonResponse.DATA[0].BLK == 1) {

				// Construct Block Page URL
				var myBlockPageURL;
				if (Webroot_Extension.isIframe == true)
					myBlockPageURL = Webroot_Helper.constructBlkUrl(jsonResponse,1);
				else
					myBlockPageURL = Webroot_Helper.constructBlkUrl(jsonResponse,0);

				// Navigate to Blockpage
				if (Webroot_Extension.isIframe) document.location = myBlockPageURL;
				else window.location = myBlockPageURL;

				return;
			}
			// Update BrowserAction icon (only for main frame)
			else if (Webroot_Extension.isIframe == false) chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: jsonResponse }, function (response) { });
		}

		if (jsonResponse.DATA[0].NOPP == 2) {
			//TODO remove mode == 2 as soon as dynRTAP gets supported in integrated
			if (Webroot_Extension.mode == 2) RtapObserver.startObserver();
			return;
		}
		if (jsonResponse.DATA[0].NOPP == 1 || jsonResponse.DATA[0].PRIVATEIP == 1) return;

		// Perform RTAP
		if (Webroot_Extension.processRTAP(document.URL, false)) return;

	},

	// ---------------------------------------- //
	// RTAP --> if page classified as malicious --> Navigates to BlockPage
	// ---------------------------------------- //
	processRTAPResponse: function (jsonResponse)
	{
		// RTAP
		if (Webroot_Extension.frameRef.toString() != jsonResponse.REF) return;

				// Check Reputation
		if (jsonResponse.DATA[0].ISPHIS == 1) {
			if (jsonResponse.DATA[0].ISWHT == 1) {
				Webroot_Extension.isRTAPpending = false;
				return;
			}

			// Construct Block Page URL
			if (Webroot_Extension.isIframe == true) {
				var myBlockPageURL = Webroot_Helper.constructBlkUrl(jsonResponse, 1);
				document.location = myBlockPageURL;
			}
			else {
				var myBlockPageURL = Webroot_Helper.constructBlkUrl(jsonResponse);
				window.location = myBlockPageURL;
			}

			Webroot_Extension.isRTAPpending = false;
			return;
		}
		else {
			Webroot_Extension.isRTAPpending = false;
			if ((Webroot_Extension.mode == 2) && (!RtapObserver.IsContentObservingSet)) RtapObserver.startObserver();
		}
	},

	updateConfig: function () {
		if (Webroot_Extension.isIframe) return;
		var ms = Date.now() - Webroot_Extension.lastConfigRefresh;
		if (ms < 2000) return;

		Webroot_Extension.lastConfigRefresh = Date.now();
		chrome.runtime.sendMessage({ msg: "CONFIG", skipresponse: 1 }, function (response) { });
	},

	updateSettingsFromWSA: function (jsonResponse) {

		if (!jsonResponse || !jsonResponse.SETTINGS || !jsonResponse.SETTINGS.DATA) return;

		var settings = jsonResponse.SETTINGS.DATA;
		if (settings.hasOwnProperty('URLBlocking')) Webroot_Extension.urlBlocking = settings.URLBlocking;
		if (settings.hasOwnProperty('PhishBlocking')) Webroot_Extension.phishBlocking = settings.PhishBlocking;
		if (settings.hasOwnProperty('SearchAnnotation')) Webroot_Extension.searchAnnotation = settings.SearchAnnotation;
		if (settings.hasOwnProperty('Mode')) Webroot_Extension.mode = settings.Mode;
		if (settings.hasOwnProperty('AgentPwd')) Webroot_Extension.agentPwd = settings.AgentPwd;
		if (settings.hasOwnProperty('Flg')) Webroot_Extension.Flg = settings.Flg;
	}
};

chrome.storage.onChanged.addListener(function (changes, namespace) {
	if (namespace == "local") {
		if (changes["Settings"]) {
			var ms = Date.now() - Webroot_Extension.lastConfigRefresh;
			if (ms > 2000) return;
			Webroot_Extension.initConfig(changes["Settings"].newValue);
		}
		if (changes["PI"]) {
			Webroot_Extension.PIIDetectionEnabled = changes["PI"].newValue == 1 ? true : false;
		}
		if (changes["LogSettings"]) {
			if (changes["LogSettings"].newValue && changes["LogSettings"].newValue.LOGLEVEL >= 1) Webroot_Extension.logLevel = changes["LogSettings"].newValue.LOGLEVEL;
		} 
	}
});

// Initialize ContentScript
Webroot_Extension.init();

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse)
{
	if (!msg || !msg.responseText) return;

	var jsonResponse = msg.responseText;

	// ------ //
	// CONFIG //
	// ------ //
	if (jsonResponse.OP == 4)
	{
		if ((Date.now() - Webroot_Extension.cfgReceivedAt) < 1000) return;

		// Handle Config Response
		var iSuccess = Webroot_Extension.checkResponseError(msg);
		if (iSuccess <= 0)
		{
			if (iSuccess < 0) console.info("WTS_Extension [RUNTIME.ONMESSAGE][OP-4]: " + JSON.stringify(jsonResponse));
			return;
		}
		// if Standalone and no KeyCode terminate
		if ((jsonResponse.STANDALONE == 1) && !jsonResponse.KC) {
			// Update the browser action to resemble missing keycode
			chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "KC_MISSING" }, function (response) { });
			return;
		}
		Webroot_Extension.cfgReceivedAt = Date.now();
		Webroot_Extension.runScript();
	}

	// ---- //
	// BCAP //
	// ---- //
	else if (jsonResponse.OP == 1)
	{
		// Handle BCAP Response
		var iSuccess = Webroot_Extension.checkResponseError(msg);
		if (iSuccess <= 0)
		{
			if (iSuccess < 0) console.info("WTS_Extension [RUNTIME.ONMESSAGE][OP-1]: " + JSON.stringify(jsonResponse));
			return;
		}

		var dataEntries = jsonResponse.DATA.length;
		if (dataEntries > 1) SRA.processSRAResponse(jsonResponse); //SRA
		else Webroot_Extension.processBCAPResponse(jsonResponse);      //BCAP
		return;
	}

	// ---- //
	// RTAP //
	// ---- //
	else if (jsonResponse.OP == 2)
	{
		// Handle BCAP Response
		var iSuccess = Webroot_Extension.checkResponseError(msg);
		if (iSuccess <= 0)
		{
			Webroot_Extension.isRTAPpending = false;
			if (iSuccess < 0) console.info("WTS_Extension [RUNTIME.ONMESSAGE][OP-2]: " + JSON.stringify(jsonResponse));
			return;
		}

		//Check response
		Webroot_Extension.processRTAPResponse(jsonResponse);
		return;
	}

	// --------- //
	// WHITELIST //
	// --------- //
	else if (jsonResponse.OP == 3)
	{
		// Handle WhiteList Response
		var iSuccess = Webroot_Extension.checkResponseError(msg);
		if (iSuccess <= 0)
		{
			if (iSuccess < 0) console.info("WTS_Extension [RUNTIME.ONMESSAGE][OP-3]: " + JSON.stringify(jsonResponse));
			return;
		}

		//Check response
		Webroot_Extension.processWhiteListResponse(document.URL,msg);
		return;
	}
});