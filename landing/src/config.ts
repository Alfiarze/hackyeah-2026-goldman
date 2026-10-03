// Where "Open the dashboard" links point. Same host as the gateway by default;
// set PUBLIC_DASHBOARD_URL at build time when the landing page is hosted separately.
const raw = import.meta.env.PUBLIC_DASHBOARD_URL || "/dashboard/";
export const dashboardUrl = raw.endsWith("/") ? raw : `${raw}/`;
