/**
 * usePushNotifications — Syrabit.ai
 * Manages Web Push permission, VAPID key fetching, and subscription storage.
 * Requires the service worker to be registered (sw.js handles push events).
 */
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';
const API_BASE = `${BACKEND_URL}/api`;

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export function usePushNotifications() {
  const [permission, setPermission] = useState(
    typeof Notification !== 'undefined' ? Notification.permission : 'default'
  );
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);

  const isSupported =
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    typeof Notification !== 'undefined';

  // On mount, check if already subscribed
  useEffect(() => {
    if (!isSupported) return;
    navigator.serviceWorker.ready.then((reg) => {
      reg.pushManager.getSubscription().then((sub) => {
        setSubscribed(!!sub);
      });
    });
  }, [isSupported]);

  const subscribe = useCallback(async () => {
    if (!isSupported) {
      setError('Push notifications are not supported in this browser.');
      return false;
    }
    setLoading(true);
    setError(null);
    try {
      // 1. Request permission
      const perm = await Notification.requestPermission();
      setPermission(perm);
      if (perm !== 'granted') {
        setError('Push permission denied.');
        setLoading(false);
        return false;
      }

      // 2. Fetch VAPID public key
      const { data } = await axios.get(`${API_BASE}/push/vapid-public-key`);
      const applicationServerKey = urlBase64ToUint8Array(data.public_key);

      // 3. Subscribe via PushManager
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      });

      // 4. Send subscription to backend
      await axios.post(
        `${API_BASE}/push/subscribe`,
        { subscription: sub.toJSON() },
        { withCredentials: true }
      );

      setSubscribed(true);
      setLoading(false);
      return true;
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Subscription failed.');
      setLoading(false);
      return false;
    }
  }, [isSupported]);

  const unsubscribe = useCallback(async () => {
    if (!isSupported) return false;
    setLoading(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        const endpoint = sub.endpoint;
        await sub.unsubscribe();
        await axios.delete(
          `${API_BASE}/push/subscribe`,
          { data: { endpoint }, withCredentials: true }
        );
      }
      setSubscribed(false);
    } catch (e) {
      setError(e?.message || 'Unsubscribe failed.');
    } finally {
      setLoading(false);
    }
  }, [isSupported]);

  return { isSupported, permission, subscribed, loading, error, subscribe, unsubscribe };
}
