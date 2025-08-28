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


def _invoke_dynamic_policies(self, appd_id, policy_payload, hr_payloads):
    """
    Create health rules, dedupe their names, inject into the policy payload,
    then create the policy in AppDynamics.
    """

    # 1. Create or reuse health rules
    hr_results = self.api.create_health_rules(appd_id, hr_payloads)

    # 2. Collect names of all successfully created/existing health rules
    healthrule_names = [
        r["data"]["name"] for r in hr_results
        if r.get("success") and r.get("data", {}).get("name")
    ]

    # 3. Remove duplicates while preserving order
    seen = set()
    unique_healthrule_names = []
    for name in healthrule_names:
        if name not in seen:
            seen.add(name)
            unique_healthrule_names.append(name)

    # 4. Inject health rules into the policy payload
    policy_payload["healthRuleNames"] = unique_healthrule_names

    # 5. Create the policy
    log.info(f"Creating policy for AppD ID: {appd_id} with {len(unique_healthrule_names)} health rules")
    policy_result = self.api.post_appd_policy(appd_id, policy_payload)

    if not policy_result.get("success"):
        log.error(f"Policy creation failed: {policy_result.get('message') or policy_result.get('error')}")

    return policy_result

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
=========================
apis.py

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
=========================

main.py

create_healthrules() now returns a list of names.

_invoke_dynamic_policies() is the single place that creates HRs + injects them into policies.

No duplicate HR creation in apis.py.

apis.py

create_policy_with_dynamic_healthrules() only posts the policy.

It no longer recreates health rules.

policy.j2

Already set up to take healthrule_names from params
