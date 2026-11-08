import asyncio

from productivity_tracker.broker import FocusBroker


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_a_click_is_taken_by_its_host_once():
    broker = FocusBroker()
    broker.put("DESK", 42)

    assert asyncio.run(broker.take("desk", 0)) == 42
    assert asyncio.run(broker.take("desk", 0)) is None


def test_nothing_waiting_times_out_empty():
    assert asyncio.run(FocusBroker().take("desk", 0.01)) is None


def test_a_click_for_another_host_is_left_alone():
    broker = FocusBroker()
    broker.put("laptop", 42)

    assert asyncio.run(broker.take("desk", 0)) is None
    assert asyncio.run(broker.take("laptop", 0)) == 42


def test_a_later_click_replaces_the_one_still_waiting():
    broker = FocusBroker()
    broker.put("desk", 1)
    broker.put("desk", 2)

    assert asyncio.run(broker.take("desk", 0)) == 2
    assert asyncio.run(broker.take("desk", 0)) is None


def test_a_click_too_old_to_mean_anything_is_dropped():
    clock = Clock()
    broker = FocusBroker(ttl=30, clock=clock)
    broker.put("desk", 42)
    clock.now += 31

    assert asyncio.run(broker.take("desk", 0)) is None


def test_a_collector_already_waiting_is_woken_by_the_click():
    async def scenario() -> int | None:
        broker = FocusBroker()
        waiting = asyncio.create_task(broker.take("desk", 5))
        await asyncio.sleep(0)
        broker.put("desk", 42)
        return await asyncio.wait_for(waiting, 1)

    assert asyncio.run(scenario()) == 42


def test_two_collectors_on_one_pc_share_a_click():
    # A PC can briefly run two, across an upgrade: one gets it, the other waits on.
    async def scenario() -> list[int | None]:
        broker = FocusBroker()
        waiters = [asyncio.create_task(broker.take("desk", 0.05)) for _ in range(2)]
        await asyncio.sleep(0)
        broker.put("desk", 42)
        return await asyncio.gather(*waiters)

    assert sorted(asyncio.run(scenario()), key=str) == [42, None]
