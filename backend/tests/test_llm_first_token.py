"""v2.4.5：首 token 看门狗（SilentStreamWatchdog）语义测试。

背景：httpx 的 read timeout 只在"两个 chunk 之间"计时，"首字迟迟不来"它不兜底。
真跑线上 office.nianan.site 测到 deepseek-v4.1-flash 首 token 静默 29~54s、偶发
不吐字，任务挂到 900s 硬超时才收场——用户侧就是"卡住了一直不动"。

看门狗必须满足：
1. 到点且没收到首个 chunk → 回调一次关流；
2. 已收到首个 chunk → 即使计时器先排上队也绝不关流（会截断正常输出）；
3. cancel 之后不再回调（正常收尾不该误伤）。
"""
import time

from app.core.llm import SilentStreamWatchdog


def test_watchdog_fires_when_stream_silent():
    fired: list[int] = []
    wd = SilentStreamWatchdog(0.05, lambda: fired.append(1))

    wd.start()
    time.sleep(0.2)

    assert wd.fired is True
    assert fired == [1]


def test_watchdog_never_fires_after_first_chunk():
    fired: list[int] = []
    wd = SilentStreamWatchdog(0.05, lambda: fired.append(1))

    wd.start()
    wd.mark_chunk()  # 首字已到 → 失活
    time.sleep(0.2)

    assert wd.fired is False
    assert fired == []


def test_watchdog_cancel_before_deadline_is_silent():
    fired: list[int] = []
    wd = SilentStreamWatchdog(0.05, lambda: fired.append(1))

    wd.start()
    wd.cancel()
    time.sleep(0.2)

    assert wd.fired is False
    assert fired == []


def test_watchdog_swallows_close_errors():
    def boom() -> None:
        raise RuntimeError("socket already closed")

    wd = SilentStreamWatchdog(0.03, boom)
    wd.start()
    time.sleep(0.15)

    assert wd.fired is True  # 关流抛错也要标记已触发，错误由上层转成 LlmError
