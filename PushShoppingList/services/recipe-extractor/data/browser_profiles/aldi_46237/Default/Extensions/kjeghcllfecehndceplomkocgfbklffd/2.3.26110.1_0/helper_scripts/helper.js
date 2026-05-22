/********************************************************************************
  Module:		helper
  Description:	- Script containing all the helper methods used by the background
				  and the content scripts
/********************************************************************************
  Property of:	Webroot Inc.
  Copyright:	Webroot Inc. (c) 2026
/********************************************************************************
  Creator:		melsaie@webroot.com
  Manager:		pblaimschein@webroot.com
  Created:		02/10/2017 (mm/dd/yyyy)
********************************************************************************/

// ------------- //
// Uri class     //
// ------------- //
class Uri {
	constructor(url) {
		if (!url) {
			this.raw = "";
			this.protocol = "";
			this.authority = "";
			this.host = "";
			this.port = "";
			this.fullpath = "";
			this.path = "";
			this.filename = "";
			this.queryString = "";
			this.anchor = "";
			this.querySeparator = "";
			this.pathAndQuery = "";
			this.urlWithoutQuery = "";
			return;
		}
		var uriParts;
		try {
			uriParts = new RegExp("^(?:([^:/?#.]+):)?(?://)?(([^:/?#]*)(?::(\\d*))?)?((/(?:[^?#](?![^?#/]*\\.[^?#/.]+(?:[\\?#]|$)))*/?)?([^?#/]*))?(?:\\?([^#]*))?(?:#(.*))?").exec(url);
		}
		catch (err) {
			this.raw = url;
			this.protocol = "";
			this.authority = "";
			this.host = "";
			this.port = "";
			this.fullpath = "";
			this.path = "";
			this.filename = "";
			this.queryString = "";
			this.anchor = "";
			this.querySeparator = "";
			this.pathAndQuery = "";
			this.urlWithoutQuery = "";
			return;
		}
		for (var i = 0; i < uriParts.length; i++) if (!uriParts[i]) uriParts[i] = "";
		this.raw = uriParts[0];
		this.protocol = uriParts[1];
		this.authority = uriParts[2];
		this.host = uriParts[3];
		this.port = uriParts[4];
		this.fullpath = uriParts[5];
		this.path = uriParts[6];
		this.filename = uriParts[7];
		this.queryString = uriParts[8];
		this.anchor = uriParts[9];
		if (this.queryString) {
			var pos = url.indexOf(this.queryString);
			if (pos >= 0) this.querySeparator = url[pos - 1];
		}
		else this.querySeparator = "";
		this.pathAndQuery = this.fullpath + this.querySeparator + this.queryString
		if (this.anchor) this.pathAndQuery += "#" + this.anchor;
		var uriSplitQuery = new RegExp("^[^?#&]+").exec(url);
		this.urlWithoutQuery = uriSplitQuery[0];
	}
	isHostValid() {
		if (!this.host) return false;
		if (this.host.length == 9 && this.host.toLowerCase() == "localhost") return true;
		if (this.host.indexOf(" ") >= 0) return false;
		//first dot
		if (this.host.indexOf(".") <= 0) return false;
		//no dot at the end
		if (this.host.lastIndexOf(".") == this.host.length - 1) return false;
		if (this.host.indexOf("..") >= 0) return false;
        // no mailto links
		if (this.host.indexOf("@") >= 0) return false;
		return true;
	}
	query() {
		if (!this.isHostValid()) return {};
		if (!this.queryString) return {};

		var queryDict = {};
		var queryItems = this.queryString.split('&');
		for (var i = 0; i < queryItems.length; i++) {
			var queryPair = queryItems[i].split('=');
			if (queryPair.length == 2) queryDict[queryPair[0]] = queryPair[1];
			else if (queryPair.length == 1) queryDict[queryPair[0]] = undefined;
			else if (queryPair.length > 2) {
				var firstEqual = queryItems[i].indexOf("=");
				queryDict[queryItems[i].substring(0, firstEqual)] = queryItems[i].substr(firstEqual + 1);
			}
		}
		return queryDict;
	}
}

// ------------- //
// Helper Object //
// ------------- //
const WTSURLID = {
	NONE: 0x0000,
	BLOCKPAGE: 0x0001,
	IFRAMEBLOCKPAGE: 0x0002,
	IWHITELISTPAGE: 0x0003,
	WHITELISTPAGE: 0x0004,
	ERRORPAGE: 0x0005
};

const BLOCKPAGEHOST = 'wf.webrootanywhere.com';
const BLOCKPAGEPATH = '/consumerblockpage.aspx';
const IFRAMEBLOCKPAGEPATH = '/iframeblockpage.aspx';
const WHITELISTPATH = '/webfiltering/whitelist.html';
const IWHITELISTPATH = '/webfiltering/iwhitelist.aspx';
const ERRORPAGEPATH = '/errorpages/oops.aspx';

