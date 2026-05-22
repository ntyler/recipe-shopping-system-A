/*******************************************************************************************
  Module:		SRA
  Description:	- moved from main.js to sra.js
				- handle search result annotations
/*******************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/*******************************************************************************************
  Creator:		pkulkarni@opentext.com
  Manager:		pblaimschein@opentext.com
  Created:		02/10/2025 (mm/dd/yyyy)
********************************************************************************************/

//Supported search engines/IDs
const SearchEngines = Object.freeze({ "Google": "1", "Bing": "2", "Yahoo": "3", "Gemini": "4", "ChatGPT": "5" });

// JavaScript source code
var SRA =
{
	// Initialize Rules
	SRA_DATE: '',				// Init annotaionFile date
	SRA_DATE_DEFAULT: "Wed, 08 Apr 2026 09:15:16 GMT",
	//TODO back in single line
	SRA_CONFIG_DEFAULT: [
		{ "selector": [{ "sel": "div.yuRUbf a:not([class]),div.yuRUbf a.zReHs", "Filter": ["|div.WebrootDiv"], "pos": "h3.LC20lb", "type": "SRA" }], "urlregex": "", "encode": 0, "spregex": ".*www\\.google\\..*", "SPID": 1 },
		{ "selector": [{ "sel": "li.b_algo h2 a:not([class])", "Filter": ["|div.WebrootDiv"], "pos": "", "type": "SRA" }], "urlregex": "", "encode": 0, "spregex": ".*bing\\.com\\/search.*", "SPID": 2 },
		{ "selector": [{ "sel": "div.compTitle a", "Filter": ["|div.WebrootDiv"], "pos": "|h3.title > span.d-b,:scope > span.d-ib.fz-14", "type": "SRA" }], "urlregex": "/(RU=)(.*?)/(R)", "encode": 1, "spregex": ".*search\\.yahoo\\.com\\.*", "SPID": 3 },
		{ "selector": [{ "sel": "div.sw-Card__title a", "Filter": ["|div.WebrootDiv"], "pos": "h3.sw-Card__titleMain", "type": "SRA" }], "urlregex": "", "encode": 0, "spregex": ".*search\\.yahoo\\.co\\.jp", "SPID": 3 },
		{ "selector":
				[{ "sel": "model-response a", "Filter": ["|div.WebrootDiv"], "pos": "", "type": "CBA" },
				{ "sel": "inline-source-card a", "Filter": ["|div.WebrootDiv"], "pos": "div.title", "type": "CBA" },
				{ "sel": "div.source-card-content a", "Filter": ["|div.WebrootDiv"], "pos": ".source-card-title", "type": "CBA" },
				{ "sel": "browse-web-chip a", "Filter": ["|div.WebrootDiv"], "pos": "", "type": "CBA" },
				{ "sel": "browse-web-item a", "Filter": ["|div.WebrootDiv"], "pos": ".title-container", "type": "CBA" }],
			 "urlregex": "", "encode": 0, "spregex": ".gemini\\.google\\..*", "SPID": 4,
		}
	],

	SRA_CONFIG: '',

	// Create Array of MyObjects
	links: new Array(),		// <A> TAGS
	
	// Store current domain index for use in processSRAResponse
	currentDomainIdx: -1,

	// --------------------------------------------------- //
	// Checks for search engines and annotates the results //
	// Returns True --> If search engine found             //
	// Returns False --> Otherwise                         //
	// --------------------------------------------------- //
	processSRA: function (uri, fromObserver) {

		if (Webroot_Extension.isIframe) return false;

		// Check if domain on list of supported search engines
		var domainIndex = SRA.supportedSearchEngine(uri.urlWithoutQuery);

		if (Webroot_Extension.searchAnnotation != 1) {
			if (Webroot_Extension.mode == 1) Webroot_Extension.updateConfig();
			return (domainIndex != -1);
		}

		// Perform Search Result Annotation Processing if required
		if (domainIndex != -1) {
			if (!fromObserver) {
				// Update BrowserAction if SearchEngine
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "SEARCH_ENGINE" }, function (response) { });
			}

			// Get Body content	
			var body = document.body;

			// SRA
			// create SRA Popup template
			const sraPopup = document.getElementById("WebrootDivSpan");
			if (!sraPopup) {
				const sraPopupTemplate = SRA.createSRAPopup();
				body.insertBefore(sraPopupTemplate, body.firstChild);
			}

			SRA.processSearchPage(body, domainIndex);

			return true;
		}

		return false;
	},

	// -------------------------------------- //
	//		 Check if current domain	  	  //
	//       is a supported search engine	  //
	// -------------------------------------- //	
	supportedSearchEngine: function (myDomain) {
		// Check if new Config file is loaded
		if (!SRA.SRA_CONFIG) return -1;

		// Check if domain on list of supported search engines
		for (var uriCount = 0; uriCount < SRA.SRA_CONFIG.length; uriCount++) {

			// Extract RegEx from Config File
			const newRegEx = new RegExp(SRA.SRA_CONFIG[uriCount].spregex, 'i');

			// Check URL against RegEx
			const result = myDomain.match(newRegEx);

			//if ( myDomain == SRA_CONFIG[uriCount].domain )
			if (result != null)
				return uriCount;
		}
		return -1;
	},

	// ---------------------------------------- //
	// Extract Search results and annotate them //
	// ---------------------------------------- //
	processSearchPage: function (body, domainIdx) {

		if (!SraObserver.sraObserverRunning) {
			SraObserver.startObserver();
		}

		// Create Array of MyObjects (GLOBAL)
		if (!SRA.links) SRA.links = new Array();		// <A> TAGS

		if (SRA.selectAndFilterSRA(body, domainIdx)) {
			SRA.sendSRARequests(domainIdx);
		}
	},
	// --------------------------------------------- //
	// select SearchResults to be annotated          //
	// --------------------------------------------- //
	selectAndFilterSRA: function (body, domainIdx) {

		const selectors = SRA.SRA_CONFIG[domainIdx].selector;
		for (var j = 0; j < selectors.length; j++) {

			try {
				if (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser()) {
					if (SRA.SRA_CONFIG[domainIdx].selector[j].type != "SRA") continue;
				}

				const selector = SRA.SRA_CONFIG[domainIdx].selector[j];
				const elementTags = body.querySelectorAll(selector.sel);
				if (!elementTags || (elementTags.length == 0)) continue;

				for (var i = 0; i < elementTags.length; i++) {
					SRA.collectSRALinks(elementTags[i], selector, SRA.SRA_CONFIG[domainIdx].SPID);
				}
			}
			catch (err) {
				console.log("Could not process selector", err);
				continue;
			}
		}
		if (SRA.links.length == 0) return false;

		return true;
	},
	// --------------------------------------------- //
	// forward SRA requests to background			 //
	// --------------------------------------------- //
	sendSRARequests: function (domainIdx) {

		// Store domainIdx for use in processSRAResponse
		SRA.currentDomainIdx = domainIdx;

		// Process Bulk Request
		var linksArray = "";
		const spid = SRA.SRA_CONFIG[domainIdx].SPID;
		if (spid == SearchEngines.Bing) linksArray = Webroot_Helper.create_Url_Array_FromBing(SRA.links);
		else linksArray = Webroot_Helper.create_URL_Array(SRA.links, domainIdx);
		if (!linksArray || (linksArray.length == 0)) return false;

		chrome.runtime.sendMessage({ msg: "SRA", links: linksArray }, function (response) {
			// Check for errors
			const error = response.responseText;
			if (error != 0) {
				// Log error
				console.info("WTS_Extension [PROCESSSEARCHPAGE]: " + JSON.stringify(error));

				// Update BrowserAction (Case: WSA UNREACHABLE)
				chrome.runtime.sendMessage({ msg: "update_browseraction_icon", data: "WSA_UNREACHABLE" }, function (response) { });
				return false;
			}
		});

		return true;

	},
	// --------------------------------------------- //
	//         check filters and collect SRA		 //
	// --------------------------------------------- //
	collectSRALinks: function (elem, selector, spid) {
		if (!elem) return;
		if (!selector) return;

		try {
			if (SRA.isSRAFiltered(elem, selector.Filter)) return;

			if (spid == SearchEngines.Bing) {
				if (elem.localName != "a") return;

				var uri = new Uri(elem.href);
				if (!uri || !uri.urlWithoutQuery) return;
				if (!uri.isHostValid()) return;

				// extract from bing.com/cf
				if (uri.host == "www.bing.com") {
					var queryDict = uri.query();
					var targetUrl = queryDict["u"];
					if (!targetUrl) return;

					targetUrl = atob(targetUrl.substring(2).replaceAll("-", "+").replaceAll("_", "/"));
					uri = new Uri(targetUrl);
					if (!uri || !uri.urlWithoutQuery) return;
					if (!uri.isHostValid()) return;
				}
				SRA.links.push(new SRA.myobject(elem, SearchEngines.Bing, uri, selector));
			}
			else { // all other than Bing
				SRA.links.push(new SRA.myobject(elem, spid, null, selector));
			}
		}
		catch (err) {
			console.log("Could not process SRA link", err);
		}

	},
	// ---------------------------- //
	// 	  UPDATE Search Results  	//
	// ---------------------------- //
	processSRAResponse: function (msg) {
		if (!msg || !msg.DATA || !msg.DATA.length) return;
		if (Webroot_Extension.isIframe) return;

		var SRA_Counts = { "Red": 0, "Green": 0, "Yellow": 0 };
		var CBA_Counts = { "Red": 0, "Green": 0, "Yellow": 0 };

		// Get URL'S Count
		const urlCount = msg.DATA.length;
		
		// Traverse Entrie URL's
		for (var i = 0; i < urlCount; i++) {
			try {
				// Get Reference
				const data = msg.DATA[i];
				const myRef = data.REF;
				if ((myRef > SRA.links.length) || (!SRA.links[myRef - 1].myElement)) continue;

				// Get results
				const iconObj = SRA.addSRAIcon(data);
				iconObj.iconNode.myData = data;

				const link = SRA.links[myRef - 1].myElement;
				const pos = SRA.links[myRef - 1].selector.pos;

				// Increment color counts for the appropriate annotation type
				if (SRA.links[myRef - 1].selector.type === "CBA") {
					if (iconObj.color == "Red") CBA_Counts["Red"]++;
					else if (iconObj.color == "Green") CBA_Counts["Green"]++;
					else if (iconObj.color == "Yellow") CBA_Counts["Yellow"]++;
				} else if (SRA.links[myRef - 1].selector.type === "SRA") {
					if (iconObj.color == "Red") SRA_Counts["Red"]++;
					else if (iconObj.color == "Green") SRA_Counts["Green"]++;
					else if (iconObj.color == "Yellow") SRA_Counts["Yellow"]++;
				}

				// Add HTML element to Current Node
				const sraParent = SRA.getSRAPosition(link, pos);
				if (sraParent) {
                    if (sraParent.querySelector("div.WebrootDiv")) continue; // avoid duplicate items

					sraParent.insertBefore(iconObj.iconNode, sraParent.firstChild);

					const hoverParent = SRA.links[myRef - 1].selector.HoverParent;
					if (hoverParent == "1") {
						link.addEventListener('mouseenter', SRA.hoverSRA);
						link.addEventListener('mouseleave', SRA.hoverSRAout);
					}
					else {
						iconObj.iconNode.addEventListener('mouseenter', SRA.hoverSRA);
						iconObj.iconNode.addEventListener('mouseleave', SRA.hoverSRAout);
					}
				}
			}
			catch (err) {
				console.log("error in processing SRA response", err);
			}
		}
		SRA.links.length = 0;

        //prepare data for SRACBAcounter
		const hasSRACount = (SRA_Counts.Green + SRA_Counts.Yellow + SRA_Counts.Red) > 0;
		const hasCBACount = (CBA_Counts.Green + CBA_Counts.Yellow + CBA_Counts.Red) > 0;

		if (hasSRACount || hasCBACount) {
			var SRACBA_ObjectSum = [];
			if (hasSRACount) SRACBA_ObjectSum.push({ "Type": "SRA", "Red": SRA_Counts.Red, "Green": SRA_Counts.Green, "Yellow": SRA_Counts.Yellow });
			if (hasCBACount) SRACBA_ObjectSum.push({ "Type": "CBA", "Red": CBA_Counts.Red, "Green": CBA_Counts.Green, "Yellow": CBA_Counts.Yellow });

			var origin = "";
			if (Webroot_Extension.currentUri.host.toLowerCase().includes("gemini.google")) origin = "Gemini";
			else if (Webroot_Extension.currentUri.host.toLowerCase().includes("google")) origin = "Google";
			else if (Webroot_Extension.currentUri.host.toLowerCase().includes("chatgpt")) origin = "ChatGPT";
			else if (Webroot_Extension.currentUri.host.toLowerCase().includes("bing")) origin = "Bing";
			else if (Webroot_Extension.currentUri.host.toLowerCase().includes("yahoo")) origin = "Yahoo";

			chrome.runtime.sendMessage({ msg: "SRACBAcounter", origin: origin, time: new Date() - initDateTime, SRACBA: SRACBA_ObjectSum }, function (response) { });
		}

		if (!SraObserver.sraObserverRunning && Webroot_Extension.currentUri?.urlWithoutQuery.toLowerCase().indexOf(".google.") >= 0) {
			SraObserver.startObserver();
		}
	},
	isSRAFiltered: function (linkNode, filterArray) {
		if (!linkNode) return true;
		if (!filterArray) return false;

		for (var i = 0; i < filterArray.length; i++) {
			if (!filterArray[i]) continue;
			const filterItems = filterArray[i].split("|", 2);
			if (!filterItems) continue;

			var pre = "";
			var post = "";
			var sraFilter = linkNode;
			if (filterItems.length == 2) {
				pre = filterItems[0];
				post = filterItems[1];
			}
			else post = filterItems[0];

			if (sraFilter && pre) sraFilter = sraFilter.closest(pre);
			if (sraFilter && post) sraFilter = sraFilter.querySelector(post);

			if (sraFilter && sraFilter != linkNode) return true;
		}
		return false;
	},
	getSRAPosition: function (linkNode, pos) {
		var pre = "";
		var post = "";
		var sraParent = linkNode;

		if (!sraParent) return null;
		if (!pos) return sraParent;
		const posItems = pos.split("|",2);
		if (!posItems) return sraParent;

		if (posItems.length == 2) {
			pre = posItems[0];
			post = posItems[1];
		}
		else post = posItems[0];

		if (sraParent && pre) sraParent = sraParent.closest(pre);
		if (sraParent && post) sraParent = sraParent.querySelector(post);
        if (!sraParent) sraParent = linkNode;

		return sraParent;
	},

	// --------------------------------------- //
	// Add Reputation Icon based on Reputation //
	// Reputation Scores Received from Server  //
	// --------------------------------------- //
	addSRAIcon: function (sraResponse) {

		var SraIconObj = { iconNode:{}, color:""};

		// Handle <RED> Reputation
		if (sraResponse.BLK == 1 || sraResponse.BCRI < 21) {
			SraIconObj.iconNode = SRA.createSRAIcon("red");
            SraIconObj.color = "Red";
		}
		// Handle <GREEN> Reputation
		else if (sraResponse.BCRI >= 61) {
			SraIconObj.iconNode = SRA.createSRAIcon("green");
            SraIconObj.color = "Green";
		}
		// Handle <YELLOW> Reputation
		else if (sraResponse.BCRI >= 21 && sraResponse.BCRI <= 60) {
			SraIconObj.iconNode = SRA.createSRAIcon("yellow");
            SraIconObj.color = "Yellow";
		}
		else {
			SraIconObj.iconNode = SRA.createSRAIcon("yellow");
			SraIconObj.color = "Yellow";

		}

		return SraIconObj;
	},
	// --------------------------------------- //
	// create WebrootDiv element               //
	// --------------------------------------- //
	createSRAIcon: function (icon) {

		// SRA Icon
		var img = document.createElement('img');
		if (icon == 'green')
			img.src = chrome.runtime.getURL("images/sra/GoSm.svg");
		else if (icon == 'yellow')
			img.src = chrome.runtime.getURL("images/sra/YieldSm.svg");
		else if (icon == 'red')
			img.src = chrome.runtime.getURL("images/sra/StopSm.svg");
		img.setAttribute("alt", "Webroot Classification: " + icon);

		// Create encapsulating <div> element for SRA icon
		var newNode = document.createElement('div');
		newNode.className = "WebrootDiv";
		newNode.appendChild(img);

		return newNode;
	},
	createSRAPopup: function () {
		var span = document.createElement('span');
		span.id = "WebrootDivSpan";
		span.className = "WebrootSRAPopup green";

		var pre1 = document.createElement('pre');
		pre1.className = "webrootlogotitle";
		var img1 = document.createElement('img');
		img1.height = "12";
		if (isBusiness == 1) {
			img1.src = chrome.runtime.getURL("images/sra/WebrootSmallOT.svg");
			img1.style.verticalAlign = "middle";

		}
		else img1.src = chrome.runtime.getURL("images/sra/WebrootSmall.svg")
		img1.setAttribute("alt", "Webroot");
		pre1.appendChild(img1);
		pre1.append(" - " + "Trustworthy");

		var pre2 = document.createElement('pre');
		pre2.className = "webrootlogobody";
		pre2.append("It's safe to go ahead.");
		span.appendChild(pre1);
		span.appendChild(pre2);

		return span;
	},
	updateSRAPopup: function (sraElem, sraPopupElem) {

		const data = sraElem.myData;
		if (!data) return false;

		// Handle <RED> Reputation
		if (data.BLK == 1 || data.BCRI < 21) {
			switch (data.BLKREASON) {
				case 200:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_PHISHING");
					break;
				case 49:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_KEYLOGGER");
					break;
				case 56:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_MALWARE");
					break;
				case 57:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_PHISHING");
					break;
				case 59:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_SPYWARE");
					break;
				case 67:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_BOTNET");
					break;
				case 71:
					toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_SPAM");
					break;
				default:
					// Check for malicious categories
					var blockedCat = "-1";

					for (var i = 0; i < data["CAT.CONF"].length; i++) {
						var splitResult1 = data["CAT.CONF"][i].split('.')[0];

						if (splitResult1 == "49" || splitResult1 == "56" || splitResult1 == "57" || splitResult1 == "59" || splitResult1 == "67" || splitResult1 == "71") {
							blockedCat = splitResult1;
							break;
						}
					}

					switch (blockedCat) {
						case "49":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_KEYLOGGER");
							break;
						case "56":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_MALWARE");
							break;
						case "57":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_PHISHING");
							break;
						case "59":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_SPYWARE");
							break;
						case "67":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_BOTNET");
							break;
						case "71":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_SPAM");
							break;
						case "-1":
							toolTipTitle = chrome.i18n.getMessage("TITLE_BCAP_RISK");
							break;
					}
			}

			return SRA.setSRAPopupData("red", toolTipTitle, chrome.i18n.getMessage("TEXT_RISK"));
		}
		// Handle <GREEN> Reputation
		else if (data.BCRI >= 61) {
			return SRA.setSRAPopupData("green", chrome.i18n.getMessage("TITLE_BCAP_TRUSTWORTHY"), chrome.i18n.getMessage("TEXT_TRUSTWORTHY"));
		}
		// Handle <YELLOW> Reputation
		else if (data.BCRI >= 21 && data.BCRI <= 60) {
			return SRA.setSRAPopupData("yellow", chrome.i18n.getMessage("TITLE_BCAP_SUSPICIOUS"), chrome.i18n.getMessage("TEXT_SUSPICIOUS"));
		}
		else {
			return SRA.setSRAPopupData("yellow", chrome.i18n.getMessage("TITLE_BCAP_SUSPICIOUS"), chrome.i18n.getMessage("TEXT_SUSPICIOUS"));
		}
		return false;
	},
	setSRAPopupData: function (icon, txt, txt_detail) {
		const sraPopup = document.getElementById("WebrootDivSpan");
		if (!sraPopup) return false;

		// sraPopup classList
		sraPopup.classList.remove("green");
		sraPopup.classList.remove("yellow");
		sraPopup.classList.remove("red");
		if (icon == 'green') sraPopup.classList.add("green");
		else if (icon == 'yellow') sraPopup.classList.add("yellow");
		else if (icon == 'red') sraPopup.classList.add("red");

		// sraPopup headline
		sraPopup.firstChild.childNodes[1].textContent = " - " + txt;
		// sraPopup details
		sraPopup.children[1].textContent = txt_detail;

		return true;
	},
	// ---------------------------------------- //
	// Object carrying reference to DOM  		//
	// element to be modified when BrightCloud  //
	// API replies								//
	// ---------------------------------------- //
	myobject: function (o, spid, uri, selector) {
		this.SPID = spid;
		this.myElement = o;
		this.uri = uri;
		this.selector = selector;
	},
	hoverSRA: function (event) {
		//console.log("hoverSRA", event.srcElement.className, event); //TODO remove
		if (event.type == "mouseenter") {
			if (event.srcElement.className == "WebrootDiv") {

				if (SRA.updateSRAPopup(event.srcElement)) {
					let rect = event.srcElement.getBoundingClientRect();
                    if (rect && rect.height > 50 && event.srcElement.children && event.srcElement.children.length > 0) rect = event.srcElement.children[0].getBoundingClientRect(); // adjust position for frames (Gemini CBA) 
					const sraPopup = document.getElementById("WebrootDivSpan");
					sraPopup.style.top = (window.scrollY + rect.bottom) + "px";
					sraPopup.style.left = (window.scrollX + rect.right) + "px";
					sraPopup.style.visibility = "visible";
				}
			}
			// workaround for AI mode side panel
			else if (event.srcElement.className == "NDNGvf" && event.srcElement.nodeName == "A") {
				const divElem = event.srcElement.parentElement.querySelector("div.WebrootDiv");
				const rect = divElem.getBoundingClientRect();
				const divElemScreenRect = new DOMRect()
				if (divElem && SRA.updateSRAPopup(divElem)) {
					const sraPopup = document.getElementById("WebrootDivSpan");
					const rect = divElem.getBoundingClientRect();
					sraPopup.style.top = (window.scrollY + rect.bottom) + "px";
					sraPopup.style.left = (window.scrollX + rect.right) + "px";
					sraPopup.style.visibility = "visible";
				}
			}
		}
	},
	hoverSRAout: function (event) {

		if (event.type == "mouseleave") {
			if (event.srcElement.className == "WebrootDiv") {
				const sraPopup = document.getElementById("WebrootDivSpan");
				if (!sraPopup) return;

				if (sraPopup.style.visibility == "visible") {
					sraPopup.style.visibility = "hidden";
					sraPopup.style.top = "0";
					sraPopup.style.left = "0";
				}
			}
			// workaround for AI mode side panel
			else if (event.srcElement.className == "NDNGvf" && event.srcElement.nodeName == "A") {
				const sraPopup = document.getElementById("WebrootDivSpan");
				if (!sraPopup) return;

				if (sraPopup.style.visibility == "visible") {
					sraPopup.style.visibility = "hidden";
					sraPopup.style.top = "0";
					sraPopup.style.left = "0";
				}
			}
		}
	}
}