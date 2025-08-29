import os
import sys
import json
import logging
from pathlib import Path
from logger import logger as custom_logger
from apis import AppDynamics
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

# ─── Configure logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s"
)
log = custom_logger if custom_logger else logging.getLogger(__name__)

# ─── Load Jinja2 templates ─────────────────────────────────────────────────────
template_env = Environment(
    loader=FileSystemLoader(
        searchpath=Path(__file__).parent.parent / "templates"
    ),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    lstrip_blocks=True,
    trim_blocks=True,
)

# ─── Environment variables ─────────────────────────────────────────────────────
appd_env               = os.getenv("APPD_ENV", "").strip()
BusinessName           = os.getenv("BusinessName", "").strip().upper()
ApplicationName        = os.getenv("ApplicationName", "").strip()
appd_tier              = os.getenv("APPD_TIER", "").strip()
email_list             = os.getenv("USER_EMAIL", "").strip()
user_email             = [e.strip() for e in email_list.split(",") if e.strip()]
account_name           = os.getenv("APPD_CON", "").strip()
secrets_file_path      = os.getenv("SECRETS_PATH", "").strip()
critical_value         = os.getenv("CRITICAL_VALUE", "").strip() or None
warning_value          = os.getenv("WARNING_VALUE", "").strip() or None
update_flag            = os.getenv("UPDATE", "").strip().lower() == "true"
healthrule_name        = os.getenv("HEALTHRULE_NAME", "").strip()
monitoring             = os.getenv("Synthetic", "").strip().lower()
create_healthrule_flag = os.getenv("CREATE_HEALTHRULE", "").strip().lower() == "true"

# ─── Helpers ───────────────────────────────────────────────────────────────────

def get_secrets(account_name: str):
    """Reads CLIENT_ID and SECRET from the secrets file."""
    key = account_name.upper().replace("-", "_")
    with open(secrets_file_path, "r") as f:
        data = json.load(f)
    return data.get(f"{key}_CLIENT_ID"), data.get(f"{key}_SECRET")

def load_config():
    """Loads config.json from the project root."""
    try:
        with open("config.json", "r") as f:
            cfg = json.load(f)
            log.info("Loaded config.json successfully")
            return cfg
    except FileNotFoundError:
        log.error("config.json not found in %s", os.getcwd())
    except json.JSONDecodeError as err:
        log.error("Malformed config.json: %s", err)
    sys.exit(1)

def render_template_json(template_name, params):
    """Renders Jinja2 template to a Python dict."""
    try:
        raw = template_env.get_template(template_name).render(params)
        return json.loads(raw)
    except TemplateNotFound as e:
        log.error("Template not found: %s", e)
        sys.exit(1)

def select_healthrule_templates(config, tier_type, monitoring):
    if monitoring == "synthetic":
        return config["synthetic_healthrules"]
    if tier_type == "Application Server":
        return config["jvm_healthrules"]
    if tier_type == ".NET Application Server":
        return config["clr_healthrules"]
    return config["base_healthrules"]

# ─── Core Actions ─────────────────────────────────────────────────────────────

def create_healthrules(appd, appd_id, config, tier_type, monitoring, params):
    """
    Create or confirm health rules. Returns list of created/existing names.
    """
    templates = select_healthrule_templates(config, tier_type, monitoring)
    payloads = [render_template_json(t, params) for t in templates]
    results = appd.create_health_rules(appd_id, payloads)

    hr_names = []
    for r in results:
        if r.get("success") and r.get("data", {}).get("name"):
            name = r["data"]["name"]
            log.info("Health rule '%s' created or already existed", name)
            hr_names.append(name)
        else:
            msg = r.get("message") or r.get("error")
            log.warning("Health rule failed: %s", msg)

    return hr_names

