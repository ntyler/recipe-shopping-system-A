/****************************************************************************************
  Module:		background helper
  Description:	helper functions for background script
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pblaimschein@webroot.com
  Manager:		jmayr@webroot.com
  Created:		11/13/2019 (mm/dd/yyyy)
*****************************************************************************************/

var ipm_timer = null;
var tabIdLegacyUpdate = null;

chrome.runtime.onInstalled.addListener(function (details) {

	chrome.tabs.create({ url: 'background_scripts/legacyupdate.html', active: false })
		.then((tab) => tabIdLegacyUpdate = tab.id);

});

function IPMAlarm(alarm) {
	Module.OnIPMTime();
}

async function onModuleLoaded() {

	console.log('WTS: Module loaded');

	if (tabIdLegacyUpdate) {

		const complete = new Promise((resolve, reject) => {

			return check();

			function check() {
				let tab = chrome.tabs.get(tabIdLegacyUpdate);
				tab.then((x) => {
					setTimeout(check, 30);
				})
				.catch((x) => resolve(0)); //closed
			}
		});
		await complete;
	}

	Webroot_Background.init();
}

var WTSLog = {
	logLevelval: 0,
	get logLevel() {
		return WTSLog.logLevelval;
	},
	set logLevel(value) {
		if ((WTSLog.logLevelval !== value) && !isNaN(value)) {
			WTSLog.logLevelval = value;
			chrome.storage.local.set({
				"LogSettings": { "LOGLEVEL": WTSLog.logLevelval }
			}, function () {
				if (chrome.runtime.lastError) {
					console.log("WTS: Error writing LogSettings to storage - error:", chrome.runtime.lastError);
				}
			});
			if (Webroot_Background && Webroot_Background.INITIALIZED) Module.extDBG(JSON.stringify({ "LOGLEVEL": WTSLog.logLevel }));
		}
	},
	init: function () {

		if ((Webroot_Browser.identify_browser() == Webroot_Browser.CHROME) || (Webroot_Browser.identify_browser() == Webroot_Browser.EDGE_CHROMIUM)) {
			chrome.management.getSelf(function (result) {
				if (result.installType == "development") {
					WTSLog.logLevelval = 3;
					chrome.storage.local.set({ "LogSettings": { "LOGLEVEL": 3 } }, function () { });
				}
			});
		}
		else if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) {
			var pSelf = browser.management.getSelf();
			pSelf.then(function (result) {
				if (result.installType == "development") {
					WTSLog.logLevelval = 3;
					chrome.storage.local.set({ "LogSettings": { "LOGLEVEL": 3 } }, function () { });
				}
			});
		}
	},

	log: function (logVal1, logVal2) {

		if (WTSLog.logLevel < 3) return;
		console.log("WTS: ", logVal1 ? logVal1 : "", logVal2 ? logVal2 : "");
	},
	trace: function (message) {

		if (WTSLog.logLevel < 4) return;
		console.log("WTS: ", message);
	},
	logJSONRequest: function (request) {
		if (WTSLog.logLevel < 4) return;
		if (!request) return;

		if (request[0] != "{") {
			console.log("WTS: ", request);
			return;
		}
		var iDelim = request.indexOf("###URLCAT-SECTION-DELIMITER###");
		var txt = "";
		var json = {};
		if (iDelim > 0) {
			json = JSON.parse(request.substr(0, iDelim));
			txt = request.substr(iDelim + 30);
		}
		else json = JSON.parse(request);
		if (!json["PAYLOAD"]) {
			console.log("WTS: Unexpected JSON", request);
			return;
		}

		tab = json["TABID"];
		ref = "";
		op = json["PAYLOAD"]["OP"];
		switch (op) {
			case 1: op2 = "BCAP"; break;
			case 2:
				op2 = "RTAP";
				ref = json["PAYLOAD"]["REF"];
				break;
			case 3: op2 = "WL"; break;
			case 4: op2 = "CFG"; break;
			case 7: op2 = "VALIDATEKC"; break;
			case 8: op2 = "SAVEAS"; break;
			case 10: op2 = "IPM"; break;
			default: op2 = op;
		}
		url = " ";
		data = json["PAYLOAD"]["DATA"];
		if ((data.length > 1)) op2 = "SRA";
		else if ((data.length > 0) && data[0]["URL"]) {
			url = data[0]["URL"];
		}
		if (op2 == "WL") url = json["PAYLOAD"]["DATA"]

		hdr = "WTS: Request OP:" + op2 + " TAB:" + tab;
		if (ref) hdr += " REF:" + ref;

		console.log(hdr, data, url);
		if (txt) console.log("WTS: ", txt);
	},
	logJSONResponse: function (json) {
		if (WTSLog.logLevel < 3) return;

		if (!json["PAYLOAD"]) {
			console.log("WTS: Unexpected JSON", json);
			return;
		}

		tab = json["TABID"];
		err = json["PAYLOAD"]["ERR"];
		sa = json["PAYLOAD"]["STANDALONE"];
		ref = "";
		op = json["PAYLOAD"]["OP"];
		switch (op) {
			case 1: op2 = "BCAP"; break;
			case 2:
				ref = json["PAYLOAD"]["REF"];
				op2 = "RTAP";
				break;
			case 3: op2 = "WL"; break;
			case 4: op2 = "CFG"; break;
			case 7: op2 = "VALIDATEKC"; break;
			case 8: op2 = "SAVEAS"; break;
			case 10: op2 = "IPM"; break;
			default: op2 = op;
		}

		url = " ";
		data = " ";
		if (json["PAYLOAD"]["DATA"]) {
			if (json["PAYLOAD"]["DATA"].length > 1) {
				if (op2 == "BCAP") op2 = "SRA";
				data = Object.assign({}, json["PAYLOAD"]["DATA"]); //clone
			}
			else if (json["PAYLOAD"]["DATA"].length == 1) {
				data = Object.assign({}, json["PAYLOAD"]["DATA"][0]); //clone
				if (json["PAYLOAD"]["DATA"][0]["URL"]) url = json["PAYLOAD"]["DATA"][0]["URL"];
			}
			else data = Object.assign({}, json["PAYLOAD"]["DATA"]);
		}
		else {
			data = Object.assign({}, json["PAYLOAD"]);
		}

		hdr = "WTS: Response ERR:" + err + " SA:" + sa;
		if (ref) hdr += " REF:" + ref;
		hdr += " OP:" + op2;
		hdr += " TAB:" + tab;

		console.log(hdr, data, url);
	},
	logPIIRequest: function (request, sender) {
		if (WTSLog.logLevel < 4) return;

		const hdr = "WTS: Request PII TAB: " + sender?.tab?.id + " msg: " + request.msg;
		const data = request.data.length < 100 ? request.data : request.data.substr(0, 99) + "...";
		console.log(hdr, data);
	},
	logPIIResponse: function (response, request, sender) {
		if (WTSLog.logLevel < 3) return;

		const hdr = "WTS: Response PII TAB: " + sender?.tab?.id + " msg: " + request.msg;
		const data = request.data.length < 100 ? request.data : request.data.substr(0, 99) + "...";
		console.log(hdr, response, data);
	}
}
WTSLog.init();

