import asyncio

from dist.core import read, write, connect
from dist.center import Center

loop = asyncio.get_event_loop()


def test_metadata():
    c = Center(8006, loop=loop)

    @asyncio.coroutine
    def f():
        reader, writer = yield from connect('127.0.0.1', 8006, loop=loop)

        msg = {'op': 'add-keys',
               'address': 'alice',
               'keys': ['x', 'y'],
               'reply': True}
        yield from write(writer, msg)
        response = yield from read(reader)
        assert response == b'OK'

        msg = {'op': 'add-keys',
               'address': 'bob',
               'keys': ['y', 'z'],
               'reply': True}
        yield from write(writer, msg)
        response = yield from read(reader)
        assert response == b'OK'

        msg = {'op': 'who-has',
               'keys': ['x', 'y']}
        yield from write(writer, msg)
        response = yield from read(reader)
        assert response == {'x': set(['alice']), 'y': set(['alice', 'bob'])}

        msg = {'op': 'del-keys',
               'address': 'bob',
               'keys': ['y'],
               'reply': True}
        yield from write(writer, msg)
        response = yield from read(reader)
        assert response == b'OK'

        msg = {'op': 'has-what',
               'keys': ['alice', 'bob'],
               'close': True}
        yield from write(writer, msg)
        response = yield from read(reader)
        assert response == {'alice': set(['x', 'y']), 'bob': set(['z'])}

    loop.run_until_complete(asyncio.gather(c.go(), f()))
