import os
import re
import copy
import uuid
import datetime
from rtconfig.message import *
from rtconfig.exceptions import *
from rtconfig.mixin import CallbackHandleMixin
from rtconfig.utils import to_hash, OSUtils, format_env_data, strftime
from rtconfig.backend import default_backends
from rtconfig.helpers import _, CallbackSet, LinkDict
from contextlib import contextmanager


ENV_DOMAIN = {
    'default': {},
    'environ': {},
    'history': {}
}


class ConfigProject:
    def __init__(self, config_name, store_backend, env=None, context=None):
        self.config_name = config_name
        self.store_backend = store_backend
        self.env = env
        self.context = context
        self._source_data = None
        self.request = None
    
    @contextmanager
    def use_env(self, env=None, context=None, request=None):
        self.validate_env(env)
        self.env = env
        self.context = context
        self.request = request
        try:
            yield
        except Exception as ex:
            raise ex
        finally:
            self.env = None
            self.context = None

    def validate_env(self, env):
        if env and env not in self.source_data:
            raise ProjectEnvErrorException(
                config_name=self.config_name, env=env
            )
    
    @property
    def source_data(self):
        return self.store_backend.read(self.config_name, ENV_DOMAIN)

    def _get_data_from_env(self):
        return self.source_data.get(self.env) or {} \
            if self.env else self.source_data

    def key_exist(self, key):
        return key in self._get_data_from_env()

    def record_history(self, env, source_data, data):
        if not (data and isinstance(data, dict)):
            return
        data = list(data.values())[0]
        org_data = source_data[self.env].get(data['key']) or {}
        if to_hash(org_data) == to_hash(data):
            return
        if 'history' not in source_data:
            source_data['history'] = {}
        source_data['history'].setdefault(env, {})
        source_data['history'][env].setdefault(data['key'], [])
        source_data['history'][env][data['key']].append(dict(
            before=org_data,
            after=data,
            operator=self.request.user.id if self.request else None,
            lut=strftime(datetime.datetime.now())
        ))

    async def set_source_data(self, data):
        if not data:
            data = ENV_DOMAIN
        assert isinstance(data, dict)
        source_data = self.source_data
        if self.env:
            source_data.setdefault(self.env, {})
            self.record_history(self.env, source_data, data)
            source_data[self.env].update(data)
        else:
            list(map(self.validate_env, data))
            source_data = data
        await self.update_config(source_data)

    async def remove_source_data(self, keys):
        assert isinstance(keys, list)
        source_data = self.source_data
        if self.env:
            env_data = source_data.get(self.env) or {}
        else:
            env_data = source_data
        for key in keys:
            try:
                del env_data[key]
            except KeyError:
                continue
        await self.update_config(source_data)

    def get_hash_code(self):
        return to_hash(self.get_env_data())

    async def update_config(self, source_data):
        await self.store_backend.write(self.config_name, source_data)

    async def remove_config(self):
        await self.store_backend.delete(self.config_name)

    def get_env_kv_data(self, source_data, env):
        env_data = source_data.get(env) or {}
        return {i['key']: i['value'] for i in env_data.values()}

    def get_env_data(self):
        env_data, source = {}, copy.deepcopy(self.source_data)
        env_variable = self.get_env_kv_data(source, 'environ')
        for env in ['default', self.env, 'global']:
            env_data.update(self.get_env_kv_data(source, env))

        try:
            if self.context:
                environ = copy.copy(self.context['environ'])
                environ.update(self.context)
                for key, value in environ.items():
                    if key not in env_variable:
                        continue
                    env_variable[key] = value
        except:
            pass
        return format_env_data(env_data, **env_variable)

    def config_message(self, message, response_mode=RESPONSE_MODE_NOTIFY):
        with self.use_env(message.env, message.context):
            env_hash_code = self.get_hash_code()
            if message.hash_code == env_hash_code:
                message_type, data = MT_NO_CHANGE, {}
            else:
                message_type, data = MT_CHANGED, self.get_env_data()
            return Message(
                message_type,
                self.config_name,
                env_hash_code,
                data,
                request=message.request,
                env=message.env,
                response_mode=response_mode
            ).get_push_message()

    def detail_info(self):
        return dict(
            config_name=self.config_name,
            source_data=self.source_data
        )


