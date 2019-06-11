import os
import io
import json
import time
import asyncio
import logging
import datetime
import threading
from urllib.parse import urlparse
from rtconfig.exceptions import ProjectNoFoundException
from rtconfig.utils import OSUtils, object_merge, strftime

try:
    import redis
    redis_usable = True
except:
    redis_usable = False


try:
    import pymongo
    import pymongo.uri_parser
    mongodb_usable = True
except:
    mongodb_usable = False


logger = logging.getLogger(__name__)
default_backends = {}
__all__ = ["BaseBackend"]
type_map = {
    'string': str,
    'int': int,
    'float': float,
    'bool': bool,
}


class BaseBackend:
    __charset__ = "utf-8"
    __visit_name__ = 'base'

    def __init__(self, loop=None, notify_callback=None):
        self.loop = loop
        self.notify_callback = notify_callback

    @classmethod
    def configuration_schema(cls):
        return {}

    def read(self, config_name, default=None, check_exist=False):
        raise NotImplementedError

    async def write(self, config_name, data, merge=False):
        raise NotImplementedError

    async def delete(self, config_name):
        raise NotImplementedError

    def iter_backend(self):
        raise NotImplementedError

    async def publish(self, callback_func, *args, **kwargs):
        if self.notify_callback:
            await self.notify_callback(self.get_callback_message(
                callback_func, *args, **kwargs))

    def subscribe(self):
        pass

    @staticmethod
    def get_callback_message(callback_func, *args, **kwargs):
        return json.dumps(dict(
            func=callback_func,
            args=list(args),
            kwargs=kwargs
        ))

    @classmethod
    def validate_options(cls, app_config, **kwargs):
        options = kwargs
        for key, schema in cls.configuration_schema().items():
            type_str = schema.get('type', None)
            default_value = schema.get("default", None)
            required = schema.get("required", False)
            app_key = key.upper()
            if app_key in app_config:
                if not isinstance(app_config[app_key], type_map[type_str]):
                    raise TypeError("App config {} (type invalid)".format(app_key))
                else:
                    options[key] = app_config[app_key]
            elif required:
                raise ValueError("App config {} (required)".format(app_key))
            else:
                options[key] = default_value
        return options

    def description(self):
        return {schema.get('desc', key): getattr(self, key, '--')
                for key, schema in self.configuration_schema().items()}

    def __init_subclass__(cls, **kwargs):
        __all__.append(cls.__name__)
        try:
            backend_name = cls.__visit_name__
        except AttributeError:
            backend_name = ''.join('_%s' % c if c.isupper() else c
                                   for c in cls.__name__).strip('_').lower()
        default_backends[backend_name] = cls


class JsonFileBackend(BaseBackend):
    _extension = '.json'
    __visit_name__ = 'json_file'

    @classmethod
    def configuration_schema(cls):
        return {
            'config_store_directory': {
                'required': False,
                'type': 'string',
                'desc': '数据存储目录',
                'default': '~/rtconfig/data'
            }
        }

    def __init__(self, config_store_directory, loop=None, notify_callback=None):
        super().__init__(loop, notify_callback)
        self.config_store_directory = os.path.abspath(
            os.path.expanduser(config_store_directory))
        self.os_util = OSUtils()

        if not self.os_util.directory_exists(self.config_store_directory):
            self.os_util.makedirs(self.config_store_directory)

    def get_file_path(self, config_name):
        file_name = config_name + self._extension
        return os.path.join(self.config_store_directory, file_name)

    def read(self, config_name, default=None, check_exist=False):
        file_path = self.get_file_path(config_name)
        try:
            with io.open(file_path, encoding=self.__charset__) as open_file:
                source_data = json.load(open_file)
            logger.debug("Backend read json: {}".format(file_path))
        except IOError:
            logger.debug("Backend read json: {} (Ignored, file not Found)".format(file_path))
            if check_exist:
                raise ProjectNoFoundException(config_name=config_name)
            source_data = default or {}
        return source_data

    async def write(self, config_name, source_data, merge=False):
        file_path = self.get_file_path(config_name)
        if self.os_util.file_exists(file_path) and merge:
            with io.open(file_path, encoding=self.__charset__) as open_file:
                object_merge(json.load(open_file), source_data)

        with io.open(file_path, "w", encoding=self.__charset__) as open_file:
            json.dump(source_data, open_file)
        await self.publish('callback_config_changed', config_name)

    def iter_backend(self):
        for _, _, file_names in OSUtils().walk(self.config_store_directory):
            for file_name in file_names:
                config_name, extension = os.path.splitext(file_name)
                if extension != self._extension:
                    continue
                yield config_name

    async def delete(self, config_name):
        file_path = self.get_file_path(config_name)
        if self.os_util.file_exists(file_path):
            self.os_util.remove_file(file_path)
        await self.publish('callback_config_changed', config_name)


