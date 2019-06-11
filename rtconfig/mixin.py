import os
import traceback
from rtconfig.message import *
from rtconfig.exceptions import ProjectNoFoundException

logger = logging.getLogger(__name__)


class CallbackHandleMixin:
    async def notify_changed(self, message):
        try:
            await NotifyMessage(manager=self, **json.loads(message)).run()
        except Exception as ex:
            self.logger.error(str(ex))
            self.logger.error(traceback.format_exc())

    async def callback_config_changed(self, config_name):
        try:
            config_project = self.get_config_project(config_name)
        except ProjectNoFoundException:
            return
        for ws in self._connection_pool.get(config_name) or []:
            message = self._connection_message.get(ws)
            if not (message and message.config_name == config_name):
                continue
            with config_project.use_env(message.env, message.context):
                env_hash_code = config_project.get_hash_code()
            if env_hash_code == message.hash_code:
                continue
            message.message_type = MT_CHANGED
            push_message = config_project.config_message(
                message, response_mode=RESPONSE_MODE_REPLY
            )
            self.logger.info('[%s] Config changed, Push client: %s',
                             config_name, message.context['pid'])
            await ws.send(push_message)

    async def callback_add_connection(self, ws_key, data):
        self._other_connection_pool[ws_key] = data
        logger.info(f"{os.getpid()} Other connection num: %s",
                    len(self._other_connection_pool))

    async def callback_remove_connection(self, ws_key):
        self._other_connection_pool.pop(ws_key, None)
        logger.info(f"{os.getpid()} Other connection num: %s",
                    len(self._other_connection_pool))
