/****************************************************************************************
  Module:		rtap_observer.js
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pblaimschein@opentext.com
  Manager:		jmayr@opentext.com
  Created:		02/10/2025 (mm/dd/yyyy)
*****************************************************************************************/

// JavaScript source code
var RtapObserver =
{
	RTAPobserverTimer: null,
	IsContentObservingSet: false,

	RTAPobserverTimerFkt: function () {
		if (Webroot_Extension.currentChksum !== 0) {

			var chksum = Webroot_Extension.getContentHash(document.body.outerHTML);
			if (chksum !== Webroot_Extension.currentChksum) {
				Webroot_Extension.processRTAP(document.URL, true);
				Webroot_Extension.currentChksum = chksum;
			}
		}
	},

	startObserver: function () {
		var mutationObserver = new MutationObserver(function (mutation) {
			if (Webroot_Extension.isRTAPpending) {
				clearTimeout(RtapObserver.RTAPobserverTimer);
				RtapObserver.RTAPobserverTimer = setTimeout(RtapObserver.RTAPobserverTimerFkt, 2000);
				return;
			}

			if (document.readyState == "complete") {
				for (var x = 0; x < mutation.length; x++) {
					for (var y = 0; y < mutation[x].addedNodes.length; y++) {
						if (mutation[x].addedNodes[y].querySelectorAll) {
							var item = mutation[x].addedNodes[y].querySelectorAll('input[type="password"],textarea,input[type="text"]');
							if (item.length) {
								if (Webroot_Extension.logLevel >= 3) {
									for (var z = 0; z < item.length; z++) {
										Webroot_Extension.Log("observed change:", item[z].baseURI + ': ' + item[z].type + '#' + item[z].id + '.' + item[z].className);
									}
								}
								if (RtapObserver.RTAPobserverTimer == null) {
									RtapObserver.RTAPobserverTimer = setTimeout(RtapObserver.RTAPobserverTimerFkt, 2000);
								}
								else {
									clearTimeout(RtapObserver.RTAPobserverTimer);
									RtapObserver.RTAPobserverTimer = setTimeout(RtapObserver.RTAPobserverTimerFkt, 2000);
								}
							}
						}
					}
				}
			}
		});

		Webroot_Extension.currentChksum = Webroot_Extension.getContentHash(Webroot_Helper.extractPageHtml(document));
		mutationObserver.observe(document.body, { attributes: false, childList: true, characterData: false, subtree: true });
		RtapObserver.IsContentObservingSet = true;
	}

}