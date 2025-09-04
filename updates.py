import os
from sys import exit
from pathlib import Path
from jinja2.exceptions import TemplateNotFound
import json
import urllib.parse
from logger import logger
from apis import AppDynamics
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound
from pathlib import Path
from copy import deepcopy

log = logger

# Load all available Jinja2 templates to be called for later rendering
template_env = Environment(
    loader=FileSystemLoader(
        searchpath=Path(__file__).parent.parent.joinpath("templates"),
    ),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    lstrip_blocks=True,
    trim_blocks=True,
)

# Fetch and trim environment variables
appd_env = os.getenv("APP_ENV", "").strip()
BusinessName = os.getenv("BusinessName", "").strip()
ApplicationName = os.getenv("ApplicationName", "").strip()
appd_tier = os.getenv("APPD_TIER", "").strip()
email_list = os.getenv("USER_EMAIL", "").strip()
user_email = [email.strip() for email in email_list.split(",") if email.strip()]
account_name = os.getenv("APPD_CON", "").strip()
secrets_file_path = os.getenv("SECRETS_PATH", "").strip()
critical_value = os.getenv("CRITICAL_VALUE", "").strip()
warning_value = os.getenv("WARNING_VALUE", "").strip()
update_flag = os.getenv("UPDATE", "").strip().lower() == "true"
healthrule_name = os.getenv("HEALTHRULE_NAME", "").strip()

# load secrets

def get_secrets(account_name: str):
    account_name_upper = account_name.upper()
    formatted_account_name = account_name_upper.replace('-', '_')
    print(secrets_file_path)

    with open(secrets_file_path, 'r') as file:
        secrets = json.load(file)
    client_id = secrets.get(f"{formatted_account_name}_CLIENT_ID")
    client_secret = secrets.get(f"{formatted_account_name}_SECRET")
    
    return client_id, client_secret

# Load local config
def load_config():
    """
    Scans the local repositories for config.json file and loads it as
    a dictionary.
    """
    config = {}
    # Attempt to load the config.json from the local repository.
    try:
        with open("config.json", "r") as jsonfile:
            config = json.load(jsonfile)
            print("Load config successful\n")
            return config

    except FileNotFoundError:
        print(os.getcwd())
        print("Could not find config.json in project root")

    except json.JSONDecodeError as error:
        print("Corrupted or Malformed JSON in config")
        print(error)

def render_template_json(template, params):
    """
    Accepts a template filename and parameters to pass to the template
    when rendering. Produces a rendered template as a string.
    
    """
    try:
        appd_obj = template_env.get_template(template).render(params)
        appd_obj_json = json.loads(appd_obj)
        json_string = json.dumps(appd_obj_json, indent=2)
        return json_string

    except TemplateNotFound as e:
        exit(f"{e.__class__.__name__} : templates/{e}")

def get_delete_policy_names():
    policy_names = []

    policy_params = deepcopy(params)
    policy_params["healthrules"] = ["dummy_name"]  ## Dummy healthrule names to render policy

    if tier_type == "Application Server":        
        # Create Linux specific policies
        for i in config["jvm_policy"]:
            try:
                linux_policy_json = render_template_json(i, policy_params)
                policy_names.append(json.loads(linux_policy_json).get("name").strip())
            except Exception as e:
                log.warning(f"Failed to render template jvm_policy for {appd_tier}: {e}")
                continue  # Skip to next action
    
    elif tier_type == ".NET Application Server":
        # Create Windows specific policies
        for i in config["clr_policy"]:
            try:
                windows_policy_json = render_template_json(i, policy_params)
                policy_names.append(json.loads(windows_policy_json).get("name").strip())
            except Exception as e:
                log.warning(f"Failed to render template jvm_policy for {appd_tier}: {e}")
                continue  # Skip to next action

    else:
        # Create Base Policies
        for i in config["base_policies"]:
            base_policy_json = render_template_json(i, policy_params)
            policy_names.append(json.loads(base_policy_json).get("name").strip())

    log.info(f"Policies to be deleted: {', '.join(policy_names)}")
    return policy_names

