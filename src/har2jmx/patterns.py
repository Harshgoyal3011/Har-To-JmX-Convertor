from __future__ import annotations

import re

TOKEN_NAME_RE = re.compile(
    r"(?:csrf|xsrf|token|auth|session|sid|nonce|state|request.?id|trace.?id|jwt|bearer|access(?:_|-)?token|refresh(?:_|-)?token|saml|oauth|viewstate|eventvalidation|relaystate|requestverificationtoken|authenticity_token|security_token|id_token|idtoken|client_id|tenant_id|application_id|applicationid|subscription_id|device_id|verification_token)",
    re.IGNORECASE,
)
USER_DATA_RE = re.compile(
    r"(?:username|user|email|password|pass|phone|mobile|customer|client|account|order|reference|transaction|invoice|ticket|id|name|city|country|zip|postal|address|date|dob|ssn"
    r"|aadhaar|passport|branch|policy|claim|pincode|pan[_-]?(?:number|no|card)"
    r"|query|search|keyword|term|criteria|filter"
    # free-text user input — the actual thing a user types: a prompt, a message, a review. For a GenAI
    # or content app this is THE variable to vary per user (same prompt x250 tests nothing real).
    r"|content|prompt|message|comment|description|note|question|review|caption|feedback|subject)",
    re.IGNORECASE,
)
TOKEN_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-+/=.]{16,}$")
# Pagination / continuation handles: opaque server state that points at the *next* page. A recorded
# cursor is valid only for that dataset snapshot, so it can never be parameterized — it must be
# re-extracted from each page's response and fed to the next request. Matched on the producing field.
PAGINATION_TOKEN_RE = re.compile(
    r"(?:^|[_.\-])?(?:next(?:_?(?:cursor|page(?:_?token)?|link|url|offset|marker|key))?|"
    r"cursor|continuation(?:_?token)?|page_?token|scroll_?id|marker|bookmark|start_?key)$",
    re.IGNORECASE,
)
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HIDDEN_INPUT_RE = re.compile(
    r'<input[^>]+type=["\']hidden["\'][^>]+name=["\'](?P<name>[^"\']+)["\'][^>]+value=["\'](?P<value>[^"\']*)["\']',
    re.IGNORECASE,
)
AUTHORIZATION_BEARER_RE = re.compile(r"Bearer\s+(?P<token>[A-Za-z0-9\-_.=]+)", re.IGNORECASE)
JSON_PAIR_RE = re.compile(
    r'"(?P<name>[A-Za-z0-9_.:-]*(?:csrf|xsrf|token|auth|session|sid|nonce|state|requestId|traceId|access_token|refresh_token|jwt|saml|viewState|eventValidation|relayState|requestVerificationToken|clientId|tenantId|applicationId)[A-Za-z0-9_.:-]*)"\s*:\s*"(?P<value>[^"]{8,})"',
    re.IGNORECASE,
)
HTML_INPUT_RE = re.compile(
    r'<input[^>]+name=["\'](?P<name>[^"\']*(?:csrf|xsrf|token|auth|session|sid|nonce|state|viewstate|eventvalidation|relaystate|requestverificationtoken)[^"\']*)["\'][^>]+value=["\'](?P<value>[^"\']{4,})["\']',
    re.IGNORECASE,
)
ID_FIELD_RE = re.compile(r"(?:^id$|_id$|[a-z]Id$|ID$)")
CLASSIFICATION_LABELS = {
    "A": "Business Input",
    "B": "Runtime Object Identifier",
    "C": "Session Identifier",
    "D": "Security Identifier",
    "E": "Temporary Identifier",
    "F": "Static Constant",
}
PATH_ID_RE = re.compile(r"^(?:[0-9]{5,}|[0-9a-fA-F]{8,})$")
EMAIL_VALUE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_VALUE_RE = re.compile(r"^\+?[0-9][0-9\-\s()]{7,14}[0-9]$")
GRAPHQL_OPERATION_RE = re.compile(r'"operationName"\s*:\s*"(?P<name>[^"]+)"')
ENTERPRISE_APP_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"force\.com|salesforce\.com|lightning\.force", re.IGNORECASE), "Salesforce"),
    (re.compile(r"successfactors|sap\.com|hana\.ondemand|s4hana", re.IGNORECASE), "SAP"),
    (re.compile(r"guidewire|gw-policycenter|gw-billingcenter|gw-claimcenter", re.IGNORECASE), "Guidewire"),
    (re.compile(r"service-now\.com|servicenow", re.IGNORECASE), "ServiceNow"),
    (re.compile(r"sharepoint|\.sharepoint\.com", re.IGNORECASE), "SharePoint"),
    (re.compile(r"dynamics\.com|crm\.dynamics", re.IGNORECASE), "Microsoft Dynamics"),
    (re.compile(r"oraclecloud|oracle\.com", re.IGNORECASE), "Oracle"),
    (re.compile(r"myworkday|workday\.com", re.IGNORECASE), "Workday"),
    (re.compile(r"okta\.com", re.IGNORECASE), "Okta (Auth)"),
    (re.compile(r"auth0\.com", re.IGNORECASE), "Auth0 (Auth)"),
    (re.compile(r"login\.microsoftonline\.com|graph\.microsoft\.com", re.IGNORECASE), "Microsoft Entra / Azure AD"),
]
STATIC_RESOURCE_TYPES = {"stylesheet", "script", "image", "font", "media", "manifest", "other"}
STATIC_EXTENSIONS = {
    ".css", ".js", ".mjs", ".map", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".webm", ".mp3", ".wav", ".avi",
    ".pdf", ".zip", ".gz", ".br",
}
STATIC_PATH_RE = re.compile(r"/(?:static|assets|asset|content|css|js|scripts|fonts|images|img|media|vendor|dist|build)/", re.IGNORECASE)
API_PATH_RE = re.compile(r"/(?:api|rest|graphql|oauth|auth|login|logout|session|token|saml|openid)(?:/|$)", re.IGNORECASE)
NOISE_HOST_RE = re.compile(
    r"(google-analytics|googletagmanager|doubleclick|hotjar|segment|mixpanel|newrelic|datadog|"
    r"clarity|facebook|linkedin|fonts\.googleapis|fonts\.gstatic)",
    re.IGNORECASE,
)
NOISE_PATH_RE = re.compile(r"/(?:collect|analytics|telemetry|metrics|beacon|favicon|css2)(?:/|$|\?)", re.IGNORECASE)