var Webroot_Helper = {

	// Define variables
	sraEncodingType: Object.freeze({ "NoEncoding": "0", "Url": "1" }),

	// ---------------------------------- //
	//		 Create BULK URL JSON array	  //
	//       to be sent to service		  //
	// ---------------------------------- //
	create_URL_Array: function (linksArray, domainIndex) {

		var request = [];
		var uri = null;

		// Iterate through the Links array
		for (var i = 0; i < linksArray.length; i++) {
			if (i < 100) {
				// BreakDown URL
				if (linksArray[i].myElement.localName == "a") {
					// <A> Tag
					uri = new Uri(linksArray[i].myElement.href);
				}
				else {
					// <IFRAME> Tag
					uri = new Uri(linksArray[i].myElement.src);
				}

				var processedURL = uri?.urlWithoutQuery;
				
				// Extract URL
				if (SRA.SRA_CONFIG[domainIndex].urlregex != '') {
					var regex = new RegExp(SRA.SRA_CONFIG[domainIndex].urlregex, 'i');
					var matches = processedURL.match(regex);
					if (matches)
						processedURL = matches[2];
				}

				// Decode URL
				if (SRA.SRA_CONFIG[domainIndex].encode == Webroot_Helper.sraEncodingType.Url) {
					try {
						processedURL = decodeURIComponent(processedURL);
					} catch (e) { processedURL = processedURL; }
				}

				request.push({
					"URL": processedURL,
					"REF": i + 1
				});

			}
		}

		//WTS-626: add second URL for classification to array if only one search result exists
		if (linksArray.length == 1) {
			request.push({
				"URL": "www.google.com",
				"REF": 2
			});
		}

		return request;
	},

	// ---------------------------------- //
	//		 Create BULK URL JSON array	  //
	//       to be sent to service		  //
	// ---------------------------------- //
	create_Url_Array_FromBing: function (linksArray) {
		var request = [];

		// Iterate through the Links array
		for (var i = 0; i < linksArray.length; i++) {
			if (i < 100) {

				var processedURL = linksArray[i].uri.urlWithoutQuery;

				if (processedURL.endsWith("..")) {
					var pos = processedURL.lastIndexOf("?");
					if (pos < 0) pos = processedURL.lastIndexOf("/");
					else pos = pos - 1;
					if (pos < 0) continue;
					processedURL = processedURL.substring(0, pos + 1);
				}

				request.push({
					"URL": processedURL,
					"REF": i + 1
				});

			}
		}
		if (request.length == 0) return request;

		//WTS-626: add second URL for classification to array if only one search result exists
		if (linksArray.length == 1) {
			request.push({
				"URL": "www.google.com",
				"REF": 2
			});
		}

		return request;

	},


	// ---------------------------- //
	// Get Size of String in Bytes  //
	// ---------------------------- //
	getByteLen: function (normal_val) {
		// Force string type
		normal_val = String(normal_val);

		var byteLen = 0;
		for (var i = 0; i < normal_val.length; i++) {
			var c = normal_val.charCodeAt(i);
			byteLen += c < (1 << 7) ? 1 :
					   c < (1 << 11) ? 2 :
					   c < (1 << 16) ? 3 :
					   c < (1 << 21) ? 4 :
					   c < (1 << 26) ? 5 :
					   c < (1 << 31) ? 6 : Number.NaN;
		}
		return byteLen;
	},
	// ------------------------- //
	// Check if host is BlockPage host //
	// ------------------------- //
	isWTSHost: function (uri) {

		if (!uri) return false;
		if (!uri.raw) return false;
		if (uri.host.toLowerCase() != BLOCKPAGEHOST) return false;
		if (uri.protocol.toLowerCase() != "https") return false;

		return true;
	},
	// ---------------------------------- //
	// Check if URL is WTS related        //
	// ---------------------------------- //	
	isWTSUrl: function (uri)
	{
		var wtsUrlId = WTSURLID.NONE;

		if (!Webroot_Helper.isWTSHost(uri)) return wtsUrlId;

		var urlPath = uri.fullpath.toLowerCase();

		if (urlPath == BLOCKPAGEPATH) wtsUrlId = WTSURLID.BLOCKPAGE;
		else if (urlPath == IFRAMEBLOCKPAGEPATH) wtsUrlId = WTSURLID.IFRAMEBLOCKPAGE;
		else if (urlPath == IWHITELISTPATH) wtsUrlId = WTSURLID.IWHITELISTPAGE;
		else if (urlPath == WHITELISTPATH) wtsUrlId = WTSURLID.WHITELISTPAGE;
		else if (urlPath == ERRORPAGEPATH) wtsUrlId = WTSURLID.ERRORPAGE;

		return wtsUrlId;
	},
	// ----------------------- //
	// Construct BLOCKPAGE URL //
	// ----------------------- //
	constructBlkUrl: function (responseMsg, isIframe) {
		var myBlockPageURL;
		var obj = responseMsg;

		if (isIframe) myBlockPageURL = "https://" + BLOCKPAGEHOST + IFRAMEBLOCKPAGEPATH;
		else myBlockPageURL = "https://" + BLOCKPAGEHOST + BLOCKPAGEPATH;

		// Add <FLG>
		myBlockPageURL += '?q=' + responseMsg["V2BLOB"];
		// return BLOCKPAGE URL
		return myBlockPageURL;
	},

	// ------------------------- //
	// Extract page HTML content //
	// ------------------------- //
	extractPageHtml: function (document)
	{
		if (!document) return "";

		// Get Root Document HTML
		var RootHTML = "";
		if (document.head && document.head.outerHTML)
			RootHTML += document.head.outerHTML;
		if (document.body && document.body.outerHTML)
			RootHTML += document.body.outerHTML;

		if (RootHTML.length > 0) RootHTML = "<html>" + RootHTML + "</html>";

		return RootHTML;
	},
	// public method for decoding
	decodeBase64: function (input)
	{
		input = input.replace(/[^A-Za-z0-9\+\/\=]/g, "");
		input = atob(input);
		input = decodeURIComponent(escape(input));
		return input;
	}
};