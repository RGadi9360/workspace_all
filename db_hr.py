from sys import exit
import json
import requests
import os
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jinja2.exceptions import TemplateNotFound

BASE_PAYLOAD_TEMPLATE = {
    "name": None,  # Placeholder for health_rule_name
    "enabled": "true",
    "useDataFromLastNMinutes": 30,
    "waitTimeAfterViolation": 30,
    "scheduleName": "Always",
    "affects": {
        "affectedEntityType": "DATABASES",
        "databaseType": None,  # Placeholder for database type
        "affectedDatabases": {
            "databaseScope": None  # Placeholder for database scope
        }
    },
    "evalCriterias": {}
}

HEADERS_TEMPLATE = {
    'Authorization': 'Bearer {token}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

PARAMS_TEMPLATE = {
    "business_name": "{{business_name}}",
    "application_name": "{{application_name}}",
    "appd_env": "{{appd_env}}",
    "user_email": "{{user_email}}"
}

TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(
        searchpath=Path(__file__).parent.parent.joinpath("templates"),
    ),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    lstrip_blocks=True,
    trim_blocks=True,
)

def render_template_json(template, params):
    """
    Accepts a template filename and parameters to pass to the template
    when rendering. Produces a rendered template as a string.
    
    """
    try:
        appd_obj = TEMPLATE_ENV.get_template(template).render(params)
        appd_obj_json = json.loads(appd_obj)
        json_string = json.dumps(appd_obj_json, indent=2)
        return json_string

    except TemplateNotFound as e:
        exit(f"{e.__class__.__name__} : templates/{e}")

def post_request(url, headers, payload):
    try:
        response = requests.post(
                url= url,
                headers=headers,
                data=payload,
        )
        print(f"*******71****: {url} {payload}")
        if response.status_code != 201:
            response_text = json.loads(response.text.encode("utf8"))
            print(
                f"Status code {response.status_code} returned, {response_text['message']}\n"
                )
        else:
            print(
                f"Successfully created action, response code: {response.status_code}\n"
                )
            data = response.json()

            return data
    except Exception as e:
        sys.exit(
            f"Error  for {url} : {e}, response status code:{response.status_code} response text:{response.text}\n"
        )

def databases_generator(databases):
    """Generate the specific database list."""
    if databases is None:
        return []

    db_list_raw = list(filter(None, databases.split(",")))

    if len(db_list_raw) <= 0:
        return []

    db_list = [
        {"serverName": database.strip(), "collectorConfigName": database.strip()}
        for database in db_list_raw
    ]

    return db_list


def get_db_calls_per_min(data=None):
    """Template for DB calls per min."""
    new_data = data.copy()
    new_data["name"] += " - DB Calls Per Min"
    new_data["evalCriterias"] = {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "High Number of Connections",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Number of Connections",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "GREATER_THAN_SPECIFIC_VALUE",
                            "compareValue": 200000,
                        },
                    },
                    "triggerEnabled": "true",
                    "minimumTriggers": 15,
                },
                {
                    "name": "Number of Connections above 4 standard deviations of the default baseline",
                    "shortName": "B",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Number of Connections",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "BASELINE_TYPE",
                            "baselineCondition": "GREATER_THAN_BASELINE",
                            "baselineName": "Default Baseline",
                            "compareValue": 4,
                            "baselineUnit": "STANDARD_DEVIATIONS",
                        },
                    },
                    "triggerEnabled": "false",
                    "minimumTriggers": 15,
                },
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    }
    return new_data

def get_db_conn_per_min(data=None):
    """Template for DB connections per min."""
    new_data = data.copy()
    new_data["name"] += " - DB Connections Per Minute"
    new_data["evalCriterias"] = {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "High Number of Connections",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Number of Connections",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "GREATER_THAN_SPECIFIC_VALUE",
                            "compareValue": 30,
                        },
                    },
                    "triggerEnabled": "true",
                    "minimumTriggers": 10,
                },
                {
                    "name": "Number of Connections above 4 standard deviations of the default baseline",
                    "shortName": "B",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Number of Connections",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "BASELINE_TYPE",
                            "baselineCondition": "GREATER_THAN_BASELINE",
                            "baselineName": "Default Baseline",
                            "compareValue": 3,
                            "baselineUnit": "STANDARD_DEVIATIONS",
                        },
                    },
                    "triggerEnabled": "false",
                    "minimumTriggers": 10,
                },
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    }
    return new_data

