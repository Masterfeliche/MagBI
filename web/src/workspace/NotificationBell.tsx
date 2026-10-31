/** The bell in the top bar: alerts that fired, newest first. */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { sharing, type AppNotification } from "../shared/sharing";

const POLL_MS = 60_000;

export function NotificationBell() {
  const navigate = useNavigate();
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  function load() {
    sharing
      .notifications()
      .then((body) => {
        setItems(body.items);
        setUnread(body.unread);
      })
      .catch(() => undefined);
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  async function readAll() {
    await sharing.markRead().catch(() => undefined);
    load();
  }

  async function follow(item: AppNotification) {
    if (!item.read) await sharing.markRead([item.id]).catch(() => undefined);
    setOpen(false);
    load();
    if (item.link) navigate(item.link);
  }

  return (
    <div className="bell" ref={box}>
      <button
        type="button"
        className="bell-button"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path fill="currentColor" d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22zm7-6V11a7 7 0 0 0-5.5-6.84V3a1.5 1.5 0 0 0-3 0v1.16A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2z" />
        </svg>
        {unread > 0 && <span className="bell-count">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="bell-head">
            <strong>Notifications</strong>
            {unread > 0 && <button type="button" className="ws-link" onClick={() => void readAll()}>Mark all read</button>}
          </div>
          {items.length === 0 ? (
            <p className="ws-muted bell-empty">Nothing yet. Set an alert on a card from a report's Alerts button.</p>
          ) : (
            <ul className="bell-list">
              {items.map((item) => (
                <li key={item.id}>
                  <button type="button" className={item.read ? "bell-item" : "bell-item unread"} onClick={() => void follow(item)}>
                    <span className="bell-title">{item.title}</span>
                    <span className="bell-body">{item.body}</span>
                    <span className="bell-time">{new Date(item.createdAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
