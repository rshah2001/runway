// Runway's service worker: shows heads-up alerts sent by the server (backend/app/alerts.py) and opens
// Today when one is tapped. It caches nothing — the app always loads fresh from the server.
self.addEventListener('push', (event) => {
  let alert = {};
  try {
    alert = event.data ? event.data.json() : {};
  } catch {
    alert = { body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(
    self.registration.showNotification(alert.title || 'Runway', {
      body: alert.body || '',
      tag: alert.tag, // a newer alert about the same dip replaces the older one
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: alert.url || '/' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((open) => {
      for (const c of open) {
        if (c.url.startsWith(self.location.origin) && 'focus' in c) return c.focus();
      }
      return self.clients.openWindow(url);
    }),
  );
});