def create_actions(appd, appd_id, config, params):
    """
    Create base actions. Logs successes and duplicates.
    """
    for tmpl in config["base_actions"]:
        payload = render_template_json(tmpl, params)
        res = appd.post_appd_action(appd_id, payload)
        if res.get("success") and res.get("data", {}).get("name"):
            log.info("Action '%s' created or already existed", res["data"]["name"])
        else:
            msg = res.get("message") or res.get("error")
            log.warning("Action failed: %s", msg)


def _invoke_dynamic_policies(appd, appd_id, config, tier_type, monitoring, params):
    """
    1) Ensures health rules exist & collects their names
    2) Renders each policy with that name list injected
    3) Posts the policy
    """
    # 1) Create/confirm health rules & get their names
    params["healthrule_names"] = create_healthrules(appd, appd_id, config, tier_type, monitoring, params)
    log.info("Using health rules: %s", params["healthrule_names"])

    # 2) Render & post each policy
    for tmpl in config.get("policies", []):
        policy = render_template_json(tmpl, params)
        res = appd.create_policy_with_dynamic_healthrules(appd_id, policy)
        name = policy.get("name", "<unknown>")
        if res.get("success"):
            log.info("Policy '%s' created or updated", name)
        else:
            msg = res.get("message") or res.get("error")
            log.warning("Policy '%s' failed: %s", name, msg)


# ─── Main Flow ────────────────────────────────────────────────────────────────

def main():
    # 1) Load config & secrets
    config = load_config()
    client_id, client_secret = get_secrets(account_name)

    # 2) Instantiate client & resolve IDs
    appd = AppDynamics(appd_env, client_id, account_name, client_secret)
    appd_id = appd.get_appID(ApplicationName)

    # 3) Determine tier_type for non-synthetic runs
    tier_type = None
    if monitoring != "synthetic" and not update_flag:
        if not appd_tier:
            log.error("APPD_TIER is required for this operation.")
            sys.exit(1)
        tiers = appd.get_appd_tier(appd_id, appd_tier)
        if not tiers:
            log.error("Tier '%s' not found in app %s", appd_tier, ApplicationName)
            sys.exit(1)
        tier_type = tiers[0]["type"]

        # 4) Build template params
    params = {
        "appd_env":        appd_env,
        "BusinessName":    BusinessName,
        "ApplicationName": ApplicationName,
        "appd_tier":       appd_tier,
        "user_email":      user_email,
        "critical_value":  critical_value,
        "warning_value":   warning_value,
        "update":          update_flag,
        "healthrule_name": healthrule_name,
    }

    # 5) Onboarding vs. update
    try:
        if monitoring == "synthetic" or tier_type in config.get("supported_tier_types", []):
            # Actions + Policies (health rules handled inside _invoke_dynamic_policies)
            create_actions(appd, appd_id, config, params)
            _invoke_dynamic_policies(appd, appd_id, config, tier_type, monitoring, params)
        else:
            log.warning("Skipping unsupported tier type: %s", tier_type)
    except Exception as e:
        log.error("Onboarding error: %s", e)
        return 1
    
    # 6) Threshold update path
    if update_flag and healthrule_name:
        res = appd.update_health_rule_thresholds(
            appd_id,
            healthrule_name,
            critical_value,
            warning_value
        )
        if res.get("success"):
            log.info(res["message"])
        else:
            log.warning(res.get("message") or res.get("error"))

    # 7) One-off health-rule creation
    elif create_healthrule_flag:
        if not appd_tier:
            log.error("APPD_TIER is required for one-off creation.")
            return 1
        params["healthrule_names"] = create_healthrules(appd, appd_id, config, tier_type, monitoring, params)

    return 0



# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    banner = (
        f"Updating '{healthrule_name}' thresholds..."
        if update_flag else
        "Onboarding synthetic health rules/actions/policies..."
        if monitoring == "synthetic" else
        f"Onboarding {appd_tier} ({monitoring}) for {ApplicationName}"
    )
    print(banner, "\n")
    sys.exit(main())
