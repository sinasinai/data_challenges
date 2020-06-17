import requests
import pandas as pd
from sqlalchemy import create_engine
import os
import sys
from datetime import datetime
import pendulum
import hashlib

### Assuming that we are extracting and loading necessary attributes
### from a single endpoint in each of the extract/load steps... assuming these are pulling
### from and pushing to some sort of users endpoint based on the desired attributes
EXTRACT = 'https://www.extractapi.com/v1/users'
LOAD = 'https://www.loadapi.com/v1/users'


DB_USER = os.getenv('DB_USER')
DB_PWD = os.getenv('DB_PWD')
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')

EXTRACT_KEY = os.getenv('EXTRACT_KEY')
LOAD_KEY = os.getenv('LOAD_KEY')

### Most systems work with UTC time and many use ISO 8601 for datetime conventions, so assuming that's the case here
### Need to use this datetime to build out *incremental* pull/push update capacity

UTC = pendulum.timezone('UTC')
DATE_MODIFIED = str(datetime.now(UTC).isoformat()))

LOAD_SQL = '''
    BEGIN;
    INSERT INTO endpoint_user_table
    (
        select
        user_id,
        full_name,
        email,
        cell,
        datetime_modified
        from endpoint_temp_user_table

    );

    DROP TABLE endpoint_temp_user_table;
    COMMIT;

'''

POST_SQL = '''



'''

### Assuming a PostgreSQL database but can modify this URI to reflect whatever database we're using internally
### Can also modify it to reflect it if we're using a platform like Civis... these credentials should be
### environmental variables or accessible in the environment that the script is running

ENGINE = create_engine('postgresql://' + DB_USER + ':' + DB_PWD + '@' + DB_HOST + '/' + DB_NAME)

def extract():

    ### assuming that the endpoint has this wonderful datetime_modified attribute that lets us pull info
    ### for users that have modified/updated records... this would obviously have to be modified in other situations
    ### where we don't have a way of conducting incremental updates
    print('Querying endpoint and extracting data...',file=sys.stdout)
    response = requests.get(EXTRACT,params = {'datetime_modified':DATE_MODIFIED,'key':EXTRACT_KEY})
    users = response.json()

    # Making assumptions about the response payload, this can definitely be optimized but this is meant as a v1
    user_dict = {}
    userids = []
    names = []
    emails = []
    cells = []
    datetime_modified = []

    for user in users:

        userids.append(user['user_id'])
        names.append(user['full_name'])
        emails.append(user['email'])
        cells.append(user['cell'])
        datetime_modified.append(user['datetime_modified'])

    user_dict['user_id'] = userids
    user_dict['full_name'] = names
    user_dict['email'] = emails
    user_dict['cell'] = cells
    user_dict['datetime_modified'] = datetime_modified

    users_df = pd.DataFrame.from_dict(user_dict).drop_duplicates()

    return(users_df)


def transform(payload):
    ### Conducts some basic standardizations and loads data into temp table in Indivisible DB

    print('Standardizing data and loading into Indivisible database...',file=sys.stdout)
    payload['user_id'] = payload['user_id'].astype('int64')
    payload['full_name'] = payload['full_name'].astype('str').str.title()
    payload['email'] = payload['full_name'].astype('str').str.lower()
    payload['cell'] = payload['full_name'].astype('str').str.replace('([\+]|[-])','').astype('str')
    payload['datetime_modified'] = payload['datetime_modified'].astype('str')
    payload.to_sql('endpoint_temp_user_table',engine,schema='indivisible',index=False,chunksize=10000,method='multi')
    return(payload)

def load():

### executes the load statemnt for SQL to drop the temp table and insert the newly modified values into the indivisible DB
    with engine.connect() as con:
        con.execute(LOAD_SQL)

def post(payload):

    m = hashlib.md5()
    update_payload = {}
    ### creating a hashed entity index to collect relevant all user data under a single endpoint to push to final endpoint_temp_user_table
    ### in reality would probably need to load using an ID convention they provide or trust that they will be able to
    ### reasonably infer and match to existing users in their production DB... could also just load list-wise without all this
    ### but given we don't know how the API is structured or works this seems like a fair assumption

    for n, row in payload.iterrows():

        update_payload[m.hexdigest((m.update(str(row['full_name'] + row['email'] + ['cell']).encode('utf-8'))))] = \
            {

            'email': row['email'],
            'cell': row['cell'],
            'full_name': row['full_name']

            }
    print('Uploading data to platform endpoint...',file=sys.stdout)
    response = requests.post(LOAD,params={'key':LOAD_KEY}, data = update_payload)
    print('Done!',file=sys.stdout)



if __name__ == "__main__":
    payload = extract()
    payload = transform(payload)
    load(payload)

### Since I'm assuming we're using cloud compute containers to run this process, we can use
### something like an AWS Lambda's crontab 0 6,18 * * * to run twice a day at 6 am and 6 pm before/after work hours
