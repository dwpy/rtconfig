import os
import io
import json
import hashlib
import logging
from datetime import datetime
from urllib.parse import urlparse
from rtconfig.utils import OSUtils, strftime
from rtconfig.exceptions import GlobalApiException
from alita_login import UserMixin
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


class User(UserMixin):
    def __init__(self, data=None):
        self.data = data or {}
        for k, v in self.data.items():
            setattr(self, k, v)

    def get_id(self):
        try:
            return self.id
        except AttributeError:
            raise NotImplementedError('No `id` attribute - override `get_id`')


class AuthManager:
    __charset__ = "utf-8"

    def __init__(self, app):
        self.app = app
        self.os_util = OSUtils()

    def make_password(self, password):
        return hashlib.md5(password.encode("utf-8")).hexdigest()

    def get_all(self):
        raise NotImplementedError

    def save_all(self, all_user):
        raise NotImplementedError

    def get_user(self, username):
        return self.get_all().get(username)

    def get_user_by_id(self, user_id):
        return {i['id']: i for i in self.get_all().values()}.get(user_id)

    def update_user(self, username, password=None, **kwargs):
        all_user = self.get_all()
        if password:
            kwargs['password'] = self.make_password(password)
        if username in all_user:
            kwargs['lut'] = strftime(datetime.now())
        else:
            kwargs['username'] = username
            kwargs['created'] = strftime(datetime.now())
            max_user = max(all_user.values(), key=lambda x: x['id']) if all_user else None
            kwargs['id'] = max_user['id'] + 1 if max_user else 1
        kwargs['lut'] = strftime(datetime.now())
        all_user.setdefault(username, {})
        all_user[username].update(kwargs)
        self.save_all(all_user)

    def check_password(self, username, password):
        user = self.get_user(username)
        if not user:
            raise GlobalApiException('用户名不存在')
        if self.make_password(password) != user['password']:
            raise GlobalApiException('密码错误')
        return user

    def load_user(self, user):
        user = user if isinstance(user, dict) \
            else self.get_user_by_id(user)
        return User(user) if user else None

    def init_admin(self):
        if 'admin' not in self.get_all():
            self.update_user('admin', 'admin')


class FileAuthManager(AuthManager):

    def __init__(self, app):
        super().__init__(app)
        self.store_directory = os.path.abspath(
            os.path.expanduser(self.app.config['CONFIG_STORE_DIRECTORY']))
        self.user_file = os.path.join(self.store_directory, 'user.data')
        self.init_admin()

    def get_all(self):
        try:
            with io.open(self.user_file, encoding=self.__charset__) as open_file:
                return json.load(open_file)
        except IOError:
            return {}

    def save_all(self, all_user):
        with io.open(self.user_file, "w", encoding=self.__charset__) as open_file:
            json.dump(all_user, open_file)


class RedisAuthManager(AuthManager):
    _auth_data_scope = 'rt_auth_data'

    def __init__(self, app):
        super().__init__(app)
        self.redis_url = self.app.config['REDIS_URL']
        if not redis_usable:
            raise RuntimeError('You need install [redis] package.')
        self.init_admin()

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

    def get_all(self):
        return {k.decode(self.__charset__): json.loads(v.decode(self.__charset__))
                for k, v in self.redis_client.hgetall(self._auth_data_scope).items()}

    def save_all(self, all_user):
        self.redis_client.hmset(self._auth_data_scope, {
            k: json.dumps(v) for k, v in all_user.items()})


class MongodbAuthManager(AuthManager):
    _auth_data_scope = 'rt_auth_data'

    def __init__(self, app):
        super().__init__(app)
        self.mongodb_url = self.app.config['MONGODB_URL']
        if not mongodb_usable:
            raise RuntimeError('You need install [pymongo] package.')
        self.init_admin()

    @property
    def db_client(self):
        logger.debug("Creating Mongodb connection (%s)", self.mongodb_url)
        res = pymongo.uri_parser.parse_uri(self.mongodb_url, warn=True)
        db_connection = pymongo.MongoClient(self.mongodb_url)
        return db_connection[res["database"]]

    def get_all(self):
        return {i['username']: i for i in self.db_client[self._auth_data_scope].find()}

    def save_all(self, all_user):
        db = self.db_client
        for username, user in all_user.items():
            model = db[self._auth_data_scope].find_one({'username': username})
            if model:
                db[self._auth_data_scope].update_one(
                    {'username': username}, {'$set': user})
            else:
                db[self._auth_data_scope].insert_one(user)


__all__ = [
    'FileAuthManager',
    'RedisAuthManager',
    'MongodbAuthManager'
]
