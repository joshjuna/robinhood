# main.py
import time
from datetime import datetime
import json
import math
import os

import logger
import pyotp
import robin_stocks.robinhood as rh

from fastapi import FastAPI, Request
import boto3

app = FastAPI(title="Robinhood Server")
logger = logger.Logger("main").get()
config_file = open('config.json')
config = json.loads(config_file.read())
config_file.close()

is_test = True if (config['is_test'] != "false") else False


class SymbolStatus:
    def __init__(self, symbol):
        self.symbol = symbol
        position = robin_get_position(self.symbol)
        if position is None:
            logger.debug("position is None")
            self.state = "SOLD"
            self.qty = 0
            self.time = None
        else:
            self.qty = math.floor(float(position['shares_available_for_exercise']))
            if self.qty < 1:
                logger.debug("shares_available_for_exercise < 1")
                self.state = "SOLD"
                self.qty = 0
                self.time = None
            else:
                self.state = "BOUGHT"
                self.price = position['average_buy_price']

        json_status = load_state(symbol)

        if json_status is not None:
            self.state = json_status['state']
            try:
                self.price = json_status['price']
            except KeyError:
                self.price = 0.0
            try:
                self.time = json_status['time']
            except KeyError:
                self.time = None

    def __str__(self):
        return json.dumps(self.__dict__)


class Alert:
    def __init__(self, alert_text):
        self.symbol = alert_text['symbol']
        self.action = alert_text['action']
        if self.action == "NMACD":
            self.plot = alert_text['plot']
            if self.plot > 0:
                self.action = "NMACD_READY"
            elif self.plot < 0:
                self.action = "SELL"

        self.interval = int(alert_text['interval'])
        self.qty = int(alert_text['qty'])
        try:
            self.price = alert_text['price']
        except KeyError:
            self.price = None
        try:
            self.time = alert_text['time']
        except KeyError:
            self.time = None

    def __str__(self):
        return json.dumps(self.__dict__)


@app.post("/robin")
async def robin(info: Request):
    try:
        alert_message = await info.json()
        logger.info("****************************************")
        logger.debug("Request: {}".format(info.__dict__))

        logger.debug("Request Message: {}".format(alert_message))

        if not is_test:
            logger.info("Running as Production")
        else:
            logger.info("Running as Testing")

        await login()

        alert = Alert(alert_message)
        logger.info("Alert: {}".format(alert.__dict__))

        symbol_state = SymbolStatus(alert.symbol)
        logger.info("Symbol State: {}".format(symbol_state.__dict__))

        process_alert(alert, symbol_state)

        store_state(symbol_state)

        return {
            "status": "SUCCESS"
        }
    except Exception as e:
        logger.info("ERROR: {}".format(e))


def process_alert(alert, symbol_state):
    logger.debug("process_alert. symbol_state: {} => alert_action:{}".format(symbol_state.state, alert.action))
    if alert.action == 'READY_BB' or alert.action == "READY_5in1":
        process_ready_bb_or_5in1(alert, symbol_state)

    if alert.action == 'READY_NMACD':
        process_ready_nmacd(alert, symbol_state)

    if alert.action == 'SELL':
        process_sell(alert, symbol_state)


def process_ready_bb_or_5in1(alert, symbol_state):
    logger.debug('process_ready_bb_or_5in1')
    # SOLD to READY
    # We will record the time, if the BUY signal comes within 1-2 datapoints, we will BUY
    # OR READY_BB/READY_5in1 to READY_BB/READY_5in1
    # It is another READY signal, we update the time and action to match the new finding

    if symbol_state.state == "SOLD" or symbol_state.state == "READY_5in1" or symbol_state.state == "READY_BB":
        symbol_state.state = alert.action
        symbol_state.time = alert.time


    # READY_BUY to READY
    # This means we got a BUY signal just before the READY Signal. If it was 1-2 Datapoints earlier, we will BUY
    elif symbol_state.state == "READY_NMACD":
        if date_diff(alert.time, symbol_state.time) <= 5 * alert.interval:
            symbol_state.price = robin_buy(alert.symbol, alert.price, alert.qty)
            symbol_state.time = alert.time
            symbol_state.state = "BOUGHT"
        else:
            logger.debug("Ready alert expired - 5 * alert.interval")
            symbol_state.time = alert.time
            symbol_state.state = alert.action

    # BOUGHT to READY
    # We have the holding, we ignore this


def process_ready_nmacd(alert, symbol_state):
    logger.debug('process_ready_nmacd')
    # READY to BUY
    # We check if the Ready signal was a while back, and if good, we are a buy
    if symbol_state.state == "READY_BB" or symbol_state.state == "READY_5in1":
        if date_diff(alert.time, symbol_state.time) <= 2 * alert.interval:
            symbol_state.state = "BOUGHT"
            symbol_state.time = alert.time
            symbol_state.price = robin_buy(alert.symbol, alert.price, alert.qty)
        else:
            logger.debug("Ready alert expired - 2 * alert.interval")
            symbol_state.state = alert.action
            symbol_state.time = alert.time
    elif symbol_state.state == "READY_NMACD":
        symbol_state.time = alert.time
    elif symbol_state.state == "SOLD":
        symbol_state.state = alert.action
        symbol_state.time = alert.time
    elif symbol_state.state == "BOUGHT":
        pass
    logger.debug("Processed State: {}".format(symbol_state.__dict__))


