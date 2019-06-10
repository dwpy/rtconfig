import json


class RTConfigServerError(Exception):
    """rt config server error"""


class BaseConfigException(Exception):
    """
    Baseclass for all HTTP exceptions.
    """
    def __init__(self, code=None, description=None, **options):
        if code is not None:
            self.code = code
        if description is not None:
            self.description = description
        self.options = options

    code = None
    description = None

    def __str__(self):
        return self.description.format(**self.options)

    def get_message(self):
        return json.dumps({
            'code': self.code,
            'error_msg': str(self)
        })


class ProjectNoFoundException(BaseConfigException):
    code = 404
    description = "Project {config_name} config manager not exist."


class ProjectExistException(BaseConfigException):
    code = 403
    description = "Project {config_name} config manager existed."


class ProjectNameErrorException(BaseConfigException):
    code = 403
    description = "Project {config_name} formatter error."


class ProjectExtensionInvalidException(BaseConfigException):
    code = 403
    description = "Project store {extension} not support."


class ConnectException(BaseConfigException):
    code = 400
    description = "Connection happened unknown exception: \n{exp_info}"


class ProjectEnvErrorException(BaseConfigException):
    code = 404
    description = "Project {config_name} env [{env}] or value error."


class ConfigVersionException(BaseConfigException):
    code = 400
    description = "Project {config_name} version changed error."


class GlobalApiException(Exception):
    def __init__(self, msg):
        self.msg = msg
