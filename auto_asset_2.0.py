import os
import re
import json
import glob
import math
import datetime
import shutil
import logging
import requests
import xml.etree.ElementTree as ET
from logging.handlers import RotatingFileHandler
from collections import Counter

##############################################################
#Path handling
ROOT = os.path.dirname(os.path.realpath(__file__))
DIR_REPORTS = os.path.join(ROOT, 'Reports')
DIR_REPORTS_ISSUES = os.path.join(DIR_REPORTS, 'Issues')
DIR_REPORTS_EXPIRED = os.path.join(DIR_REPORTS, 'Expired')
DIR_REPORTS_UID = os.path.join(DIR_REPORTS, 'UID Error')
DIR_REPORTS_DONE = os.path.join(DIR_REPORTS, 'Processed')
DIR_CONFIG = os.path.join(ROOT, 'Config')
DIR_CONFIG_JSON = os.path.join(DIR_CONFIG, 'config.json')
DIR_CONFIG_DEFECTS = os.path.join(DIR_CONFIG, 'defects.json')
DIR_CONFIG_LOGS = os.path.join(DIR_CONFIG, 'logs.log')
DIRS = {
    'DIR_REPORTS': DIR_REPORTS,
    'DIR_REPORTS_ISSUES': DIR_REPORTS_ISSUES,
    'DIR_REPORTS_EXPIRED': DIR_REPORTS_EXPIRED,
    'DIR_REPORTS_UID': DIR_REPORTS_UID,
    'DIR_REPORTS_DONE': DIR_REPORTS_DONE,
    'DIR_CONFIG': DIR_CONFIG
}
CONFIG_BOILER = {
    'Interval': 'default',
    'Overwrite Existing Razor Data': 'true',
    'Razor API Key': '',
    'Razor URL': '',
    'Blancco Username': '',
    'Blancco Password': '',
    'Battery Fail Threshold': 60,
    'Master Item Laptop Model': {
        "attributeType": 'Laptop',
        "itemTypeId": 1,
        "manufacturer": 0,
        "manufacturerId": 0,
        "primaryCategoryId": 70,
        "title": "string"
    },
    'Master Item Desktop Model': {
        "attributeType": 'Desktop',
        "manufacturer": 0,
        "manufacturerId": 0,
        "primaryCategoryId": 69,
        "title": "string"
        }
}
################################################################
#LOGGING
if not os.path.exists(DIR_CONFIG):
    os.makedirs(DIR_CONFIG)

# Set up RotatingFileHandler
file_handler = RotatingFileHandler(
    DIR_CONFIG_LOGS,  # Log file path
    maxBytes=1*1024*1024,  # Maximum log size (1MB)
    backupCount=2  # Number of backup logs to keep
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
# Create a logger
log = logging.getLogger()
log.setLevel(logging.DEBUG)
log.addHandler(file_handler)
# Set up console output (StreamHandler)
log_handler = logging.StreamHandler()
log_handler.setLevel(logging.INFO)
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s]: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
log.addHandler(log_handler)

################################################################
#PATHING
#Make directories if they are not found
for key, path in DIRS.items():
    if not os.path.exists(path):
        os.makedirs(path)
        log.info(f"Created directory: {path}")

#Make config file if not found
if not os.path.exists(DIR_CONFIG_JSON):
    with open(DIR_CONFIG_JSON, 'w') as file:
        log.info('Created config file')
        json.dump(CONFIG_BOILER, file, indent=4)

#Make defects file if not found
if not os.path.exists(DIR_CONFIG_DEFECTS):
    with open(DIR_CONFIG_DEFECTS, 'w') as file:
        log.critical('Defects config was not found. Empty defects.json created in Config folder.')
        log.critical('Script exiting.')
        json.dump({}, file, indent=4)
        exit()

#Check that the config file has all boilerplate entries
try:
    with open(DIR_CONFIG_JSON, 'r') as file:
        #Grab existing data
        config_data = json.load(file)

        #Check for missing data
        for key, value in CONFIG_BOILER.items():
            if key not in config_data:
                config_data[key] = value
                log.warning(f'Detected missing config info. Pulling {key} from config boiler.')
    #Write missing data
    with open(DIR_CONFIG_JSON, 'w') as file:
        json.dump(config_data, file, indent=4)
