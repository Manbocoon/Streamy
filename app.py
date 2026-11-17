import sys
sys.dont_write_bytecode = True

import discord, time, logging
from modules.chzzk import ChzzkMonitor
from discord.ext import commands

from config import (
    DISCORD_TOKEN,
    DEV_GUILD_ID,
    YOUTUBE_CHECK_INTERVAL,
    CHECK_INTERVAL
)

from database.database import Database
from modules.youtube import YouTubeMonitor
from time_utils import KSTLogFilter

# 한국 표준시(KST, UTC+9) 적용
logging.Formatter.converter = lambda *args: time.gmtime(
    time.time() + 9 * 60 * 60
)

logging.basicConfig(
    level=logging.INFO,     # DEBUG 단계에서는 logging.DEBUG로 변경 시 각종 로그 출력됨
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

for handler in logging.getLogger().handlers:
    handler.addFilter(KSTLogFilter())




# Discord ChatBot
class StreamyBot(commands.Bot):

    def __init__(self):

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents
        )

        self.youtube_monitor = None
        self.chzzk_monitor = None

    async def setup_hook(self):

        db = Database()
        await db.initialize()

        # 명령어 모듈
        await self.load_extension("modules.commands")

        # YouTube 감시 모듈
        self.youtube_monitor = YouTubeMonitor(
            self,
            interval=YOUTUBE_CHECK_INTERVAL
        )

        # Chzzk 감시 모듈
        self.chzzk_monitor = ChzzkMonitor(
            self,
            interval=CHECK_INTERVAL
        )

        self.youtube_monitor.start()
        self.chzzk_monitor.start()

        # 슬래시 명령어 동기화
        if DEV_GUILD_ID:

            guild = discord.Object(
                id=int(DEV_GUILD_ID)
            )

            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

            print("개발 서버 명령어 동기화 완료")

        else:

            await self.tree.sync()

            print("전역 명령어 동기화 완료")

    async def on_ready(self):

        print("=" * 40)
        print("Streamy 로그인 완료")
        print(f"봇 이름: {self.user}")
        print(f"봇 ID: {self.user.id}")
        print(f"접속 서버: {len(self.guilds)}개")
        print(
            f"YouTube 감지 주기: "
            f"{YOUTUBE_CHECK_INTERVAL}초"
        )
        print("=" * 40)

    async def close(self):

        if self.chzzk_monitor:
            await self.chzzk_monitor.stop()

        if self.youtube_monitor:
            await self.youtube_monitor.stop()

        await super().close()


if __name__ == "__main__":

    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN이 설정되지 않았습니다."
        )

    bot = StreamyBot()
    bot.run(DISCORD_TOKEN)
