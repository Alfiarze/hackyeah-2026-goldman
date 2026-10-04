// Line icons for the navigation, drawn on a 24px grid with one stroke weight.
import React from "react";

const P = {
  start: <><path d="M12 3l2.6 5.6L20 12l-5.4 3.4L12 21l-2.6-5.6L4 12l5.4-3.4z" /><circle cx="12" cy="12" r="1.6" /></>,
  playground: <><path d="M9 3h6" /><path d="M10 3v6.2L4.6 18.4A1.7 1.7 0 0 0 6.1 21h11.8a1.7 1.7 0 0 0 1.5-2.6L14 9.2V3" /><path d="M7.2 15h9.6" /></>,
  scenarios: <><circle cx="12" cy="12" r="9" /><path d="M10 8.5v7l5.5-3.5z" /></>,
  agent: <><rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 4v4" /><circle cx="12" cy="3.5" r="1" /><circle cx="9.5" cy="13" r="1" /><circle cx="14.5" cy="13" r="1" /><path d="M9.5 16.5h5" /></>,
  livechat: <><path d="M4 5h16v11H9l-5 4z" /><path d="M8 9h8M8 12h5" /></>,
  live: <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />,
  audit: <><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4" /><path d="M9 11h7M9 14.5h7M9 18h4" /></>,
  tasks: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V3h6v1" /><path d="M8.5 11l1.7 1.7L13.5 9.5" /><path d="M8.5 16.5h7" /></>,
  budget: <><path d="M4 18a8 8 0 1 1 16 0" /><path d="M12 18l4-5.5" /><circle cx="12" cy="18" r="1.3" /></>,
  controls: <><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></>,
  policy: <><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4" /><path d="M10 12l-2 2 2 2M14 12l2 2-2 2" /></>,
  signatures: <><path d="M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6z" /><path d="M12 8v4.5" /><circle cx="12" cy="15.8" r="0.4" /></>,
  tools: <><path d="M9 3v5M15 3v5" /><path d="M6.5 8h11v3a5.5 5.5 0 0 1-11 0z" /><path d="M12 16.5V21" /></>,
  approvals: <><circle cx="12" cy="8" r="4" /><path d="M5 21a7 7 0 0 1 14 0" /><path d="M15.5 14.5l2 2 3.5-3.5" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5" /><circle cx="12" cy="7.8" r="0.5" /></>,
  download: <><path d="M12 4v11M7 10.5l5 5 5-5" /><path d="M5 20h14" /></>,
  key: <><circle cx="8" cy="14" r="4" /><path d="M11 11l8-8M16 6l2.5 2.5" /></>,
  clip: <path d="M20 11.5l-7.8 7.8a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8" />,
};

export default function Icon({ name, size = 20, className = "" }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{P[name]}</svg>
  );
}
