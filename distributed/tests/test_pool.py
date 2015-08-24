import asyncio
from operator import add
from queue import Queue

from distributed.center import Center
from distributed.worker import Worker
from distributed.pool import Pool, spawn_loop, divide_tasks
from contextlib import contextmanager

loop = asyncio.get_event_loop()


def test_pool():
    c = Center('127.0.0.1', 8017, loop=loop)

    a = Worker('127.0.0.1', 8018, c.ip, c.port, loop=loop, ncores=1)
    b = Worker('127.0.0.1', 8019, c.ip, c.port, loop=loop, ncores=1)

    p = Pool(c.ip, c.port, loop=loop, start=False)

    @asyncio.coroutine
    def f():
        yield from p._sync_center()

        computation = yield from p._apply_async(add, [1, 2])
        assert set(p.available_cores.values()) == set([0, 1])
        x = yield from computation._get()
        assert list(p.available_cores.values()) == [1, 1]
        result = yield from x._get()
        assert result == 3

        computation = yield from p._apply_async(add, [x, 10])
        y = yield from computation._get()
        result = yield from y._get()
        assert result == 13

        assert set((len(a.data), len(b.data))) == set((0, 2))

        x = yield from p._apply_async(add, [1, 2])
        y = yield from p._apply_async(add, [1, 2])
        assert list(p.available_cores.values()) == [0, 0]
        xx = yield from x._get()
        yield from xx._get()
        assert set(p.available_cores.values()) == set([0, 1])
        yy = yield from y._get()
        yield from yy._get()
        assert list(p.available_cores.values()) == [1, 1]

        seq = yield from p._map(lambda x: x * 100, [1, 2, 3])
        result = yield from seq[0]._get(False)
        assert result == 100
        result = yield from seq[1]._get(False)
        assert result == 200
        result = yield from seq[2]._get(False)
        assert result == 300

        yield from p._close()

        a.close()
        b.close()
        c.close()

    loop.run_until_complete(asyncio.gather(c.go(), a.go(), b.go(), f()))


def test_pool_thread():
    p = Pool('127.0.0.1', 8000, start=False)
    p.start()
    p.close()


@contextmanager
def cluster():
    loop = asyncio.new_event_loop()
    c = Center('127.0.0.1', 8100, loop=loop)
    a = Worker('127.0.0.1', 8101, c.ip, c.port, loop=loop)
    b = Worker('127.0.0.1', 8102, c.ip, c.port, loop=loop)

    kill_q = Queue()

    @asyncio.coroutine
    def stop():
        while kill_q.empty():
            yield from asyncio.sleep(0.01)
        kill_q.get()

    cor = asyncio.gather(c.go(), a.go(), b.go(), loop=loop)
    cor2 = asyncio.wait([stop(), cor], loop=loop,
            return_when=asyncio.FIRST_COMPLETED)

    thread, loop = spawn_loop(cor, loop)

    try:
        yield c, a, b
    finally:
        a.close()
        b.close()
        c.close()
        kill_q.put(b'')
        thread.join()


def test_cluster():
    with cluster() as (c, a, b):
        pool = Pool(c.ip, c.port)

        pc = pool.apply_async(add, [1, 2])
        x = pc.get()
        assert x.get() == 3
        assert x.get() == 3
        pool.close()


def test_workshare():
    who_has = {'x': {'Alice'},
               'y': {'Alice', 'Bob'},
               'z': {'Bob'}}
    needed = {1: {'x'},
              2: {'y'},
              3: {'z'},
              4: {'x', 'z'},
              5: set()}

    shares, extra = divide_tasks(who_has, needed)
    assert shares == {'Alice': [2, 1], 'Bob': [2, 3]}
    assert extra == {4, 5}