(() => {
  'use strict';

  const installButton = document.getElementById('installAppBtn');
  let installEvent = null;

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch((error) => {
      console.warn('[PWA] Service worker registration failed:', error);
    });
  }

  if (!installButton) return;

  const isInstalled =
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;

  if (isInstalled) return;

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installEvent = event;
    installButton.hidden = false;
  });

  installButton.addEventListener('click', async () => {
    if (!installEvent) return;

    installEvent.prompt();
    const choice = await installEvent.userChoice;
    installEvent = null;

    if (choice.outcome === 'accepted') installButton.hidden = true;
  });

  window.addEventListener('appinstalled', () => {
    installEvent = null;
    installButton.hidden = true;
  });
})();