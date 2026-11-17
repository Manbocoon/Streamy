import os, discord, logging, pytz, datetime, json, re
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHZZK_CLIENT_ID = os.getenv("CHZZK_CLIENT_ID")
CHZZK_CLIENT_SECRET = os.getenv("CHZZK_CLIENT_SECRET")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")

DATABASE_PATH = "database/bot.db"
CHECK_INTERVAL = 150
YOUTUBE_CHECK_INTERVAL = 150
TIMEZONE = pytz.timezone("Asia/Seoul")

# Discord Attributes
# ACTIVITY = discord.Activity(type=discord.ActivityType.watching, name="돌려줘요#1111")
ACTIVITY = None     #None #discord.Game(name="Update: 역할부여")
STATUS = discord.Status.online
OWNER_ID = 275158242517057538
BOT_ID = 1571927395194376342
INVITE_LINK = r"https://discord.com/oauth2/authorize?client_id=1571927395194376342"