def get_db_exec_time(data=None):
    """Template for DB time spent in executions."""
    new_data = data.copy()
    new_data["name"] += " - DB Time Spent in Executions"
    new_data["evalCriterias"] = {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "Query Execution Time",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Time Spent in Executions (s)",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "GREATER_THAN_SPECIFIC_VALUE",
                            "compareValue": 3000,
                        },
                    },
                    "triggerEnabled": "true",
                    "minimumTriggers": 15,
                },
                {
                    "name": "Condition 2",
                    "shortName": "B",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Time Spent in Executions (s)",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "BASELINE_TYPE",
                            "baselineCondition": "GREATER_THAN_BASELINE",
                            "baselineName": "Daily Trend - Last 30 days",
                            "compareValue": 4,
                            "baselineUnit": "STANDARD_DEVIATIONS",
                        },
                    },
                    "triggerEnabled": "false",
                    "minimumTriggers": 15,
                },
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    }
    return new_data

def get_gc_block(data=None):
    """Template for DB gc current block receive time."""
    new_data = data.copy()
    new_data["name"] += " - DB gc current block receive time"
    new_data["evalCriterias"] = {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "gc current block receive time HIGH",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|Server Statistic|gc current block receive time",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "GREATER_THAN_SPECIFIC_VALUE",
                            "compareValue": 12000,
                        },
                    },
                    "triggerEnabled": "true",
                    "minimumTriggers": 15,
                },
                {
                    "name": "Condition 2",
                    "shortName": "B",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|Server Statistic|gc current block receive time",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "BASELINE_TYPE",
                            "baselineCondition": "GREATER_THAN_BASELINE",
                            "baselineName": "Default Baseline",
                            "compareValue": 4,
                            "baselineUnit": "STANDARD_DEVIATIONS",
                        },
                    },
                    "triggerEnabled": "false",
                    "minimumTriggers": 15,
                },
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    }
    return new_data


def get_connections(data=None):
    """Template for DB connections."""
    new_data = data.copy()
    new_data["name"] += " - Drop in connections"
    new_data["evalCriterias"] = {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "Drop in connections",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|Number of Connections",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "LESS_THAN_SPECIFIC_VALUE",
                            "compareValue": 1,
                        },
                    },
                    "triggerEnabled": "true",
                    "minimumTriggers": 10,
                }
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    }
    return new_data

def get_availability(data=None):
    """Template for DB availability."""
    new_data = data.copy()
    new_data["name"] += " - DBAvailablity"
    new_data["evalCriterias"] = {
        "criticalCriteria": {
            "conditionAggregationType": "ALL",
            "conditionExpression": None,
            "conditions": [
                {
                    "name": "DBAvailablity",
                    "shortName": "A",
                    "evaluateToTrueOnNoData": "false",
                    "evalDetail": {
                        "evalDetailType": "SINGLE_METRIC",
                        "metricAggregateFunction": "VALUE",
                        "metricPath": "DB|KPI|DB Availability",
                        "metricEvalDetail": {
                            "metricEvalDetailType": "SPECIFIC_TYPE",
                            "compareCondition": "LESS_THAN_SPECIFIC_VALUE",
                            "compareValue": 1,
                        },
                    },
                    "triggerEnabled": "true",
                    "minimumTriggers": 10,
                }
            ],
            "evalMatchingCriteria": None,
        },
        "warningCriteria": None,
    }
    return new_data

