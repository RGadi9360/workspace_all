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
            name = payload.get("name")

            # ✅ Treat 409 Conflict (already exists) as success for health rules
            if resp.status_code == 409 and endpoint == "health-rules":
                log.info(
                    f"{entity_name.title()} '{name}' already exists for {appd_id}; treating as success."
                )
                return {"success": True, "data": {"name": name}, "status": 409}

            # ✅ Expected 201 Created on normal success
            if resp.status_code == 201:
                log.info(
                    f"Successfully created {entity_name} '{name}' for {appd_id} "
                    f"(Status: {resp.status_code})"
                )
                # Some AppD endpoints return empty body on success → fallback to payload
                try:
                    data = resp.json()
                except ValueError:
                    data = {"name": name}
                return {"success": True, "data": data, "status": resp.status_code}

            # ❌ Any other unexpected code
            try:
                msg = resp.json().get("message", resp.text)
            except ValueError:
                msg = resp.text
            log.warning(
                f"Failed to create {entity_name} '{name}' for {appd_id}: "
                f"{msg} (Status: {resp.status_code})"
            )
            return {
                "success": False,
                "status": resp.status_code,
                "message": msg,
                "data": {"name": name},
            }
    
        except Exception as e:
            log.exception(
                f"Exception while creating {entity_name} for {appd_id}"
            )
            return {"success": False, "error": str(e), "data": {"name": payload.get("name")}}


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

    def create_policy_with_dynamic_healthrules(self, appd_id, policy_payload):
        """
        Posts the given policy with already-injected healthRule names.
        Assumes health rules were created earlier in the flow.
        """
        try:
            scope = policy_payload["events"]["healthRuleEvents"]["healthRuleScope"]
            if scope.get("healthRuleScopeType") == "SPECIFIC_HEALTH_RULES":
                if not scope.get("healthRules"):
                    log.warning("Policy has SPECIFIC_HEALTH_RULES but no healthRules provided.")
            return self.post_appd_policy(appd_id, policy_payload)
        except Exception as e:
            log.exception(f"Error creating policy for app {appd_id}")
            return {"success": False, "error": str(e)}

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
