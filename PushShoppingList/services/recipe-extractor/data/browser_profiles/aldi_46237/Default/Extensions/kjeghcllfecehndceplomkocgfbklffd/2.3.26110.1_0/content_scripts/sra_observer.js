/****************************************************************************************
  Module:		sra_observer.js
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pblaimschein@opentext.com
  Manager:		jmayr@opentext.com
  Created:		02/10/2025 (mm/dd/yyyy)
*****************************************************************************************/

// JavaScript source code
var SraObserver =
{
	sraObserverTimer: null,
	sraObserverRunning: false,

	sraObserverTimerFkt: function () {
		if (chrome.runtime.id !== undefined) {

			//Consider current date as initDate for latency before initiating SRA from observer
			initDateTime = new Date();
			SRA.processSRA(Webroot_Extension.currentUri, true);
		}
		SraObserver.sraObserverTimer = null;
	},
	getDOMPath: function (elem) {
		if (!elem) return "";

		const node = elem.nodeName + (elem.id ? "#" + elem.id : "") + (elem.className ? "." + elem.className : "");
		if (elem == document.body) return node;
		return SraObserver.getDOMPath(elem.parentElement) +"|" + node;
	},
	isNotFiltered: function (mutation) {

		if (!mutation) return false;

		for (var i = 0; i < mutation.length; i++) {
			for (var j = 0; j < mutation[i].addedNodes.length; j++) {
				if (mutation[i].addedNodes[j].className != "WebrootDiv") return true;
			}
		}

		return false;
	},

	startObserver: function () {
		var mutationObserver = new MutationObserver(function (mutation) {
			if (document.readyState == "complete" && SraObserver.isNotFiltered(mutation)) {
				if (SraObserver.sraObserverTimer != null) {
					clearTimeout(SraObserver.sraObserverTimer);
				}
				SraObserver.sraObserverTimer = setTimeout(SraObserver.sraObserverTimerFkt, 500);
			}
		});
		mutationObserver.observe(document.body, { childList: true, attributes: false, subtree: true, characterData: false });
		SraObserver.sraObserverRunning = true;
	}
}