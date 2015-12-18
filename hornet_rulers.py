#!/usr/bin/env python3

import concurrent.futures
import logging
import os
import sqlite3

import prometheus_client
import tornado.ioloop
import tornado.web

class InstrumentedHandler(tornado.web.RequestHandler):

    _duration_metric = prometheus_client.Summary(
        'http_request_duration_seconds',
        'HTTP request latencies in seconds.',
        ['handler'])
    _total_metric = prometheus_client.Counter(
        'http_requests_total',
        'Total number of HTTP requests made.',
        ['code', 'handler', 'method'])
    _exceptions_metric = prometheus_client.Counter(
        'http_exceptions_total',
        'Total number of Exceptions raised inside handlers.',
        ['handler', 'exception'])

    def on_finish(self):
        handler = type(self).__name__
        self._duration_metric.labels(handler).observe(self.request.request_time())
        self._total_metric.labels(self.get_status(), handler, self.request.method.lower()).inc()
        super().on_finish()

    def write_error(self, status_code, **kwargs):
        if 'exc_info' in kwargs:
            typ, error, tb = kwargs['exc_info']
            self._exceptions_metric.labels(type(self).__name__, typ.__name__).inc()
        super().write_error(status_code, **kwargs)


class URLManager:

    def __init__(self, filename):
        self.db = sqlite3.connect(filename)
        with self.db:
            cursor = self.db.cursor()
            cursor.execute('CREATE TABLE IF NOT EXISTS urls (link TEXT, url TEXT);')

    def set_url(self, link, url):
        with self.db:
            cursor = self.db.cursor()
            cursor.execute('UPDATE urls SET url = ? WHERE link = ?;', [url, link])
            if cursor.rowcount == 0:
                cursor.execute('INSERT INTO urls (link, url) VALUES (?, ?);', [link, url])

    def delete_url(self, link):
        with self.db:
            cursor = self.db.cursor()
            cursor.execute('DELETE FROM urls WHERE link = ?;', [link])

    def get_url(self, link):
        with self.db:
            cursor = self.db.cursor()
            cursor.execute('SELECT url FROM urls WHERE link = ?;', [link])
            row = cursor.fetchone()
            if row is None:
                return None
            else:
                return row[0]


class MainHandler(InstrumentedHandler):

    def initialize(self, url_manager):
        self.url_manager = url_manager
        self.prefix = '{}://{}'.format(self.request.protocol, self.request.host)

    def get(self, link):
        if len(link) == 0:
            self.render('index.html', prefix=self.prefix, link='', url='')
            return

        url = self.url_manager.get_url(link)
        if url is None:
            self.render('index.html', prefix=self.prefix, link=link, url='')
            return
        self.redirect(url)

    def post(self, unused_link):
        link = self.get_body_argument('link', '')
        url = self.get_body_argument('url', '')
        confirmed = self.get_body_argument('confirmed', False)

        if len(link) == 0:
            self.render('index.html', prefix=self.prefix, link=link, url=url)
            return

        existing_url = url_manager.get_url(link)

        if len(url) == 0:
            if existing_url is None:
                self.render('index.html', prefix=self.prefix, link=link, url='')
                return
            if not confirmed:
                self.render('confirm_delete.html', prefix=self.prefix, link=link, existing_url=existing_url)
                return
            url_manager.delete_url(link)
            self.render('deleted.html', prefix=self.prefix, link=link)
            return

        if not url.startswith('http'):
            url = 'http://{}'.format(url)

        if existing_url is not None and not confirmed:
            self.render('confirm_update.html', prefix=self.prefix, link=link, existing_url=existing_url, url=url)
            return

        self.url_manager.set_url(link, url)
        self.render('updated.html', prefix=self.prefix, link=link, url=url)


class MetricsHandler(InstrumentedHandler):

    def get(self):
        self.write(prometheus_client.generate_latest())
        self.set_header('Content-Type', prometheus_client.CONTENT_TYPE_LATEST)
        self.finish()


if __name__ == "__main__":
    logging.getLogger("tornado.access").setLevel(logging.INFO)
    url_manager = URLManager(os.getenv('DATABASE'))
    app = tornado.web.Application(
        [
            (r'/metrics', MetricsHandler),
            (r'/(.*)', MainHandler, {'url_manager': url_manager}),
        ],
        template_path='templates')
    app.listen(3204)
    tornado.ioloop.IOLoop.current().start()
