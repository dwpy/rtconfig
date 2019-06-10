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

## Config data store method
json_file
- STORE_PATH

redis
- REDIS_URL

## Notes
- `json_file` store type not support multiprocess deploy.
