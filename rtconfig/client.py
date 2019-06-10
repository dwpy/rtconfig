import os
import types
import asyncio
import threading
import importlib
import traceback
import websockets
from rtconfig.message import *
from rtconfig.exceptions import RTConfigServerError

try:
    from dotenv.main import DotEnv, find_dotenv

    def load_dotenv(dotenv_path=None, stream=None, verbose=False, override=False):
        f = dotenv_path or stream or find_dotenv(usecwd=True)
        return DotEnv(f, verbose=verbose).set_as_environment_variables(override=override)
except ImportError:
    def load_dotenv():
        pass


STATUS_RUN = 'run'
STATUS_STOP = 'stop'


class RtConfigClient:
    _ignore_environs = [
        'LS_COLORS'
    ]
    _environ_variables = [
        'ws_url',
        'env',
        'auto_start',
        'ping_interval',
        'retry_interval'
        'debug',
        'force_exit'
    ]

    def __init__(self, config_name,
                 ws_url=None,
                 logger=None,
                 ping_interval=60 * 5,
                 retry_interval=5,
                 recv_interval=1,
                 config_module=None,
                 daemon=True,
                 auto_start=True,
                 log_file_name=None,
                 context=None,
                 debug=False,
                 env='default',
                 force_exit=True):
        self._data = None
        self._thread = None
        self.debug = debug
        self.config_name = config_name
        self.ws_url = ws_url
        self.hash_code = ''
        self.ping_interval = ping_interval
        self.retry_interval = retry_interval
        self.recv_interval = recv_interval
        self.logger = logger or logging.getLogger(__name__)
        self._config_module = None
        self.daemon = daemon
        self.auto_start = auto_start
        self.log_file_name = log_file_name
        self.loop = self.init_loop()
        self.send_flag = True
        self.first_connection = True
        self.context = context or {}
        self.env = env
        self.task = None
        self.force_exit = force_exit
        self.status = STATUS_RUN
        assert isinstance(self.context, dict)
        if config_module is not None:
            self.config_to_module(config_module)
        config_logging(self.log_file_name, logger=self.logger)
        self.load_environ()
        if self.auto_start:
            self.run_forever()

    def init_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return asyncio.get_event_loop()

    def load_environ(self):
        load_dotenv()
        for name in self._environ_variables:
            key = ('rtc_%s' % name).upper()
            if key not in os.environ:
                continue
            setattr(self, name, os.environ[key])

    @property
    def data(self):
        return self._data
    
    @property
    def connect_url(self):
        return os.path.join(self.ws_url, 'connect')

    def config_to_module(self, config_module):
        if isinstance(config_module, str):
            config_module = importlib.import_module(config_module)
        self._config_module = config_module

    def change_module_config(self):
        if not self._config_module:
            return
        for key, value in self._data.items():
            if isinstance(self._config_module, types.ModuleType):
                self._config_module.__dict__[key] = value
            elif isinstance(self._config_module, dict):
                self._config_module[key] = value

    def no_change(self, message):
        pass

    def changed(self, message):
        self.logger.info('Config changed: %s', message)
        self.hash_code = message.hash_code
        self._data = message.data
        self.change_module_config()

    def get_context(self):
        self.load_environ()
        environ = dict(os.environ)
        for key in self._ignore_environs:
            environ.pop(key, None)
        return dict(
            pid=os.getpid(),
            ping_interval=self.ping_interval,
            retry_interval=self.retry_interval,
            recv_interval=self.recv_interval,
            daemon=self.daemon,
            auto_start=self.auto_start,
            environ=environ,
            **self.context
        )

    def get_message(self):
        return Message(
                "no_change",
                self.config_name,
                self.hash_code,
                env=self.env,
                context=self.get_context()
            ).get_pull_message()

    def close(self):
        self.status = STATUS_STOP

        async def cancel_task():
            if self.task:
                self.task.cancel()
                self.task = None
        asyncio.run_coroutine_threadsafe(cancel_task(), self.loop)
        if self._thread:
            self._thread.join()
            self._thread = None

    async def send_message(self, ws, ping=False):
        if self.send_flag:
            await ws.send(self.get_message())
        received_msg = await ws.recv()
        json_data = json.loads(received_msg)
        try:
            message = Message(**json_data)
        except TypeError as ex:
            raise RTConfigServerError(json_data.get('error_msg', str(ex)))
        message_handler = getattr(self, message.message_type, None)
        if message_handler and callable(message_handler):
            message_handler(message)
        self.send_flag = ping or message.response_mode == RESPONSE_MODE_REPLY
        self.first_connection = ping

    async def ping(self):
        async with websockets.connect(self.connect_url) as ws:
            await self.send_message(ws, ping=True)

    async def connect(self):
        async with websockets.connect(self.connect_url) as ws:
            while self.status == STATUS_RUN:
                try:
                    self.task = asyncio.ensure_future(self.send_message(ws))
                    self.loop.call_later(self.ping_interval, self.task.cancel)
                    await self.task
                except asyncio.CancelledError:
                    self.send_flag = True
                finally:
                    await asyncio.sleep(self.recv_interval)

    async def loop_connect(self):
        while True:
            try:
                await self.connect()
            except Exception as ex:
                self.logger.error(str(ex))
                self.logger.exception(traceback.format_exc())
            finally:
                if self.status != STATUS_RUN:
                    break
                self.logger.info(
                    'Retry to connect config server: %s.',
                    self.ws_url
                )
                self.send_flag = True
                await asyncio.sleep(self.retry_interval)

    def run_forever(self):
        def loop_async(ping=False):
            loop_handler = self.ping if ping else self.loop_connect
            self.loop.run_until_complete(loop_handler())

        if self._thread and self._thread.isAlive():
            raise RuntimeError('RtConfig client is running.')
        if not self.ws_url:
            raise RuntimeError('RtConfig client ws_url must be support.')
        try:
            loop_async(ping=True)
        except Exception as ex:
            if self.force_exit:
                raise ex
            self.logger.exception(traceback.format_exc())

        try:
            import uwsgidecorators

            @uwsgidecorators.postfork
            @uwsgidecorators.thread
            def thread_loop_async():
                loop_async()
        except ImportError:
            self._thread = threading.Thread(target=loop_async)
            self._thread.setDaemon(self.daemon)
            self._thread.start()
