self.addEventListener("push", (event) => {
    let payload = {};

    try {
        payload = event.data ? event.data.json() : {};
    } catch (_error) {
        payload = {
            body: event.data ? event.data.text() : "Recipe Shopping List notification"
        };
    }

    const title = payload.title || "Recipe Shopping List";
    const options = {
        body: payload.body || payload.message || "You have a new update.",
        icon: payload.icon || "/static/images/ai-pantry-logo.svg",
        badge: payload.badge || "/static/images/ai-pantry-logo.svg",
        data: {
            url: payload.url || "/#userAccountSection"
        }
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || "/#userAccountSection";

    event.waitUntil((async () => {
        const windows = await clients.matchAll({ type: "window", includeUncontrolled: true });

        for (const windowClient of windows) {
            if ("focus" in windowClient) {
                await windowClient.focus();
                if ("navigate" in windowClient) {
                    return windowClient.navigate(targetUrl);
                }
                return;
            }
        }

        if (clients.openWindow) {
            return clients.openWindow(targetUrl);
        }
    })());
});
