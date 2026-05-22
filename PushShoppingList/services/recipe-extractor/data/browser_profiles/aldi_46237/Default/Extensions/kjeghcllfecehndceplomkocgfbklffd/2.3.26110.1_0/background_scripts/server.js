/****************************************************************************************
  Module:		server
  Description:	- Background script required for communicating with local WSA plugin.
				- Handles sending requests and recieving responses from local WSA plugin.
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		melsaie@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		02/10/2017 (mm/dd/yyyy)
*****************************************************************************************/

// ------------- //
// SERVER Object //
// ------------- //
var Webroot_Server = {
	// ----------------------------
	// Create Config JSON structure.
	// Returns a stringified <JSON>
	// --------------------------- //
	createConfigRequest: function (tabId, skipResponse, integratedCheck) {

		// Create JSON object
		var JSON_Object = {
			TABID: tabId,
			PAYLOAD: {
				VER: 1,
				OP: 4,
				BRWSR: Webroot_Browser.identify_browser(),
				FEATURE: 6,
				DATA: [
					{
						BROWSER: Webroot_Browser.browserFlags()
					}
				]
			}
		};

		if (skipResponse) {
			JSON_Object.OPTCFG = 1;
		}

		if (integratedCheck) {
			JSON_Object.INTEGRATEDCHECK = 1;
		}

		// Return string form of the JSON object
		return JSON.stringify(JSON_Object);
	},
		
	// ----------------------------
	// Create SRA JSON structure.
	// Returns a stringified <JSON>
	// --------------------------- //
	createSraRequest: async function (linksArray, tabId) {
		await Webroot_urlCache.findUrls(linksArray);

		var newRequest = {
			"TABID": tabId,
			"PAYLOAD": {
				"VER": 1,
				"OP": 1,
				"BRWSR": Webroot_Browser.identify_browser(),
				"DATA": linksArray
			}
		}

		// Return string form of the JSON object
		return JSON.stringify(newRequest);
	},

	// ----------------------------
	// Create BCAP JSON structure.
	// Returns a stringified <JSON>
	// --------------------------- //
	createBcapRequest: async function (myURL, tabId, refId) {

		var myURI = new Uri(myURL);
		// BreakDown URL
		var processedURL = myURI.urlWithoutQuery;
		var processedServer = myURI.host;
		var jsnData = [
			{
				URL: processedURL,
				REF: refId
			}
		];

		const ipCachePromise = Webroot_IP_cache.get_IP(processedServer);
		const urlCachePromise = Webroot_urlCache.findUrls(jsnData);

		var values = await Promise.all([ipCachePromise, urlCachePromise]);
		{

			jsnData[0]["IP"] = values[0];

			// Create JSON object
			var JSON_Object = {
				TABID: tabId,
				PAYLOAD: {
					VER: 1,
					OP: 1,
					BRWSR: Webroot_Browser.identify_browser(),
					FEATURE: 7,
					DATA: jsnData
				}
			};

			// Return string form of the JSON object
			return JSON.stringify(JSON_Object);
		};
	},

	// --------------------------
	// Create RTAP JSON structure.
	// Returns a stringified <JSON>
	// --------------------------- //
	createRtapRequest: async function (isDynRTAP, documentOuterHTML, documentURL, tabId, ref) {

		var documentURI = new Uri(documentURL);
		var processedURL = documentURI.urlWithoutQuery.toLowerCase();
		var processedServer = documentURI.host;
		var ip = await Webroot_IP_cache.get_IP(processedServer);

		if (WTSLog.logLevel == 3) {
			if (!isDynRTAP) WTSLog.log("Request OP:RTAP URL:" + processedURL);
			else WTSLog.log("Request OP:DRTAP URL:" + processedURL);
		}

		// Add TABID
		var JSON_Object = {
			"TABID": tabId,
			"PAYLOAD": {
				"VER": 1,
				"OP": 2,
				"BRWSR": Webroot_Browser.identify_browser(),
				FEATURE: 4,
				"REF": ref,
				"DATA": [
					{
						"URL": processedURL,
						"IP": ip,
						"UID": 1,
						"PARENT": 0,
						"ISDYNRTAP": isDynRTAP ? 1 : 0
					}
				],
				"RESET": 1
			}
		};

		// Return string form of the JSON object
		request = JSON.stringify(JSON_Object);

		// Add ROOT PAGE INNER CONTENT
		request += "###URLCAT-SECTION-DELIMITER###";
		request += documentOuterHTML;

		return request;
	},

	// ----------------------------
	// Create Whitelist JSON structure for QueryV1.
	// Returns a stringified <JSON>
	// --------------------------- //
	createWhiteListRequest_QueryV1: function (whiteListURL, tabId)
	{
		var processedURL = "";

		var whitelistURI = new Uri(whiteListURL);
		// Split URL
		var paramDict = whitelistURI.query();

		// Extract PassHash
		var passValue = paramDict["bpass"];

		// Extract Encoded Blocked URL
		var encodedBlkURL = paramDict["burl"];

		// Decode Blocked URL
		var decodedBlkURL = Webroot_Helper.decodeBase64(encodedBlkURL);

		// BreakDown URL
		var uri = new Uri(decodedBlkURL);
		processedURL = uri.host;
		if (WTSLog.logLevel == 3) WTSLog.log("Request OP:WL URL:" + processedURL);

		var whiteListRequest = {
			"TABID": tabId,
			"PAYLOAD": {
				"VER": 1,
				"OP": 3,
				"BRWSR": Webroot_Browser.identify_browser(),
				"DATA": [
					processedURL
				]
			}
		}
		// Add PassHash
		if (passValue != '0') {
			whiteListRequest["PAYLOAD"]["HASH"] = passValue;
		}

		// Return string form of the JSON object
		return JSON.stringify(whiteListRequest);
	},

	// ----------------------------
	// Create Whitelist JSON structure for QueryV1.
	// Returns a stringified <JSON>
	// --------------------------- //
	createWhiteListRequest_QueryV2: function (qParam, passHash, tabId) {

		var whiteListRequest = {
			"TABID": tabId,
			"PAYLOAD": {
				"VER": 1,
				"OP": 3,
				"BRWSR": Webroot_Browser.identify_browser(),
				"DATA": [
					{
						"Q": qParam
					}
				]
			}
		}
		// Add PassHash
		if (passHash != '0') {
			whiteListRequest["PAYLOAD"]["HASH"] = passHash;
		}

		// Return string form of the JSON object
		return JSON.stringify(whiteListRequest);
	},

	// -------------------------------------- //
	//		 Create SAVEAS JSON structure  	  //
	//       to be sent to server			  //
	// -------------------------------------- //
	create_saveas_request: function (fileURL, filePath, tabId) {

		if (WTSLog.logLevel == 3) WTSLog.log("Request OP:SAVEAS URL:" + fileURL + " FILE:" + filePath);

		var JSON_Object = {
			TABID: tabId,
			PAYLOAD: {
				VER: 1,
				OP: 8,
				BRWSR: Webroot_Browser.identify_browser(),
				DATA: [
					{
						URL: fileURL,
						FILE: filePath
					}
				]
			}
		};

		return JSON.stringify(JSON_Object);
	},

	// ----------------------------
	// Create BCAP JSON structure.
	// Returns a stringified <JSON>
	// --------------------------- //
	createValidateRequest: function (keycode)
	{
		// Create JSON object
		var JSON_Object = {
			TABID: 0,
			PAYLOAD: {
				VER: 1,
				OP: 7,
				BRWSR: Webroot_Browser.identify_browser(),
				DATA: [
					{
						KC: keycode
					}
				]
			}
		};

		// Return string form of the JSON object
		return JSON.stringify(JSON_Object);
	},

	// --------------------------
	// Create error JSON response.
	// Returns a <JSON> object
	// ------------------------ //
	createJsonErrorResponse: function (iError, iOP)
	{
		// Create JSON object
		var JSON_Object =
		{
			VER: 1,
			OP: iOP,
			ERR: iError,
		};

		return JSON_Object;
	},

	// --------------------------------------------------
	// Checks if OptionsDialog needs to be displayed.
	// Returns <void>
	// ----------------------------------------------- //
	checkDisplayOptionsDialog: function () {

		const installedSinceDays = Math.floor((Date.now() - new Date(Webroot_Background.INSTALLDATE)) / 1000 / 60 / 60 / 24);

		if (installedSinceDays >= 30) return;

		chrome.storage.local.get(['AutoOpenDisabled', 'lastOptionsPage'], function (result) {

			var lastOptionsPageHours = Number.MAX_SAFE_INTEGER;
			if ((typeof result.lastOptionsPage == 'number') && (result.lastOptionsPage >= new Date("2010-01-01").getTime() / 1000) && (result.lastOptionsPage <= Date.now() / 1000)) lastOptionsPageHours = Math.floor((Date.now() - result.lastOptionsPage * 1000) / 1000 / 60 / 60);

			if (!result.AutoOpenDisabled && lastOptionsPageHours >= 24) {
				Webroot_Background.displayOptionsPage();
			}
		});
	},

	// --------------------------------------------------
	// Update the config settings of the backgroundScript.
	// Returns <void>
	// ----------------------------------------------- //
	updateSettings: function (jsonObj, tabId)
	{
		if (!jsonObj) return;

		if (jsonObj.STANDALONE)
		{
			var oldStandalone = Webroot_Background.STANDALONE
			Webroot_Background.STANDALONE = jsonObj.STANDALONE;
			

			// If no KC available in response
			if (!jsonObj.KC)
			{
				// IF no KC stored in extension
				if (!Webroot_Background.KEYCODE && (Webroot_Background.OPTIONSPAGESTARTEDONCE == 0) )
				{
					Webroot_Server.checkDisplayOptionsDialog();
				}

				return jsonObj;
			}
			else {
				if (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser()) {

					chrome.permissions.contains(
						{ origins: ["https://*/*", "http://*/*"] },
						(hasAllUrls) => {
							if (!hasAllUrls) Webroot_Server.checkDisplayOptionsDialog();
						}
					);
				}
			}

			if (!Webroot_Background.KEYCODE || Webroot_Background.KEYCODE != jsonObj.KC.toLowerCase())
			{
				Webroot_Background.KEYCODE = jsonObj.KC.toLowerCase();
			}
			Webroot_Background.Enabled = 1;

			return jsonObj;
		}
		if (jsonObj.VER == 1)
		{
			Webroot_Background.STANDALONE = 0;
			Webroot_Background.KEYCODE = '';

			if (jsonObj.DATA && jsonObj.DATA[0]) {
				if (jsonObj.DATA[0].URLBlocking) Webroot_Background.Enabled = jsonObj.DATA[0].URLBlocking;
				else Webroot_Background.Enabled = 0;

				if (jsonObj.DATA[0].Flg) Webroot_Background.Flg = jsonObj.DATA[0].Flg;
				else Webroot_Background.Flg = 0;

				if (jsonObj.DATA[0].AgentPwd) Webroot_Background.agentPwd = jsonObj.DATA[0].AgentPwd;
				else Webroot_Background.agentPwd = 0;
			}
			else {
				Webroot_Background.Enabled = 0;
				Webroot_Background.Flg = 0;
				Webroot_Background.agentPwd = 0;
			}

			return jsonObj;
		}
		else
		{
			Webroot_Background.STANDALONE = 0;

			var obj = Webroot_Server.createJsonErrorResponse(10426, jsonObj);
			return obj;
		}
	},

	// ----------------------------------------------------------
	// Turns the Config settings OFF within the backgroundScript.
	// Returns <void>
	// ------------------------------------------------------- //
	analyseErrorResponse: function (jsonObj)
	{

		Webroot_Background.STANDALONE = jsonObj.PAYLOAD.STANDALONE;
		Webroot_Background.STATUSID = jsonObj.PAYLOAD.ERR;

		if (jsonObj.PAYLOAD.ERR == 55) { // ERR=55 -> "Privacy not accepted" (FF)
			Webroot_Server.checkDisplayOptionsDialog();
		}

		// If <VALIDATE> message
		if (jsonObj.PAYLOAD.OP == 7)
		{
			if (jsonObj.PAYLOAD.KC && (jsonObj.PAYLOAD.ERR == 54)) {
				Webroot_Background.KEYCODE = jsonObj.PAYLOAD.KC.toLowerCase();
				Webroot_Background.STATUSID = jsonObj.PAYLOAD.ERR;

				chrome.runtime.sendMessage({ msg: "VALIDATE", response: jsonObj.PAYLOAD });
			}
			else
			{
				chrome.runtime.sendMessage({ msg: "VALIDATE", response: jsonObj.PAYLOAD });
			}

		}
		if (jsonObj.PAYLOAD.OP == 4)
		{
			if (jsonObj.PAYLOAD.KC && ((jsonObj.PAYLOAD.ERR == 54) || (jsonObj.PAYLOAD.ERR == 53)) ) {
				Webroot_Background.KEYCODE = jsonObj.PAYLOAD.KC.toLowerCase();
				Webroot_Background.STATUSID = jsonObj.PAYLOAD.ERR;

			}
			Webroot_Background.Enabled = 0;
		}

		// If message originating from background_script, then return
		if (jsonObj.TABID == 0) return;

		// Send error response to contentScript
		chrome.tabs.sendMessage(jsonObj.TABID, { responseText: jsonObj.PAYLOAD }, function () {
			var err = chrome.runtime.lastError;
		});
	},

	// -----------------------------------------------------------
	// Performs the right operation based on the response recieved.
	// Returns <void>
	// -------------------------------------------------------- //
	analyseSuccessResponse: function (jsonObj)
	{
		Webroot_Background.STATUSID = 0;

		// CONFIG
		if (jsonObj.PAYLOAD.OP == 4)
		{
			// Analyse Response
			var result = Webroot_Server.updateSettings(jsonObj.PAYLOAD, jsonObj.TABID);

			// If message originating from background_script, then return
			if (jsonObj.TABID == 0) return true;
			result.TABID = jsonObj.TABID;

			// Send response to ContentScript
			chrome.tabs.sendMessage(jsonObj.TABID, { responseText: result }, null, function () {
				var err = chrome.runtime.lastError;
			});
			return true;
		}

		// VALIDATE
		else if (jsonObj.PAYLOAD.OP == 7)
		{
			// Update background script members
			Webroot_Background.KEYCODE = jsonObj.PAYLOAD.KC.toLowerCase();
			Webroot_Background.Enabled = 1;

			// Send response to the Settings/Keycode page/flyout
			chrome.runtime.sendMessage({ msg: "VALIDATE", response: jsonObj.PAYLOAD });
			return true;
		}
		else if (jsonObj.PAYLOAD.OP == 10) {
			chrome.runtime.sendMessage({ msg: "IPM", response: jsonObj.PAYLOAD });
			return true;
		}

		// Analyse Response
		jsonObj.PAYLOAD.TABID = jsonObj.TABID;
		if (jsonObj.TABID >= 0x80000000) onDownloadBCAP(jsonObj.TABID - 0x80000000, jsonObj.PAYLOAD);
		else chrome.tabs.sendMessage(jsonObj.TABID, { responseText: jsonObj.PAYLOAD }, null, function () {
			var err = chrome.runtime.lastError;
		});
	},
};