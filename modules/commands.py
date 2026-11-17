
import discord
from discord import app_commands
from discord.ext import commands

from database.database import Database


class StreamCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    @app_commands.command(
        name="등록",
        description="알림을 받을 스트리머를 등록합니다."
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="치지직", value="chzzk"),
        app_commands.Choice(name="유튜브", value="youtube")
    ])
    @app_commands.choices(video_type=[
        app_commands.Choice(name="전체", value="all"),
        app_commands.Choice(name="쇼츠만", value="shorts"),
        app_commands.Choice(name="일반 동영상만", value="normal")
    ])
    @app_commands.describe(
        platform="플랫폼 선택",
        channel_id="스트리머 채널 ID",
        display_name="표시할 스트리머 이름",
        video_type="유튜브 동영상 알림 종류"
    )
    async def register(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        channel_id: str,
        display_name: str = None,
        video_type: app_commands.Choice[str] = None
    ):

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        selected_video_type = (
            video_type.value
            if video_type and platform.value == "youtube"
            else "all"
        )

        try:
            await self.db.add_subscription(
                interaction.guild_id,
                platform.value,
                channel_id.strip(),
                display_name or channel_id.strip()
            )

            # 등록 직후 동영상 종류 설정
            if platform.value == "youtube" and selected_video_type != "all":
                items = await self.db.get_subscriptions(
                    interaction.guild_id
                )
                selected = next(
                    (
                        item for item in items
                        if item["platform"] == platform.value
                        and item["channel_id"] == channel_id.strip()
                    ),
                    None
                )

                if selected:
                    await self.db.update_subscription_settings(
                        interaction.guild_id,
                        selected["id"],
                        video_type=selected_video_type
                    )

            await interaction.response.send_message(
                f"✅ **{display_name or channel_id}** 등록 완료!\n"
                f"라이브 알림: ON\n"
                f"동영상 알림: ON\n"
                f"동영상 종류: {selected_video_type}",
                ephemeral=True
            )

        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                message = "이미 등록된 스트리머입니다."
            else:
                message = "등록 중 오류가 발생했습니다."
                print(f"등록 오류: {e}")

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    @app_commands.command(
        name="목록",
        description="등록된 스트리머 목록과 알림 설정을 확인합니다."
    )
    async def streamer_list(self, interaction: discord.Interaction):

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        items = await self.db.get_subscriptions(
            interaction.guild_id
        )

        items = sorted(items, key=lambda item: item["id"])

        embed = discord.Embed(
            title="📋 등록된 스트리머",
            color=0x5865F2
        )

        if not items:
            embed.description = "등록된 스트리머가 없습니다."
        else:
            for index, item in enumerate(items, start=1):
                platform = (
                    "치지직"
                    if item["platform"] == "chzzk"
                    else "유튜브"
                )

                live_status = (
                    "🟢 ON" if item["live_enabled"] else "🔴 OFF"
                )

                video_status = (
                    "🟢 ON" if item["video_enabled"] else "🔴 OFF"
                )

                value = (
                    f"{platform}\n"
                    f"`{item['channel_id']}`\n"
                    f"라이브 알림: {live_status}"
                )

                if item["platform"] == "youtube":
                    video_type = {
                        "all": "전체",
                        "shorts": "쇼츠만",
                        "normal": "일반 동영상만"
                    }.get(item["video_type"], "전체")

                    value += (
                        f"\n동영상 알림: {video_status}"
                        f"\n동영상 종류: {video_type}"
                    )

                embed.add_field(
                    name=f"#{index} | {item['display_name']}",
                    value=value,
                    inline=False
                )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @app_commands.command(
        name="삭제",
        description="등록된 스트리머를 삭제합니다."
    )
    @app_commands.describe(
        subscription_id="목록에 표시된 등록 번호"
    )
    async def delete(
        self,
        interaction: discord.Interaction,
        subscription_id: int
    ):

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        items = await self.db.get_subscriptions(
            interaction.guild_id
        )
        items = sorted(items, key=lambda item: item["id"])

        if subscription_id < 1 or subscription_id > len(items):
            await interaction.response.send_message(
                "해당 등록 번호를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        selected_item = items[subscription_id - 1]

        result = await self.db.remove_subscription(
            interaction.guild_id,
            selected_item["id"]
        )

        message = (
            f"✅ **{selected_item['display_name']}** 스트리머 등록을 해제했습니다."
            if result
            else "스트리머 삭제 중 오류가 발생했습니다."
        )

        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    @app_commands.command(
        name="설정",
        description="등록된 스트리머의 알림 설정을 변경합니다."
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="치지직", value="chzzk"),
        app_commands.Choice(name="유튜브", value="youtube")
    ])
    @app_commands.choices(video_type=[
        app_commands.Choice(name="전체", value="all"),
        app_commands.Choice(name="쇼츠만", value="shorts"),
        app_commands.Choice(name="일반 동영상만", value="normal")
    ])
    @app_commands.describe(
        subscription_id="목록에 표시된 등록 번호",
        display_name="변경할 표시 이름",
        platform="변경할 플랫폼",
        live_enabled="라이브 알림 ON/OFF",
        video_enabled="동영상 알림 ON/OFF",
        video_type="동영상 알림 종류"
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        subscription_id: int,
        display_name: str = None,
        platform: app_commands.Choice[str] = None,
        live_enabled: bool = None,
        video_enabled: bool = None,
        video_type: app_commands.Choice[str] = None
    ):

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        items = await self.db.get_subscriptions(
            interaction.guild_id
        )
        items = sorted(items, key=lambda item: item["id"])

        if subscription_id < 1 or subscription_id > len(items):
            await interaction.response.send_message(
                "해당 등록 번호를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        selected = items[subscription_id - 1]

        new_platform = platform.value if platform else None
        new_video_type = video_type.value if video_type else None

        # 유튜브 전용 설정은 유튜브 스트리머에만 적용
        resulting_platform = new_platform or selected["platform"]

        if resulting_platform != "youtube" and (
            video_enabled is not None or new_video_type is not None
        ):
            await interaction.response.send_message(
                "동영상 알림 설정은 유튜브 스트리머에게만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        # 변경할 항목이 하나도 없는 경우
        if all(value is None for value in (
            display_name,
            new_platform,
            live_enabled,
            video_enabled,
            new_video_type
        )):
            await interaction.response.send_message(
                "변경할 설정을 하나 이상 입력해주세요.",
                ephemeral=True
            )
            return

        try:
            result = await self.db.update_subscription_settings(
                interaction.guild_id,
                selected["id"],
                display_name=display_name,
                platform=new_platform,
                live_enabled=live_enabled,
                video_enabled=video_enabled,
                video_type=new_video_type
            )

            if not result:
                await interaction.response.send_message(
                    "설정 변경에 실패했습니다.",
                    ephemeral=True
                )
                return

            changes = []

            if display_name is not None:
                changes.append(f"표시 이름: {display_name}")

            if new_platform is not None:
                changes.append(f"플랫폼: {new_platform}")

            if live_enabled is not None:
                changes.append(
                    f"라이브 알림: {'ON' if live_enabled else 'OFF'}"
                )

            if video_enabled is not None:
                changes.append(
                    f"동영상 알림: {'ON' if video_enabled else 'OFF'}"
                )

            if new_video_type is not None:
                type_name = {
                    "all": "전체",
                    "shorts": "쇼츠만",
                    "normal": "일반 동영상만"
                }[new_video_type]
                changes.append(f"동영상 종류: {type_name}")

            await interaction.response.send_message(
                f"✅ **{selected['display_name']}** 설정을 변경했습니다.\n"
                + "\n".join(changes),
                ephemeral=True
            )

        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                message = "해당 플랫폼에 같은 채널 ID가 이미 등록되어 있습니다."
            else:
                message = "설정 변경 중 오류가 발생했습니다."
                print(f"설정 변경 오류: {e}")

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    @app_commands.command(
        name="알림채널",
        description="라이브 또는 동영상 알림 채널을 설정합니다."
    )
    @app_commands.choices(alert_type=[
        app_commands.Choice(name="라이브 알림", value="live"),
        app_commands.Choice(name="동영상 알림", value="video")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(
        self,
        interaction: discord.Interaction,
        alert_type: app_commands.Choice[str]
    ):

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "텍스트 채널에서만 설정할 수 있습니다.",
                ephemeral=True
            )
            return

        await self.db.set_alert_channel(
            interaction.guild_id,
            interaction.channel_id,
            alert_type.value
        )

        channel_name = (
            "라이브 알림"
            if alert_type.value == "live"
            else "동영상 알림"
        )

        await interaction.response.send_message(
            f"✅ 현재 채널을 {channel_name} 채널로 설정했습니다.",
            ephemeral=True
        )

    @app_commands.command(
        name="서버설정",
        description="현재 서버의 알림 채널 설정을 확인합니다."
    )
    async def server_settings(self, interaction: discord.Interaction):

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "서버에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        live_channel_id = await self.db.get_alert_channel(
            interaction.guild_id,
            "live"
        )

        video_channel_id = await self.db.get_alert_channel(
            interaction.guild_id,
            "video"
        )

        items = await self.db.get_subscriptions(
            interaction.guild_id
        )

        embed = discord.Embed(
            title="⚙️ Streamy 서버 설정",
            color=0x5865F2
        )

        embed.add_field(
            name="라이브 알림 채널",
            value=f"<#{live_channel_id}>" if live_channel_id else "미설정",
            inline=False
        )

        embed.add_field(
            name="동영상 알림 채널",
            value=f"<#{video_channel_id}>" if video_channel_id else "미설정",
            inline=False
        )

        embed.add_field(
            name="등록된 스트리머",
            value=f"{len(items)}명",
            inline=True
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


    @app_commands.command(
        name="테스트",
        description="플랫폼별 알림 테스트 메시지를 전송합니다."
    )
    @app_commands.choices(notification_type=[
        app_commands.Choice(name="치지직 라이브", value="chzzk_live"),
        app_commands.Choice(name="유튜브 라이브", value="youtube_live"),
        app_commands.Choice(name="유튜브 동영상", value="youtube_video")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(
        self,
        interaction: discord.Interaction,
        notification_type: app_commands.Choice[str]
    ):
        from modules.notifier import (
            send_live_notification,
            send_video_notification
        )

        await interaction.response.defer(ephemeral=True)

        test_type = notification_type.value

        if test_type == "chzzk_live":
            result = await send_live_notification(
                self.bot,
                interaction.guild_id,
                "chzzk",
                "테스트 스트리머",
                "Streamy 치지직 라이브 테스트입니다!",
                "https://chzzk.naver.com/",
                thumbnail="https://img.youtube.com/vi/aqz-KE-bpKQ/hqdefault.jpg",
                channel_url="https://chzzk.naver.com/"
            )
            display_name = "치지직 라이브"

        elif test_type == "youtube_live":
            result = await send_live_notification(
                self.bot,
                interaction.guild_id,
                "youtube",
                "테스트 스트리머",
                "Streamy 유튜브 라이브 테스트입니다!",
                "https://www.youtube.com/",
                thumbnail="https://img.youtube.com/vi/aqz-KE-bpKQ/hqdefault.jpg",
                channel_url="https://www.youtube.com/"
            )
            display_name = "유튜브 라이브"

        else:  # youtube_video
            result = await send_video_notification(
                self.bot,
                interaction.guild_id,
                "테스트 스트리머",
                "Streamy 유튜브 동영상 테스트입니다!",
                "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
                thumbnail="https://img.youtube.com/vi/aqz-KE-bpKQ/hqdefault.jpg",
                channel_url="https://www.youtube.com/"
            )
            display_name = "유튜브 동영상"

        await interaction.followup.send(
            f"✅ {display_name} 테스트 알림을 전송했습니다."
            if result
            else "❌ 알림 전송에 실패했습니다. 알림 채널과 봇 권한을 확인해주세요.",
            ephemeral=True
        )



async def setup(bot):
    await bot.add_cog(StreamCommands(bot))