class RedisBackend(BaseBackend):
    __visit_name__ = "redis"
    _config_data_scope = 'rt_config_data'

    @classmethod
    def configuration_schema(cls):
        return {
            'redis_url': {
                'required': True,
                'type': 'string',
                'desc': 'Redis链接'
            },
            'open_notify': {
                'required': False,
                'type': 'bool',
                'desc': '开启通知',
                'default': True
            },
            'notify_channel': {
                'required': False,
                'type': 'string',
                'desc': '通知信道',
                'default': 'rtc_config'
            },
        }

    def __init__(self, redis_url=None, open_notify=True, notify_channel=None, loop=None, notify_callback=None):
        super().__init__(loop, notify_callback)
        self.redis_url = redis_url
        self.open_notify = open_notify
        self.notify_channel = notify_channel
        self._thread = None
        if not redis_usable:
            raise RuntimeError('You need install [redis] package.')

    @property
    def redis_client(self):
        logger.debug("Creating Redis connection (%s)", self.redis_url)
        redis_conf = urlparse(self.redis_url)
        db = redis_conf.path[1] if redis_conf.path else 0
        return redis.StrictRedis(
            host=redis_conf.hostname,
            port=redis_conf.port, db=db,
            password=redis_conf.password
        )

    def read(self, config_name, default=None, check_exist=False):
        if isinstance(default, dict):
            default = json.dumps(default).encode(self.__charset__)
        else:
            default = b'{}'
        data = self.redis_client.hget(self._config_data_scope, config_name)
        if data is None and check_exist:
            raise ProjectNoFoundException(config_name=config_name)
        return json.loads((data or default).decode(self.__charset__))

    async def write(self, config_name, source_data, merge=False):
        if merge:
            object_merge(self.read(config_name), source_data)
        self.redis_client.hset(
            self._config_data_scope,
            config_name,
            json.dumps(source_data)
        )
        await self.publish('callback_config_changed', config_name)

    def iter_backend(self):
        return (i.decode(self.__charset__) for i in
                self.redis_client.hkeys(self._config_data_scope))

    async def delete(self, config_name):
        self.redis_client.hdel(self._config_data_scope, config_name)
        await self.publish('callback_config_changed', config_name)

    async def publish(self, callback_func, *args, **kwargs):
        if not self.open_notify:
            return
        self.redis_client.publish(self.notify_channel, self.get_callback_message(
                callback_func, *args, **kwargs))

    def subscribe(self):
        if not (self.open_notify and self.notify_callback):
            return

        def init_loop():
            try:
                return asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return asyncio.get_event_loop()

        def loop_subscribe():
            ps = self.redis_client.pubsub()
            ps.subscribe(self.notify_channel)
            for item in ps.listen():
                if item['type'] == 'message':
                    message = item['data'].decode()
                    logger.info(f"{os.getpid()} From {self.notify_channel} get message : %s", message)
                    if item['data'] == 'over':
                        logger.info("Stop subscribe redis.")
                        break
                    loop = self.loop or init_loop()
                    loop.run_until_complete(self.notify_callback(message))
            ps.unsubscribe('spub')
            logger.info("Cancel subscribe redis.")

        self._thread = threading.Thread(target=loop_subscribe)
        self._thread.setDaemon(True)
        self._thread.start()
        logger.info('Start subscribe thread.')


