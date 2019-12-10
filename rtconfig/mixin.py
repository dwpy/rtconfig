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

        async def _notify_config_changed(cn):
            for ws in self._connection_pool.get(cn) or []:
                message = self._connection_message.get(ws)
                if not (message and message.config_name == cn):
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
                                 cn, message.context['pid'])
                await ws.send(push_message)

        await _notify_config_changed(config_name)
        for depend_config in self.iter_dependency_config(config_name):
            await _notify_config_changed(depend_config)
