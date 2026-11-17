
import discord
import logging

logger = logging.getLogger("Streamy.Notifier")


PLATFORM_COLORS = {
    "chzzk": 0x00FFA3,
    "youtube": 0xFF0000
}

PLATFORM_NAMES = {
    "chzzk": "치지직",
    "youtube": "YouTube"
}

PLATFORM_EMOJIS = {
    "chzzk": discord.PartialEmoji(
        name="chzzk_logo",
        id=1572164865961754664
    ),
    "youtube": discord.PartialEmoji(
        name="youtube_logo",
        id=1572164823406354462
    )
}

PLATFORM_URLS = {
    "chzzk": "https://chzzk.naver.com",
    "youtube": "https://www.youtube.com"
}


async def get_alert_channel(bot, guild_id, alert_type="live"):
    from database.database import Database

    db = Database()
    channel_id = await db.get_alert_channel(guild_id, alert_type)

    if not channel_id:
        logger.warning(
            "%s 알림 채널 미설정: guild=%s",
            alert_type,
            guild_id
        )
        return None

    channel = bot.get_channel(channel_id)

    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            logger.exception(
                "알림 채널 조회 실패: guild=%s channel=%s",
                guild_id,
                channel_id
            )
            return None

    if not hasattr(channel, "send"):
        logger.error(
            "알림 채널에 메시지를 보낼 수 없음: channel=%s",
            channel_id
        )
        return None

    return channel


async def send_live_notification(
    bot,
    guild_id,
    platform,
    streamer_name,
    title,
    url,
    thumbnail=None,
    channel_url=None
):
    # 라이브 알림 전용 채널
    channel = await get_alert_channel(
        bot,
        guild_id,
        "live"
    )

    if channel is None:
        return False

    platform_name = PLATFORM_NAMES.get(platform, platform)
    platform_emoji = PLATFORM_EMOJIS.get(platform)

    platform_url = PLATFORM_URLS.get(platform, url)
    channel_url = channel_url or url

    embed = discord.Embed(
        title=streamer_name,
        url=channel_url,
        description=f"**[{title or '제목 없음'}]({url})**",
        color=PLATFORM_COLORS.get(platform, 0x5865F2)
    )

    embed.set_author(
        name=platform_name,
        url=platform_url,
        icon_url=str(platform_emoji.url) if platform_emoji else None
    )

    if thumbnail:
        embed.set_image(url=thumbnail)

    embed.set_footer(
        text="Streamy | Live Notification"
    )

    view = discord.ui.View()

    view.add_item(
        discord.ui.Button(
            label="방송 보기",
            emoji=platform_emoji,
            url=url,
            style=discord.ButtonStyle.link
        )
    )

    message = (
        "새로운 라이브 방송이 시작되었습니다!\n"
        f"{url}"
    )

    try:
        await channel.send(
            content=message,
            embed=embed,
            view=view
        )

        logger.info(
            "방송 알림 전송 성공: 플랫폼=%s, 스트리머=%s, 채널=%s",
            platform,
            streamer_name,
            channel.id
        )

        return True

    except discord.HTTPException:
        logger.exception(
            "디스코드 방송 알림 전송 실패: guild=%s channel=%s",
            guild_id,
            channel.id
        )
        return False

    except Exception:
        logger.exception(
            "방송 알림 처리 중 예상하지 못한 오류: streamer=%s",
            streamer_name
        )
        return False


async def send_video_notification(
    bot,
    guild_id,
    streamer_name,
    title,
    url,
    thumbnail=None,
    channel_url=None
):
    # 동영상 업로드 알림 전용 채널
    channel = await get_alert_channel(
        bot,
        guild_id,
        "video"
    )

    if channel is None:
        return False

    channel_url = channel_url or "https://www.youtube.com"
    youtube_emoji = PLATFORM_EMOJIS["youtube"]

    embed = discord.Embed(
        title=streamer_name,
        url=channel_url,
        description=f"**[{title or '제목 없음'}]({url})**",
        color=PLATFORM_COLORS["youtube"]
    )

    embed.set_author(
        name="YouTube",
        url="https://www.youtube.com",
        icon_url=str(youtube_emoji.url)
    )

    if thumbnail:
        embed.set_image(url=thumbnail)

    embed.set_footer(
        text="Streamy | YouTube Upload Notification"
    )

    view = discord.ui.View()

    view.add_item(
        discord.ui.Button(
            label="영상 보기",
            emoji=youtube_emoji,
            url=url,
            style=discord.ButtonStyle.link
        )
    )

    message = (
        "새로운 동영상이 업로드되었습니다!\n"
        f"{url}"
    )

    try:
        await channel.send(
            content=message,
            embed=embed,
            view=view
        )

        logger.info(
            "동영상 알림 전송 성공: 스트리머=%s, 채널=%s",
            streamer_name,
            channel.id
        )

        return True

    except discord.HTTPException:
        logger.exception(
            "디스코드 동영상 알림 전송 실패: guild=%s channel=%s",
            guild_id,
            channel.id
        )
        return False

    except Exception:
        logger.exception(
            "동영상 알림 처리 중 예상하지 못한 오류: streamer=%s",
            streamer_name
        )
        return False
