
import asyncio
import logging
import re
import xml.etree.ElementTree as ET

import aiohttp
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from database.database import Database
from modules.notifier import (
    send_live_notification,
    send_video_notification
)
from datetime import datetime, timedelta, timezone

ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"

logger = logging.getLogger("Streamy.YouTube")

class YtDlpLogger:

    def debug(self, message):
        pass

    def warning(self, message):
        logger.warning("yt-dlp 경고: %s", message)

    def error(self, message):
        # 정상적인 비라이브 상태 메시지는 무시
        if "The channel is not currently live" in message:
            return

        # 실제 오류는 extract_live의 예외 처리에서 기록



class YouTubeMonitor:

    def __init__(self, bot, interval=180):
        self.bot = bot
        self.db = Database()
        self.interval = interval
        self.task = None
        self.session = None

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
            "YouTube 감시 시작 - 주기: %s초",
            self.interval
        )

        timeout = aiohttp.ClientTimeout(total=20)

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                )
            }
        )

        try:
            while True:
                try:
                    await self.check_all()
                except Exception:
                    logger.exception("YouTube 전체 감시 오류")

                await asyncio.sleep(self.interval)

        finally:
            if self.session and not self.session.closed:
                await self.session.close()

    async def check_all(self):

        subscriptions = await self.db.get_all_subscriptions(
            "youtube"
        )

        """
        logger.info(
            "YouTube 등록 채널 %s개 확인",
            len(subscriptions)
        )
        """
        
        for sub in subscriptions:

            try:
                await self.check_channel(sub)

            except Exception:
                logger.exception(
                    "YouTube 채널 확인 실패: %s",
                    sub["channel_id"]
                )

            # 채널별 요청 간격
            await asyncio.sleep(1)

    @staticmethod
    def normalize_channel_id(value):

        value = str(value).strip()

        match = re.search(
            r"UC[a-zA-Z0-9_-]{20,}",
            value
        )

        if not match:
            raise ValueError(
                "유튜브 채널 ID는 UC로 시작하는 채널 ID여야 합니다."
            )

        return match.group(0)

    async def fetch_feed(self, channel_id):

        url = FEED_URL.format(channel_id)

        for attempt in range(3):

            try:
                async with self.session.get(url) as response:

                    if response.status != 200:
                        raise RuntimeError(
                            f"YouTube 피드 HTTP 오류: {response.status}"
                        )

                    xml_data = await response.text()

                root = ET.fromstring(xml_data)

                entries = []

                for entry in root.findall(
                    f"{{{ATOM_NS}}}entry"
                ):

                    video_id = entry.findtext(
                        f"{{{YT_NS}}}videoId"
                    )

                    title = entry.findtext(
                        f"{{{ATOM_NS}}}title"
                    )

                    published = entry.findtext(
                        f"{{{ATOM_NS}}}published"
                    )

                    link = entry.find(
                        f"{{{ATOM_NS}}}link"
                    )

                    if not video_id or not published:
                        continue

                    try:
                        published_dt = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )

                        if published_dt.tzinfo is None:
                            published_dt = published_dt.replace(
                                tzinfo=timezone.utc
                            )

                        published_dt = published_dt.astimezone(
                            timezone.utc
                        )

                    except ValueError:
                        logger.warning(
                            "YouTube 게시 시각 파싱 실패: %s (%s)",
                            video_id,
                            published
                        )
                        continue

                    entries.append({
                        "video_id": video_id,
                        "title": title or "제목 없음",
                        "published": published_dt.isoformat(),
                        "url": (
                            link.get("href")
                            if link is not None
                            else f"https://www.youtube.com/watch?v={video_id}"
                        ),
                        "thumbnail": (
                            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        )
                    })

                return entries

            except Exception as e:

                logger.warning(
                    "YouTube 피드 요청 실패 (%s/3): %s",
                    attempt + 1,
                    e
                )

                if attempt < 2:
                    await asyncio.sleep(10 * (attempt + 1))

        raise RuntimeError("YouTube 피드 요청 3회 실패")


    async def is_shorts(self, video_id):
        """
        YouTube 쇼츠 URL의 리다이렉트 결과로 동영상 종류를 판별합니다.

        반환값:
            True  = 쇼츠
            False = 일반 동영상
            None  = 판별 실패
        """

        url = f"https://www.youtube.com/shorts/{video_id}"

        try:
            async with self.session.get(
                url,
                allow_redirects=True
            ) as response:

                final_path = response.url.path.lower()

                if "/shorts/" in final_path:
                    return True

                if "/watch" in final_path:
                    return False

                logger.warning(
                    "YouTube 동영상 종류 판별 실패: %s (%s)",
                    video_id,
                    response.url
                )

                return None

        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.warning(
                "YouTube 쇼츠 판별 요청 실패: %s",
                video_id
            )
            return None



    @staticmethod
    def extract_live(channel_id):

        url = (
            f"https://www.youtube.com/channel/"
            f"{channel_id}/live"
        )

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 25,
            "logger": YtDlpLogger()
        }

        try:
            with YoutubeDL(options) as ydl:

                info = ydl.extract_info(
                    url,
                    download=False
                )

            if not info:
                return False, None

            is_live = (
                info.get("is_live") is True
                or info.get("live_status") == "is_live"
            )

            if not is_live:
                return True, None

            return True, {
                "live_id": str(info.get("id")),
                "title": info.get("title") or "제목 없음",
                "url": (
                    info.get("webpage_url")
                    or url
                ),
                "thumbnail": info.get("thumbnail")
            }

        except DownloadError as e:

            error_message = str(e)

            if "The channel is not currently live" in error_message:
                return True, None

            logger.warning(
                "YouTube 라이브 정보 추출 실패: %s",
                error_message
            )

            return False, None

        except Exception:
            logger.exception(
                "YouTube 라이브 추출 중 오류"
            )

            return False, None



    async def check_channel(self, sub):

        guild_id = sub["guild_id"]
        subscription_id = sub["id"]

        channel_id = self.normalize_channel_id(
            sub["channel_id"]
        )

        streamer_name = (
            sub["display_name"]
            or channel_id
        )

        state = await self.db.get_youtube_state(
            subscription_id
        )

        initialized = (
            bool(state["initialized"])
            if state else False
        )

        last_video_id = (
            state["last_video_id"]
            if state else None
        )

        last_published = (
            state["last_published"]
            if state else None
        )

        previous_live_id = (
            state["live_video_id"]
            if state else None
        )

        # 유튜버 등록 시각 가져오기
        registered_at = datetime.fromisoformat(
            sub["created_at"]
        )

        if registered_at.tzinfo is None:
            registered_at = registered_at.replace(
                tzinfo=timezone.utc
            )

        registered_at = registered_at.astimezone(
            timezone.utc
        )


        # 1. 새 동영상 감지
        try:
            entries = await self.fetch_feed(channel_id)

            if entries:

                # 게시 시각을 기준으로 가장 최신 영상 확인
                for entry in entries:
                    entry["published_dt"] = datetime.fromisoformat(
                        entry["published"]
                    )

                latest_entry = max(
                    entries,
                    key=lambda x: x["published_dt"]
                )

                latest_published = latest_entry["published"]
                last_video_id = latest_entry["video_id"]

                logger.debug(
                    "[YouTube DEBUG] 채널=%s | "
                    "DB 게시 시각=%s | 최신 게시 시각=%s | "
                    "등록 시각=%s",
                    streamer_name,
                    last_published,
                    latest_published,
                    registered_at.isoformat()
                )

                # 최초 초기화 또는 기존 DB 마이그레이션
                if not initialized or not last_published:

                    # 등록 시각을 최초 게시 시각 기준으로 설정
                    last_published = registered_at.isoformat()

                    initialized = True

                    logger.info(
                        "YouTube 등록 시각 기준 초기화 완료: %s",
                        streamer_name
                    )

                else:

                    last_published_dt = datetime.fromisoformat(
                        last_published
                    )

                    if last_published_dt.tzinfo is None:
                        last_published_dt = last_published_dt.replace(
                            tzinfo=timezone.utc
                        )

                    last_published_dt = last_published_dt.astimezone(
                        timezone.utc
                    )

                # 마지막 확인 시각보다 7일 이전까지 검사
                # 단, 유튜버 등록 시각 이전 영상은 절대 제외
                cutoff_dt = max(
                    datetime.fromisoformat(last_published).replace(
                        tzinfo=timezone.utc
                    ) - timedelta(days=7),
                    registered_at
                )

                # 등록 시각 이후의 영상만 후보로 선정
                candidates = [
                    entry
                    for entry in entries
                    if (
                        entry["published_dt"] > registered_at
                        and entry["published_dt"] >= cutoff_dt
                    )
                ]

                # 오래된 영상부터 순서대로 처리
                candidates.sort(
                    key=lambda x: x["published_dt"]
                )

                candidate_ids = [
                    entry["video_id"]
                    for entry in candidates
                ]

                processed_ids = (
                    await self.db.get_youtube_processed_video_ids(
                        subscription_id,
                        candidate_ids
                    )
                )

                new_count = 0

                for entry in candidates:

                    video_id = entry["video_id"]

                    # 이미 처리한 영상이면 생략
                    if video_id in processed_ids:
                        continue

                    # 동영상 알림 OFF면 처리 완료로 기록
                    if not bool(sub["video_enabled"]):

                        await self.db.mark_youtube_video_processed(
                            subscription_id,
                            video_id,
                            entry["published"]
                        )

                        processed_ids.add(video_id)
                        continue

                    video_type = sub["video_type"]

                    # 쇼츠 / 일반 동영상 필터
                    if video_type != "all":

                        is_shorts = await self.is_shorts(
                            video_id
                        )

                        # 판별 실패 시 다음 검사에서 재시도
                        if is_shorts is None:
                            logger.warning(
                                "동영상 종류 미확인으로 처리 보류: %s",
                                video_id
                            )
                            continue

                        if video_type == "shorts" and not is_shorts:
                            await self.db.mark_youtube_video_processed(
                                subscription_id,
                                video_id,
                                entry["published"]
                            )

                            processed_ids.add(video_id)
                            continue

                        if video_type == "normal" and is_shorts:
                            await self.db.mark_youtube_video_processed(
                                subscription_id,
                                video_id,
                                entry["published"]
                            )

                            processed_ids.add(video_id)
                            continue

                    # Discord 알림 전송
                    sent = await send_video_notification(
                        self.bot,
                        guild_id,
                        streamer_name,
                        entry["title"],
                        entry["url"],
                        entry["thumbnail"],
                        channel_url=(
                            f"https://www.youtube.com/channel/{channel_id}"
                        )
                    )

                    # 전송 성공한 경우에만 처리 완료 기록
                    if sent:

                        await self.db.mark_youtube_video_processed(
                            subscription_id,
                            video_id,
                            entry["published"]
                        )

                        processed_ids.add(video_id)
                        new_count += 1

                        logger.info(
                            "YouTube 새 동영상 업로드 감지: %s - %s",
                            streamer_name,
                            entry["title"]
                        )

                    else:

                        logger.warning(
                            "YouTube 동영상 알림 전송 실패. "
                            "다음 검사에서 재시도: %s",
                            video_id
                        )

                # 마지막 게시 시각은 절대 과거로 되돌리지 않음
                latest_published_dt = datetime.fromisoformat(
                    latest_published
                )

                if latest_published_dt.tzinfo is None:
                    latest_published_dt = latest_published_dt.replace(
                        tzinfo=timezone.utc
                    )

                latest_published_dt = latest_published_dt.astimezone(
                    timezone.utc
                )

                current_last_published_dt = datetime.fromisoformat(
                    last_published
                )

                if current_last_published_dt.tzinfo is None:
                    current_last_published_dt = (
                        current_last_published_dt.replace(
                            tzinfo=timezone.utc
                        )
                    )

                current_last_published_dt = (
                    current_last_published_dt.astimezone(
                        timezone.utc
                    )
                )

                if latest_published_dt < current_last_published_dt:
                    latest_published = (
                        current_last_published_dt.isoformat()
                    )

                await self.db.save_youtube_published_state(
                    subscription_id,
                    latest_published
                )

                last_published = latest_published

                logger.debug(
                    "[YouTube DEBUG] 채널=%s | "
                    "후보=%s개 | 신규 전송=%s개 | "
                    "최신 게시 시각=%s",
                    streamer_name,
                    len(candidates),
                    new_count,
                    last_published
                )

        except Exception:

            logger.exception(
                "YouTube 업로드 확인 실패: %s",
                streamer_name
            )

        # 2. 라이브 방송 감지
        live_ok, live_info = await asyncio.wait_for(
            asyncio.to_thread(
                self.extract_live,
                channel_id
            ),
            timeout=45
        )

        # 추출 자체가 실패한 경우 기존 상태 유지
        if not live_ok:
            await self.db.save_youtube_state(
                subscription_id,
                last_video_id,
                previous_live_id,
                initialized
            )
            return


        current_live_id = (
            live_info["live_id"]
            if live_info else None
        )


        if current_live_id:

            if current_live_id != previous_live_id:

                if bool(sub["live_enabled"]):

                    await send_live_notification(
                        self.bot,
                        guild_id,
                        "youtube",
                        streamer_name,
                        live_info["title"],
                        live_info["url"],
                        live_info["thumbnail"],
                        channel_url=(
                            f"https://www.youtube.com/channel/{channel_id}"
                        )
                    )

                    logger.info(
                        "YouTube 라이브 시작: %s",
                        streamer_name
                    )
                else:
                    logger.info(
                        "YouTube 라이브 알림 OFF 상태로 전송 생략: %s",
                        streamer_name
                    )


        elif previous_live_id:

            logger.info(
                "YouTube 라이브 종료: %s",
                streamer_name
            )

        # 라이브 상태 갱신
        previous_live_id = current_live_id

        # YouTube 감시 상태 DB 저장
        await self.db.save_youtube_state(
            subscription_id,
            last_video_id,
            previous_live_id,
            initialized
        )