def process_sell(alert, symbol_state):
    logger.debug('process_sell')
    if symbol_state.state == "BOUGHT":
        robin_sell(alert, symbol_state)
        symbol_state.state = "SOLD"
        symbol_state.time = alert.time
    else:
        symbol_state.state = "SOLD"
        logger.debug("We have nothing to SELL")


def store_state(symbol_state):
    f = open(symbol_state.symbol + ".status", "w")
    f.write(json.dumps(symbol_state.__dict__))
    logger.info("Saved Symbol State: {}".format(symbol_state.__dict__))
    f.close()

    if not is_test and (symbol_state.state == "SOLD" or symbol_state.state == "BOUGHT"):
        logger.debug("Deleting the status for SOLD/BOUGHT in Production")
        try:
            os.remove(symbol_state.symbol + ".status")
        except Exception as e:
            logger.info("Error in deleting the file - {}".format(e))


def load_state(symbol):
    logger.debug("load_state")
    try:
        f = open(symbol + ".status", "r")
        json_status = json.loads(f.read())
        f.close()
    except FileNotFoundError:
        json_status = None
    logger.debug("load_state: {}".format(json_status))
    return json_status


async def login():
    totp = pyotp.TOTP(config['pyotp']).now()
    rh.login(config['username'], config['password'], store_session=True, mfa_code=totp)


def robin_buy(symbol, price, qty):
    logger.debug("robin_buy {} at price: {}".format(symbol, price))
    if not is_test:
        logger.info("Placing BUY Order for {} at price: {}".format(symbol, price))
        order_result = rh.order_buy_limit(
            symbol=symbol,
            quantity=qty,
            limitPrice=price * 1.001,
            timeInForce='gfd',
            extendedHours=True,
            jsonify=True)
        logger.debug(order_result)
        time.sleep(5)
        order_status = rh.get_stock_order_info(order_result['id'])
        logger.debug(order_status)
        logger.info("BUY Order Status: {}, qty: {}, price: {}".format(order_status['state'], order_status['quantity'],
                                                                      order_status['average_price']))
        return order_status['average_price']
    else:
        return price


def robin_sell(alert, symbol_state):
    logger.info("Place SELL Order for {} at price: {}".format(alert.symbol, alert.price))
    if not is_test:
        try:
            sell_qty = alert.qty if (alert.qty >= symbol_state.qty) else symbol_state.qty

            order_result = rh.order_sell_market(
                symbol=alert.symbol,
                quantity=sell_qty,
                timeInForce='gfd',
                extendedHours=True,
                jsonify=True)
            logger.debug(order_result)

            time.sleep(5)
            order_status = rh.get_stock_order_info(order_result['id'])
            logger.info(
                "SELL Order Status: {}, qty: {}, price: {}".format(order_status['state'], order_status['quantity'],
                                                                   order_status['average_price']))
            symbol_state.price = order_status['average_price']
        except Exception as e:
            logger.info("Something went wrong placing the sell order - {}".format(e))


def robin_get_position(symbol):
    instrument = rh.get_instruments_by_symbols([symbol])
    instrument_id = instrument[0]['id']

    stock_positions = rh.get_open_stock_positions()

    for stock_position in stock_positions:
        if stock_position['instrument_id'] == instrument_id:
            logger.debug('stock_position: {}'.format(stock_position))
            return stock_position

    logger.debug('stock_position: {}'.format(None))
    return None


def date_diff(date_2, date_1):
    date_time_obj_1 = datetime.strptime(date_1, '%Y-%m-%dT%H:%M:%SZ')
    date_time_obj_2 = datetime.strptime(date_2, '%Y-%m-%dT%H:%M:%SZ')

    c = date_time_obj_2 - date_time_obj_1
    logger.info("DateDiff: {} - {} = {}".format(date_time_obj_2, date_time_obj_1, (c.seconds / 60)))
    return c.seconds / 60


@app.post("/place_order")
async def place_order(info: Request):
    logger.info("*********************************")
    logger.info("Raw Request: {}".format(info.__dict__))
    req = await info.json()
    logger.info("Request: {}".format(req))
    await login()

    symbol = req['symbol']
    price = req['price']
    qty = req['qty']
    buy_plot = req['buy_plot']

    current_position = robin_get_position(symbol)
    action = "buy" if (buy_plot > 0) else "sell"

    if action == "buy":
        if current_position is None or (math.floor(float(current_position['quantity'])) < 1 and math.floor(
                float(current_position['shares_held_for_buys'])) < 1):
            return robin_buy(symbol, price, qty)
        else:
            logger.info("Already BOUGHT")
            return "Already BOUGHT"
    elif action == "sell":
        if current_position is not None and math.floor(float(current_position['shares_available_for_exercise'])) >= qty:
            return robin_sell(symbol, price, qty)
        else:
            logger.info("Nothing to SELL")
            return "Nothing to SELL"


@app.post("/get_position")
async def get_position(info: Request):
    req = await info.json()
    symbol = req['symbol']

    await login()

    return robin_get_position(symbol)


@app.post("/email")
async def email(info: Request):
    req = await info.json()
    ses_client = boto3.client("ses", region_name="us-west-2")

    CHARSET = "UTF-8"
    response = ses_client.send_email(
        Destination={
            "ToAddresses": [
                "joshjuna@gmail.com",
            ],
        },
        Message={
            "Body": {
                "Text": {
                    "Charset": CHARSET,
                    "Data": "Hello, world!",
                }
            },
            "Subject": {
                "Charset": CHARSET,
                "Data": "Amazing Email Tutorial",
            },
        },
        Source="joshjuna@gmail.com",
    )
    print(response)
