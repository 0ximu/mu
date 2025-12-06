import { useEffect, useRef } from 'react';
import { muClient } from '../api/client';
import { useGraphStore } from '../store/graphStore';
import type { GraphEvent } from '../api/types';

const RECONNECT_DELAY = 3000;
const MAX_RECONNECT_ATTEMPTS = 5;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const { handleGraphEvent, setWsConnected } = useGraphStore();

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    mountedRef.current = true;

    const connect = () => {
      // Don't connect if unmounted or already connected
      if (!mountedRef.current) return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      if (wsRef.current?.readyState === WebSocket.CONNECTING) return;

      try {
        const ws = muClient.connectWebSocket((event: GraphEvent) => {
          handleGraphEvent(event);
        });

        ws.onopen = () => {
          if (!mountedRef.current) {
            ws.close();
            return;
          }
          console.log('WebSocket connected');
          setWsConnected(true);
          reconnectAttemptsRef.current = 0;
        };

        ws.onclose = () => {
          if (!mountedRef.current) return;
          console.log('WebSocket disconnected');
          setWsConnected(false);
          wsRef.current = null;

          // Attempt to reconnect
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttemptsRef.current += 1;
            console.log(
              `Reconnecting... (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`
            );
            reconnectTimeoutRef.current = setTimeout(connect, RECONNECT_DELAY);
          }
        };

        ws.onerror = () => {
          // Error details not available in browser WebSocket API
        };

        wsRef.current = ws;
      } catch (error) {
        console.error('Failed to connect WebSocket:', error);
        setWsConnected(false);
      }
    };

    connect();

    return () => {
      mountedRef.current = false;

      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      setWsConnected(false);
    };
  }, [handleGraphEvent, setWsConnected]);

  return {
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
  };
}
