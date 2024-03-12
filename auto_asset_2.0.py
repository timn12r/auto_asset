import requests
import os
import json
import glob
import xml.etree.ElementTree as ET
import shutil

#Path handling
ROOT = os.path.dirname(os.path.realpath(__file__))
DIR_REPORTS = os.path.join(ROOT, 'Reports')
DIR_REPORTS_ISSUES = os.path.join(DIR_REPORTS, 'Issues')
DIR_REPORTS_UID = os.path.join(DIR_REPORTS, 'UID Error')
DIR_REPORTS_DONE = os.path.join(DIR_REPORTS, 'Processed')
DIR_CONFIG = os.path.join(ROOT, 'Config')
DIR_CONFIG_JSON = os.path.join(DIR_CONFIG, 'config.json')
DIR_CONFIG_DEFECTS = os.path.join(DIR_CONFIG, 'defects.json')
DIRS = {
    'DIR_REPORTS': DIR_REPORTS,
    'DIR_REPORTS_ISSUES': DIR_REPORTS_ISSUES,
    'DIR_REPORTS_UID': DIR_REPORTS_UID,
    'DIR_REPORTS_DONE': DIR_REPORTS_DONE,
    'DIR_CONFIG': DIR_CONFIG
}
CONFIG_BOILER = {
    'Interval': 'default',
    'Razor API Key': '',
    'Razor URL': '',
    'Blancco Username': '',
    'Blancco Password': '',
    'CPU Pattern Intel': '(Intel\\(R\\)) (\\S+) (\\S+)',
    'CPU Pattern AMD': '(AMD) (\\S+ \\S+ \\S+)',
    'Battery Fail Threshold': '60'
}
#Make directories if they are not found
for key, path in DIRS.items():
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"Created directory: {path}")
        
#Make defects file if not found
if not os.path.exists(DIR_CONFIG_DEFECTS):
    with open(DIR_CONFIG_DEFECTS, 'w') as file:
        print('WARN: Defects config was not found. Empty configuration created in Config folder.')
        json.dump({}, file, indent=4)

#Make config file if not found
if not os.path.exists(DIR_CONFIG_JSON):
    with open(DIR_CONFIG_JSON, 'w') as file:
        print('Created config file')
        json.dump(CONFIG_BOILER, file, indent=4)
#Check that the config file has all boilerplate entries
try:
    with open(DIR_CONFIG_JSON, 'r') as file:
        #Grab existing data
        config_data = json.load(file)

        #Check for missing data
        for key, value in CONFIG_BOILER.items():
            if key not in config_data:
                config_data[key] = value
    #Write missing data
    with open(DIR_CONFIG_JSON, 'w') as file:
        json.dump(config_data, file, indent=4)
except:
    #Overwrite entire json file with boiler if json is empty or corrupt
    with open(DIR_CONFIG_JSON, 'w') as file:
        json.dump(CONFIG_BOILER, file, indent=4)
#Load config data
with open(DIR_CONFIG_JSON, 'r') as file:
    CONFIG_DATA = json.load(file)

#HTTP Operations
RAZOR_URL = CONFIG_DATA['Razor URL']
HEADERS = {
    'Authorization': f'Bearer {CONFIG_DATA['Razor API Key']}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}
def HTTP(op, url, data):
    success = True
    match op:
        case 'GET':
            response = requests.get(url=url, headers=HEADERS)
        case 'POST':
            response = requests.post(url=url, headers=HEADERS, json=data)
        case 'PUT':
            response = requests.put(url=url, headers=HEADERS, json=data)
        case _:
            return 'HTTP: Invalid operation provided.'
    if response.status_code != 200:
        print(f'[{response.status_code}]: HTTP request: {op} failed. Response from server: {response.text}')
        success = False
    return response.status_code, response.json(), success

#Report Operations
def error_handler(error, report, data):
    match error:
        case 'Bad UID':
            print(f'[ERROR]: Bad UID detected with filename {report}!')
            try:
                os.rename(report, os.path.join(DIR_REPORTS_UID, f'{data}.xml'))
            except:
                print(f'Could not rename file {report}')
                shutil.move(report, DIR_REPORTS_UID)
        case _:
            print('[ERROR]: Bad error operation code provided!')

def check_for_reports(dir):
    reports = []
    if (new_reports := glob.glob(f'{DIR_REPORTS}/*.xml')):
        print('New reports found!')
        for report in new_reports:
            reports.append(report)
    else:
        print(' No reports found.')
    return reports

def parse_report(report):
    keys = {
        'UID': None,
        'Cosmetic Defect': None,
        'Functional Defect': None,
        'UUID': None,
        'model': None
    }
    custom_fields = './/entries[@name = "fields"]/entry[@name = '
    tree = ET.parse(report)
    root = tree.getroot()
    try:
        #Grab Custom Field Data
        keys['UID'] = root.findtext(f'{custom_fields}"UID"]').upper()
        c_defects = root.findall(f'{custom_fields}"Cosmetic Defect"]')
        keys['Cosmetic Defect'] = [entry.text.replace('No defects', '') for entry in c_defects]
        f_defects = root.findall(f'{custom_fields}"Functional Defect"]')
        keys['Functional Defect'] = [entry.text.replace('No defects', '') for entry in f_defects]
        keys['UUID'] = root.findtext('.//document_id')
        keys['model'] = root.findtext('.//entries[@name = "system"]/entry[@name = "version"]')
    except Exception as e:
        print(f'{report}: Report parse error: {e}')
    return keys

def correct_asset(report, data):
    uid = data['UID']
    
    if (HTTP('GET', f'{RAZOR_URL}Asset/{uid}', None))[2]:
        print('Success!')
    else:
        error_handler('Bad UID', report, uid)

#Instantiate empty reports dictionary
reports = {}
#Check for reports and parse them if found.
#Reports parsed will be added to reports{} with model report: report_data
if (report_files := check_for_reports(DIR_REPORTS)):
    for report in report_files:
        report_data = parse_report(report)
        reports[report] = report_data

if reports:
    for report, report_data in reports.items():
        correct_asset(report, report_data)
