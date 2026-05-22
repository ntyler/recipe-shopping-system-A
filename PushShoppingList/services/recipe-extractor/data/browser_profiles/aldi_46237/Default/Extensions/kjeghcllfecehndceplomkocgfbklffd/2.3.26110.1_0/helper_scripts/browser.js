/****************************************************************************************
  Module:		browser
  Description:	- Contains the definition of the Browser object.
				- Enables us to identify the currently running browser
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		melsaie@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		02/10/2017 (mm/dd/yyyy)
*****************************************************************************************/

// ------------- //
// Browser Object //
// ------------- //
OS_INFO = Object.freeze({ UNKNOWN: "UNKNOWN", WINDOWS: "WINDOWS", MAC_OS: "MAC_OS", CHROME_OS: "CHROME_OS" });

var Webroot_Browser = {

	// Define supported browsers
	CHROME: "CR",
	FIREFOX: "FF",
	EDGE_LEGACY: "EG",
	EDGE_CHROMIUM: "EC",
	SAFARI: "SA",
	current: null,
	currentOS: OS_INFO.UNKNOWN,
	currentOSName: null,
	currentFlag: null,

	// ---------------------------------------- //
	//	 Identify the currently running browser	//
	// ---------------------------------------- //
	identify_browser: function()
	{
		if (this.current) return this.current;
		var userAgent = navigator.userAgent.toLowerCase();

		if(userAgent.indexOf("edge") != -1) {
			chrome = browser;
			this.current = this.EDGE_LEGACY;
			this.currentFlag = 16;
		}
		else if (userAgent.indexOf("edg") != -1) {
			this.current = this.EDGE_CHROMIUM;
			this.currentFlag = 32;
		}
		else if (userAgent.indexOf("chrome") != -1) {
			this.current = this.CHROME;
			this.currentFlag = 4;
		}
		else if (userAgent.indexOf("firefox") != -1) {
			chrome = browser;
			this.current = this.FIREFOX;
			this.currentFlag = 8;
		}
		else if (userAgent.indexOf("safari") != -1) {
			this.current = this.SAFARI;
			this.currentFlag = 64;
		}
		else return "Unknown";

		return this.current;
	},

	browserFlags: function ()
	{
		if (this.current == null) this.identify_browser();
		return this.currentFlag;
	},

	identify_os: function () {

		if (this.currentOS != OS_INFO.UNKNOWN) return this.currentOS;

		if (navigator.appVersion.indexOf("Win") != -1) this.currentOS = OS_INFO.WINDOWS;
		else if (navigator.appVersion.indexOf("Mac") != -1) this.currentOS = OS_INFO.MAC_OS;
		else if (navigator.appVersion.indexOf("CrOS") != -1) this.currentOS = OS_INFO.CHROME_OS;

		return this.currentOS;
	},

	identifiy_osName: function () {

		if (this.currentOSName != null) return this.currentOSName;

		let regex = /\(([^)]+)\)/.exec(navigator.appVersion);
		if (regex != null) this.currentOSName = regex[1];

		return this.currentOSName;
	}
};

Webroot_Browser.identify_browser();

