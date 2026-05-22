/****************************************************************************************
  Module:		Webroot_IP_cache
  Description:	- caches surfed URLs IP
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		aroiter@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		08/04/2020 (mm/dd/yyyy)
*****************************************************************************************/
var Webroot_IP_cache = {

    TimeItemElapsed: 10 * 60, 
	init: function (standaloneMode) {

		if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) Webroot_IP_cache.referrer = "moz-extension://";
		else Webroot_IP_cache.referrer = "chrome-extension://";

		if (standaloneMode) {
			Webroot_IP_cache.standaloneMode = true;
			Webroot_IP_cache.enabled = true;

			chrome.management.getSelf(function (result) {
				if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) {
					let iStart = result.optionsUrl.indexOf("://");
					let iEnd = result.optionsUrl.indexOf("/", iStart ? iStart + 3 : 0);
					if (iStart && iEnd) Webroot_IP_cache.referrer += result.optionsUrl.substring(iStart + 3, iEnd).toLowerCase();
				}
				else if (result.id) Webroot_IP_cache.referrer += result.id.toLowerCase();
			});
		}

		if (Webroot_IP_cache.standaloneMode) {
			chrome.webRequest.onResponseStarted.addListener(
				Webroot_IP_cache.onResponse,
				{
					urls: ["http://*/*", "https://*/*"],
					types: ["main_frame", "sub_frame", "xmlhttprequest", "websocket"]
				}
			);
			Webroot_IP_cache.openDB();
		}
	},
	onResponse: function (details) {

		if (!Webroot_IP_cache.standaloneMode) return;
		if (!details || !details.url || !details.ip) return;
		if (Webroot_IP_cache.detectPrivateProxy(details)) return;

		var uri = new Uri(details.url);
		if (!uri.isHostValid()) return;

		if (Webroot_IP_cache.IPCacheDB) {
			var ip = details.ip;
			if (ip == '::1') ip = '127.0.0.1';
			Webroot_IP_cache.addIPtoDB({ URL: uri.host , ip: ip, insertionDate: Date.now() });
		}
	},
	detectPrivateProxy(details) {

		let origin = "";
		if (Webroot_Browser.identify_browser() == Webroot_Browser.FIREFOX) origin = details.originUrl ? details.originUrl.toLowerCase() : "";
		else origin = details.initiator ? details.initiator.toLowerCase() : "";

		if (origin.startsWith(Webroot_IP_cache.referrer)) {
			if (details.statusCode != 200) return false;

			var urlLower = details.url.toLowerCase();

			// if integrated mode
			if (urlLower == "http://127.0.0.1:27019/") {
				if (Webroot_IP_cache.enabled) {
					Webroot_IP_cache.enabled = false;
					Webroot_IP_cache.standaloneMode = false;
					Webroot_IP_cache.clearIPCacheDB();
					Webroot_urlCache.clearUrlCache();
				}
				return true;
			}

			if (urlLower.startsWith("https://sn.webrootcloudav.com/")) {

				if (Webroot_IP_cache.ipIsPrivate(details.ip)) {
					if (Webroot_IP_cache.enabled) {
						Webroot_IP_cache.enabled = false;
						Webroot_IP_cache.clearIPCacheDB();
						Webroot_urlCache.clearUrlCache();
						Module.onProxyDetected(true);
						WTSLog.log("Proxy detected!", details.ip);
					}
				}
				else {
					if (!Webroot_IP_cache.enabled) {
						Webroot_IP_cache.enabled = true;
						Webroot_IP_cache.clearIPCacheDB();
						Webroot_urlCache.clearUrlCache();
						Module.onProxyDetected(false);
						WTSLog.log("Proxy removed!", " ");
					}
				}
			}
		}

		return !Webroot_IP_cache.enabled;
	},
	ipIsPrivate(sIP) {

		const iIP = Webroot_IP_cache.sIPtoiIP(sIP);
		if (!iIP) return false;

		if (Webroot_IP_cache.ipMatch(iIP, 0x7F000000, 0xFF000000)) return true;
		if (Webroot_IP_cache.ipMatch(iIP, 0x0A000000, 0xFF000000)) return true;
		if (Webroot_IP_cache.ipMatch(iIP, 0xAC100000, 0xFFF00000)) return true;
		if (Webroot_IP_cache.ipMatch(iIP, 0xC0A80000, 0xFFFF0000)) return true;

		return false;

	},
	sIPtoiIP(sIP) {
		if (!sIP) return 0;

		const aIP = sIP.split(".");
		if (aIP.length != 4) return 0;

		var iIP = 0;
		for (var i = 0; i < aIP.length; i++) {
			if (i > 0) iIP *= 256;
			const byte = parseInt(aIP[i]);
			if (byte < 0 || byte > 255) return 0;
			iIP += parseInt(aIP[i]);
		}
		return iIP;
	},
	ipMatch(iIP, iCompareIP, iCompareMask) {

		if (((iIP & iCompareMask) >>> 0) === iCompareIP) return true; // >>> -> 0 interpret as unsigned
		return false;
	},
	get_IP(url) {

		if (!Webroot_IP_cache.enabled) return Promise.resolve('');
		if (Webroot_Browser.SAFARI == Webroot_Browser.identify_browser()) return Promise.resolve('');

		var ret = Webroot_IP_cache.getIPfromDB(url);

		Webroot_IP_cache.cleanup_ip_cache();

		return ret;
	},
	cleanup_ip_cache() {

		var td1 = Date.now() / 1000;
		var td2 = Webroot_IP_cache.lastCleanUp / 1000;

		if ((td1 - td2) < 60 * 10) return;

		Webroot_IP_cache.lastCleanUp = Date.now();

		Webroot_IP_cache.removeOldEntriesfromDB();
	},
	openDB() {
		var req = indexedDB.open('WTSDB', 1);
		req.onsuccess = function (evt) {
			Webroot_IP_cache.IPCacheDB = this.result;
		};
		req.onerror = function (evt) {
			WTSLog.log("openDb:", evt.target.errorCode);
		};

		req.onupgradeneeded = function (evt) {
			var store = evt.currentTarget.result.createObjectStore(
				Webroot_IP_cache.DBSTORE_NAME, { keyPath: 'URL', autoIncrement: false });

			//store.createIndex('ip', 'ip', { unique: false });
			store.createIndex('insertionDate', 'insertionDate', { unique: false });
		};

		return req;
	},
	getIPfromDB(url) {
		return new Promise((resolve) => {
			try {
				if (!Webroot_IP_cache.IPCacheDB) {
					resolve("");
					return;
				}
				var trans = Webroot_IP_cache.IPCacheDB.transaction(Webroot_IP_cache.DBSTORE_NAME, 'readonly');
				var store = trans.objectStore(Webroot_IP_cache.DBSTORE_NAME);
				var newerThan = (Date.now() - Webroot_IP_cache.TimeItemElapsed * 1000);

				var req = store.get(url);
				req.onsuccess = function (evt) {
					if (evt.target.result && (evt.target.result['insertionDate'] >= newerThan)) resolve(evt.target.result.ip);
					else resolve("");
				};
				req.onerror = function (evt) {
					resolve("");
				}
			}
			catch (e) {
				WTSLog.log("Exception on getIPfromDB", e);
				resolve("");
            }
		});
	},
	addIPtoDB(json) {
		if (!Webroot_IP_cache.IPCacheDB) return;
		try {
			var trans = Webroot_IP_cache.IPCacheDB.transaction(Webroot_IP_cache.DBSTORE_NAME, 'readwrite');
			var store = trans.objectStore(Webroot_IP_cache.DBSTORE_NAME);
			var req = store.put(json);
			//return req;
		}
		catch (e) {
			WTSLog.log("Failed to write to IPCache", e);
        }
	},
	removeOldEntriesfromDB() {
		if (!Webroot_IP_cache.IPCacheDB) return;
		var olderThan = (Date.now() - Webroot_IP_cache.TimeItemElapsed * 1000);

		var trans = Webroot_IP_cache.IPCacheDB.transaction(Webroot_IP_cache.DBSTORE_NAME, 'readwrite');
		var store = trans.objectStore(Webroot_IP_cache.DBSTORE_NAME);
		var index = store.index("insertionDate");
		const oldIdx = index.getAllKeys(IDBKeyRange.upperBound(olderThan));
		oldIdx.onsuccess = () => {
			for (var i = 0; i < oldIdx.result.length; i++) {
				try {
					store.delete(oldIdx.result[i]);
				}
				catch (e) {
					WTSLog.log("failed to delete IP cache entry", oldIdx.result[i]);
				};
			}
		};
	},
	clearIPCacheDB() {
		if (!Webroot_IP_cache.IPCacheDB) return;
		var trans = Webroot_IP_cache.IPCacheDB.transaction(Webroot_IP_cache.DBSTORE_NAME, 'readwrite');
		var store = trans.objectStore(Webroot_IP_cache.DBSTORE_NAME);
		store.clear();

		return store;
    },
	traceDB() {
		if (!Webroot_IP_cache.IPCacheDB) return;
		var trans = Webroot_IP_cache.IPCacheDB.transaction(Webroot_IP_cache.DBSTORE_NAME, 'readonly');
		var store = trans.objectStore(Webroot_IP_cache.DBSTORE_NAME);

		var reqCount = store.count();
		reqCount.onsuccess = function (evt) {
			console.log('Number of records', evt.target.result);
		}
		reqCount.onerror = function (evt) {
			console.log("failed to retrieve DB entry count", this.error);
		}

		var reqOpenCursor = store.openCursor();
		reqOpenCursor.onsuccess = function (evt) {
			var cursor = evt.target.result;
			if (!cursor) return;
			console.log("IPCache-Entry:", cursor.value);
			cursor.continue();
		}

		return reqOpenCursor;
    },
	DBSTORE_NAME: 'IP_Cache',
	enabled: false,
	standaloneMode: false,
	referrer: "chrome-extension://",
	IPCacheDB: null,
	lastCleanUp: 0
};
