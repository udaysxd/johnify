"use client";
import { useEffect } from "react";

export default function ServiceWorker() {
  useEffect(() => {
    if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
      const onLoad = () => {
        const swUrl = "/sw.js";
        navigator.serviceWorker
          .register(swUrl)
          .catch((err) => {
            // Silent failure; keep app functional
            console.debug('[SW] registration failed', err);
          });
      };
      if (document.readyState === 'complete') {
        onLoad();
      } else {
        window.addEventListener('load', onLoad, { once: true });
      }
    }
  }, []);
  return null;
}
