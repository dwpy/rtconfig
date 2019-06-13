import os
import argparse
from urllib.parse import urlparse
from alita import Alita
from rtconfig import RtConfig
from alita_session import Session
from alita_login import LoginManager
from rtconfig.auth import *

DEFAULT_CONFIG = {
    'STORE_TYPE': 'json_file',
    'BROKER_URL': '~/rtconfig',
}

STORE_CONFIG_SCHEME = {
    'json_file': {
        'backend_config_name': 'CONFIG_STORE_DIRECTORY',
        'session_engine': 'alita_session.fs',
        'auth_manager_class': FileAuthManager
    },
    'redis': {
        'backend_config_name': 'REDIS_URL',
        'session_engine': 'alita_session.redis',
        'auth_manager_class': RedisAuthManager
    },
    'mongodb': {
        'backend_config_name': 'MONGODB_URL',
        'session_engine': 'alita_session.mongo',
        'auth_manager_class': MongodbAuthManager
    },
}


def _transfer_config_json_file_url(store_path):
    return os.path.join(store_path, 'data')


def _transfer_session_json_file_url(store_path):
    return dict(
        path=os.path.join(store_path, 'session')
    )


def _transfer_session_redis_url(redis_url):
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


def _transfer_session_mongodb_url(mongodb_url):
    import pymongo.uri_parser
    res = pymongo.uri_parser.parse_uri(mongodb_url, warn=True)
    return dict(
        host=mongodb_url,
        db=res["database"]
    )


def init_config(server_app):
    store_type = server_app.config['STORE_TYPE']
    broker_url = server_app.config['BROKER_URL']

    if store_type not in STORE_CONFIG_SCHEME:
        raise RuntimeError('Store type %s not support!' % store_type)
    scheme = STORE_CONFIG_SCHEME[store_type]
    try:
        backend_config = globals()['_transfer_config_%s_url' % store_type](broker_url)
    except KeyError:
        backend_config = broker_url
    server_app.config[scheme['backend_config_name']] = backend_config
    server_app.config['SESSION_ENGINE'] = scheme['session_engine']
    server_app.config['SESSION_ENGINE_CONFIG'] = globals()['_transfer_session_%s_url' % store_type](broker_url)
    server_app.config['AUTH_MANAGER'] = scheme['auth_manager_class'](server_app)


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
    parser.add_argument(
        '--store-type',
        action="store",
        default=DEFAULT_CONFIG['STORE_TYPE'],
        help="Rtconfig server store type"
    )
    parser.add_argument(
        '--broker-url',
        action="store",
        default=DEFAULT_CONFIG['BROKER_URL'],
        help="Rtconfig server broker url"
    )
    return parser.parse_args()


if __name__ == '__main__':
    options = argparse_options().__dict__
    DEFAULT_CONFIG['STORE_TYPE'] = options.pop('store_type', None)
    DEFAULT_CONFIG['BROKER_URL'] = options.pop('broker_url', None)
    app = create_app()
    app.run(**options)