BUSINESS_TRANSACTION_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"/(auth|login|signin|sign-in|logon|authenticate|sso|saml|oauth|openid|authorize)(/|$|\?)", re.IGNORECASE), "Login"),
    (re.compile(r"/token(/|$|\?)", re.IGNORECASE), "Login"),
    (re.compile(r"/(logout|signout|sign-out|logoff|log-off)(/|$|\?)", re.IGNORECASE), "Logout"),
    (re.compile(r"/(csrf|xsrf|anti-?forgery|nonce)(/|$|\?)", re.IGNORECASE), "Login"),
    (re.compile(r"/(dashboard|home|landing|portal|welcome|main)(/|$|\?)", re.IGNORECASE), "Open Dashboard"),
    (re.compile(r"/(customer|client|contact|person|individual).*(creat|new|add|register|open)", re.IGNORECASE), "Create Customer"),
    (re.compile(r"/(customer|client|contact).*(search|find|lookup|query|list)", re.IGNORECASE), "Search Customer"),
    (re.compile(r"/(customer|client|contact|account)(/|$|\?)", re.IGNORECASE), "Open Customer"),
    (re.compile(r"/(policy|polic).*(creat|new|add|submit|bind|issue|quot)", re.IGNORECASE), "Create Policy"),
    (re.compile(r"/(policy|polic).*(search|find|lookup|query|list)", re.IGNORECASE), "Search Policy"),
    (re.compile(r"/(policy|polic|coverage|endorsement|renewal|cancell)(/|$|\?)", re.IGNORECASE), "Open Policy"),
    (re.compile(r"/(claim|loss|fnol).*(creat|new|add|submit|file|open|report)", re.IGNORECASE), "Submit Claim"),
    (re.compile(r"/(claim|loss).*(search|find|lookup|query|list)", re.IGNORECASE), "Search Claims"),
    (re.compile(r"/(claim|loss|adjuster|reserve|settlement)(/|$|\?)", re.IGNORECASE), "Open Claim"),
    (re.compile(r"/(payment|pay|billing|invoice|charge|checkout|confirm)(/|$|\?)", re.IGNORECASE), "Payment"),
    (re.compile(r"/(cart|basket|bag)(/|$|\?)", re.IGNORECASE), "View Cart"),
    (re.compile(r"/(order|purchase).*(creat|new|submit|place|confirm)", re.IGNORECASE), "Place Order"),
    (re.compile(r"/(order|purchase)(/|$|\?)", re.IGNORECASE), "View Orders"),
    (re.compile(r"/(product|catalog|item|sku).*(search|find|lookup|list)", re.IGNORECASE), "Search Products"),
    (re.compile(r"/(product|catalog|item|sku)(/|$|\?)", re.IGNORECASE), "View Product"),
    (re.compile(r"/(upload|document|file|attach)(/|$|\?)", re.IGNORECASE), "Upload Document"),
    (re.compile(r"/(report|export|download|print|pdf|excel)(/|$|\?)", re.IGNORECASE), "Generate Report"),
    (re.compile(r"/graphql(/|$|\?)", re.IGNORECASE), "GraphQL"),
    (re.compile(r"/(search|find|query|lookup)(/|$|\?)", re.IGNORECASE), "Search"),
    (re.compile(r"/(user|profile|setting|preference|my-?account)(/|$|\?)", re.IGNORECASE), "User Settings"),
]

