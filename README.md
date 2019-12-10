## rtconfig

A simple Python lib for manage remote server configuration. 
- Configuration remote unified management center.
- When the configuration changes, pushed to client in real time.

## Installing
```
pip install rtconfig
```

## Server deploy
You can start server directly by single process.
```
python -m rtconfig.server
```
Command options:
- --host: str, server host
- --port: str, server port
- --auto-reload: bool, if auto reload
- --store-type: str, rtconfig server store type
- --broker-url: str, rtconfig server broker url
- --login-disable: bool, rtconfig server disable login
- --config: str, rtconfig server config file path

## Client connect
Create a new python module `conf.py`, then write code like this:
```
from rtconfig import RtConfigClient
client = RtConfigClient('demo',ws_url='ws://127.0.0.1:8089',config_module=globals())
```
So, you can use real time configuration like this:
```
conf.config_name
```

## Configuration
You can create `service.py` python config file, And add file path to params `--config=services.py`. 

Configuration options:

| config name |  type  | default | description |
|--------|--------|--------|--------|
|    DEBUG    | bool |   false   |    debug mode    |
|    MAX_CONNECTION  | int |  1024   |    max client connections    |
|    STORE_TYPE   | string  | json_file   |  data store type    |
|    BROKER_URL   |  string  |  |  data store broker url   |
|    LOGIN_DISABLED   |  bool  | false  |  server disable login   |
|    OPEN_CLIENT_AUTH_TOKEN   |  bool  | false |  data store broker url   |

## Config data store method broker url
json_file
>BROKER_URL = "~/rtconfig" (默认可不填)

redis
>BROKER_URL = "redis://127.0.0.1:6379/0"

mongodb
>BROKER_URL = "mongodb://127.0.0.1:27017/demo?connect=false"

## Notes
- `rtconfig` not support multiprocess deploy now.
