"""Constants for Hidroelectrica integration."""

DOMAIN = "hidroelectrica"
DEFAULT_UPDATE_INTERVAL = 3600  # 1 hour
MINIMUM_UPDATE_INTERVAL = 300   # 5 minutes

# Config entry keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Portal URLs
PORTAL_BASE = "https://ihidro.ro/portal"
LOGIN_URL = f"{PORTAL_BASE}/"
DASHBOARD_URL = f"{PORTAL_BASE}/Dashboard.aspx"
BILL_DASHBOARD_URL = f"{PORTAL_BASE}/BillDashboard.aspx"
BILLING_HISTORY_URL = f"{PORTAL_BASE}/BillingHistory.aspx"
INDEX_HISTORY_URL = f"{PORTAL_BASE}/IndexHistory.aspx"
SELF_METER_URL = f"{PORTAL_BASE}/SelfMeterReading.aspx"
USAGES_URL = f"{PORTAL_BASE}/Usages.aspx"
COMMON_URL = f"{PORTAL_BASE}/Common.aspx"

# ASP.NET hidden field that carries the CSRF token
CSRF_FIELD_NAME = "ctl00$hdnCSRFToken"
