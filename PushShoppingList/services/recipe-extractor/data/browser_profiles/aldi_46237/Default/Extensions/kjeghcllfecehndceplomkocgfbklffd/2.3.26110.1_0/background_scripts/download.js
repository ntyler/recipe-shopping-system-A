/****************************************************************************************
  Module:		download
  Description:	- Handles downloads of URLs (saveAs)
				- Extracts download data (URL, filename,...) for scanning for malware
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pblaimschein@webroot.com
  Manager:		jmayr@webroot.com
  Created:		03/24/2020 (mm/dd/yyyy)
*****************************************************************************************/

if (Webroot_Browser.SAFARI != Webroot_Browser.identify_browser()) {

	var TimerIds = {};

	function reportDownload(downloadItem) {
		if (downloadItem.error) return;
		if ((Webroot_Browser.identify_browser() != Webroot_Browser.FIREFOX) && (downloadItem.state != 'complete')) return;
		if (!downloadItem.filename && !downloadItem.finalUrl) return;

		var url = downloadItem.finalUrl;
		if (!url) url = downloadItem.url;
		const uri = new Uri(url);
		if (!uri || uri?.raw == '') return;

		if (Webroot_Helper.isWTSUrl(uri)) return;

		// Check for open port
		const portId = downloadItem.id + 0x80000000;
		returnObj = ComPorts.checkPort(portId);
		if (returnObj.error != 0) return;
		const port = returnObj.port;

		// Create Request
		const RequestMsg = Webroot_Server.create_saveas_request(url, downloadItem.filename, portId);

		// Send request to NativeApp
		const iError = ComPorts.sendNonJSModuleMessage(RequestMsg, port);
	}

	function processBCAP(downloadid, downloadItem, jsnData) {
		if (downloadItem.error) return;

		if (!jsnData.DATA || !jsnData.DATA[0] || !jsnData.DATA[0].BLK) {
			if (Webroot_Browser.identify_browser() != Webroot_Browser.FIREFOX) {
				if (downloadItem.canResume) chrome.downloads.resume(downloadItem.id);
			}
			else reportDownload(downloadItem);
			return;
		}

		if (downloadItem.state == "complete") {
			// Remove any downloaded file data
			chrome.downloads.removeFile(downloadid);
		}
		else {
			// Cancel the download
			chrome.downloads.cancel(downloadid, function () {
				if (chrome.runtime.lastError) chrome.downloads.removeFile(downloadid);
			});

		}
		// Construct Block Page URL
		var url = downloadItem.finalUrl;
		if (!url) url = downloadItem.url;
		var myBlockPageURL = Webroot_Helper.constructBlkUrl(jsnData);

		if (!myBlockPageURL) return;

		// Navigate to Block Page
		chrome.tabs.create({ url: myBlockPageURL, active: true });

	}

	function onDownloadBCAP(downloadid, jsnData) {
		if (!downloadid) return;
		if (!jsnData) return;
		if (jsnData.err) return;
		if (jsnData.OP != 1) return;

		if (Webroot_Browser.identify_browser() != Webroot_Browser.FIREFOX) {

			let obj = TimerIds[downloadid];
			if (obj) {
				clearTimeout(obj.timer);
				TimerIds[downloadid] = null;
				delete TimerIds[downloadid];
			}

			chrome.downloads.search({ id: downloadid }, function (item) {

				for (var i = 0; i < item.length; i++) {
					processBCAP(downloadid, item[i], jsnData);
				}
			});
		}
		else {

			browser.downloads.search({ id: downloadid }).then(function (item) {

				for (var i = 0; i < item.length; i++) {
					processBCAP(downloadid, item[i], jsnData);
				}
			});

		}
	}

	function doDownloadBCAP(downloadItem) {
		var url = downloadItem.finalUrl;
		if (!url) url = downloadItem.url;
		const uri = new Uri(url);
		if (!uri || uri?.raw == '') return;

		if (Webroot_Helper.isWTSUrl(uri)) return 0;

		if (Webroot_Browser.identify_browser() != Webroot_Browser.FIREFOX) {
			chrome.downloads.pause(downloadItem.id);

			const id = setTimeout(onDownloadAlarm, 3000, downloadItem.id);
			TimerIds[downloadItem.id] = { timer: id };
		}

		const portId = downloadItem.id + 0x80000000;
		// Check for open port
		returnObj = ComPorts.checkPort(portId);
		if (returnObj.error != 0) return 0;
		const port = returnObj.port;

		// Create Request
		Webroot_Server.createBcapRequest(url, portId, 1).then((RequestMsg) => {

			// Send request to NativeApp
			const iError = ComPorts.sendNonJSModuleMessage(RequestMsg, port);
		});
	}

	// Chrome Edge
	if (Webroot_Browser.identify_browser() != Webroot_Browser.FIREFOX) {

		function reportDownloadviaID(id) {

			chrome.downloads.search({ id: id }, function (item) {

				for (var i = 0; i < item.length; i++) {
					if (item[i].error) continue;
					if (!item[i].filename) continue;

					reportDownload(item[i]);
				}
			});
		}

		function onDownloadAlarm(alarm) {

			var downloadid = alarm;

			chrome.downloads.search({ id: downloadid }, function (item) {
				for (var i = 0; i < item.length; i++) {

					if (item[i].error) continue;
					if (item[i].canResume) chrome.downloads.resume(downloadid);
				}
			});
		}

		chrome.downloads.onChanged.addListener(function (downloadItem) {
			if (!downloadItem.id) return 0;
			if (downloadItem.error) return 0;
			if (!Webroot_Background.INITIALIZED || !Webroot_Background.Enabled) return 0;
			if (!downloadItem.state || !downloadItem.state.current || (downloadItem.state.current != "complete")) return 0;

			reportDownloadviaID(downloadItem.id);
		});

		chrome.downloads.onDeterminingFilename.addListener(function (downloadItem) {
			if (!downloadItem.id) return 0;
			if (downloadItem.error) return 0;
			if (!downloadItem.url && !downloadItem.finalUrl) return 0;
			if (!Webroot_Background.INITIALIZED || !Webroot_Background.Enabled) return 0;

			doDownloadBCAP(downloadItem);
		});
	}
	else { // FireFox

		chrome.downloads.onCreated.addListener(function (downloadItem) {
			if (!downloadItem.id) return 0;
			if (downloadItem.error) return 0;
			if (!downloadItem.url) return 0;
			if (!Webroot_Background.INITIALIZED || !Webroot_Background.Enabled) return 0;

			doDownloadBCAP(downloadItem);
		});

	}
}

