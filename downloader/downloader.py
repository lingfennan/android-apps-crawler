#!/usr/bin/env python
# encoding: utf-8
import sys
import threading
import sqlite3
import time
import urllib2
import os
import hashlib
import signal
import Queue
import socket
import errno

NUM_THREAD = 20
work_queue_lock = threading.Lock()
update_database_lock = threading.Lock()

class Downloader(threading.Thread):
    def __init__(self, work_queue, output_dir, database_filepath):
        threading.Thread.__init__(self)
        self.exit_event = threading.Event()
        self.work_queue = work_queue
        self.proxies = None
        #Define proxy below
        #self.proxies = {"http": ""}
        self.output_dir = output_dir
        self.current_file_size = 0
        self.file_size = 0
        self.database_filepath = database_filepath

    def exit(self):
        print("%s: asked to exit." % self.getName())
        self.exit_event.set()
        self.join()
        return self.report()

    def report(self):
        if self.file_size == 0:
            return 0
        return float(self.current_file_size) / self.file_size

    def run(self):
        while not self.exit_event.isSet():
            work_queue_lock.acquire()
            if not self.work_queue.empty():
                self.id, self.url = self.work_queue.get()
                work_queue_lock.release()
                try:
                    self.download()
                    self.save()
                    self.update_database()
                except urllib2.HTTPError:
                    self.update_database(-1)
                except socket.error as e:
                    if e.errno == errno.ECONNRESET:
                        # self.update_database(-1)
                        print("Connection reset")
            else:
                work_queue_lock.release()
        print("%s: received exit event." % self.getName())

    def download(self):
        print("%s: downloading %s" % (self.getName(), self.url))
        self.current_file_size = 0
        self.file_size = 0
        proxy_handler = urllib2.ProxyHandler()
        if (self.proxies):
            proxy_handler = urllib2.proxyHandler(self.proxies);
        opener = urllib2.build_opener(proxy_handler)
        opener.addheaders = [
            ('User-Agent', r"Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.11 "
                "(KHTML, like Gecko) Chrome/23.0.1271.97 Safari/537.11"),
            ('Referer', self.url)
        ]
        urllib2.install_opener(opener)
        opening = urllib2.urlopen(self.url)
        meta = opening.info()
        self.file_size = int(meta.getheaders("Content-Length")[0])
        temp_file_name = "%d.apk" % (time.time() * 1000000)
        temp_dir = self.output_dir + os.sep + "temp"
        self.temp_output_path = temp_dir + os.sep + temp_file_name
        with open(self.temp_output_path, 'wb') as fil:
            block_size = 10240
            while True:
                buf = opening.read(block_size)
                self.current_file_size += len(buf)
                fil.write(buf)
                if not buf:
                    break

    def save(self):
        with open(self.temp_output_path, 'r') as fil:
            m = hashlib.md5()
            m.update(fil.read())
            md5_digest = m.hexdigest()
        new_output_path = self.output_dir + os.sep + md5_digest + ".apk"
        if os.path.isfile(new_output_path):
            os.remove(new_output_path)
        os.rename(self.temp_output_path, new_output_path)
        print("%s: %s.apk is completed." % (self.getName(), md5_digest))

    def update_database(self, result=1):
        update_database_lock.acquire()
        try:
            connection = sqlite3.connect(self.database_filepath)
            cursor = connection.cursor()
            # TODO: currently use id to update, in order to avoid string encoding problems.
            cursor.execute('update apps set downloaded = ? where id = ?',
                    (result, self.id,))
            connection.commit()
        except sqlite3.OperationalError:
            print("%s: Operational Error" % (self.getName()))
        finally:
            connection.close()
            update_database_lock.release()

class Monitor(threading.Thread):
    def __init__(self, threads):
        threading.Thread.__init__(self)
        self.threads = threads
        self.exit_event = threading.Event()
        self.status_queue = Queue.Queue(maxsize=30)
        self.freeze_exit = False
    def exit(self):
        self.exit_event.set()
        self.join()
    def exitFreeze(self):
        # Exit because of thread freeze
        self.freeze_exit = True
        for t in self.threads:
            t.exit()
        self.exit()
    def run(self):
        while not self.exit_event.isSet():
            report_str = ""
            for t in self.threads:
                report_value = t.report()
                if report_value == 0:
                    report_str += (" new")
                else:
                    report_str += ("%3.0f%%" % (report_value*100))
            print(report_str)
            # Maintain a queue of past status, if the status shows that the program freezes, then terminate and restart.
            self.status_queue.put(report_str)
            if self.status_queue.full():
                self.status_queue.get()
                if not self.isAlive():
                    print("Monitor found the process is freezed!")
                    self.exitFreeze()
            time.sleep(1)
    def isAlive(self):
        # If the status doesn't change for maxsize * sleep_interval, the program is considered not alive.
        if self.status_queue.empty():
            return True
        first = self.status_queue.queue[0]
        for i in range(1, self.status_queue.qsize()):
            if first != self.status_queue.queue[i]:
                return True
        return False

