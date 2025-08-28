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
    Batch-create health rules (idempotent). Logs each created or existing.
    """
    templates = select_healthrule_templates(config, tier_type, monitoring)
    payloads = [render_template_json(t, params) for t in templates]
    results = appd.create_health_rules(appd_id, payloads)

    for r in results:
        if r.get("success") and r.get("data", {}).get("name"):
            name = r["data"]["name"]
            log.info("Health rule '%s' created or already existed", name)
        else:
            msg = r.get("message") or r.get("error")
            log.warning("Health rule failed: %s", msg)

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
    # 1) Create or confirm health rules
    templates = select_healthrule_templates(config, tier_type, monitoring)
    hr_payloads = [render_template_json(t, params) for t in templates]
    hr_results = appd.create_health_rules(appd_id, hr_payloads)

    # 2) Capture names
    params["healthrule_names"] = [
        r["data"]["name"] for r in hr_results
        if r.get("success") and r.get("data", {}).get("name")
    ]
    log.info("Using health rules: %s", params["healthrule_names"])

    # 3) Render & post each policy
    for tmpl in config.get("policies", []):
        policy = render_template_json(tmpl, params)
        res = appd.create_policy_with_dynamic_healthrules(
            appd_id, hr_payloads, policy
        )
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
            create_healthrules(appd, appd_id, config, tier_type, monitoring, params)
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
        paylds = [render_template_json(t, params) for t in config["base_healthrules"]]
        results = appd.create_health_rules(appd_id, paylds)
        for r in results:
            if r.get("success"):
                log.info(r["message"] if r.get("message") else "Health rule created")
            else:
                log.warning(r.get("message") or r.get("error"))

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
=======================================
apis.py

from urllib3.util.retry import Retry
from requests import Session
from requests.adapters import HTTPAdapter
import json
import urllib
import logging

log = logging.getLogger(__name__)

class AppDynamics:
    def __init__(self, env, client_id, account_name, client_secret):
        self.client_id = client_id
        self.env = env
        self.account_name = account_name
        self.client_secret = client_secret
        self.session = Session()
        self.base_url = f"https://{account_name}.saas.appdynamics.com/controller/"
        self.token = self.get_access_token()
        self.session.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.params = {"output": "json"}
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=5,
                    read=5,
                    connect=5,
                    backoff_factor=0.2,
                    allowed_methods=frozenset(["GET", "POST", "PUT"]),
                    status_forcelist=(500, 502, 504, 403),
                )
            ),
        )

    def get_access_token(self):
        try:
            url = f"{self.base_url}api/oauth/access_token"
            payload = {
                "grant_type": "client_credentials",
                "client_id": f"{self.client_id}@{self.account_name}",
                "client_secret": self.client_secret,
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            response = self.session.post(url, data=payload, headers=headers)
            response.raise_for_status()
            return response.json()["access_token"]
        except Exception:
            log.exception("Error retrieving access token")
            raise

    def get_appID(self, ApplicationName):
        try:
            encoded_name = urllib.parse.quote(ApplicationName)
            response = self.session.get(
                f"{self.base_url}rest/applications/{encoded_name}",
                params=self.params,
            )
            response.raise_for_status()
            return response.json()[0]["id"]
        except Exception:
            log.exception(f"Error looking up application ID for {ApplicationName}")
            raise

    def get_appd_nodes(self, appd_id):
        try:
            response = self.session.get(
                f"{self.base_url}rest/applications/{appd_id}/nodes",
                params=self.params,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            log.exception(f"Error retrieving nodes for application ID {appd_id}")
            raise

    def get_appd_tier(self, appd_id, appd_tier):
        try:
            tier = urllib.parse.quote(appd_tier)
            response = self.session.get(
                f"{self.base_url}rest/applications/{appd_id}/tiers/{tier}/",
                params=self.params,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            log.exception(f"Error retrieving tier {appd_tier} for application ID {appd_id}")
            raise


    def _post(self, endpoint, appd_id, payload, entity_name):
        # Guard against bad payloads 
        if isinstance(payload, str):
            log.error(
                f"Invalid payload type (str) passed for {entity_name}. "
                "Expected dict or list."
            )
            return {"success": False, "error": "Payload must be a dict or list"}
    
        # Debug payload
        log.debug(f"Payload type for {entity_name}: {type(payload)}")
        log.debug("POST body preview:\n%s", json.dumps(payload, indent=2))
    
        url = f"{self.base_url}alerting/rest/v1/applications/{appd_id}/{endpoint}"
    
        try:
            resp = self.session.post(url, params=self.params, json=payload)
    
            # Idempotent health-rule creation: 409 = already exists
            if resp.status_code == 409 and endpoint == "health-rules":
                name = payload.get("name")
                log.info(
                    f"{entity_name.title()} '{name}' already exists; "
                    "treating as success"
                )
                return {"success": True, "data": {"name": name}}
    
            # Everything else must be 201 Created
            if resp.status_code != 201:
                try:
                    msg = resp.json().get("message", resp.text)
                except ValueError:
                    msg = resp.text
                log.warning(
                    f"Failed to create {entity_name} for {appd_id}: "
                    f"{msg} (Status: {resp.status_code})"
                )
                return {
                    "success": False,
                    "status": resp.status_code,
                    "message": msg,
                }
    
            # Success branch
            log.info(
                f"Successfully created {entity_name} for {appd_id} "
                f"(Status: {resp.status_code})"
            )
            return {"success": True, "data": resp.json()}
    
        except Exception as e:
            log.exception(
                f"Exception while creating {entity_name} for {appd_id}"
            )
            return {"success": False, "error": str(e)}


    def post_appd_hr(self, appd_id, payload):
        return self._post("health-rules", appd_id, payload, "health rule")

    def post_appd_policy(self, appd_id, payload):
        return self._post("policies", appd_id, payload, "policy")

    def post_appd_action(self, appd_id, payload):
        return self._post("actions", appd_id, payload, "action")

    def create_health_rules(self, appd_id, health_rule_payloads):
        results = []
        for idx, payload in enumerate(health_rule_payloads, start=1):
            log.info(f"Creating health rule {idx}/{len(health_rule_payloads)} for AppD ID: {appd_id}")
            result = self.post_appd_hr(appd_id, payload)
            if not result["success"]:
                log.warning(f"Health rule {idx} failed: {result.get('message') or result.get('error')}")
            results.append(result)
        return results

    def create_policy_with_dynamic_healthrules(self,
                                               appd_id,
                                               health_rule_payloads,
                                               policy_payload):
        """
        1. Create health rules.
        2. Collect their actual 'name' fields from the response.
        3. Inject those names into the policy_payload['events']['healthRuleEvents']['healthRuleScope']['healthRules'].
        4. Post the assembled policy.
        """
        # Step 1: create and collect
        results = self.create_health_rules(appd_id, health_rule_payloads)
        created_names = []
        for r in results:
            if r.get("success") and r.get("data"):
                name = r["data"].get("name")
                if name:
                    created_names.append(name)

        log.info(f"Successfully created health rules: {created_names}")

        # Step 2: inject into policy payload
        scope = policy_payload["events"]["healthRuleEvents"]["healthRuleScope"]
        if scope.get("healthRuleScopeType") == "SPECIFIC_HEALTH_RULES":
            scope["healthRules"] = created_names

        # Step 3: post the combined policy
        return self.post_appd_policy(appd_id, policy_payload)

    def update_health_rule_thresholds(self,
                                      appd_id,
                                      healthrule_name,
                                      critical_value=None,
                                      warning_value=None):
        try:
            # Step 1: fetch all health rules
            url = f"{self.base_url}alerting/rest/v1/applications/{appd_id}/health-rules"
            response = self.session.get(url, params=self.params)
            response.raise_for_status()
            health_rules = response.json()

            # Step 2: locate target
            target = next((hr for hr in health_rules if hr["name"] == healthrule_name), None)
            if not target:
                log.warning(f"Health rule '{healthrule_name}' not found.")
                return {"success": False, "message": "Health rule not found"}

            hr_id = target["id"]

            # Step 3: fetch details and update thresholds
            hr_detail_url = (
                f"{self.base_url}alerting/rest/v1/applications/{appd_id}/health-rules/{hr_id}"
            )
            detail_resp = self.session.get(hr_detail_url, params=self.params)
            detail_resp.raise_for_status()
            hr_data = detail_resp.json()

            eval_criterias = hr_data.get("evalCriterias", {})
            critical_conditions = (eval_criterias.get("criticalCriteria") or {}).get("conditions", [])
            warning_conditions = (eval_criterias.get("warningCriteria") or {}).get("conditions", [])

            # Step 4: guard multi-conditions
            if len(critical_conditions) > 1 or len(warning_conditions) > 1:
                msg = (
                    f"Health rule '{healthrule_name}' has multiple conditions. "
                    "Threshold update skipped."
                )
                log.warning(msg)
                return {"success": False, "message": msg}

            # Step 5: apply new thresholds
            if critical_value is not None and critical_conditions:
                metric = critical_conditions[0]["evalDetail"]["metricEvalDetail"]
                if "compareValue" in metric:
                    old = metric["compareValue"]
                    metric["compareValue"] = float(critical_value)
                    log.info(
                        f"Updated critical threshold from {old} to {critical_value} "
                        f"for '{healthrule_name}'."
                    )

            if warning_value is not None:
                if warning_conditions:
                    metric = warning_conditions[0]["evalDetail"]["metricEvalDetail"]
                    if "compareValue" in metric:
                        old = metric["compareValue"]
                        metric["compareValue"] = float(warning_value)
                        log.info(
                            f"Updated warning threshold from {old} to {warning_value} "
                            f"for '{healthrule_name}'."
                        )
                else:
                    log.info(
                        f"No warning criteria for '{healthrule_name}'. Skipping warning update."
                    )

            # Step 6: PUT update
            put_url = (
                f"{self.base_url}"
                f"alerting/rest/v1/applications/{appd_id}/health-rules/{hr_id}"
            )
            put_resp = self.session.put(put_url, params=self.params, json=hr_data)
            put_resp.raise_for_status()

            log.info(f"Successfully updated thresholds for '{healthrule_name}'")
            return {"success": True, "message": "Thresholds updated"}

        except Exception as e:
            log.exception(f"Error updating health rule '{healthrule_name}'")
            return {"success": False, "error": str(e)}