def delete_policies():
    log.info("------------------------\n")
    log.info("Starting policy deletion...\n")

    policy_names = get_delete_policy_names()

    policy_ids = appd.get_appd_policy_ids(appd_id, policy_names)

    for policy_id in policy_ids:
        try:
            log.info(f"Deleting policy ID {policy_id} for {appd_tier}...")
            appd.delete_appd_policy(appd_id, policy_id)
            log.info(f"Successfully deleted policy ID {policy_id} for {appd_tier}...!")
        except Exception as e:
            log.error(f"Failed to delete policy ID {policy_id} for {appd_tier}: {str(e)}")
            continue

def get_delete_action_names():
    action_names = []

    for i in config["base_actions"]:
        base_action_json = render_template_json(i, params)
        action_names.append(json.loads(base_action_json).get("name").strip())

    log.info(f"Actions to be deleted: {', '.join(action_names)}")
    return action_names

def delete_actions():
    log.info("------------------------\n")
    log.info("Starting action deletion...\n")

    action_names = get_delete_action_names()

    action_ids = appd.get_appd_action_ids(appd_id, action_names)

    for action_id in action_ids:
        try:
            log.info(f"Deleting action ID {action_id} for {appd_tier}...")
            appd.delete_appd_action(appd_id, action_id)
            log.info(f"Successfully deleted action ID {action_id} for {appd_tier}...!")
        except Exception as e:
            log.error(f"Failed to delete action ID {action_id} for {appd_tier}: {str(e)}")
            continue
    
def get_delete_healthrule_names():   
    healthrule_names = []

    if tier_type == "Application Server":
        # Create JVM specific health rules
        for i in config["jvm_healthrules"]:
            jvmhr_json = render_template_json(i, params)
            healthrule_names.append(json.loads(jvmhr_json).get("name").strip())

    elif tier_type == ".NET Application Server":
        # Create Dot net specific health rules
        for i in config["clr_healthrules"]:
            clrhr_json = render_template_json(i, params)
            healthrule_names.append(json.loads(clrhr_json).get("name").strip())

    else:
        # Create Base Health rules
        for i in config["base_healthrules"]:
            hr_json = render_template_json(i, params)
            healthrule_names.append(json.loads(hr_json).get("name").strip())

    log.info(f"Health rules to be deleted: {', '.join(healthrule_names)}")
    return healthrule_names

def delete_healthrules():
    log.info("------------------------\n")
    log.info("Starting health rule deletion...\n")

    healthrule_names = get_delete_healthrule_names()

    healthrule_ids = appd.get_appd_hr_ids(appd_id, healthrule_names)

    for hr_id in healthrule_ids:
        try:
            log.info(f"Deleting health rule ID {hr_id} for {appd_tier}...")
            appd.delete_appd_hr(appd_id, hr_id)
            log.info(f"Successfully deleted health rule ID {hr_id} for {appd_tier}...!")
        except Exception as e:
            log.error(f"Failed to delete health rule ID {hr_id} for {appd_tier}: {str(e)}")
            continue

def main():
    """AppDynamics HR Generator"""

    log.info("################################")
    log.info("##   AppDynamics Onboarder    ##")
    log.info("################################\n")


    if params["update"] and params["healthrule_name"]:
        result = appd.update_health_rule_thresholds(
            appd_id,
            params["healthrule_name"],
            params["critical_value"],
            params["warning_value"]
        )
        if result["success"]:
            log.info(result["message"])
        else:
            log.warning(result.get("message", result.get("error", "Unknown error")))

    # Exit gracefully.
    exit(0)

# Parameters dictionary to pass to templates
client_id, client_secret = get_secrets(account_name)
params = {
    "appd_env": appd_env,
    "BusinessName": BusinessName,
    "ApplicationName": ApplicationName,
    "appd_tier": appd_tier,
    "user_email": user_email,
    "client_id": client_id,
    "account_name": account_name,
    "client_secret": client_secret,
    "critical_value": critical_value if critical_value else None,
    "warning_value": warning_value if warning_value else None,
    "update": update_flag,
    "healthrule_name": healthrule_name
}
appd = AppDynamics(
    params["appd_env"],
    params["client_id"],
    params["account_name"],
    params["client_secret"]
)
#appd = AppDynamics(params['appd_env'], params['client_id'], params['account_name'], params['client_secret'] )
appd_id = appd.get_appID(params['ApplicationName'])
tier_type = appd.get_appd_tier(appd_id, params['appd_tier'])[0]["type"]
config = load_config()

if __name__ == "__main__":
    main()