def get_download_url(database_filepath, downloaded = 0):
    """Get download url and their ids. Return ids, because the string has lots of encoding problems. Use id as a
    circumvent approach.

    :param database_filepath: the path to the database file.
    :param downloaded: the status of downloaded, -1 means error, 0 mean undownloaded, 1 mean downloaded.
    :return: list of urls and their ids, matching the specified download status.
    """
    undownloaded_urls = []
    try:
        connection = sqlite3.connect(database_filepath)
        cursor = connection.cursor()
        sql = "select * from apps where downloaded = %d" % downloaded
        cursor.execute(sql)
        records = cursor.fetchall()
        undownloaded_urls = [(r[0], r[1]) for r in records]
    except sqlite3.OperationalError:
        print("get_download_url(): Operational Error.")
    finally:
        connection.close()
    return undownloaded_urls

def fill_work_queue(work_queue, undownloaded_urls):
    for u in undownloaded_urls:
        id, url = u
        if isinstance(url, unicode):
            url = url.encode('utf-8')
        work_queue.put((id, url))

def import_work(work_queue, database_filepath):
    undownloaded_urls = get_download_url(database_filepath)
    fill_work_queue(work_queue, undownloaded_urls)
    print("number of undownloaded urls: %d" % len(undownloaded_urls))
    return len(undownloaded_urls)

class Watcher:
    """this class solves two problems with multithreaded
    programs in Python, (1) a signal might be delivered
    to any thread (which is just a malfeature) and (2) if
    the thread that gets the signal is waiting, the signal
    is ignored (which is a bug).

    The watcher is a concurrent process (not thread) that
    waits for a signal and the process that contains the
    threads.  See Appendix A of The Little Book of Semaphores.
    http://greenteapress.com/semaphores/

    I have only tested this on Linux.  I would expect it to
    work on the Macintosh and not work on Windows.

    Refer to: http://code.activestate.com/recipes/496735-workaround-for-missed-sigint-in-multithreaded-prog/
    """

    def __init__(self):
        """ Creates a child thread, which returns.  The parent
            thread waits for a KeyboardInterrupt and then kills
            the child thread.
        """
        self.child = os.fork()
        if self.child == 0:
            return
        else:
            self.watch()

    def watch(self):
        try:
            os.wait()
        except KeyboardInterrupt:
            # I put the capital B in KeyBoardInterrupt so I can
            # tell when the Watcher gets the SIGINT
            print("KeyBoardInterrupt")
            self.kill()
        sys.exit()

    def kill(self):
        try:
            os.kill(self.child, signal.SIGKILL)
        except OSError: pass

def main():
    if len(sys.argv) < 2:
        print("Usage: %s <SQLite database> <output directory>" % (sys.argv[0]))
        sys.exit(1)
    else:
        database_filepath = sys.argv[1]
        output_dir = sys.argv[2]

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    temp_dir = output_dir + os.sep + "temp"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    Watcher()
    threads = []
    work_queue = Queue.Queue()
    for i in range(NUM_THREAD):
        t = Downloader(work_queue, output_dir, database_filepath)
        t.daemon = True
        t.start()
        threads.append(t)
    monitor_thread = Monitor(threads)
    monitor_thread.daemon = True
    monitor_thread.start()

    exit_flag = 0
    while exit_flag < 2:
        import_work(work_queue, database_filepath)
        if work_queue.empty():
            exit_flag += 1
        else:
            exit_flag = 0
        while not work_queue.empty():
            time.sleep(10)
            if monitor_thread.freeze_exit:
                # If program exits due to freeze, restart main()
                return "restart"
    for t in threads:
        t.exit()
    monitor_thread.exit()

if __name__ == '__main__':
    while main() == "restart":
        print("**************************main() returned due to freeze_exit! Restarting!***************************")
