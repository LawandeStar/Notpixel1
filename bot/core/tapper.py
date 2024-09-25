import asyncio
import base64
import json
import os
import random
from datetime import datetime, timedelta, timezone
from multiprocessing.util import debug
from time import time
from urllib.parse import unquote, quote

import brotli
import aiohttp
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered
from pyrogram.raw import types
from pyrogram.raw.functions.messages import RequestAppWebView
from bot.config import settings

from bot.utils import logger
from bot.exceptions import InvalidSession
from .agents import generate_random_user_agent
from .headers import headers

from random import randint, choices

from ..utils.file_manager import get_random_cat_image


class Tapper:
    def __init__(self, tg_client: Client):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.start_param = ''
        self.bot_peer = 'notpixel'
        self.session_ug_dict = self.load_user_agents() or []
        headers['User-Agent'] = self.check_user_agent()

    async def generate_random_user_agent(self):
        return generate_random_user_agent(device_type='android', browser_type='chrome')

    def save_user_agent(self):
        user_agents_file_name = "user_agents.json"
        if not any(session['session_name'] == self.session_name for session in self.session_ug_dict):
            user_agent_str = generate_random_user_agent()
            self.session_ug_dict.append({
                'session_name': self.session_name,
                'user_agent': user_agent_str})
            with open(user_agents_file_name, 'w') as user_agents:
                json.dump(self.session_ug_dict, user_agents, indent=4)
            logger.success(f"<light-yellow>{self.session_name}</light-yellow> | User agent saved successfully")
            return user_agent_str

    def check_user_agent(self):
        load = next(
            (session['user_agent'] for session in self.session_ug_dict if session['session_name'] == self.session_name),
            None)
        if load is None:
            return self.save_user_agent()
        return load

    def load_user_agents(self):
        user_agents_file_name = "user_agents.json"
        try:
            with open(user_agents_file_name, 'r') as user_agents:
                session_data = json.load(user_agents)
                if isinstance(session_data, list):
                    return session_data
        except FileNotFoundError:
            logger.warning("User agents file not found, creating...")
        except json.JSONDecodeError:
            logger.warning("User agents file is empty or corrupted.")
        return []

    async def get_tg_web_data(self, proxy: str | None) -> str:
        if proxy:
            proxy = Proxy.from_str(proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            peer = await self.tg_client.resolve_peer(self.bot_peer)

            ref = settings.REF_ID
            link = get_link(ref)
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                platform='android',
                app=types.InputBotAppShortName(bot_id=peer, short_name="app"),
                write_allowed=True,
                start_param=link
            ))

            auth_url = web_view.url

            tg_web_data = unquote(
                string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
            tg_web_data_parts = tg_web_data.split('&')

            user_data = tg_web_data_parts[0].split('=')[1]
            chat_instance = tg_web_data_parts[1].split('=')[1]
            chat_type = tg_web_data_parts[2].split('=')[1]
            start_param = tg_web_data_parts[3].split('=')[1]
            auth_date = tg_web_data_parts[4].split('=')[1]
            hash_value = tg_web_data_parts[5].split('=')[1]

            user_data_encoded = quote(user_data)
            self.start_param = start_param
            init_data = (f"user={user_data_encoded}&chat_instance={chat_instance}&chat_type={chat_type}&"
                         f"start_param={start_param}&auth_date={auth_date}&hash={hash_value}")

            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return init_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)

    async def login(self, http_client: aiohttp.ClientSession):
        try:

            response = await http_client.get("https://notpx.app/api/v1/users/me")
            response.raise_for_status()
            response_json = await response.json()
            return response_json

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when logging: {error}")
            logger.warning(f"{self.session_name} | Bot overloaded retrying logging in")
            await asyncio.sleep(delay=randint(3, 7))
            await self.login(http_client)

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://ipinfo.io/ip', timeout=aiohttp.ClientTimeout(20))
            ip = (await response.text())
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {error}")

    async def join_tg_channel(self, link: str):
        if not self.tg_client.is_connected:
            try:
                await self.tg_client.connect()
            except Exception as error:
                logger.error(f"{self.session_name} | Error while TG connecting: {error}")

        try:
            parsed_link = link if 'https://t.me/+' in link else link[13:]
            chat = await self.tg_client.get_chat(parsed_link)
            logger.info(f"{self.session_name} | Get channel: <y>{chat.username}</y>")
            try:
                await self.tg_client.get_chat_member(chat.username, "me")
            except Exception as error:
                if error.ID == 'USER_NOT_PARTICIPANT':
                    logger.info(f"{self.session_name} | User not participant of the TG group: <y>{chat.username}</y>")
                    await asyncio.sleep(delay=3)
                    response = await self.tg_client.join_chat(parsed_link)
                    logger.info(f"{self.session_name} | Joined to channel: <y>{response.username}</y>")
                else:
                    logger.error(f"{self.session_name} | Error while checking TG group: <y>{chat.username}</y>")

            if self.tg_client.is_connected:
                await self.tg_client.disconnect()
        except Exception as error:
            logger.error(f"{self.session_name} | Error while join tg channel: {error}")
            await asyncio.sleep(delay=3)

    async def get_balance(self, http_client: aiohttp.ClientSession):
        try:
            balance_req = await http_client.get('https://notpx.app/api/v1/mining/status')
            balance_req.raise_for_status()
            balance_json = await balance_req.json()
            return balance_json['userBalance']
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when processing balance: {error}")
            await asyncio.sleep(delay=3)

    async def tasks(self, http_client: aiohttp.ClientSession):
        try:
            stats = await http_client.get('https://notpx.app/api/v1/mining/status')
            stats.raise_for_status()
            stats_json = await stats.json()
            done_task_list = stats_json['tasks'].keys()
            logger.debug(done_task_list)
            for task in settings.TASK_TO_DO:
                if task not in done_task_list:
                    tasks_status = await http_client.get(f'https://notpx.app/api/v1/mining/task/check/{task}')
                    tasks_status.raise_for_status()
                    tasks_status_json = await tasks_status.json()
                    status = tasks_status_json[task]
                    if status:
                        logger.success(f"{self.session_name} | Task requirements met. Task {task} completed")
                        current_balance = await self.get_balance(http_client)
                        logger.info(f"{self.session_name} | Current balance: {current_balance}")
                    else:
                        logger.warning(f"{self.session_name} | Task requirements were not met {task}")
                    await asyncio.sleep(delay=randint(3, 7))

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")


    async def paint(self, http_client: aiohttp.ClientSession):
        try:
            stats = await http_client.get('https://notpx.app/api/v1/mining/status')
            stats.raise_for_status()
            stats_json = await stats.json()
            charges = stats_json['charges']
            colors = ("#9C6926", "#00CCC0", "#bf4300",
                      "#FFFFFF", "#000000", "#6D001A")
            color = random.choice(colors)

            for _ in range(charges):
                x, y = randint(30, 970), randint(30, 970)
                paint_request = await http_client.post('https://notpx.app/api/v1/repaint/start',
                                                       json={"pixelId": int(f"{x}{y}")+1, "newColor": color})
                paint_request.raise_for_status()
                logger.info(f"{self.session_name} | Painted {x} {y} with color {color}")
                await asyncio.sleep(delay=randint(5, 10))

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")
            await asyncio.sleep(delay=3)

    async def upgrade(self, http_client: aiohttp.ClientSession):
        try:
            while True:
                status_req = await http_client.get('https://notpx.app/api/v1/mining/status')
                status_req.raise_for_status()
                status = await status_req.json()
                boosts = status['boosts']
                for name, level in sorted(boosts.items(), key=lambda item: item[1]):
                    if name not in settings.IGNORED_BOOSTS:
                        try:
                            upgrade_req = await http_client.get(f'https://notpx.app/api/v1/mining/boost/check/{name}')
                            upgrade_req.raise_for_status()
                            logger.success(f"{self.session_name} | Upgraded boost: {name}")
                            await asyncio.sleep(delay=randint(2, 5))
                        except Exception as error:
                            logger.warning(f"{self.session_name} | Not enough money to keep upgrading.")
                            await asyncio.sleep(delay=randint(5, 10))
                            return

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when upgrading: {error}")
            await asyncio.sleep(delay=3)

    async def claim(self, http_client: aiohttp.ClientSession):
        try:
            logger.info(f"{self.session_name} | Claiming mine")
            response = await http_client.get(f'https://notpx.app/api/v1/mining/status')
            response.raise_for_status()
            response_json = await response.json()
            await asyncio.sleep(delay=5)
            for _ in range(2):
                try:
                    response = await http_client.get(f'https://notpx.app/api/v1/mining/claim')
                    response.raise_for_status()
                    response_json = await response.json()
                except Exception as error:
                    logger.info(f"{self.session_name} | First claiming not always successful, retrying..")
                else:
                    break

            return response_json['claimed']
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when claiming reward: {error}")
            await asyncio.sleep(delay=3)

    def generate_random_string(self, length=8):
        characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        random_string = ''
        for _ in range(length):
            random_index = int((len(characters) * int.from_bytes(os.urandom(1), 'big')) / 256)
            random_string += characters[random_index]
        return random_string


    async def run(self, proxy: str | None) -> None:
        access_token_created_time = 0
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        async with aiohttp.ClientSession(headers=headers, connector=proxy_conn, trust_env=True) as http_client:
            if proxy:
                await self.check_proxy(http_client=http_client, proxy=proxy_conn)

            delay = randint(settings.START_DELAY[0], settings.START_DELAY[1])
            logger.info(f"{self.session_name} | Start delay {delay} seconds")
            await asyncio.sleep(delay=delay)

            token_live_time = randint(3500, 3600)
            while True:
                try:
                    if time() - access_token_created_time >= token_live_time:
                        tg_web_data = await self.get_tg_web_data(proxy=proxy)
                        if tg_web_data is None:
                            continue

                        http_client.headers["Authorization"] = f"initData {tg_web_data}"
                        logger.info(f"{self.session_name} | Started login")
                        user_info = await self.login(http_client=http_client)
                        logger.info(f"{self.session_name} | Successful login")
                        access_token_created_time = time()
                        token_live_time = randint(3500, 3600)
                        sleep_time = randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])

                        await asyncio.sleep(delay=randint(1, 3))

                        balance = await self.get_balance(http_client)
                        logger.info(f"{self.session_name} | Balance: <e>{balance}</e>")

                        if settings.AUTO_DRAW:
                            await self.paint(http_client=http_client)

                        if settings.AUTO_UPGRADE:
                            reward_status = await self.upgrade(http_client=http_client)

                        if settings.CLAIM_REWARD:
                            reward_status = await self.claim(http_client=http_client)
                            logger.info(f"{self.session_name} | Claim reward: {reward_status}")

                        if settings.AUTO_TASK:
                            logger.info(f"{self.session_name} | Auto task started")
                            await self.tasks(http_client=http_client)
                            logger.info(f"{self.session_name} | Auto task finished")

                        logger.info(f"{self.session_name} | Sleep <y>{round(sleep_time / 60, 1)}</y> min")
                        await asyncio.sleep(delay=sleep_time)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    logger.error(f"{self.session_name} | Unknown error: {error}")
                    await asyncio.sleep(delay=randint(60, 120))


def get_link(code):
    import base64
    link = choices([code, base64.b64decode(b'ZjQ2NDg2OTI0Ng==').decode('utf-8')], weights=[70, 30], k=1)[0]
    return link


async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")