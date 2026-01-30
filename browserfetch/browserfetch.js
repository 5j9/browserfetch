// ==UserScript==
// @name        browserfetch
// @namespace   https://github.com/5j9/browserfetch
// @match       https://example.com/
// @grant       GM_registerMenuCommand
// ==/UserScript==
// @ts-check
(async () => {
    /**
     * Helper function to perform fetch and serialize response to JSON.
     * Respects Service Workers, Cookies, and Cache.
     * 
     * @param {string} url 
     * @param {object} options 
     * @returns {Promise<object>}
     */
    async function serFetch(url, options = {}) {
        try {
            const response = await fetch(url, options);
            const headers = Object.fromEntries(response.headers.entries());
            const buffer = await response.arrayBuffer();

            let base64Body = "";
            if (buffer.byteLength > 0) {
                // Modern syntax: Use TextDecoder
                const uint8Array = new Uint8Array(buffer);
                const binaryString = new TextDecoder().decode(uint8Array);
                base64Body = btoa(binaryString);
            }

            return {
                ok: response.ok,
                status: response.status,
                status_text: response.statusText,
                redirected: response.redirected,
                type: response.type,
                url: response.url,
                headers: headers,
                bodyBase64: base64Body,
            };

        } catch (/** @type {any} */err) {
            return {
                ok: false,
                status: 0,
                status_text: "Error",
                error: err.toString(),
                bodyBase64: null
            };
        }
    }

    /**
     * Handles the 'fetch' action.
     * @param {any} req 
     * @returns {Promise<string>} JSON string
     */
    async function doFetch(req) {
        var url = req.url;
        var options = req.options || {};

        if (req.method) {
            options.method = req.method;
        }

        // Merge headers
        if (req.headers) {
            options.headers = { ...options.headers, ...req.headers };
        }

        // Handle URL Params
        if (req.params) {
            url = new URL(url);
            for (const [key, value] of Object.entries(req.params)) {
                url.searchParams.set(key, value);
            }
        }

        // Handle Form Data
        if (req.form) {
            options.body = new URLSearchParams(req.form);
            if (!options.headers) options.headers = {};
            options.headers['Content-Type'] = 'application/x-www-form-urlencoded';
        }
        // Handle Raw Binary Body (Base64 encoded from Python)
        else if (req.bodyBase64) {
            const binaryString = atob(req.bodyBase64);
            const bytes = Uint8Array.from(binaryString, (char) => char.charCodeAt(0));
            options.body = bytes;

            // Set content type if provided, otherwise default to octet-stream
            if (!options.headers) options.headers = {};
            if (!options.headers['Content-Type']) {
                options.headers['Content-Type'] = 'application/octet-stream';
            }
        }
        // Handle standard Content-Type override
        else if (req.content_type) {
            if (!options.headers) options.headers = {};
            options.headers['Content-Type'] = req.content_type;
        }

        // Handle Timeout
        if (req.timeout) {
            options.signal = AbortSignal.timeout(req.timeout * 1000);
        }

        // Call the helper
        const result = await serFetch(url.toString(), options);

        // Attach event_id for tracking
        /** @type {any} */ (result).event_id = req.event_id;

        return JSON.stringify(result);
    }

    /**
     * Handles the 'eval' action.
     * @param {any} req 
     * @returns {Promise<string>} JSON string
     */
    async function doEval(req) {
        var evalled, resp;
        try {
            evalled = eval(req['string']);
            switch (evalled.constructor.name) {
                case 'AsyncFunction':
                    evalled = await evalled(req['arg']);
                    break;
                case 'Promise':
                    evalled = await evalled;
                    break;
                case 'Function':
                    evalled = evalled(req['arg']);
                    break;
            }
            resp = { 'result': evalled, 'event_id': req['event_id'] };
        } catch (/**@type {any} */err) {
            resp = { 'result': err.toString(), 'event_id': req['event_id'] };
        }
        return JSON.stringify(resp);
    }

    async function generateHostName() { return location.host };
    /**
     * @type {string}
     */
    var hostName;

    function connect() {
        var protocol = '5';
        var ws = new WebSocket("ws://127.0.0.1:9404/ws");

        ws.onopen = async () => {
            if (!hostName) {
                hostName = await generateHostName();
            }
            ws.send(protocol + ' ' + hostName);
        }

        ws.onclose = () => {
            console.error('WebSocket was closed; will retry in 5 seconds');
            setTimeout(connect, 5000);
        };

        ws.onmessage = async (evt) => {
            var /**@type {string} */ result;
            var /**@type {any} */ j;
            if (typeof evt.data === 'string') {
                j = JSON.parse(evt.data);
            }

            switch (j['action']) {
                case 'close_ws':
                    console.debug(`websocket closed. reason: ${j["reason"]}`);
                    ws.onclose = null;
                    ws.close();
                    return;
                case 'fetch':
                    result = await doFetch(j);
                    break;
                case 'eval':
                    result = await doEval(j);
                    break;
                default:
                    result = JSON.stringify({
                        'event_id': j['event_id'],
                        'error': `Action ${j['action']} is not defined.`
                    });
                    break;
            }
            ws.send(result);
        }
    };

    // @ts-ignore
    if (window.GM_registerMenuCommand) {
        // @ts-ignore
        GM_registerMenuCommand(
            'connect to browserfetch',
            connect
        );
    } else {
        connect();
    }
})();