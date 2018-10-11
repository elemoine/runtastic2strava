#!/usr/bin/env python
import datetime
import json
import os
import re
import sys
import time
import pathlib
import configparser
import stat

import requests
import stravalib


DAYS_WINDOW = int(os.getenv("RUNTASTIC_DAYS_WINDOW", 3))
STRAVA_UPLOAD = "upload@strava.com"

config = configparser.ConfigParser()
config_path = pathlib.Path.home() / '.runtastic2strava.conf'
config_file = str(config_path)
if not config_path.is_file():
    print('no configuration file found ({})'.format(config_file))
    sys.exit(1)
mode = stat.S_IMODE(config_path.stat().st_mode)
if mode != 0o600:
    print('{} mode is not 0600'.format(config_file))
    sys.exit(1)
config.read(config_file)

configobj = config['DEFAULT']
runtastic_email = configobj['runtastic_email']
runtastic_password = configobj['runtastic_password']
runtastic_username = configobj['runtastic_username']
strava_access_token = configobj['strava_access_token']

login = requests.post("https://www.runtastic.com/en/d/users/sign_in",
                      data={"user[email]": runtastic_email,
                            "user[password]": runtastic_password})

if login.status_code // 100 != 2:
    print("Error logging in Runtastic, aborting")

resp = requests.get("https://www.runtastic.com/en/users/%s/sport-sessions"
                    % runtastic_username,
                    cookies=login.cookies)

if resp.status_code // 100 != 2:
    print("Error doing Runtastic request, aborting")
    sys.exit(1)

match_data = re.search(r"index_data = ([^;]+);", resp.text)
if not match_data:
    print("Error looking for data, aborting")
    sys.exit(1)

activities = json.loads(match_data.group(1))

last_sync_day = (datetime.datetime.utcnow()
                 - datetime.timedelta(days=DAYS_WINDOW)).strftime("%Y-%m-%d")

client = stravalib.Client(access_token=strava_access_token)

# Only send the last N days of activities
for activity in filter(lambda a: a[1] >= last_sync_day, activities):
    activity_id = activity[0]
    filename = "%s.tcx" % activity_id
    filealreadyexists = pathlib.Path(filename).exists()
    if not filealreadyexists:
        while True:
            resp = requests.get(
                "https://www.runtastic.com/en/users/%s/sport-sessions/%s.tcx"
                % (runtastic_username, activity_id),
                cookies=login.cookies)
            if resp.status_code == 403:
                print('Runtastic query failed with 403, wait for 10 minutes and try again')
                time.sleep(600)  # 10 minutes
                continue
            if resp.status_code != 200:
                raise Exception('Runtastic query failed')
            break
    else:
        print('file {} already exists'.format(filename))
    if filealreadyexists:
        mode = 'r'
    else:
        mode = 'w+'
    with open(filename, mode) as f:
        if not filealreadyexists:
            # save the file
            f.write(resp.text)
            f.seek(0)
        try:
            client.upload_activity(f, data_type="tcx")
            print("Sent activity %s from %s" % (activity_id, activity[1]))
        except stravalib.exc.ActivityUploadFailed as e:
            print("Failed to upload {} from {}: {}".format(activity_id, activity[1], str(e)))
            if not ('duplicate' in str(e)
                    or 'Unrecognized file type' in str(e)
                    or 'The file is empty' in str(e)):
                raise
