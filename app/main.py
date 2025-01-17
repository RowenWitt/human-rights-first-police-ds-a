from random import choice
from typing import Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_utils.tasks import repeat_every
from pydantic import BaseModel

from app.script_tracking import add_to_use_count, add_to_positive_count
from app.scraper import deduplicate, frankenbert_rank, scrape_twitter, DB
import app.bot as bot

from app.models import form_out, form_in, check, new_script

from app.tweep_dm import form_tweet

from app.script_tracking import add_script

import app.dist_lock as dist_lock
import logging, json

# importing distributed lock class
lock = dist_lock.lock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

description = """
DS API for the Human Rights First Blue Witness Dashboard

To use these interactive docs:
- Click on an endpoint below
- Click the **Try it out** button
- Edit the Request body or any parameters
- Click the **Execute** button
- Scroll down to see the Server response Code & Details
"""


class InputString(BaseModel):
    text: str


app = FastAPI(
    title='Labs 37 HRF BW DS API',
    description=description,
    docs_url='/',
    version="0.37.1",
)


@app.post("/form-out/", response_model=form_out)
async def create_form_out(data: form_out):
    """ replies to a given tweet with a link, prompting a Twitter user to send a dm to our bot """
    DB.update_tables({"status":"awaiting response"}, data.tweet_id, "ForceRanks")
    bot.send_form(data)



@app.post("/form-in/")
async def create_form_in(data: form_in):
    """ receives form response and stores in Conversations table """
    location = bot.find_location(data.city + ',' + data.state)
    if location['status'] == "OK":
        loc_list = location['candidates'][0]['formatted_address'].split(',')

        if len(loc_list) == 4:
            city = loc_list[1]
            state = loc_list[2].split()[0]

        if len(loc_list) == 3:
            city = loc_list[0]
            state = loc_list[1].split()[0]

        data.lat = location['candidates'][0]['geometry']['location']['lat']
        data.long = location['candidates'][0]['geometry']['location']['lng']
    else:
        print(location['status'])
    bot.receive_form(data)



@app.post("/approval-check/")
async def create_check(data: check):
    """ returns value of Conversations table row with given tweet_id """
    out = DB.get_root_twelve(data.tweet_id)
    return out


@app.post("/approve/")
async def approve(data: check):
    """ updates ForceRanks with value of Conversations table row which is a form response """
    for_update = DB.get_root_twelve(data.tweet_id)
    data = {}
    data['city'] = for_update[0]['Conversations'].root_tweet_city
    data['state'] = for_update[0]['Conversations'].root_tweet_state
    data['force_rank'] = for_update[0]['Conversations'].root_tweet_force_rank
    data['incident_date'] = for_update[0]['Conversations'].root_tweet_date
    data['status'] = 'approved'
    data['lat'] = for_update[0]['Conversations'].root_tweet_lat
    data['long'] = for_update[0]['Conversations'].root_tweet_long

    DB.update_tables(data, for_update[0]['Conversations'].tweet_id, "ForceRanks")
    data2 = {}
    data2['conversation_status'] = 13
    DB.update_tables(data2, for_update[0]['Conversations'].tweet_id, "Conversations")
    return data


@app.post("/add-script/", response_model=new_script)
async def post_script(data: new_script):
    """ This endpoint allows the Admin to put a new script into the bot_scripts table """
    add_script(data)

# Testing endpoint 
@app.post("/bump-use-count/")
async def add_one_to_use_count(script_id):
    add_to_use_count(script_id)

@app.post("/update-pos-count/")
async def bump_pos_and_success_rate(script_id):
    add_to_positive_count (script_id)


@app.get("/frankenbert/{user_input}")
async def frankenbert(user_input: str):
    """ Prediction endpoint, for testing and demonstration purposes """
    rank, conf, *_ = frankenbert_rank(user_input)
    return {"Rank": rank, "Confidence": conf}


@app.get("/view-data/")
async def view_data():
    """ update and get first 5000 observations dump endpoint """
    await update()

    database_state = lock.get('DatabaseState')
    if database_state is not None:
        logger.info('Retrieved DatabaseState from cache')
        return database_state
    else:
        logger.info('Cache error')



@app.get("/redis-check/{key}")
async def redis_check(key: str):
    check = lock.get(key)
    return check


@app.get("/redis-flush")
async def redis_flush():
    lock.flush()


@app.get("/to-approve/")
async def to_approve():
    """ get all rows of Conversations that are form responses that have not been approved """
    needs_approval = DB.get_twelves()
    return needs_approval


@app.on_event("startup")
@repeat_every(seconds=60 * 60 * 2)
@app.get("/advance-all/")
async def advance_all():
    """ advances all conversations, repeats every hour, only one worker at a time """
    if lock.lock("advance_all", 30) == True:
        logger.info('lock "advance_all" created')
        bot.advance_all()
        lock.unlock("advance_all")
        logger.info('lock "advance_all" unlocked')
    else:
        logger.info('lock "advance_all" in use')

@app.on_event("startup")
@repeat_every(seconds=60 * 60 * 4)
async def update():
    """ 1. scrape twitter for police use of force
        2. deduplicate data based on tweet id
        3. insert data into database
        4. repeat every 4 hours """
    if lock.lock("db_update", 30) == True:
            logger.info('lock "db_update" created')
            # lock.delete('DatabaseState')
            search = choice((
                'police', 'pigs',
                'cops', 'ACAB', 'arrested',
                'police brutality',
                'police violence',
                'police abuse',
                'beaten', 'killed by police', 
                'taser', 'baton', 'use of force',
                'shot', 'lethal', 'non-lethal', 
                'pepper spray', 'oc', 'tear gas', 
                'rubber bullets', 'push', 
                'non-violent', 'tased', 'clashed with police',
                '#policebrutality', '#pig', '#pigs', 
                '#5-0', '#policeofficer', '#ACAB', 
                '#1312', '#fuckthepolice', 
                '#BlackLivesMatter', '#policeaccountability'
            ))
            data: List[Dict] = scrape_twitter(search)
            clean_data: List[Dict] = deduplicate(data)

            DB.insert_data_force_ranks(clean_data)

            data = DB.load_data_force_ranks()
            data = {e:DB.model_to_dict(i[0]) for (e,i) in enumerate(data)}
            data = json.dumps(data, default = str)
            lock.store('DatabaseState', data)
            logger.info('Stored DatabaseState in cache')

            lock.unlock("db_update")
            logger.info('lock "db_update" unlocked')
    else:
        logger.info('lock "db_update" in use')


app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],  # List of approved origins
    allow_credentials=True,  # Can only allow certain headers as well
    allow_methods=['*'],
    allow_headers=['*'],
)

if __name__ == '__main__':
    import uvicorn

    """ To run locally, use this command in the terminal:
    python3 -m app.main
    """
    uvicorn.run(app)
