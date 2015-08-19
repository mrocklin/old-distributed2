import asyncio
import random
from toolz import merge, partial

from .core import read, write, connect, delay, manage_data, serve, send_recv


class Worker(object):
    def __init__(self, ip, port, center_ip, center_port, bind='*', loop=None):
        self.ip = ip
        self.port = port
        self.center_ip = center_ip
        self.center_port = center_port
        self.bind = bind
        self.loop = loop
        self.data = dict()

    @asyncio.coroutine
    def go(self):
        data_cor = partial(manage_data, self.data)
        work_cor = partial(work, self.loop, self.data, self.ip, self.port,
                                 self.center_ip, self.center_port)
        handlers = {'compute': work_cor,
                    'get-data': data_cor,
                    'update-data': data_cor,
                    'del-data': data_cor}

        resp = yield from send_recv(self.center_ip, self.center_port,
                                    op='register', address=(self.ip, self.port),
                                    reply=True, close=True)
        assert resp == b'OK'

        yield from serve(self.bind, self.port, handlers, loop=self.loop)


@asyncio.coroutine
def collect(loop, reader, writer, needed):
    who_has = yield from send_recv(reader, writer, op='who-has', keys=needed,
            reply=True)
    assert set(who_has) == set(needed)

    # TODO: This should all be done in parallel and in fewer messages
    results = []
    for key, addresses in who_has.items():
        host, port = random.choice(list(addresses))
        result = yield from send_recv(host, port, op='get-data', keys=[key],
                loop=loop, reply=True, close=True)
        results.append(result)

    # TODO: Update metadata to say that we have this data

    return merge(results)


@asyncio.coroutine
def work(loop, data, ip, port, metadata_ip, metadata_port, reader, writer, msg):
    m_reader, m_writer = yield from connect(metadata_ip, metadata_port, loop)

    assert msg['op'] == 'compute'

    function = msg['function']
    key = msg['key']
    args = msg.get('args', ())
    kwargs = msg.get('kwargs', {})
    needed = msg.get('needed', [])

    if msg['needed']:
        other = yield from collect(loop, m_reader, m_writer, needed)
        data2 = merge(data, other)
    else:
        data2 = data

    args2 = keys_to_data(args, data2)
    kwargs2 = keys_to_data(kwargs, data2)

    result = yield from delay(loop, msg['function'], *args2, **kwargs)

    data[key] = result

    yield from write(m_writer, {'op': 'add-keys',
                                'address': (ip, port),
                                'keys': [key],
                                'reply': True,
                                'close': True})
    response = yield from read(m_reader)
    assert response == b'OK'
    m_writer.close()

    if msg.get('reply'):
        yield from write(writer, b'OK')


def keys_to_data(o, data):
    """

    >>> keys_to_data(('x', 'y'), {'x': 1})
    (1, 'y')
    >>> keys_to_data({'a': 'x', 'b': 'y'}, {'x': 1})
    {'a': 1, 'b': 'y'}
    """
    if isinstance(o, (tuple, list)):
        result = []
        for arg in o:
            try:
                result.append(data[arg])
            except (TypeError, KeyError):
                result.append(arg)
        result = type(o)(result)

    if isinstance(o, dict):
        result = {}
        for k, v in o.items():
            try:
                result[k] = data[v]
            except (TypeError, KeyError):
                result[k] = v
    return result