class ConfigManager(CallbackHandleMixin):
    _default_store_type = 'json_file'
    _connection_pool = LinkDict()
    _connection_message = LinkDict()
    _other_connection_pool = {}
    _config_name_regex = re.compile('^[\u4e00-\u9fa5_a-zA-Z0-9_]+$')

    def __init__(self, app, os_utils=None, logger=None, log_file_name=None, store_type=None):
        self.app = app
        self.debug = self.app.config.get('DEBUG', True)
        self.max_connection = self.app.config.get('MAX_CONNECTION', 1024)
        self.os_utils = os_utils or OSUtils()
        self.logger = logger or logging.getLogger(__name__)
        self.log_file_name = log_file_name
        self.store_type = store_type or self.app.config.get(
            'STORE_TYPE', self._default_store_type)
        self.store_backend = None
        self.rt_log = self.app.config.get("RT_SERVER_LOG", True)
        config_logging(self.log_file_name, self.logger)
        self.init_store_backend_instance()

    @property
    def system_info(self):
        return {
            '存储方式': self.store_type,
            'DEBUG模式': self.debug,
            '最大连接数': self.max_connection,
            **self.store_backend.description()
        }

    @property
    def client_info(self):
        info = {
            '配置项目数': self.config_project_num(),
            '客户端连接数': self.connection_num(),
        }
        try:
            import psutil
            p = psutil.Process(os.getpid())
            info.update({
                'CPU利用率': "%s%%" % round(p.cpu_percent(1), 2),
                '内存利用率': "%s%%" % round(p.memory_percent(), 2),
            })
        except ImportError:
            pass
        return info

    def init_store_backend_instance(self):
        store_backend_class = default_backends[self.store_type]
        options = store_backend_class.validate_options(
            self.app.config, loop=self.app.loop,
            notify_callback=self.notify_changed)
        self.store_backend = store_backend_class(**options)
        self.store_backend.subscribe()

    def connection_num(self, config_name=None):
        return len(self.get_connection_clients(config_name))

    def config_project_num(self):
        return len(self.get_config_project_list())

    def get_config_project(self, config_name, check_exist=False):
        self.store_backend.read(config_name, check_exist=check_exist)
        return ConfigProject(config_name, self.store_backend)

    def get_config_project_info(self, config_name):
        config_project = self.get_config_project(config_name)
        return dict(
            connect_num=self.connection_num(config_name),
            **config_project.detail_info()
        )

    def get_config_project_list(self):
        return [self.get_config_project_info(i)
                for i in self.store_backend.iter_backend()]

    def validate_name(self, name):
        return self._config_name_regex.match(name)

    async def create_config_project(self, config_name, copy_from=None):
        if not self.validate_name(config_name):
            raise ProjectNameErrorException(config_name=config_name)
        try:
            self.get_config_project(config_name, check_exist=True)
        except ProjectNoFoundException:
            config_project = self.get_config_project(config_name)
        else:
            raise ProjectExistException(config_name=config_name)
        env, data = None, None
        if copy_from:
            copy_from_project = self.get_config_project(copy_from)
            data = copy.deepcopy(copy_from_project.source_data)
        with config_project.use_env(env):
            await config_project.set_source_data(data)
        return config_project

    async def update_config_project(self, request, config_name, source_data, env=None):
        config_project = self.get_config_project(config_name)
        with config_project.use_env(env=env, request=request):
            await config_project.set_source_data(source_data)
        return config_project

    async def add_env_config(self, request, config_name, env, data):
        config_project = self.get_config_project(config_name)
        with config_project.use_env(env=env, request=request):
            await config_project.set_source_data(data)
        return config_project

    async def remove_env_config(self, config_name, env, keys):
        config_project = self.get_config_project(config_name)
        with config_project.use_env(env):
            await config_project.remove_source_data(keys)
        return config_project

    def env_key_exist(self, config_name, env, key):
        config_project = self.get_config_project(config_name)
        with config_project.use_env(env):
            return config_project.key_exist(key)

    async def remove_config_project(self, config_name):
        config_project = self.get_config_project(config_name)
        await config_project.remove_config()

    async def add_connection(self, ws, message):
        try:
            if self.connection_num() > self.max_connection:
                raise ConnectException(
                    description='Number of connection is already the '
                                'maximum %s.' % self.max_connection)
            config_name = message.config_name
            self.get_config_project(config_name)
            self._connection_pool.setdefault(config_name, CallbackSet(
                on_remove=self._connection_message))
            if not hasattr(ws, 'ws_key'):
                ws.ws_key = uuid.uuid4().hex
            desc = 'report' if ws in self._connection_pool[config_name] else 'first'
            self._connection_pool[config_name].add(ws)
            self._connection_message[ws] = message
            await self.store_backend.publish(
                'callback_add_connection', ws.ws_key,
                self.format_message_data(message))
            self.logger.info('[%s] Client %s connected, pid: %s.',
                             message.config_name, desc,
                             message.context['pid'])
        except KeyError:
            raise ProjectNoFoundException(config_name=message.config_name)

    async def remove_connection(self, ws, message):
        try:
            await self.store_backend.publish('callback_remove_connection', ws.ws_key)
            self._connection_pool[message.config_name].remove(ws)
            self.logger.info('[%s] Client disconnected: %s.',
                             message.config_name, message.context['pid'])
        except KeyError:
            pass

    def format_message_data(self, message):
        context = dict(
            client=message.context,
            request=dict(
                headers=dict(message.request.headers),
            )
        )
        data = dict(
            pid=os.getpid(),
            message_type=message.message_type,
            config_name=message.config_name,
            hash_code=message.hash_code,
            data=message.data,
            context=context,
            env=message.env,
            client_ip=message.request.environ.get("client")[0],
            lut=strftime(message.lut)
        )
        try:
            config_project = self.get_config_project(message.config_name)
            with config_project.use_env(message.env, message.context):
                data['server_hash_code'] = config_project.get_hash_code()
        except ProjectNoFoundException:
            data['server_hash_code'] = '--'
        return data

    def get_connection_clients(self, config_name=None):
        result, client_list = [], self._other_connection_pool
        client_list.update({ws.ws_key: self.format_message_data(message)
                            for ws, message in self._connection_message.items()})
        for data in client_list.values():
            if config_name and data['config_name'] != config_name:
                continue
            result.append(data)
        return result
