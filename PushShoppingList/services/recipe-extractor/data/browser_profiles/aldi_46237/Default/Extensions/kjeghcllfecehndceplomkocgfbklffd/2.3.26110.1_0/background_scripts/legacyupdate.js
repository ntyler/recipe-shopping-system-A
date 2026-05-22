/****************************************************************************************
  Module:		LegacyUpdate
  Description:	script updating from old WTS versions
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pblaimschein@webroot.com
  Manager:		jmayr@webroot.com
  Created:		11/02/2022 (mm/dd/yyyy)
*****************************************************************************************/

// Mapping localstorage to storage.local
// old -> new 
// PrivacyAccepted -> PrivacyAccepted		e.g. 1
// IPMs -> IPMs								e.g. 1667493499|
// instDate -> InstallDate					e.g. 1667493499 or 2022-10-02 10:00:00 -> 1667493499
// MIDs -> MIDs								e.g. "85E236E8BB2D0228F61E5E14885BDAEB13A887E5|A5FD619FEEFE6DDEBCF4F6A8CD2155E3D81AD71A|A5FD619FEEFE6DDEBCF4F6A8CD2155E3D81AD71A"
// rules -> ConfigRules.CONFIG				e.g. []
// rulesDate -> ConfigRules.DATE			e.g. "Fri, 02 Sep 2022 09:33:24 GMT"
// chrToken -> Auth.TOKEN					e.g. 03Tz43d1jQWJUdaDttUtJ7tO3vLpWRZesHUSrJVfqGzgV... -> { "KCEXPIRYDATE": "2024-06-21 06:00:00Z", "KCISBUSINESS": 0, "TOKENEXPIRE": 1654865992, "TOKEN": "03Tz43d1jQWJUdaDttUtJ7tO3vLpWRZesHUSrJVfqGzgVGX9SBu8J9+BQbTaYX/TDkSsFPVl4HlmOej7II7v3t/EoD7WnNXvU4Pn/6aCN6tDJkMyBfEIm38g+CYzlqxYbzdjBR8vl2OglBzJQmbkYKVFRyVAEc0yMehXa8yBNUCkMEZdcJU0EBWYuUMv4SLBLS7jen/zLR0hw1jKFS749Yzw==" }
// chrTokenExp -> Auth.TOKENEXPIRE			e.g. 1654865992 -> { "KCEXPIRYDATE": "2024-06-21 06:00:00Z", "KCISBUSINESS": 0, "TOKENEXPIRE": 1654865992, "TOKEN": "03Tz43d1jQWJUdaDttUtJ7tO3vLpWRZesHUSrJVfqGzgVGX9SBu8J9+BQbTaYX/TDkSsFPVl4HlmOej7II7v3t/EoD7WnNXvU4Pn/6aCN6tDJkMyBfEIm38g+CYzlqxYbzdjBR8vl2OglBzJQmbkYKVFRyVAEc0yMehXa8yBNUCkMEZdcJU0EBWYuUMv4SLBLS7jen/zLR0hw1jKFS749Yzw==" }
// chrBusinessKC -> Auth.KCISBUSINESS		e.g. 0 -> { "KCEXPIRYDATE": "2024-06-21 06:00:00Z", "KCISBUSINESS": 0, "TOKENEXPIRE": 1654865992, "TOKEN": "03Tz43d1jQWJUdaDttUtJ7tO3vLpWRZesHUSrJVfqGzgVGX9SBu8J9+BQbTaYX/TDkSsFPVl4HlmOej7II7v3t/EoD7WnNXvU4Pn/6aCN6tDJkMyBfEIm38g+CYzlqxYbzdjBR8vl2OglBzJQmbkYKVFRyVAEc0yMehXa8yBNUCkMEZdcJU0EBWYuUMv4SLBLS7jen/zLR0hw1jKFS749Yzw==" }
// chrKCExpDate -> Auth.KCEXPIRYDATE		e.g. 2024-06-21 06:00:00Z -> { "KCEXPIRYDATE": "2024-06-21 06:00:00Z", "KCISBUSINESS": 0, "TOKENEXPIRE": 1654865992, "TOKEN": "03Tz43d1jQWJUdaDttUtJ7tO3vLpWRZesHUSrJVfqGzgVGX9SBu8J9+BQbTaYX/TDkSsFPVl4HlmOej7II7v3t/EoD7WnNXvU4Pn/6aCN6tDJkMyBfEIm38g+CYzlqxYbzdjBR8vl2OglBzJQmbkYKVFRyVAEc0yMehXa8yBNUCkMEZdcJU0EBWYuUMv4SLBLS7jen/zLR0hw1jKFS749Yzw==" }
// whListServer -> whList					e.g. test.at|
// rtapcounter -> rtapcounter				e.g. {} 
// rulesLastAttempt -> rulesLastAttempt		e.g. 1667494311 or 2022-10-02 10:00:00 -> 1667494311
// WSACheckAttempt -> WSACheckAttempt		e.g. 1667494311 or 2022-10-02 10:00:00 -> 1667494311
// chrKC -> KC								e.g. 1EFEJOEJ5597CEF34C45
// Mode -> Mode								e.g. 1