class AppDPolicyActionBuilder:

    def __init__( self, business_name, db_type, application_name, appd_env, databases, user_email, account_name, client_secret, client_id ):
        """
        Initializes the AppDPolicyActionBuilder with basic parameters for health rules and actions.
        
        :param business_name: Name of the business.
        :param application_name: Name of the application in AppDynamics.
        :param env: The environment (e.g., Production, Development).
        :param tier: The application tier in AppDynamics.
        :param user_email: The email address for action notifications.
        """
        self.business_name = business_name
        self.db_type = db_type
        self.application_name = application_name
        self.appd_env = appd_env
        self.databases = databases_generator(databases)
        self.user_email = user_email
        self.account_name = account_name
        self.client_secret = client_secret
        self.client_id = client_id
        self.token= ""
        self.headers = HEADERS_TEMPLATE
        self.health_rules = []
        self.policies = []
        self.actions = []
        self.base_url = f'https://cvs-ent-{appd_env.lower()}-01.saas.appdynamics.com/controller/'

    def populate_params(self):

        """Populate the PARAMS_TEMPLATE with actual values."""

        populated_params = {
            key: value.replace(f"{{{{{key.lower()}}}}}", str(getattr(self, key.lower())))
            for key, value in PARAMS_TEMPLATE.items()
        }
        # Additional specific replacements if necessary
        return populated_params
    

    def generate_access_token(self):

        """Retrieve the access token using client credentials."""
        base_url = f"https://cvs-ent-{self.appd_env.lower()}-01.saas.appdynamics.com/controller/"
        url = f"{base_url}api/oauth/access_token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": f"{self.client_id}@{self.account_name}",
            "client_secret": self.client_secret,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()  # Raise an error for bad status codes
        token_data = response.json()
        self.token = token_data["access_token"]
        self.headers = {k: v.format(token=self.token) for k, v in HEADERS_TEMPLATE.items()}

    def create_payload(self, health_rule_name):
   
        payload = BASE_PAYLOAD_TEMPLATE.copy()
        payload["name"] = health_rule_name
        payload["affects"]["databaseType"] = self.db_type
        if len(self.databases) > 0:
            payload["affects"]["affectedDatabases"]["databaseScope"] = "SPECIFIC_DATABASES"
            payload["affects"]["affectedDatabases"]["databases"] = self.databases
        else:
            payload["affects"]["affectedDatabases"]["databaseScope"] = "ALL_DATABASES"

        return payload
    
    def process_health_rule(self, health_rule_name, original_payload, health_rules, get_payload_func, success_msg, failed_msg):
 
        if len(self.databases) > 0:
            for server in self.databases:
                server_name = server["serverName"]
                original_payload["name"] = health_rule_name + "-" + server_name
                original_payload["affects"]["affectedDatabases"]["databases"] = [server]

                # Generate new payload
                new_payload = get_payload_func(data=original_payload)

                # Append to health_rules list
                health_rules.append({
                    'hr_payload': json.dumps(new_payload),
                    'success_msg': success_msg,
                    'failed_msg': failed_msg
                })
        else:
            # Handle the case for all databases
            new_payload = get_payload_func(data=original_payload)
            print(f"print nepayayload line *****474****: {new_payload}")


            health_rules.append({
                'hr_payload': json.dumps(new_payload),
                'success_msg': success_msg,
                'failed_msg': failed_msg
            })

    def create_health_rules(self, health_rules):

        health_rules_name_list = []

        for rule in health_rules:
            # Parse the health rule name from the payload
            rule_name = json.loads(rule['hr_payload'])
            health_rules_name_list.append(rule_name['name'])
        
            print(f'******** Creating {rule_name["name"]} ********')
            print('Payload:', rule['hr_payload'])

            # Send the health rule creation request
            appd_api_response = requests.post(
                f'{self.base_url}/alerting/rest/v1/applications/15/health-rules',
                data=rule['hr_payload'],
                headers=self.headers
            )

            # Print response and success/failure message
            print('Response:', appd_api_response.text)
            if appd_api_response.status_code == 201:
                print(rule['success_msg'])
            else:
                print(rule['failed_msg'])
        return health_rules_name_list
    def post_appd_action(self, payload):
        url = self.base_url+'alerting/rest/v1/applications/15/actions'
        print(f"*******line 511**** paylod: {payload}")
        return post_request( url, self.headers, payload )
    

    def post_appd_policy(self, payload):
        url = self.base_url+'alerting/rest/v1/applications/15/policies'
        return post_request( url, self.headers, payload )

def get_secrets(account_name: str, secrets_file_path: str):
    account_name_upper = account_name.upper()
    formatted_account_name = account_name_upper.replace('-', '_')

    with open(secrets_file_path, 'r') as file:
        secrets = json.load(file)

    client_id = secrets.get(f"{formatted_account_name}_CLIENT_ID")
    client_secret = secrets.get(f"{formatted_account_name}_SECRET")

    if not client_id or not client_secret:
        exit(f"Missing secrets for account: {formatted_account_name}")
    
    return client_id, client_secret