_ACTION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_ACTION_PATH_RE = re.compile(
    r"/(search|find|create|submit|save|update|delete|add|remove|place|confirm|pay|upload|generate|export)",
    re.IGNORECASE,
)
_SPA_GAP_MS = 4000

CREATION_VERB_RE = re.compile(
    r"/(creat|submit|regist|enroll|apply|bind|issu|checkout|confirm|generat|place)",
    re.IGNORECASE,
)
EXISTING_ENTITY_VERB_RE = re.compile(
    r"/(search|list|browse|find|lookup|quer|catalog|products?|items?|customers?|"
    r"employees?|polic(?:y|ies)|accounts?|vehicles?|stores?|branch(?:es)?|documents?|assets?|"
    r"carts?)(?:/|$|\?)",
    re.IGNORECASE,
)

CONSTANT_FIELD_RE = re.compile(r"password|pass\b|pwd|pin\b", re.IGNORECASE)
TRAILING_DIGITS_RE = re.compile(r"^(?P<prefix>.*?)(?P<digits>\d+)$")
EMAIL_SPLIT_RE = re.compile(r"^(?P<local>[^@]+)@(?P<domain>.+)$")
DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m-%d-%Y", "%m/%d/%Y",
    "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y", "%d %b %Y",
)
ENTITY_NAME_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"username|password|\buser\b|login", re.IGNORECASE), "users"),
    (re.compile(r"customer", re.IGNORECASE), "customers"),
    (re.compile(r"policy", re.IGNORECASE), "policies"),
    (re.compile(r"claim", re.IGNORECASE), "claims"),
    (re.compile(r"product", re.IGNORECASE), "products"),
    (re.compile(r"order", re.IGNORECASE), "orders"),
    (re.compile(r"account", re.IGNORECASE), "accounts"),
    (re.compile(r"employee", re.IGNORECASE), "employees"),
    (re.compile(r"invoice", re.IGNORECASE), "invoices"),
    (re.compile(r"address|city|country|zip|postal|pincode", re.IGNORECASE), "addresses"),
    (re.compile(r"search|query|keyword", re.IGNORECASE), "search_terms"),
]

GENERIC_ID_FIELD_NAMES = {"id", "code", "number", "key", "uuid", "guid", "identifier", "ref", "reference"}
NOUN_STOPWORDS = {
    "api", "v1", "v2", "v3", "v4", "search", "create", "new", "add", "update", "edit",
    "delete", "remove", "list", "get", "find", "submit", "save", "confirm", "details",
    "detail", "info", "view", "index", "action", "do", "results", "result",
}
WRAPPER_KEY_STOPWORDS = {
    "results", "result", "items", "item", "data", "records", "record", "list",
    "entries", "entry", "rows", "row", "content", "payload", "response", "body",
}
TRANSACTION_VERB_STOPWORDS = {
    "search", "create", "submit", "view", "open", "edit", "update", "delete", "get",
    "list", "add", "place", "new", "find", "confirm", "generate", "upload", "login",
    "logout", "management", "manage",
}

_PATH_SEGMENT_ID_RE = re.compile(r"^[0-9a-fA-F\-]{6,}$")
_TRANSACTION_WORD_RE = re.compile(r"[A-Za-z]+")
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_SIMPLE_ID_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]{0,40}$")

EXTRACTOR_LABELS = {
    "json": "JSON Extractor (response body is JSON)",
    "css": "CSS Selector (value sourced from an HTML form field; resilient to markup/attribute-order changes)",
    "regex": "Regex Extractor (fallback strategy - no structured extractor applied to this source)",
}
