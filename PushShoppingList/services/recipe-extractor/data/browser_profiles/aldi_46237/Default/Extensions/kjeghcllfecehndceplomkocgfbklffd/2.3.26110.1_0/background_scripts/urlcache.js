/****************************************************************************************
  Module:		urlCache
  Description:	implements an UrlCache via indexedDB
/****************************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/****************************************************************************************
  Creator:		pblaimschein@webroot.com
  Manager:		jmayr@webroot.com
  Created:		23/03/2022 (mm/dd/yyyy)
*****************************************************************************************/


// ------------- //
// urlCache Object //
// ------------- //
var Webroot_urlCache = {

	DBSTORE_NAME: 'URL_Cache',
	URL_EXPIRY_SECONDS: 10 * 60,
	cacheEnabled: false,
	urlCacheDB: null,
	lastClean: 0,

	enable(enabled) {
		if (enabled != this.cacheEnabled) {
			this.cacheEnabled = enabled;
			if (this.cacheEnabled) return this.openURLCache();
			else if (this.urlCacheDB) {
				this.urlCacheDB.close();
				this.urlCacheDB = null;
            }
        }
    },
	openURLCache() {
		return new Promise((resolve, reject) => {
			var req = indexedDB.open('WTSURLDB', 1);
			req.onsuccess = function (evt) {
				Webroot_urlCache.urlCacheDB = this.result;
				resolve(true);
			};
			req.onerror = function (evt) {
				console.log("openURLCache:", evt.target.errorCode);
				reject(evt.target.errorCode);
			};

			req.onupgradeneeded = function (evt) {
				var store = evt.currentTarget.result.createObjectStore(
					Webroot_urlCache.DBSTORE_NAME, { keyPath: 'KEY', autoIncrement: false });

				//store.createIndex('ip', 'ip', { unique: false });
				store.createIndex('insertionDate', 'insertionDate', { unique: false });
			};
		});
	},
	addUrl(stringJSONObject) { // must contain URL as key
		if (!Webroot_urlCache.urlCacheDB) return;
		if (!stringJSONObject) return;

		// ************************ to JSON
		var jsnObject = {};
		try {
			jsnObject = JSON.parse(stringJSONObject);
		}
		catch (e) {
			WTSLog.log('Failed to parse JSON', e, stringJSONObject);
			return;
		}
		if (!jsnObject.URL || jsnObject.URL.length == 0) return;

		// ************************ prepare URL
		var cacheUrls = Webroot_urlCache.getCacheUrls(jsnObject.URL);
		if (cacheUrls.length == 0) return;

		// ******************** store alcat
		if (jsnObject.ALCAT == 1) {
			jsnObject['KEY'] = cacheUrls[0];
			delete jsnObject['URL'];
			Webroot_urlCache.storeUrlCache(jsnObject);
			return;
		}

		// ******************** store url
		if (cacheUrls.length > 1) {
			jsnObject['KEY'] = cacheUrls[1];
			delete jsnObject['URL'];
			Webroot_urlCache.storeUrlCache(jsnObject);
		}
	},
	appendToUrl(url, stringJSONObject) {
		if (!Webroot_urlCache.urlCacheDB) return;
		if (!url) return;
		if (!stringJSONObject) return;

		// ************************ to JSON
		var jsnObject = {};
		try {
			jsnObject = JSON.parse(stringJSONObject);
		}
		catch (e) {
			WTSLog.log('Failed to parse JSON', e, stringJSONObject);
			return;
		}
		if (jsnObject.ISPHIS == undefined || jsnObject.SCORE == undefined) return;

		// ************************ prepare URL
		var cacheUrls = Webroot_urlCache.getCacheUrls(url);
		if (cacheUrls.length == 0) return;

		// ******************** store url
		if (cacheUrls.length > 1) {
			Webroot_urlCache.updateUrlCacheEntry(cacheUrls[0], jsnObject).then((result1) => {
				if (result1 == 0) {
					Webroot_urlCache.updateUrlCacheEntry(cacheUrls[1], jsnObject).then((result2) => {
						if (result2 == 0) WTSLog.log("urlCacheDB entry not found for update");
					});
                }
			});
		}

	},
	findUrls(urlArray) {

		if (!Webroot_urlCache.urlCacheDB) return Promise.resolve(false);
		if (!urlArray || urlArray.length == 0) return Promise.resolve(false);

		// ************************ prepare URLs
		return new Promise((resolve) => {
			for (var i = 0; i < urlArray.length; i++) {
				urlArray[i]['CURLS'] = Webroot_urlCache.getCacheUrls(urlArray[i]['URL']);
			}

			Promise.all(
				urlArray.map(elem => Webroot_urlCache.fillUrlCacheEntry(elem))
			).then(
				(success) => {
					resolve(true);
					Webroot_urlCache.cleanupCheck();
				},
				(error) => {
					resolve(false);
				}
			);
		});
	},
	cleanupCheck() {
		if ((Date.now() - Webroot_urlCache.lastClean) < 60 * 5 * 1000) return;

		Webroot_urlCache.lastClean = Date.now();

		Webroot_urlCache.removeOldUrls();

	},
	removeOldUrls() {
		if (!Webroot_urlCache.urlCacheDB) return;
		var olderThan = (Date.now() - Webroot_urlCache.URL_EXPIRY_SECONDS * 1000);

		var trans = Webroot_urlCache.urlCacheDB.transaction(Webroot_urlCache.DBSTORE_NAME, 'readwrite');
		var store = trans.objectStore(Webroot_urlCache.DBSTORE_NAME);
		var index = store.index("insertionDate");
		const oldIdx = index.getAllKeys(IDBKeyRange.upperBound(olderThan));
		oldIdx.onsuccess = () => {
			for (var i = 0; i < oldIdx.result.length; i++) {
				try {
					store.delete(oldIdx.result[i]);
				}
				catch (e) {
					WTSLog.log("failed to delete URL cache entry", oldIdx.result[i]);
				};
			}
		};
	},
	clearUrlCache() {
		if (!Webroot_urlCache.urlCacheDB) return;

		var trans = Webroot_urlCache.urlCacheDB.transaction(Webroot_urlCache.DBSTORE_NAME, 'readwrite');
		var store = trans.objectStore(Webroot_urlCache.DBSTORE_NAME);
		store.clear();

	},
	traceURLDB() {
		if (!Webroot_urlCache.urlCacheDB) return;
		var trans = Webroot_urlCache.urlCacheDB.transaction(Webroot_urlCache.DBSTORE_NAME, 'readonly');
		var store = trans.objectStore(Webroot_urlCache.DBSTORE_NAME);

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
			console.log("UrlCache-Entry:", cursor.value);
			cursor.continue();
		}
	},
	getCacheUrls(url) {
		var cacheUrls = [];
		if (!url) return cacheUrls;

		var uri = new Uri(url);
		if (!uri.isHostValid()) return cacheUrls;

		var hostUrl = uri.host.toLowerCase();
		if (hostUrl.startsWith('www.')) hostUrl = hostUrl.substring(4);
		cacheUrls.push(hostUrl + '/');

		var cacheUrl = (hostUrl + uri.path).toLowerCase();
		if (cacheUrl.endsWith('/')) cacheUrl = cacheUrl.substr(0, cacheUrl.length - 1);
		cacheUrls.push(cacheUrl);

		return cacheUrls;
	},
	storeUrlCache(jsnUrlData) {
		try {
			jsnUrlData['insertionDate'] = Date.now();
			var trans = Webroot_urlCache.urlCacheDB.transaction(Webroot_urlCache.DBSTORE_NAME, 'readwrite');
			var store = trans.objectStore(Webroot_urlCache.DBSTORE_NAME);
			var req = store.put(jsnUrlData);
			return req;
		}
		catch (e) {
			WTSLog.log("Failed to write to urlCacheDB", e);
		}
	},
	updateUrlCacheEntry(cachekey, jsnAddUrlData) {
		return new Promise((resolve) => {
			var trans = Webroot_urlCache.urlCacheDB.transaction(Webroot_urlCache.DBSTORE_NAME, 'readwrite');
			var store = trans.objectStore(Webroot_urlCache.DBSTORE_NAME);
			var req = store.get(cachekey);
			req.onsuccess = function (evt) {
				var record = evt.target.result;
				if (!record) {
					resolve(0);
					return;
				}
				if (record['RTAP-ORIG'] == undefined && record['RTAP'] != undefined) record['RTAP-ORIG'] = record['RTAP'];
				if (jsnAddUrlData['ISPHIS'] == 1) record['RTAP'] = -1;
				else record['RTAP'] = 1;
				record['RTAPDATA'] = jsnAddUrlData;
				store.put(record);
				resolve(1);
			}
			req.onerror = function (evt) {
				WTSLog.log("Error updating urlCacheDB entry", evt.target.errorCode);
				resolve(-1);
			}
		});
	},
	fillUrlCacheEntry(urlElem) {
		return new Promise((resolve) => {
			try {
				if (!Webroot_urlCache.urlCacheDB || !urlElem || !urlElem['CURLS'] || !urlElem['CURLS'].length ) {
					resolve("");
					return;
				}
				var trans = Webroot_urlCache.urlCacheDB.transaction(Webroot_urlCache.DBSTORE_NAME, 'readonly');
				var store = trans.objectStore(Webroot_urlCache.DBSTORE_NAME);
				var newerThan = (Date.now() - Webroot_urlCache.URL_EXPIRY_SECONDS * 1000);

				var req1 = store.get(urlElem['CURLS'][0]);
				req1.onsuccess = function (evt1) {
					if (evt1.target.result) {
						var good = false;
						if (evt1.target.result['insertionDate'] >= newerThan) {
							good = true;
							urlElem["CACHE"] = evt1.target.result;
							urlElem["CACHE"]["CACHED"] = 1;
							urlElem["CACHE"]["URL"] = urlElem["URL"];
							delete urlElem["CACHE"]["KEY"];
						}
						delete urlElem["CURLS"];
						resolve(good);
					}
					else {
						var req2 = store.get(urlElem['CURLS'][1]);
						req2.onsuccess = function (evt2) {
							delete urlElem["CURLS"];
							if (evt2.target.result) {
								var good = false;
								if (evt2.target.result['insertionDate'] >= newerThan) {
									good = true;
									urlElem["CACHE"] = evt2.target.result;
									urlElem["CACHE"]["CACHED"] = 1;
									urlElem["CACHE"]["URL"] = urlElem["URL"];
									delete urlElem["CACHE"]["KEY"];
								}
								resolve(good);
							}
							else resolve(false);
						}
					}
				};
				req1.onerror = function (evt) {
					WTSLog.log("Failed to find UrlCache entry", evt);
					delete urlElem["CURLS"];
					resolve(false);
				}
			}
			catch (e) {
				WTSLog.log("Exception on getUrlCache", e);
				delete urlElem["CURLS"];
				resolve(false);
			}
		});
	}
}

