from datetime import datetime, timezone, timedelta
import logging, re

KST = timezone(timedelta(hours=9))


def format_kst(value):
    """
    datetime, ISO 8601 문자열, Unix timestamp를
    한국 표준시 문자열로 변환한다.
    """

    if value is None:
        return "없음"

    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, timezone.utc)

        elif isinstance(value, str):
            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        elif isinstance(value, datetime):
            dt = value

        else:
            return str(value)

        # 시간대 정보가 없는 경우 UTC로 간주
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(KST).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    except (ValueError, TypeError, OverflowError):
        return str(value)


class KSTLogFilter(logging.Filter):
    pattern = re.compile(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
        r'(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})'
    )

    def filter(self, record):
        message = record.getMessage()

        def convert(match):
            return format_kst(match.group(0))

        message = self.pattern.sub(convert, message)

        # 이미 포맷된 메시지가 다시 처리되지 않도록 갱신
        record.msg = message
        record.args = ()

        return True
