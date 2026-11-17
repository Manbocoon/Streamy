import os
import aiosqlite
import logging

from datetime import datetime, timezone
from config import DATABASE_PATH

logger = logging.getLogger("Streamy.Database")


class Database:

    def __init__(self):
        self.path = DATABASE_PATH

    async def initialize(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

        async with aiosqlite.connect(self.path) as db:

            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    alert_channel_id INTEGER,
                    live_alert_channel_id INTEGER,
                    video_alert_channel_id INTEGER
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    display_name TEXT,
                    live_enabled INTEGER NOT NULL DEFAULT 1,
                    video_enabled INTEGER NOT NULL DEFAULT 1,
                    video_type TEXT NOT NULL DEFAULT 'all',
                    created_at TEXT,
                    UNIQUE(guild_id, platform, channel_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS youtube_monitor_state (
                    subscription_id INTEGER PRIMARY KEY,
                    last_video_id TEXT,
                    live_video_id TEXT,
                    initialized INTEGER DEFAULT 0
                )
            """)

            # 기존 DB에 last_published 컬럼 추가
            async with db.execute(
                "PRAGMA table_info(youtube_monitor_state)"
            ) as cursor:
                youtube_columns = {
                    row[1] for row in await cursor.fetchall()
                }

            if "last_published" not in youtube_columns:
                await db.execute("""
                    ALTER TABLE youtube_monitor_state
                    ADD COLUMN last_published TEXT
                """)

            # 영상별 중복 방지 기록
            await db.execute("""
                CREATE TABLE IF NOT EXISTS youtube_processed_videos (
                    subscription_id INTEGER NOT NULL,
                    video_id TEXT NOT NULL,
                    published TEXT NOT NULL,
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (subscription_id, video_id)
                )
            """)


            await db.execute("""
                CREATE TABLE IF NOT EXISTS chzzk_monitor_state (
                    subscription_id INTEGER PRIMARY KEY,
                    live_id TEXT,
                    initialized INTEGER DEFAULT 0
                )
            """)

            # 기존 DB에 새 설정 컬럼이 없으면 추가
            async with db.execute(
                "PRAGMA table_info(subscriptions)"
            ) as cursor:
                subscription_columns = {
                    row[1] for row in await cursor.fetchall()
                }

            # 기존 DB에 created_at 컬럼이 없으면 추가
            if "created_at" not in subscription_columns:
                await db.execute("""
                    ALTER TABLE subscriptions
                    ADD COLUMN created_at TEXT
                """)

            # 기존 구독 데이터의 등록 시각 보정
            # 정확한 과거 등록 시각은 알 수 없으므로
            # 마이그레이션 실행 시각을 기준으로 설정
            migration_time = datetime.now(timezone.utc).isoformat()

            await db.execute("""
                UPDATE subscriptions
                SET created_at = ?
                WHERE created_at IS NULL OR created_at = ''
            """, (migration_time,))

            if "live_enabled" not in subscription_columns:
                await db.execute("""
                    ALTER TABLE subscriptions
                    ADD COLUMN live_enabled INTEGER NOT NULL DEFAULT 1
                """)

            if "video_enabled" not in subscription_columns:
                await db.execute("""
                    ALTER TABLE subscriptions
                    ADD COLUMN video_enabled INTEGER NOT NULL DEFAULT 1
                """)

            if "video_type" not in subscription_columns:
                await db.execute("""
                    ALTER TABLE subscriptions
                    ADD COLUMN video_type TEXT NOT NULL DEFAULT 'all'
                """)

            # 기존 DB에 알림 채널 컬럼이 없으면 추가
            async with db.execute(
                "PRAGMA table_info(guild_settings)"
            ) as cursor:
                guild_columns = {
                    row[1] for row in await cursor.fetchall()
                }

            if "live_alert_channel_id" not in guild_columns:
                await db.execute("""
                    ALTER TABLE guild_settings
                    ADD COLUMN live_alert_channel_id INTEGER
                """)

            if "video_alert_channel_id" not in guild_columns:
                await db.execute("""
                    ALTER TABLE guild_settings
                    ADD COLUMN video_alert_channel_id INTEGER
                """)

            # 기존 alert_channel_id를 라이브 알림 채널로 이전
            await db.execute("""
                UPDATE guild_settings
                SET live_alert_channel_id = alert_channel_id
                WHERE live_alert_channel_id IS NULL
                  AND alert_channel_id IS NOT NULL
            """)

            # 30일이 지난 YouTube 영상 처리 기록 자동 정리
            await db.execute("""
                DELETE FROM youtube_processed_videos
                WHERE datetime(published) < datetime('now', '-30 days')
            """)

            # 데이터베이스 관리 기록
            await db.execute("""
                CREATE TABLE IF NOT EXISTS maintenance_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # 마지막 VACUUM 실행 월 확인
            async with db.execute("""
                SELECT value
                FROM maintenance_state
                WHERE key = 'last_vacuum_month'
            """) as cursor:
                row = await cursor.fetchone()

            last_vacuum_month = row[0] if row else None

            await db.commit()
        
        # 매월 최초 실행 시 VACUUM
        current_month = datetime.now().strftime("%Y-%m")

        if last_vacuum_month != current_month:
            try:
                await self.vacuum_database(current_month)

            except Exception:
                logger.exception("월간 데이터베이스 VACUUM 실패")




    # ─────────────────────────────
    # 알림 채널
    # ─────────────────────────────

    async def set_alert_channel(
        self, guild_id, channel_id, alert_type="live"
    ):
        if alert_type == "live":
            column = "live_alert_channel_id"
        elif alert_type == "video":
            column = "video_alert_channel_id"
        else:
            raise ValueError("잘못된 알림 종류입니다.")

        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"""
                INSERT INTO guild_settings (
                    guild_id,
                    {column}
                )
                VALUES (?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET {column} = excluded.{column}
            """, (guild_id, channel_id))

            # 구버전 코드와의 호환성 유지
            if alert_type == "live":
                await db.execute("""
                    UPDATE guild_settings
                    SET alert_channel_id = ?
                    WHERE guild_id = ?
                """, (channel_id, guild_id))

            await db.commit()

    async def get_alert_channel(self, guild_id, alert_type="live"):
        if alert_type == "live":
            column = "live_alert_channel_id"
        elif alert_type == "video":
            column = "video_alert_channel_id"
        else:
            raise ValueError("잘못된 알림 종류입니다.")

        async with aiosqlite.connect(self.path) as db:
            async with db.execute(f"""
                SELECT {column}
                FROM guild_settings
                WHERE guild_id = ?
            """, (guild_id,)) as cursor:
                result = await cursor.fetchone()

                return result[0] if result else None




    # ─────────────────────────────
    # 스트리머 등록 / 삭제 / 조회
    # ─────────────────────────────
    async def add_subscription(
        self, guild_id, platform, channel_id, display_name
    ):
        created_at = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO subscriptions (
                    guild_id,
                    platform,
                    channel_id,
                    display_name,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                guild_id,
                platform,
                channel_id,
                display_name,
                created_at
            ))

            await db.commit()


    async def remove_subscription(self, guild_id, subscription_id):
        async with aiosqlite.connect(self.path) as db:

            await db.execute("""
                DELETE FROM chzzk_monitor_state
                WHERE subscription_id = ?
            """, (subscription_id,))

            await db.execute("""
                DELETE FROM youtube_monitor_state
                WHERE subscription_id = ?
            """, (subscription_id,))

            await db.execute("""
                DELETE FROM youtube_processed_videos
                WHERE subscription_id = ?
            """, (subscription_id,))

            cursor = await db.execute("""
                DELETE FROM subscriptions
                WHERE guild_id = ? AND id = ?
            """, (guild_id, subscription_id))

            await db.commit()
            return cursor.rowcount > 0

    async def get_subscriptions(self, guild_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT *
                FROM subscriptions
                WHERE guild_id = ?
                ORDER BY id
            """, (guild_id,)) as cursor:
                return await cursor.fetchall()

    async def get_subscription(self, guild_id, subscription_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT *
                FROM subscriptions
                WHERE guild_id = ? AND id = ?
            """, (guild_id, subscription_id)) as cursor:
                return await cursor.fetchone()

    async def get_all_subscriptions(self, platform=None):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            if platform:
                query = """
                    SELECT *
                    FROM subscriptions
                    WHERE platform = ?
                    ORDER BY id
                """
                params = (platform,)
            else:
                query = """
                    SELECT *
                    FROM subscriptions
                    ORDER BY id
                """
                params = ()

            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()

    # ─────────────────────────────
    # 스트리머별 설정 변경
    # ─────────────────────────────

    async def update_subscription_settings(
        self,
        guild_id,
        subscription_id,
        display_name=None,
        platform=None,
        live_enabled=None,
        video_enabled=None,
        video_type=None
    ):
        updates = []
        params = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)

        if platform is not None:
            updates.append("platform = ?")
            params.append(platform)

        if live_enabled is not None:
            updates.append("live_enabled = ?")
            params.append(int(live_enabled))

        if video_enabled is not None:
            updates.append("video_enabled = ?")
            params.append(int(video_enabled))

        if video_type is not None:
            if video_type not in ("all", "shorts", "normal"):
                raise ValueError("잘못된 동영상 종류입니다.")

            updates.append("video_type = ?")
            params.append(video_type)

        if not updates:
            return False

        params.extend([guild_id, subscription_id])

        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(f"""
                UPDATE subscriptions
                SET {", ".join(updates)}
                WHERE guild_id = ? AND id = ?
            """, params)

            await db.commit()
            return cursor.rowcount > 0

    # ─────────────────────────────
    # 유튜브 감시 상태
    # ─────────────────────────────

    async def get_youtube_state(self, subscription_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT *
                FROM youtube_monitor_state
                WHERE subscription_id = ?
            """, (subscription_id,)) as cursor:
                return await cursor.fetchone()

    async def save_youtube_state(
        self,
        subscription_id,
        last_video_id,
        live_video_id,
        initialized
    ):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO youtube_monitor_state (
                    subscription_id,
                    last_video_id,
                    live_video_id,
                    initialized
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(subscription_id)
                DO UPDATE SET
                    last_video_id = excluded.last_video_id,
                    live_video_id = excluded.live_video_id,
                    initialized = excluded.initialized
            """, (
                subscription_id,
                last_video_id,
                live_video_id,
                initialized
            ))

            await db.commit()

    async def get_youtube_processed_video_ids(
        self,
        subscription_id,
        video_ids
    ):
        if not video_ids:
            return set()

        placeholders = ",".join(
            "?" for _ in video_ids
        )

        async with aiosqlite.connect(self.path) as db:
            async with db.execute(f"""
                SELECT video_id
                FROM youtube_processed_videos
                WHERE subscription_id = ?
                AND video_id IN ({placeholders})
            """, (subscription_id, *video_ids)) as cursor:

                rows = await cursor.fetchall()

                return {
                    row[0] for row in rows
                }


    async def mark_youtube_video_processed(
        self,
        subscription_id,
        video_id,
        published
    ):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO youtube_processed_videos (
                    subscription_id,
                    video_id,
                    published
                )
                VALUES (?, ?, ?)
            """, (
                subscription_id,
                video_id,
                published
            ))

            await db.commit()
    

    async def save_youtube_published_state(
        self,
        subscription_id,
        last_published
    ):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO youtube_monitor_state (
                    subscription_id,
                    last_published,
                    initialized
                )
                VALUES (?, ?, 1)

                ON CONFLICT(subscription_id)
                DO UPDATE SET
                    last_published = CASE
                        WHEN youtube_monitor_state.last_published IS NULL
                        OR excluded.last_published >
                            youtube_monitor_state.last_published
                        THEN excluded.last_published
                        ELSE youtube_monitor_state.last_published
                    END
            """, (
                subscription_id,
                last_published
            ))

            await db.commit()



    # ─────────────────────────────
    # 치지직 감시 상태
    # ─────────────────────────────
    async def get_chzzk_state(self, subscription_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT *
                FROM chzzk_monitor_state
                WHERE subscription_id = ?
            """, (subscription_id,)) as cursor:
                return await cursor.fetchone()

    async def save_chzzk_state(
        self,
        subscription_id,
        live_id,
        initialized
    ):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO chzzk_monitor_state (
                    subscription_id,
                    live_id,
                    initialized
                )
                VALUES (?, ?, ?)
                ON CONFLICT(subscription_id)
                DO UPDATE SET
                    live_id = excluded.live_id,
                    initialized = excluded.initialized
            """, (
                subscription_id,
                live_id,
                initialized
            ))

            await db.commit()
            

    # ─────────────────────────────
    # 데이터베이스 용량 최적화
    # ─────────────────────────────
    async def vacuum_database(self, current_month=None):

        if current_month is None:
            current_month = datetime.now().strftime("%Y-%m")

        async with aiosqlite.connect(
            self.path,
            timeout=30
        ) as db:

            # 다른 DB 작업이 끝날 때까지 최대 30초 대기
            cursor = await db.execute(
                "PRAGMA busy_timeout = 30000"
            )
            await cursor.close()

            # 혹시 남아 있는 트랜잭션 정리
            await db.commit()

            # 데이터베이스 최적화
            cursor = await db.execute("VACUUM")
            await cursor.close()

            # 실행 기록 저장
            await db.execute("""
                INSERT INTO maintenance_state (key, value)
                VALUES ('last_vacuum_month', ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value
            """, (current_month,))

            await db.commit()

        logger.info(
            f"데이터베이스 VACUUM 실행 완료 ({current_month})"
        )