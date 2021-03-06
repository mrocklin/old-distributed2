import asyncio
from collections import defaultdict
from functools import partial
from queue import Queue
from time import sleep

from .core import read, write, client_connected, spawn_loop, sync, rpc

log = print

class Center(object):
    """ Central metadata storage

    A Center serves as central point of metadata storage among workers.  It
    maintains dictionaries of which worker has which keys and which keys are
    owned by which workers.  Computational systems tend to check in with a
    Center to determine their available resources.

    Example
    -------

    A center can be run in an event loop

    >>> c = Center('192.168.0.123', 8000)
    >>> coroutine = c.go()

    Or separately in a thread

    >>> c = Center('192.168.0.123', 8000, start=True, block=False)  # doctest: +SKIP
    >>> c.close()  # doctest: +SKIP
    """
    def __init__(self, ip, port, bind='*', loop=None, start=False, block=True):
        self.ip = ip
        self.port = port
        self.bind = bind
        self.who_has = defaultdict(set)
        self.has_what = defaultdict(set)
        self.ncores = dict()
        self.loop = loop or asyncio.new_event_loop()
        self.status = None

        if start:
            self.start(block)

    @asyncio.coroutine
    def go(self):
        handlers = {func.__name__: partial(func, self.who_has, self.has_what, self.ncores)
                    for func in [add_keys, remove_keys, who_has, has_what,
                                 register, ncores, unregister]}
        handlers['delete_data'] = partial(delete_data, self.loop, self.who_has,
                self.has_what)
        handlers['terminate'] = self._terminate

        self.server = yield from asyncio.start_server(
                client_connected(handlers), self.bind, self.port,
                loop=self.loop)
        self.status = 'running'
        log("Center server up")
        yield from self.server.wait_closed()
        self.status = 'closed'

    def start(self, block):
        if block:
            self.loop.run_until_complete(self.go())
        else:
            self._thread, _ = spawn_loop(self.go(), loop=self.loop)

    @asyncio.coroutine
    def _close(self):
        self.status = 'closing'
        self.server.close()

    @asyncio.coroutine
    def _terminate(self, reader, writer):
        yield from self._close()

    def close(self):
        sync(self._close(), self.loop)
        if hasattr(self, '_thread'):
            self._thread.join()


def register(who_has, has_what, ncores_dict, reader, writer, address=None, keys=(),
        ncores=None):
    has_what[address] = set(keys)
    ncores_dict[address] = ncores
    print("Register %s" % str(address))
    return b'OK'

def unregister(who_has, has_what, ncores, reader, writer, address=None):
    if address not in has_what:
        return b'Address not found: ' + str(address).encode()
    keys = has_what.pop(address)
    del ncores[address]
    for key in keys:
        who_has[key].remove(address)
    print("Unregister %s" % str(address))
    return b'OK'

def add_keys(who_has, has_what, ncores, reader, writer, address=None,
        keys=()):
    has_what[address].update(keys)
    for key in keys:
        who_has[key].add(address)
    return b'OK'

def remove_keys(who_has, has_what, ncores, reader, writer, keys=(),
        address=None):
    for key in keys:
        if key in has_what[address]:
            has_what[address].remove(key)
        try:
            who_has[key].remove(address)
        except KeyError:
            pass
    return b'OK'

def who_has(who_has, has_what, ncores, reader, writer, keys=None):
    if keys is not None:
        return {k: who_has[k] for k in keys}
    else:
        return who_has

def has_what(who_has, has_what, ncores, reader, writer, keys=None):
    if keys is not None:
        return {k: has_what[k] for k in keys}
    else:
        return has_what

def ncores(who_has, has_what, ncores, reader, writer, addresses=None):
    if addresses is not None:
        return {k: ncores[k] for k in addresses}
    else:
        return ncores

@asyncio.coroutine
def delete_data(loop, who_has, has_what, reader, writer, keys=None):
    who_has2 = {k: v for k, v in who_has.items() if k in keys}
    d = defaultdict(list)

    for key in keys:
        for worker in who_has[key]:
            has_what[worker].remove(key)
            d[worker].append(key)
        del who_has[key]

    coroutines = [rpc(*worker).delete_data(keys=keys, report=False)
                  for worker, keys in d.items()]

    yield from asyncio.gather(*coroutines, loop=loop)

    return b'OK'