var ComPorts = {

	// Store/read port for communication to native messaging, WebAssembly, Sockets { tabId: port }
	portDict: {},

	// ------------------------------------------------- //
	// Abstraction for NativeApi, WebAssembly and Socket://
	// Connect to NonJS module and get                   //
	// the communication port                            //
	// ------------------------------------------------- //
	connectToNonJSModule: function (tabId) {
		if (Webroot_Browser.identify_browser() == Webroot_Browser.EDGE_LEGACY) {
			var oPort = null;

			// Connect to the NativeApp
			oPort = chrome.runtime.connectNative("WTSOutOfProcessAppService");
			if (oPort == undefined) return { error: 10503, port: null };

			oPort.tabId = tabId;
			ComPorts.portDict[tabId] = oPort;
			oPort.onMessage.addListener(Webroot_Background.onNONJSresponse);
			oPort.onDisconnect.addListener(function () {
				var ooPort = oPort;
				if (ComPorts.portDict[ooPort.tabId])
					delete ComPorts.portDict[ooPort.tabId];
			});
			return { error: 0, port: oPort };
		}
		else {
			var oPort = {};

			oPort.tabId = tabId;
			ComPorts.portDict[tabId] = oPort;

			return { error: 0, port: oPort };
		}
	},

	// ------------------------------------------------- //
	// Abstraction for NativeApi, WebAssembly and Socket://
	// Disconnect from NonJS module                      //
	// ------------------------------------------------- //
	disconnectNonJSModule: function (tabId) {
		if (tabId) {
			var oPort = ComPorts.portDict[tabId]
			if (oPort) {
				if (Webroot_Browser.identify_browser() == Webroot_Browser.EDGE_LEGACY) oPort.disconnect();
				delete ComPorts.portDict[tabId];
			}
		}
	},

	// --------------------------------------------------------- //
	// Checks the port's status. If not open, creates a new one. //
	// return {error, port}                   //
	// --------------------------------------------------------- //
	checkPort: function (tabId) {
		var oPort = null;

		// Check for open port
		if (!ComPorts.portDict[tabId]) {
			// Connect with NativeApp
			returnObj = ComPorts.connectToNonJSModule(tabId);
			if (returnObj.error != 0) {
				var obj = Webroot_Server.createJsonErrorResponse(returnObj.error, 0);
				return { error: returnObj.error, port: null, jsonErrorResponse: obj };
			}
			oPort = returnObj.port;
		}
		else return ComPorts.connectToNonJSModule(tabId);

		return { error: 0, port: oPort, jsonErrorResponse: 0 };
	},


	// ------------------------------------------------- //
	// Abstraction for NativeApi, WebAssembly and Socket://
	// Send message to NonJS Module                      //
	// return int error                                  //
	// ------------------------------------------------- //
	sendNonJSModuleMessage: function (message, port) {
		if (!port) return 10404;

		WTSLog.logJSONRequest(message);

		if (!Module.WTSRequest) return 10504;
		try {
			Module.WTSRequest(message);
		}
		catch (e) {
			if (!e) console.error("WTS: WASM Exception: ");
			else if (typeof e === 'object') console.error("WTS: WASM Exception: ", e);
			else if (typeof e === 'number') console.error("WTS: WASM Exception: ", e);
			else console.error("WTS: WASM Exception: " + Module.getExceptionMessage(e));
			port.error = 1;
		}
		if (port.error) return 10505;

		return 0;
	}
}