def main():
    """Script that generates the Health Rule for any databases in the AppDynamics."""


    db_type = os.getenv("DB_TYPE", "").strip()
    business_name = os.getenv("BusinessName", "").strip()
    application_name = os.getenv("ApplicationName", "").strip()
    appd_env = os.getenv("DB_ENV", "").strip()
    databases = os.getenv("DATABASES", "").strip()
    secrets_file_path = os.getenv("SECRETS_PATH", "").strip()
    account_name = os.getenv("APPD_CON", "").strip()
    user_email = os.getenv("USER_EMAIL", "").strip().split(",")

    print(f"usr lsit of emails: {user_email}")
    print(f"type: {type(user_email)}")
    client_id, client_secret = get_secrets(account_name, secrets_file_path)

    appd_obj=AppDPolicyActionBuilder(business_name, db_type, application_name, appd_env, databases, user_email, account_name, client_secret, client_id )
    print(f"client id fetched: {client_id}")
    appd_obj.generate_access_token()

    health_rule_name = f"{business_name} | {appd_env} | {db_type}"

    original_payload = appd_obj.create_payload(health_rule_name)
    
    health_rules = []

    # DB Calls Per Minute
    appd_obj.process_health_rule(
        health_rule_name=health_rule_name,
        original_payload=original_payload,
        health_rules=health_rules,
        get_payload_func=get_db_conn_per_min,
        success_msg='******* SUCCESSFULLY CREATED DB CALLS PER MINUTE ********',
        failed_msg='******* FAILED CREATING DB CALLS PER MINUTE ********'
    )

    # DB Time Spent in Executions
    appd_obj.process_health_rule(
        health_rule_name=health_rule_name,
        original_payload=original_payload,
        health_rules=health_rules,
        get_payload_func=get_db_exec_time,
        success_msg='******* SUCCESSFULLY CREATED DROP IN CONNECTIONS ********',
        failed_msg='******* FAILED CREATING DROP IN CONNECTIONS ********'
    )
    # DB Get Connections per minute


    # DB GC Current Block Receive Time
    appd_obj.process_health_rule(
        health_rule_name=health_rule_name,
        original_payload=original_payload,
        health_rules=health_rules,
        get_payload_func=get_gc_block,
        success_msg='******* SUCCESSFULLY CREATED DB AVAILABILITY ********',
        failed_msg='******* FAILED CREATING DB AVAILABILITY ********'
    )

    # DB Availability

    appd_obj.process_health_rule(
        health_rule_name=health_rule_name,
        original_payload=original_payload,
        health_rules=health_rules,
        get_payload_func=get_connections,
        success_msg='******* SUCCESSFULLY CREATED DB EXECUTION TIME ********',
        failed_msg='******* FAILED CREATING DB EXECUTION TIME ********'
    )
    # Db avaialibity 
    appd_obj.process_health_rule(
        health_rule_name=health_rule_name,
        original_payload=original_payload,
        health_rules=health_rules,
        get_payload_func=get_availability,
        success_msg='******* SUCCESSFULLY CREATED DB EXECUTION TIME ********',
        failed_msg='******* FAILED CREATING DB EXECUTION TIME ********'
    )
    

    health_rules_name_list = appd_obj.create_health_rules(
        health_rules=health_rules
    )
    action_payload = render_template_json("useremailaction.j2",{'user_email':user_email})
    print(f"printing action payload: {action_payload}")

    policy_params =  appd_obj.populate_params()
    if health_rules_name_list and isinstance(health_rules_name_list, list):
        policy_params.update({'health_rules': health_rules_name_list})
        print(f"*********line 604******* {policy_params}")
    else:
        print("Error: health_rules_name_list is not valid. Skipping policy update.")
    policy_payload = render_template_json("databasepolicy.j2", policy_params)
    print( "calling action function ")
    appd_obj.post_appd_action( action_payload )
    print( "calling policy function ")
    appd_obj.post_appd_policy(policy_payload)
    
    exit(0)

if __name__ == '__main__':
    main()
