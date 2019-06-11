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
- --host: server host
- --port: server port
- --auto-reload: if auto reload

Or you can start server multiprocess by Gunicorn.
>gunicorn rtconfig.server:app -b 0.0.0.0:8089 -k alita.GunicornWorker -w 2

## Login account
Both of initial user name and password is `admin`.
If you want to change password or add new account, you need use command like this:
>python -m rtconfig.cli update_user {name} {password}

## Client connection
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
You can create `service.py` python file in current directory. 

Configuration options:

| config name | default | description |
|--------|--------|--------|
|    DEBUG    |    false   |    debug mode    |
|    MAX_CONNECTION  |   1024   |    max client connections    |
|    STORE_TYPE   |   json_file   |  data store type    |
|    STORE_PATH   |  ~/rtconfig   |  data store directory, when STORE_TYPE=json_file    |
|    REDIS_URL   | |  redis server url, when STORE_TYPE=redis, necessary provide    |
|    MONGODB_URL   | |  mongodb server url, when STORE_TYPE=mongodb, necessary provide    |

## Config data store method
json_file
- STORE_PATH

redis
- REDIS_URL

mongodb
- MONGODB_URL

## Notes
- `json_file` store type not support multiprocess deploy.
