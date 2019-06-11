import os
import argparse
from urllib.parse import urlparse
from alita import Alita
from rtconfig import RtConfig
from alita_session import Session
from alita_login import LoginManager
from rtconfig.auth import *

DEFAULT_CONFIG = {
    'STORE_PATH': '~/rtconfig',
    'STORE_TYPE': 'json_file',
}


def transfer_redis_url(redis_url):
    redis_url = urlparse(redis_url)
    if redis_url.path:
        redis_db = int(redis_url.path[1])
    else:
        redis_db = 0

    return dict(
        host=redis_url.hostname,
        port=redis_url.port,
        db=redis_db,
        password=redis_url.password
    )


def transfer_mongodb_url(mongodb_url):
    import pymongo.uri_parser
    res = pymongo.uri_parser.parse_uri(mongodb_url, warn=True)
    return dict(host=mongodb_url, db=res["database"])


def init_config(server_app):
    store_type = server_app.config['STORE_TYPE']
    if store_type == 'json_file':
        store_path = server_app.config['STORE_PATH']
        server_app.config['CONFIG_STORE_DIRECTORY'] = os.path.join(store_path, 'data')
        server_app.config['SESSION_ENGINE'] = 'alita_session.fs'
        server_app.config['SESSION_DIRECTORY'] = os.path.join(store_path, 'session')
        server_app.config['AUTH_MANAGER'] = FileAuthManager(server_app)
    elif store_type == 'redis':
        redis_url = server_app.config['REDIS_URL']
        server_app.config['SESSION_ENGINE'] = 'alita_session.redis'
        server_app.config['SESSION_ENGINE_CONFIG'] = transfer_redis_url(redis_url)
        server_app.config['AUTH_MANAGER'] = RedisAuthManager(server_app)
    elif store_type == 'mongodb':
        mongodb_url = server_app.config['MONGODB_URL']
        server_app.config['SESSION_ENGINE'] = 'alita_session.mongo'
        server_app.config['SESSION_ENGINE_CONFIG'] = transfer_mongodb_url(mongodb_url)
        server_app.config['AUTH_MANAGER'] = MongodbAuthManager(server_app)
    else:
        raise RuntimeError('Store type %s not support!' % store_type)


def create_app():
    server_app = Alita('rtc')
    server_app.config.from_mapping(DEFAULT_CONFIG)
    if os.path.exists('services.py'):
        server_app.config_from_pyfile(os.path.abspath('services.py'))
    init_config(server_app)
    session = Session()
    rt_config = RtConfig()
    login_manager = LoginManager()
    login_manager.login_view = 'page_view.page_login'
    session.init_app(server_app)
    rt_config.init_app(server_app)
    login_manager.init_app(server_app)
    login_manager.user_loader(server_app.config['AUTH_MANAGER'].load_user)
    return server_app


app = create_app()


def argparse_options():
    parser = argparse.ArgumentParser(
        description='Rtconfig Server options.'
    )
    parser.add_argument(
        '--host',
        action="store",
        default='0.0.0.0',
        help="Rtconfig server host",
    )
    parser.add_argument(
        '--port',
        action="store",
        default=8089,
        type=int,
        help="Rtconfig server port"
    )
    parser.add_argument(
        '--auto-reload',
        action="store_true",
        default=False,
        help="Rtconfig server auto reload"
    )
    return parser.parse_args()


if __name__ == '__main__':
    options = argparse_options().__dict__
    app.run(**options)
