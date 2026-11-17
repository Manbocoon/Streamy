
import asyncio
import logging

import aiohttp

from database.database import Database
from modules.notifier import send_live_notification


logger = logging.getLogger("Streamy.Chzzk")

BASE_URL = "https://api.chzzk.naver.com"


class ChzzkMonitor:

    def __init__(self, bot, interval=60):
        self.bot = bot
        self.db = Database()
        self.interval = interval
        self.session = None
        self.task = None

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        if self.session and not self.session.closed:
            await self.session.close()

    async def run(self):
        logger.info(
            "치지직 감시 시작 - 주기: %s초",
            self.interval
        )

        timeout = aiohttp.ClientTimeout(total=15)

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                ),
                "Referer": "https://chzzk.naver.com/"
            }
        )

        try:
            while True:
                try:
                    await self.check_all()
                except Exception:
                    logger.exception("치지직 전체 감시 오류")

                await asyncio.sleep(self.interval)

        finally:
            if self.session and not self.session.closed:
                await self.session.close()

    async def get_live_detail(self, channel_id):
        url = (
            f"{BASE_URL}/service/v3.3/channels/"
            f"{channel_id}/live-detail"
        )

        try:
            async with self.session.get(url) as response:

                if response.status == 404:
                    logger.warning(
                        "치지직 채널을 찾을 수 없음: %s",
                        channel_id
                    )
                    return False, None

                if response.status == 429:
                    logger.warning(
                        "치지직 요청 제한 발생: %s",
                        channel_id
                    )
                    return False, None

                if response.status != 200:
                    logger.warning(
                        "치지직 HTTP 오류: %s (%s)",
                        channel_id,
                        response.status
                    )
                    return False, None

                data = await response.json()

            if data.get("code") != 200:
                logger.warning(
                    "치지직 API 응답 오류: %s",
                    data.get("message")
                )
                return False, None

            content = data.get("content")

            if not isinstance(content, dict):
                logger.warning(
                    "치지직 방송 정보 없음: channel=%s, code=%s, message=%s, content=%s",
                    channel_id,
                    data.get("code"),
                    data.get("message"),
                    content
                )
                return False, None

            status = content.get("status")

            if status in ("CLOSED", "CLOSE"):
                return True, None

            if status != "OPEN":
                logger.warning(
                    "알 수 없는 치지직 방송 상태: %s",
                    status
                )
                return False, None

            live_id = content.get("liveId")

            if live_id is None:
                return False, None

            channel = content.get("channel") or {}

            thumbnail = (
                content.get("liveThumbnailImageUrl")
                or content.get("liveImageUrl")
                or content.get("defaultThumbnailImageUrl")
            )

            if thumbnail:
                thumbnail = thumbnail.replace(
                    "{type}", "720"
                )

            return True, {
                "live_id": str(live_id),
                "title": content.get("liveTitle") or "제목 없음",
                "channel_name": (
                    channel.get("channelName")
                    or content.get("channelName")
                    or channel_id
                ),
                "thumbnail": thumbnail,
                "url": f"https://chzzk.naver.com/live/{channel_id}"
            }

        except asyncio.TimeoutError:
            logger.warning(
                "치지직 요청 시간 초과: %s",
                channel_id
            )
            return False, None

        except aiohttp.ClientError:
            logger.exception(
                "치지직 네트워크 오류: %s",
                channel_id
            )
            return False, None

        except Exception:
            logger.exception(
                "치지직 방송 정보 조회 실패: %s",
                channel_id
            )
            return False, None

    async def check_all(self):

        subscriptions = await self.db.get_all_subscriptions(
            "chzzk"
        )

        """
        logger.info(
            "치지직 등록 채널 %s개 확인",
            len(subscriptions)
        )
        """

        for sub in subscriptions:

            try:
                await self.check_channel(sub)

            except Exception:
                logger.exception(
                    "치지직 채널 감시 오류: %s",
                    sub["channel_id"]
                )

            # 요청을 너무 빠르게 연속 전송하지 않도록 대기
            await asyncio.sleep(1)

    async def check_channel(self, sub):

        subscription_id = sub["id"]
        guild_id = sub["guild_id"]
        channel_id = sub["channel_id"]

        display_name = (
            sub["display_name"]
            or channel_id
        )

        # 로깅
        """
        logger.info(
            "치지직 채널 검사 시작: ID=%s, 이름=%s, 구독ID=%s",
            channel_id,
            display_name,
            subscription_id
        )
        """

        # 방송 정보 조회
        success, live_info = await self.get_live_detail(
            channel_id
        )

        # 치지직 조회 결과 로깅
        """
        logger.info(
            "치지직 조회 결과: ID=%s, success=%s, live=%s",
            channel_id,
            success,
            bool(live_info)
        )
        """

        # 조회 실패 시 기존 상태 유지
        if not success:
            return

        # 이전 방송 상태
        state = await self.db.get_chzzk_state(
            subscription_id
        )

        previous_live_id = (
            state["live_id"]
            if state else None
        )

        initialized = (
            bool(state["initialized"])
            if state else False
        )

        current_live_id = (
            live_info["live_id"]
            if live_info else None
        )

        # 최초 등록 또는 최초 감시
        if not initialized:

            # 이미 방송 중이라면 라이브 알림 설정 확인
            if current_live_id and bool(sub["live_enabled"]):

                logger.info(
                    "치지직 최초 등록 시 방송 중 확인: %s",
                    display_name
                )

                sent = await send_live_notification(
                    self.bot,
                    guild_id,
                    "chzzk",
                    display_name,
                    live_info["title"],
                    live_info["url"],
                    live_info["thumbnail"],
                    channel_url=f"https://chzzk.naver.com/{channel_id}"
                )

                if not sent:
                    logger.warning(
                        "치지직 최초 알림 전송 실패: %s",
                        display_name
                    )
                    return


            # 방송 상태 저장
            await self.db.save_chzzk_state(
                subscription_id,
                current_live_id,
                1
            )

            
            logger.info(
                "치지직 최초 상태 저장: %s (방송 중: %s)",
                display_name,
                bool(current_live_id)
            )
            

            return


        # 새로운 방송 시작
        if (
            current_live_id
            and current_live_id != previous_live_id
        ):

            if bool(sub["live_enabled"]):

                sent = await send_live_notification(
                    self.bot,
                    guild_id,
                    "chzzk",
                    display_name,
                    live_info["title"],
                    live_info["url"],
                    live_info["thumbnail"],
                    channel_url=f"https://chzzk.naver.com/{channel_id}"
                )

                if not sent:
                    logger.warning(
                        "치지직 알림 전송 실패. 다음 주기에 재시도: %s",
                        display_name
                    )
                    return

                logger.info(
                    "치지직 방송 시작 감지: %s",
                    display_name
                )

            else:
                logger.info(
                    "치지직 라이브 알림 OFF 상태로 전송 생략: %s",
                    display_name
                )


        # 방송 종료 또는 현재 방송 없음
        elif previous_live_id and not current_live_id:

            logger.info(
                "치지직 방송 종료 감지: %s",
                display_name
            )

        # 상태 저장
        await self.db.save_chzzk_state(
            subscription_id,
            current_live_id,
            1
        )
