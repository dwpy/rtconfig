import os
import json
import asyncio
import traceback
import websockets
try:
    from rtconfig.views import api_view, page_view
    from rtconfig.manager import ConfigManager
    from alita import RedirectResponse
except ImportError:
    pass

from rtconfig.exceptions import GlobalApiException, BaseConfigException, ConnectException
from rtconfig.message import Message
from rtconfig.client import RtConfigClient

__version__ = '0.1.2'


class RtConfig:
    def __init__(self, app=None):
        self.config_manager = None
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.app.static_url_path = '/rtc/static'
        self.app.static_folder = os.path.join(os.path.dirname(__file__), 'static')
        self.app.template_folder = os.path.join(os.path.dirname(__file__), 'templates')
        self.app.make_factory()
        self.app.config_manager = self.config_manager = ConfigManager(app)
        self.app.register_blueprint(api_view)
        self.app.register_blueprint(page_view)

        @self.app.request_middleware
        async def process_request(request):
            request.config_manager = self.config_manager

        @app.route('/')
        async def index(request):
            return RedirectResponse(request.app.url_for(
                'page_view.page_config_projects'))

        @app.error_handler(GlobalApiException)
        def api_exception_handler(request, exc):
            return {'code': 1, 'msg': exc.msg, 'data': {}}

        @app.websocket('/connect')
        async def client_connect(request, ws):
            config_project, received_message = None, None
            while True:
                try:
                    received_message = Message(request=request, **json.loads(await ws.recv()))
                    await self.config_manager.add_connection(ws, received_message)
                    config_project = self.config_manager.get_config_project(received_message.config_name)
                    await ws.send(config_project.config_message(received_message))
                except BaseConfigException as ex:
                    self.config_manager.logger.exception(str(ex))
                    await ws.send(ex.get_message())
                except (asyncio.CancelledError, websockets.ConnectionClosed) as ex:
                    if config_project:
                        await self.config_manager.remove_connection(ws, received_message)
                    raise ex
                except Exception as ex:
                    self.config_manager.logger.exception(traceback.format_exc())
                    await ws.send(ConnectException(exp_info=str(ex)).get_message())