class MongodbBackend(BaseBackend):
    __visit_name__ = "mongodb"
    _config_data_scope = 'rt_config_data'
    _config_publish_scope = 'rt_config_publish'

    @classmethod
    def configuration_schema(cls):
        return {
            'mongodb_url': {
                'required': True,
                'type': 'string',
                'desc': 'Mongodb链接'
            },
            'loop_interval': {
                'required': False,
                'type': 'int',
                'desc': '消息检查间隔',
                'default': 1
            },
            'open_notify': {
                'required': False,
                'type': 'bool',
                'desc': '开启通知',
                'default': True
            }
        }

    def __init__(self, mongodb_url=None, loop_interval=None, open_notify=True, loop=None, notify_callback=None):
        super().__init__(loop, notify_callback)
        self.mongodb_url = mongodb_url
        self.open_notify = open_notify
        self.loop_interval = loop_interval
        self._tsp = None
        self._thread = None
        self._clear_date = None
        self.async_lock = asyncio.Lock()
        if not mongodb_usable:
            raise RuntimeError('You need install [pymongo] package.')

    @property
    def db_client(self):
        logger.debug("Creating Mongodb connection (%s)", self.mongodb_url)
        res = pymongo.uri_parser.parse_uri(self.mongodb_url, warn=True)
        db_connection = pymongo.MongoClient(self.mongodb_url)
        return db_connection[res["database"]]

    def read(self, config_name, default=None, check_exist=False):
        model = self.db_client[self._config_data_scope].find_one({'config_name': config_name})
        if not model:
            if check_exist:
                raise ProjectNoFoundException(config_name=config_name)
            else:
                return default
        return model['data']

    async def write(self, config_name, source_data, merge=False):
        db = self.db_client
        if merge:
            object_merge(self.read(config_name), source_data)
        model = db[self._config_data_scope].find_one({'config_name': config_name})
        if not model:
            db[self._config_data_scope].insert_one(dict(
                config_name=config_name,
                data=source_data,
                created=datetime.datetime.now(),
                lut=datetime.datetime.now(),
            ))
        else:
            db[self._config_data_scope].update_one(
                {'config_name': config_name},
                {'$set': dict(
                    data=source_data,
                    lut=datetime.datetime.now()
                )}
            )
        await self.publish('callback_config_changed', config_name)

    def iter_backend(self):
        return (i['config_name'] for i in self.db_client[self._config_data_scope].find())

    async def delete(self, config_name):
        self.db_client[self._config_data_scope].remove({'config_name': config_name})
        await self.publish('callback_config_changed', config_name)

    async def publish(self, callback_func, *args, **kwargs):
        if not self.open_notify:
            return
        async with self.async_lock:
            self.db_client[self._config_publish_scope].insert_one(dict(
                tsp=int(time.time() * 1000000),
                message=self.get_callback_message(
                    callback_func, *args, **kwargs),
                created=datetime.datetime.now(),
            ))
            await asyncio.sleep(0.01)

    def get_newest_message(self, init=False):
        if init:
            ret = list(self.db_client[self._config_publish_scope]
                       .find().sort([("tsp", -1)]).limit(1))
            if ret:
                self._tsp = ret[0]['tsp']
        else:
            params = {"tsp": {"$gt": self._tsp}} if self._tsp else {}
            ret = list(self.db_client[self._config_publish_scope]
                       .find(params).sort([("tsp", 1)]))
        return ret

    def clear_history_message(self):
        date_str = strftime(datetime.datetime.now(), '%Y-%m-%d')
        if date_str == self._clear_date:
            return
        self.db_client[self._config_publish_scope].remove({'created': {'$lt': date_str}})
        self._clear_date = date_str

    def subscribe(self):
        if not (self.open_notify and self.notify_callback):
            return

        def init_loop():
            try:
                return asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return asyncio.get_event_loop()

        def loop_subscribe():
            running = True
            self.get_newest_message(init=True)
            while running:
                self.clear_history_message()
                for item in self.get_newest_message():
                    message = item['message']
                    logger.info(f"{os.getpid()} From mongodb get message : %s", message)
                    if message == 'over':
                        logger.info("Stop subscribe mongodb.")
                        running = False
                    self._tsp = item['tsp']
                    loop = self.loop or init_loop()
                    loop.run_until_complete(self.notify_callback(message))
                time.sleep(self.loop_interval)
            logger.info("Cancel subscribe mongodb.")

        self._thread = threading.Thread(target=loop_subscribe)
        self._thread.setDaemon(True)
        self._thread.start()
        logger.info('Start subscribe thread.')
