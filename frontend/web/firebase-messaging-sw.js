importScripts("https://www.gstatic.com/firebasejs/10.8.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.8.1/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: 'AIzaSyBsFQ0mhDNFaMnljm9xh06WYFhP_UUn-XE',
  appId: '1:889037144626:web:01efd65bb97982dd5af22b',
  messagingSenderId: '889037144626',
  projectId: 'petwatch-sm',
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload) {
  console.log('Mensaje recibido en la sombra: ', payload);

  const notificationTitle = payload.notification.title;
  const notificationOptions = {
    body: payload.notification.body,
    icon: '/icons/Icon-192.png'
  };

  return self.registration.showNotification(notificationTitle, notificationOptions);
});