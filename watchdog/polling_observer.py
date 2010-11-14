# -*- coding: utf-8 -*-

from dirsnapshot import DirectorySnapshot
from threading import Thread, Event
from decorator_utils import synchronized
from os.path import realpath, abspath
from Queue import Queue
from events import *

import logging

logging.basicConfig(level=logging.DEBUG,
                    format='%(pathname)s/%(funcName)s/(%(threadName)-10s) %(message)s',
                    )


class _PollingEventProducer(Thread):
    """Daemonic threaded event emitter to monitor a given path recursively
    for file system events.
    """

    def __init__(self, path, interval=1, out_event_queue=None, name=None, *args, **kwargs):
        """Monitors a given path and appends file system modification
        events to the output queue."""
        Thread.__init__(self)
        self.interval = interval
        self.out_event_queue = out_event_queue
        self.args = args
        self.kwargs = kwargs
        self.stopped = Event()
        self.snapshot = None
        self.path = path
        if name is None:
            name = 'PollingObserver(%s)' % realpath(abspath(self.path))
            self.name = name + self.name
        else:
            self.name = name
        self.setDaemon(True)

    def stop(self):
        """Stops monitoring the given path by setting a flag to stop."""
        self.stopped.set()

    @synchronized()
    def _get_directory_snapshot_diff(self):
        """Obtains a diff of two directory snapshots."""
        if self.snapshot is None:
            self.snapshot = DirectorySnapshot(self.path)
            diff = None
        else:
            new_snapshot = DirectorySnapshot(self.path)
            diff = new_snapshot - self.snapshot
            self.snapshot = new_snapshot
        return diff

    def run(self):
        """
        Appends events to the output event queue
        based on the diff between two states of the same directory.

        """
        while not self.stopped.is_set():
            self.stopped.wait(self.interval)
            diff = self._get_directory_snapshot_diff()
            if diff and self.out_event_queue:
                q = self.out_event_queue

                for path in diff.files_deleted:
                    q.put((self.path, FileDeletedEvent(path)))

                for path in diff.files_modified:
                    q.put((self.path, FileModifiedEvent(path)))

                for path in diff.files_created:
                    q.put((self.path, FileCreatedEvent(path)))

                for path, new_path in diff.files_moved.items():
                    q.put((self.path, FileMovedEvent(path, new_path)))

                for path in diff.dirs_modified:
                    q.put((self.path, DirModifiedEvent(path)))

                for path in diff.dirs_deleted:
                    q.put((self.path, DirDeletedEvent(path)))

                for path in diff.dirs_created:
                    q.put((self.path, DirCreatedEvent(path)))

                for path, new_path in diff.dirs_moved.items():
                    q.put((self.path, DirMovedEvent(path, new_path)))



class PollingObserver(Thread):
    """Observer daemon thread that spawns threads for each path to be monitored.
    """
    def __init__(self, interval=1, *args, **kwargs):
        Thread.__init__(self)
        self.interval = interval
        self.args = args
        self.kwargs = kwargs
        self.event_queue = Queue()
        self.event_producer_threads = set()
        self.rules = {}
        self.setDaemon(True)


    @synchronized()
    def add_rule(self, path, event_handler):
        """Adds a rule to watch a path and sets a callback handler instance.
        """
        if not path in self.rules:
            event_producer_thread = _PollingEventProducer(path=path, interval=self.interval, out_event_queue=self.event_queue)
            self.event_producer_threads.add(event_producer_thread)
            self.rules[path] = {
                'event_handler': event_handler,
                'event_producer_thread': event_producer_thread,
                }


    @synchronized()
    def remove_rule(self, path):
        """Stops watching a given path if already being monitored."""
        if path in self.rules:
            rule = self.rules.pop(path)
            event_producer_thread = rule['event_producer_thread']
            event_producer_thread.stop()
            self.event_producer_threads.remove(event_producer_thread)


    def run(self):
        """Spawns threads that generate events into the output queue,
        one monitor thread per path."""
        # Wait while we do not have rules.
        #while not self.rules:
        #    pass

        for t in self.event_producer_threads:
            t.start()
            try:
                while True:
                    (rule_path, event) = self.event_queue.get()
                    event_handler = self.rules[rule_path]['event_handler']
                    event_handler.dispatch(event)
            except KeyboardInterrupt:
                t.stop()


    def stop(self):
        """Stops all monitoring."""
        for t in self.event_producer_threads:
            t.stop()
            #t.join()


if __name__ == '__main__':
    import time
    import sys
    path = sys.argv[1]
    o = PollingObserver()
    o.add_rule(path, FileSystemEventHandler())
    o.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        o.remove_rule(path)
        o.stop()
        raise
    o.join()