async function moveStorageAfterUpdate() {

	var completed = {
		counter: 1,
		init: function () {
			var parent = this;
			parent.promise = new Promise((resolve, reject) => {
				parent.resolve = resolve;
			});
        },
		increase: function () {
			this.counter++;
		},
		decrease: function () {
			this.counter--;
			if (this.counter <= 0) this.resolve(0);
		}
	};
	completed.init();

	if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) {

		var sPrivacyAccepted = localStorage.getItem("PrivacyAccepted");
		if (sPrivacyAccepted != null) {
			completed.increase();
			chrome.storage.local.set({ "PrivacyAccepted": parseInt(sPrivacyAccepted) })
				.then(() => localStorage.removeItem("PrivacyAccepted"))
				.catch((error) => console.log("WTS: Failed to convert 'PrivacyAccepted' (", error, ")"))
				.finally(() => completed.decrease());
		}
	}

	// **************************** IPMs
	const IPMs = localStorage.getItem("IPMs");
	if (IPMs != null) {
		const IPMHelp = IPMs.split('|');
		if (IPMHelp.length > 1) {
			completed.increase();
			chrome.storage.local.set({ "IPMs": IPMHelp[1] })
				.then(() => localStorage.removeItem("IPMs"))
				.catch((error) => console.log("WTS: Failed to convert 'IPMs' (", error, ")"))
				.finally(() => completed.decrease());
			
		}
	}

	// *************************** InstallDate
	var InstallDate = localStorage.getItem("instDate");
	if (InstallDate != null) {

		var iInstDate = 0;
		if (InstallDate.includes("-")) {
			if (!InstallDate.endsWith("Z")) InstallDate = InstallDate + "Z";
			iInstDate = new Date(InstallDate).getTime() / 1000;
		}
		else iInstDate = parseInt(InstallDate);

		completed.increase();
		chrome.storage.local.set({ "InstallDate": iInstDate })
			.then(() => localStorage.removeItem("instDate"))
			.catch((error) => console.log("WTS: Failed to convert 'InstallDate' (", error, ")"))
			.finally(() => completed.decrease());
		
	}

	// **************************** MIDs
	var MIDs = localStorage.getItem("MIDs");
	if (MIDs != null) {
		completed.increase();
		chrome.storage.local.set({ "MIDs": MIDs })
			.then(() => localStorage.removeItem("MIDs"))
			.catch((error) => console.log("WTS: Failed to convert 'MIDs' (", error, ")"))
			.finally(() => completed.decrease())
	}

	if (!MIDs) {
		var mid1 = localStorage.getItem("MID1");
		var mid2 = localStorage.getItem("MID2");

		if (mid1 && mid2) {
			MIDs = mid1 + '|' + mid2 + '|' + mid2;

			completed.increase();
			chrome.storage.local.set({ "MIDs": MIDs })
				.then(() => {
					localStorage.removeItem("MID1");
					localStorage.removeItem("MID2");
				})
				.catch((error) => console.log("WTS: Failed to convert 'MIDs' (", error, ")"))
				.finally(() => completed.decrease());
		}
	}

	// **************************** ConfigRule Date
	var rules = localStorage.getItem("rules");
	var rulesDate = localStorage.getItem("rulesDate");
	if (rules && rulesDate) {
		var jsnRules;
		try {
			var jsnRules = JSON.parse(rules);
		}
		catch (err) { };

		if (jsnRules) {
			jsnRules["DATE"] = rulesDate;
			completed.increase();
			chrome.storage.local.set({ "ConfigRules": jsnRules })
				.then(() => {
					localStorage.removeItem("rules");
					localStorage.removeItem("rulesDate");
				})
				.catch((error) => console.log("WTS: Error writing converted ConfigRules to storage - error:", error))
				.finally(() => completed.decrease());
		}
	}

	// **************************** AUTH
	var token = localStorage.getItem("chrToken");
	var tokenExp = localStorage.getItem("chrTokenExp");
	var isBusiness = localStorage.getItem("chrBusinessKC");
	var KCexp = localStorage.getItem("chrKCExpDate");
	if ((KCexp != null) && (isBusiness != null)) {
		if (!token) token = "";
		if (!tokenExp) tokenExp = 0;

		jsnAuth = {
			"TOKEN": token,
			"TOKENEXPIRE": parseInt(tokenExp),
			"KCEXPIRYDATE": KCexp,
			"KCISBUSINESS": parseInt(isBusiness)
		};
		completed.increase();
		chrome.storage.local.set({ "Auth": jsnAuth })
			.then(() => {
				localStorage.removeItem("chrToken");
				localStorage.removeItem("chrTokenExp");
				localStorage.removeItem("chrBusinessKC");
				localStorage.removeItem("chrKCExpDate");
			})
			.catch((error) => console.log("WTS: Failed to convert 'Auth' (", error, ")"))
			.finally(() => completed.decrease());
	}

	// **************************** White List
	const whList = localStorage.getItem("whListServer");
	if (whList != null) {
		completed.increase();
		chrome.storage.local.set({ "whList": whList })
			.then(() => localStorage.removeItem("whListServer"))
			.catch((error) => console.log("WTS: Failed to convert 'whListServer' (", error, ")"))
			.finally(() => completed.decrease());
	}

	// **************************** rtap counter
	const ctRRTAP = localStorage.getItem("rtapcounter");
	if (ctRRTAP != null) {
		completed.increase();
		chrome.storage.local.set({ "rtapcounter": JSON.parse(ctRRTAP) })
			.then(() => localStorage.removeItem("rtapcounter"))
			.catch((error) => console.log("WTS: Failed to convert 'rtapcounter' (", error, ")"))
			.finally(() => completed.decrease());
	}

	// **************************** rulesLastAttempt
	var lastRulesAttempt = localStorage.getItem("rulesLastAttempt");
	if (lastRulesAttempt != null) {

		var ilastRulesAttempt = 0;
		if (lastRulesAttempt.includes("-")) {
			if (!lastRulesAttempt.endsWith("Z")) lastRulesAttempt = lastRulesAttempt + "Z";
			ilastRulesAttempt = new Date(lastRulesAttempt).getTime() / 1000;
		}
		else ilastRulesAttempt = parseInt(lastRulesAttempt);

		completed.increase();
		chrome.storage.local.set({ "rulesLastAttempt": ilastRulesAttempt })
			.then(() => localStorage.removeItem("rulesLastAttempt"))
			.catch((error) => console.log("WTS: Failed to convert 'rulesLastAttempt' (", error, ")"))
			.finally(() => completed.decrease());
	}

	// **************************** WSACheckAttempt
	var WSACheckAttempt = localStorage.getItem("WSACheckAttempt");
	if (WSACheckAttempt != null) {

		var iWSACheckAttempt = 0;
		if (WSACheckAttempt.includes("-")) {
			if (!WSACheckAttempt.endsWith("Z")) WSACheckAttempt = WSACheckAttempt + "Z";
			iWSACheckAttempt = new Date(WSACheckAttempt).getTime() / 1000;
		}
		else iWSACheckAttempt = parseInt(WSACheckAttempt);

		completed.increase();
		chrome.storage.local.set({ "WSACheckAttempt": iWSACheckAttempt })
			.then(() => localStorage.removeItem("WSACheckAttempt"))
			.catch((error) => console.log("WTS: Failed to convert 'WSACheckAttempt' (", error, ")"))
			.finally(() => completed.decrease())
	}

	// **************************** KC
	const KC = localStorage.getItem("chrKC");
	if (KC != null) {
		completed.increase();
		chrome.storage.local.set({ "KC": KC })
			.then(() => localStorage.removeItem("chrKC"))
			.catch((error) => console.log("WTS: Failed to convert 'KC' (", error, ")"))
			.finally(() => completed.decrease())
	}

	// **************************** Mode
	const sMode = localStorage.getItem("Mode");
	if (sMode != null) {
		completed.increase();
		chrome.storage.local.set({ "Mode": parseInt(sMode) })
			.then(() => localStorage.removeItem("Mode"))
			.catch((error) => console.log("WTS: Failed to convert 'Mode' (", error, ")"))
			.finally(() => completed.decrease())
	}

	// ************** wait for all conversions to complete
	completed.decrease(); // decrease initial value
	if (completed.counter > 0) console.log("Updating localstorage to storage.local.");

	completed.promise.then(() => {
		window.close();
    })
}


moveStorageAfterUpdate();