except FileNotFoundError:
    #Overwrite entire json file with boiler if json file is missing
    with open(DIR_CONFIG_JSON, 'w') as file:
        json.dump(CONFIG_BOILER, file, indent=4)
#Load config data
with open(DIR_CONFIG_JSON, 'r') as file:
    CONFIG_DATA = json.load(file)
with open(DIR_CONFIG_DEFECTS, 'r') as file:
    DEFECT_BANK = json.load(file)
if DEFECT_BANK == {}:
    log.critical('Defect bank is configured as empty. Please add defects to defects.json and try again.')
    log.critical('Script exiting.')
    exit()

################################################################
#HTTP OPERATIONS
RAZOR_URL = CONFIG_DATA['Razor URL']
HEADERS = {
    'Authorization': f'Bearer {CONFIG_DATA['Razor API Key']}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}
def HTTP(op, url, data):
    match op:
        case 'GET':
            response = requests.get(url=url, headers=HEADERS)
        case 'POST':
            response = requests.post(url=url, headers=HEADERS, json=data)
        case 'PUT':
            response = requests.put(url=url, headers=HEADERS, json=data)
        case _:
            log.critical('HTTP: Invalid operation provided.')
            return 0, None
    if response.status_code == 200:
        return response.status_code, response.json()
    else:
        log.warning(f'[{response.status_code}]: HTTP request: {op} failed. Response from server: {response.text}')
        return response.status_code, response.text

################################################################
#FUNCTION BLOCK: REPORTS
def move_report(report, uid, target_dir):
    report_name = os.path.basename(report)
    if uid is not None:
        target_file = os.path.join(target_dir, f'{uid}.xml')
        # Check if the file already exists and increment the filename if necessary
        i = 1
        while os.path.exists(target_file):
            target_file = os.path.join(target_dir, f'{uid}_{i}.xml')
            i += 1
        try:
            os.rename(report, target_file)
            log.info(f"Successfully moved report {report_name} to {target_file}")
        except Exception as e:
            log.warning(f'Could not rename file {report_name} to {target_file}: {e}')
    else:
        # If no UID, just use the original report name
        target_file = os.path.join(target_dir, f'{report_name}.xml')
        i = 1
        while os.path.exists(target_file):
            target_file = os.path.join(target_dir, f'{report_name}_{i}.xml')
            i += 1
        try:
            os.rename(report, target_file)
            log.info(f"Successfully moved report {report_name} to {target_file}")
        except Exception as e:
            log.critical(f'Could not move report {report_name}: {e}')

def error_handler(error, report, uid):
    report_name = os.path.basename(report)
    match error:
        case 'Bad UID':
            log.critical(f'Bad UID detected with filename {report_name}!')
            move_report(report, uid, DIR_REPORTS_UID)

        case 'Missing Attributes':
            today = datetime.datetime.today()
            modified_date = datetime.datetime.fromtimestamp(os.path.getmtime(report))
            file_age = today - modified_date
            log.info(f'Attributes for {uid} have not been imported yet ({math.floor(file_age.seconds/60)} minutes old).')
            #Move the report into the issues dir if it never receives its attributes
            if file_age.seconds > 600:
                log.warning(f'Attributes for {uid} were not imported after 10 minutes. Moving to Expired folder.')
                move_report(report, uid, DIR_REPORTS_EXPIRED)
        
        case 'Misc Error':
            log.warning(f'UID {uid} experienced an issue with the server. Placing into Issues folder.')
            move_report(report, uid, DIR_REPORTS_ISSUES)

def check_for_reports(dir):
    reports = []
    if (new_reports := glob.glob(f'{DIR_REPORTS}/*.xml')):
        print('New reports found!')
        for report in new_reports:
            reports.append(report)
    else:
        print('No reports found.')
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
    system_fields = './/entries[@name = "system"]/entry[@name = '
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
        keys['model'] = root.findtext(f'{system_fields}"version"]')
        keys['Manufacturer'] = root.findtext(f'{system_fields}"manufacturer"]')
        keys['Chassis Type'] = root.findtext(f'{system_fields}"chassis_type"]')
    except Exception as e:
        log.warning(f'{report}: Report parse error: {e}')
    return keys

def update_master(key_data, json_data, uid):
    chassis_type = key_data['Chassis Type']
    model = key_data['model']
    manufacturer = key_data['Manufacturer']
    search_phrase = manufacturer

    #Search for existing MFG, then grab its ID
    get_status, response = HTTP('GET', f'{RAZOR_URL}Manufacturer?SearchOptions.SearchPhrase={search_phrase}', None)
    if get_status == 200:
        items = response.get('items', [])
        manufacturerId = items[0].get('id', None)
    #Create MFG if not found in the system
    if get_status == 404:
        mfg_json = {
            "description": "This manufacturer was created by the auto asset script.",
            "name": {manufacturer}
        }
        create_mfg, response = HTTP('POST', f'{RAZOR_URL}Manufacturer', mfg_json)
        if create_mfg == 200:
            #Retry getting MFG id with newly added MFG
            get_status, response = HTTP('GET', f'{RAZOR_URL}Manufacturer?SearchOptions.SearchPhrase={search_phrase}', None)
            if get_status == 200:
                items = response.get('items', [])
                manufacturerId = items[0].get('id', None)
    #Start laying out json for new master item. Pulls model from config file and modifies where necessary.
    match chassis_type:     #Chooses chassis type based on Blancco report
        case 'Laptop'|'Notebook' | 'Convertible': master_json = config_data['Master Item Laptop Model']
        case 'Desktop': master_json = config_data['Master Item Desktop Model']
        case _: master_json = config_data['Master Item Laptop Model']
    master_json['itemNumber'] = model
    master_json['manufacturer'] = manufacturer
    master_json['manufacturerId'] = manufacturerId
    master_json['title'] = f'{model} {manufacturer}'
    #Send new master item
    post_status, response = HTTP('POST', f'{RAZOR_URL}ItemMaster', master_json)
    if post_status == 200:
        log.info('Master item added successfully!')
        send_update, response = HTTP('PUT', f'{RAZOR_URL}Asset/{uid}', json_data)
        if send_update == 200:
            log.info(f'UID {uid}: Updated successfully!')
            return True
        else:
            return False
    else:
        log.warning(f'UID {uid}: Could not add Master item! {post_status}')
        return False

def grade_asset(data):
    defects = []
    c_weights = []
    f_weights = []
    grades = []
    
    c_defect = data['Cosmetic Defect']
    f_defect = data['Functional Defect']
    defects = [defect for defect in c_defect + f_defect if defect != '']

    if all(defect is None for defect in defects):
        defects = ['-']

    for c_defect in DEFECT_BANK.get('Cosmetic Defects', []):
        if c_defect['defect'] in defects:
            c_weights.append(c_defect['weight'])

    for f_defect in DEFECT_BANK.get('Functional Defects', []):
        if f_defect['defect'] in defects:
            f_weights.append(f_defect['weight'])

    #Grade asset according to defects (based on defect weights)
    if (cosmetic_weight := sum(c_weights)) == 0:
        grades.append('A')
    elif 0 < cosmetic_weight <= .45:
        grades.append('B')
    elif .45 < cosmetic_weight:
        grades.append('C')
    
    if (functional_weight := sum(f_weights)) == 0:
        grades.append('A')
    elif 0 < functional_weight <= .4:
        grades.append('B')
    elif .4 < functional_weight <= .75:
        grades.append('C')
    else:
        grades.append('F')
    #Return list of grades ['Cosmetic Grade', 'Functional Grade'] and list of defects
    return grades, defects

def correct_asset(report, data):
    uid = data['UID']
    model = data['model']

    #Verify asset validity, then perform operations
    verify_status, response = HTTP('GET', f'{RAZOR_URL}Asset/{uid}', None)

    if verify_status == 200:
        #Dictionary of attributes that need reformating, and boolean to determine if asset needs updates
        json_data = response                                                            #JSON data about the asset
        updates, has_updates = { 'CPU Type': None, 'Battery Wear Level': None }, False  #Instantiate empty dictionary of potential updates
        attributes = json_data['attributes']                                            #Attributes from Razor
        grades, defects = grade_asset(data)                                             #Grab grades and defects

        #Filter to find attributes that need updating
        for attribute in attributes:
            if (typeName := attribute['typeName']) in updates:
                updates[typeName] = attribute['value']
        #Asset either has not received Blancco data yet or does not have a linked report
        if all(attr is None for attr in updates.values()):
            error_handler('Missing Attributes', report, uid)
            return False


        #Lenovo model corrections
        if json_data['manufacturer'] == 'LENOVO':
            if model.upper() != json_data['model']:
                json_data['model'] = model.upper()
                has_updates = True
                log.info(f'UID {uid}: Lenovo MFG detected, updating model.')


        #Clean cpu
        #Tags to remove to clean CPU formatting
        #                   Branding                 CPU   @   0.00GHz
        text_to_remove = r'Intel|\(R\)|\(TM\)|Core| CPU|\s@\s|\d+(\.\d+)?GHz'
        razor_cpus = updates['CPU Type']
        #Check if CPU(s) are not formatted in Razor
        if '@' in razor_cpus:
            has_updates = True
            log.info(f'UID {uid}: Reformatting CPU(s).')
            cpu_list = razor_cpus.split(', ')
            cleaned_cpus = [
                re.sub(text_to_remove, '', cpu).strip()
                for cpu in cpu_list
            ]
            #In cases where there are multiple CPUs. Condense them into (x2, x3, etc)
            cpu_qty = Counter(cleaned_cpus)
            formatted_cpus = [
                f'{cpu} (x{qty})' if qty > 1 else cpu
                for cpu, qty in cpu_qty.items()
            ]
            finished_cpus = ', '.join(formatted_cpus)
            for attr in attributes:
                if attr['typeName'] == 'CPU Type':
                    attr['value'] = finished_cpus

        #Clean battery and assign defect if wear level below threshold (60%)
        battery_pattern = r'\d+%'
        wear = updates['Battery Wear Level']
        if wear:
            #Search for integers in the wear level from Razor
            match = re.search(r'\b([0-9]{1,3})\b', wear)
            if match:
                #Format and update wear level for Razor's end
                wear_formatted = match.group(1) + '%'
                wear_int = int(match.group(1))
                if wear_int < config_data['Battery Fail Threshold']:
                    if '-' in defects:
                        defects.remove('-')
                        defects.append(f'Battery {wear_int}%')
                        has_updates = True
            else:
                #Catches any edge-case strings and leaves them as is
                log.warning(f'UID {uid}: Invalid wear level, skipping reformat.')
                wear_formatted = wear
            #Check to see if the wear level is correctly formatted
            if wear != wear_formatted:
                has_updates = True
                log.info(f'UID {uid}: Reformatting battery wear.')
                for attr in attributes:
                    if attr['typeName'] == 'Battery Wear Level':
                        attr['value'] = f"{wear}%"

        #Update attribute only if it isn't already occupied in Razor (prevents overwriting)
        def update_attribute(attributes, attr_type, attr_value):
            for attr in attributes:
                if attr['typeName'] == attr_type and config_data['Overwrite Existing Razor Data'] == 'false':
                    return False
            attributes.append({'typeName': attr_type, 'value': attr_value})
            return True

        #Update Defect, Cosmetic and Functionality fields, if applicable
        if update_attribute(attributes, 'Defect', ', '.join(defects)):
            log.info(f'UID {uid}: Updating "Defects".')
            has_updates = True
        if update_attribute(attributes, 'Cosmetic Grade', grades[0]):
            log.info(f'UID {uid}: Giving "Cosmetic" Grade.')
            has_updates = True
        if update_attribute(attributes, 'Functionality Grade', grades[1]):
            log.info(f'UID {uid}: Giving "Functionality" Grade.')
            has_updates = True

        #Apply updates, if any
        if has_updates:
            send_update, response = HTTP('PUT', f'{RAZOR_URL}Asset/{uid}', json_data)
            if send_update == 200:
                log.info(f'UID {uid}: Updated successfully!')
                return True
            if send_update == 404:
                log.warning('Master item not found, creating...')
                if update_master(data, json_data, uid):
                    return True
            if send_update == 400:
                error_handler('Misc Error', report, uid)
        if not has_updates:
            log.info(f'UID {uid}: No corrections to be made.')
            return True

    #UID Failed Razor verify
    if verify_status == 404:
        error_handler('Bad UID', report, uid)

    if verify_status == 400:
        error_handler('Misc Error', report, uid)
    
################################################################
#MAIN BLOCK
def main():
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
            if correct_asset(report, report_data):
                report_name = os.path.basename(report)
                uid = report_data['UID']
                
                try:
                    move_report(report, uid, DIR_REPORTS_DONE)
                except Exception as e:
                    log.warning(f'Could not move report f{report}: {e}')
                
                log.info(f'Report {report_name} has completed all operations.')
        print('Operations completed.')

if __name__ == '__main__':
    main()