var BA = {

	fNonTabbedErrorReported: 0, // ERROR or COMPONENT_ERROR
	KCExpDate: "",
	expiring: false,

	// ----------------------------- //
	// Update the BrowserAction icon //
	// ----------------------------- //
	updateBrowserAction: function (data, tabID) {

		// remove non-tabbed error-icons as soon as working again
		if (tabID && BA.fNonTabbedErrorReported &&
			data != "COMPONENT_ERROR" && data != "ERROR" && data != "WSA_UNREACHABLE" && data != "KC_MISSING") {

			BA.fNonTabbedErrorReported = 0;

			// Update Icon
			BA.setBAIcon("../images/Webroot32.png", undefined);

			// Set the PopUp
			BA.setBAPopup("/browser_actions/keycode_ui/keycode_ui.html", undefined );
		}

		// If BlockPage, display Red icon with Default PopUp
		if (data == "BLOCK_PAGE") {
			// Update Icon 
			BA.setBAIcon("../images/Stop32.png", tabID);

			// Set PopUp
			BA.constructPopUp('red', 0, tabID);
			return;
		}

		// If SearchEngine, display Green icon with Default PopUp
		if (data == "SEARCH_ENGINE") {

			// Update Icon 
			if (!BA.isExpiring())
				BA.setBAIcon("../images/Go32.png", tabID );
			else
				BA.setBAIcon("../images/GoExpire32.png", tabID );

			// Set PopUp
			BA.constructPopUp('green', 0, tabID);
			return;
		}

		// If connection failed, display grey webroot icon
		if (data == "COMPONENT_ERROR") {

			if (!tabID) BA.fNonTabbedErrorReported = 1;
			// Update Icon 
			BA.setBAIcon("../images/WebrootGray32.png", tabID );

			// Set PopUp
			BA.constructPopUp('componenterror', 0, tabID);
			return;
		}

		// If connection failed, display grey webroot icon
		if (data == "ERROR") {
			if (!tabID) BA.fNonTabbedErrorReported = 1;

			// Update Icon 
			BA.setBAIcon("../images/WebrootGray32.png", tabID );

			// Set PopUp
			BA.constructPopUp('error', 0, tabID);
			return;
		}

		// If WSA unreachable or uninstalled
		if (data == "WSA_UNREACHABLE") {
			if (!tabID) BA.fNonTabbedErrorReported = 1;

			// Update Icon 
			BA.setBAIcon("../images/WebrootGray32.png", tabID );

			// Set PopUp
			BA.constructPopUp('WSA_UNREACHABLE', 0, tabID);
			return;
		}

		// IF NO keycode exists
		if (data == "KC_MISSING") {
			if (!tabID) BA.fNonTabbedErrorReported = 1;

			// Update Icon 
			BA.setBAIcon("../images/WebrootExpire32.png", tabID);

			// Set the PopUp
			BA.setBAPopup("/browser_actions/keycode_ui/keycode_ui.html", tabID );
			return;
		}

		// IF KeyCode is expired
		if (data == "KC_EXPIRED") {
			if (!tabID) BA.fNonTabbedErrorReported = 1;
			// Update Icon 
			BA.setBAIcon("../images/WebrootExpire32.png", tabID);

			// Set the PopUp
			BA.setBAPopup("/browser_actions/keycode_ui/keycode_ui.html", tabID );
			return;
		}

		// Display the default browser action icon
		if (data == "DEFAULT") {
			// Update Icon 
			BA.setBAIcon("../images/Webroot32.png", tabID );

			// Set the PopUp
			BA.setBAPopup("/browser_actions/keycode_ui/keycode_ui.html", tabID );
			return;
		}

		// Otherwise, Process the data
		BA.processBrowserActionRequest(data, tabID);
	},

	constructPopUp: function (className, BRSN, tabID) {
		// Construct the PopUp URI with the text as QueryParams
		var popUpURI = '/browser_actions/Popup.html?' + 'cn=' + className + '&' + 'brsn=' + BRSN;

		if (BA.isExpiring()) {
			popUpURI += '&expire=' + BA.KCExpDate;
		}

		BA.setBAPopup(popUpURI, tabID);
	},

	setBAIcon: function (iconPath, tabID) {

		if (!iconPath) return;
		if (!tabID && (tabID != undefined)) return;

		if (Webroot_Browser.identify_browser() == Webroot_Browser.SAFARI) {
			var userAgent = navigator.userAgent.toLowerCase();
			if (userAgent.indexOf("17.6 safari") != -1) {
                if (iconPath.startsWith("../")) {
					iconPath = iconPath.replace("../", "./");
				}
			}
		}

		chrome.action.setIcon({ path: iconPath, tabId: tabID }, function (tab) {
			if (chrome.runtime.lastError);
		});
	},

	setBAPopup: function (filepath, tabID) {

		if (!filepath) return;
		if (!tabID && (tabID != undefined)) return;

		// Set the PopUp
		chrome.action.setPopup({ popup: filepath, tabId: tabID }, function (tab) {
			if (chrome.runtime.lastError);
		});
	},

	processBrowserActionRequest: function (data, tabID) {
		var obj = null;

		try { obj = JSON.parse(data); }
		catch (err) { obj = data; }

		// Handle <RED> Reputation
		if (obj.DATA[0].BLK == 1 || obj.DATA[0].BCRI < 21) {
			// Update Icon 
			BA.setBAIcon("../images/Stop32.png", tabID );

			if (obj.DATA[0].BLK == 1) {
				// Set PopUp
				BA.constructPopUp('red', obj.DATA[0].BLKREASON, tabID);
			}
			else {
				// Check for malicious categories
				var blockedCat = "-1";

				for (var i = 0; i < obj.DATA[0]["CAT.CONF"].length; i++) {
					var splitResult1 = obj.DATA[0]["CAT.CONF"][i].split('.')[0];

					if (splitResult1 == "49" || splitResult1 == "56" || splitResult1 == "57" || splitResult1 == "59" || splitResult1 == "67" || splitResult1 == "71") {
						blockedCat = splitResult1;
						break;
					}
				}

				// Construct PopUp
				switch (blockedCat) {
					case "49":
						BA.constructPopUp('red', 49, tabID);
						break;
					case "56":
						BA.constructPopUp('red', 56, tabID);
						break;
					case "57":
						BA.constructPopUp('red', 57, tabID);
						break;
					case "59":
						BA.constructPopUp('red', 59, tabID);
						break;
					case "67":
						BA.constructPopUp('red', 67, tabID);
						break;
					case "71":
						BA.constructPopUp('red', 71, tabID);
						break;
					case "-1":
						BA.constructPopUp('red', 0, tabID);
						break;
				}
			}
		}
		else if (obj.DATA[0].BCRI >= 61) {
			// Update Icon
			if (!BA.isExpiring())
				BA.setBAIcon("../images/Go32.png", tabID );
			else 
				BA.setBAIcon("../images/GoExpire32.png", tabID );

			// Set PopUp
			BA.constructPopUp('green', 0, tabID);
		}
		else if (obj.DATA[0].BCRI >= 21 && obj.DATA[0].BCRI <= 60) {
			// Update Icon 
			BA.setBAIcon("../images/Yield32.png", tabID );

			// Set PopUp
			BA.constructPopUp('yellow', 0, tabID);
		}
		return;
	},
	isExpiring: function () {
		if (!BA.KCExpDate) return false;

		var ichrKCExpDate = Date.parse(BA.KCExpDate);
		var dTDays = (ichrKCExpDate - Date.now()) / (1000 * 3600 * 24);
		BA.expiring = (Math.ceil(dTDays) <= 30);

		return BA.expiring;
	},
	checkExpiry: function (auth, mode) {

		if (BA.KCExpDate == "") {
			if (mode && ((mode == 1) || (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser() && (settings["Mode"] == 2)))) {
				BA.KCExpDate = null;
				BA.expiring = false;
				return;
			}
		}

		if (!auth || !auth.KCEXPIRYDATE) {
			BA.KCExpDate = "";
			return;
		}
		BA.KCExpDate = auth.KCEXPIRYDATE;
		var ichrKCExpDate = Date.parse(BA.KCExpDate);
		var dTDays = (ichrKCExpDate - Date.now()) / (1000 * 3600 * 24);
		BA.expiring = (Math.ceil(dTDays) <= 30);
	}
}