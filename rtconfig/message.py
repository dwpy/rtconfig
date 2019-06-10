import json
import attr
import logging
from rtconfig.utils import convert_dt

MT_NO_CHANGE = 'nochange'
MT_CHANGED = 'changed'

RESPONSE_MODE_REPLY = 'reply'
RESPONSE_MODE_NOTIFY = 'notify'


def config_logging(log_file_name=None, logger=None, level=logging.INFO, customize_handler=None):
    formatter = "%(asctime)s [%(process)d] [%(levelname)s]: %(message)s"
    if log_file_name and logger:
        file_handler = logging.FileHandler(log_file_name)
        file_handler.setFormatter(logging.Formatter(formatter))
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
    if customize_handler:
        customize_handler.setFormatter(logging.Formatter(formatter))
        customize_handler.setLevel(level)
        logger.addHandler(customize_handler)
    logging.basicConfig(format=formatter, level=level)


@attr.s
class Message:
    message_type = attr.ib(validator=attr.validators.instance_of(str))
    config_name = attr.ib(validator=attr.validators.instance_of(str))
    hash_code = attr.ib(validator=attr.validators.instance_of(str))
    data = attr.ib(default=dict(), validator=attr.validators.instance_of(dict))
    context = attr.ib(default=dict(), validator=attr.validators.instance_of(dict))
    request = attr.ib(default=None)
    env = attr.ib(default='default', validator=attr.validators.instance_of(str))
    response_mode = attr.ib(default=RESPONSE_MODE_NOTIFY, validator=attr.validators.instance_of(str))
    lut = attr.ib(default=None, converter=convert_dt)

    def get_pull_message(self):
        return json.dumps(dict(
            message_type=self.message_type,
            config_name=self.config_name,
            hash_code=self.hash_code,
            context=self.context,
            env=self.env,
        ))

    def get_push_message(self):
        return json.dumps(dict(
            message_type=self.message_type,
            config_name=self.config_name,
            hash_code=self.hash_code,
            data=self.data, env=self.env,
            response_mode=self.response_mode
        ))


@attr.s
class NotifyMessage:
    manager = attr.ib()
    func = attr.ib(validator=attr.validators.instance_of(str))
    args = attr.ib(validator=attr.validators.instance_of(list))
    kwargs = attr.ib(validator=attr.validators.instance_of(dict))

    async def run(self):
        await getattr(self.manager, self.func)(*self.args, **self.kwargs)
