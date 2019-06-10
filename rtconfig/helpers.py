import json
import logging
from rtconfig.exceptions import GlobalApiException


def _(*funcs):
    def wrapper(*args, **kwargs):
        try:
            for func in funcs:
                func(*args, **kwargs)
        except:
            pass
    return wrapper


def get_json_data(request):
    try:
        import hjson
    except ImportError:
        hjson = json
    if request.json.get('data'):
        json_data = request.json['data']
        try:
            return hjson.loads(json_data)
        except:
            raise GlobalApiException('不支持该Json格式数据')


class CallbackSet(set):
    def __init__(self, seq=(), on_add=None, on_remove=None):
        super().__init__(seq)
        self.on_add = on_add
        self.on_remove = on_remove

    def add(self, element):
        super().add(element)
        if self.on_add is not None:
            self.on_add(element)

    def remove(self, element):
        try:
            super().remove(element)
        except KeyError:
            pass
        if self.on_remove is not None:
            if isinstance(self.on_remove, LinkDict):
                _handler = _(lambda k: self.on_remove.pop(k))
            elif callable(self.on_remove):
                _handler = self.on_remove
            else:
                _handler = None
            if _handler:
                _handler(element)


class LinkDict(dict):
    __slots__ = ['initial', 'on_create', 'on_update', 'on_delete']

    def __init__(self, initial=None, on_create=None, on_update=None, on_delete=None):
        dict.__init__(initial or {})
        self.on_create = on_create
        self.on_update = on_update
        self.on_delete = on_delete

    def __repr__(self):
        return '<%s %s>' % (
            self.__class__.__name__,
            dict.__repr__(self)
        )

    def check_delete_callback_set(self, value):
        if isinstance(value, CallbackSet) and value.on_remove:
            if isinstance(value.on_remove, LinkDict):
                _handler = _(lambda k: value.on_remove.pop(k))
            elif callable(value.on_remove):
                _handler = value.on_remove
            else:
                _handler = None
            if _handler:
                list(map(_handler, value))

    def calls_update(name):
        def on_call(self, *args, **kwargs):
            create, update = [], []

            def _group_call_handle(key, value):
                (update if key in self else create).append((key, value))

            if len(args) == 2:
                _group_call_handle(*args)
            elif kwargs:
                for k, v in kwargs.items():
                    _group_call_handle(k, v)
            try:
                rv = getattr(super(LinkDict, self), name)(*args, **kwargs)
            except BaseException as ex:
                raise ex
            else:
                if create and self.on_create:
                    for i in create:
                        self.on_create(*i)
                if update and self.on_update:
                    for i in update:
                        self.on_update(*i)
            return rv
        on_call.__name__ = name
        return on_call

    def calls_delete(name):
        def on_call(self, key):
            try:
                value = self[key]
                rv = getattr(super(LinkDict, self), name)(key)
                if self.on_delete is not None:
                    self.on_delete(key)
                self.check_delete_callback_set(value)
                return rv
            except KeyError:
                return None
        on_call.__name__ = name
        return on_call

    def setdefault(self, key, default=None):
        on_event = self.on_update if key in self else self.on_create
        rv = super(LinkDict, self).setdefault(key, default)
        if on_event is not None:
            on_event(key, default)
        return rv

    def pop(self, key, default=None):
        try:
            modified = key in self
            if default is None:
                rv = super(LinkDict, self).pop(key)
            else:
                rv = super(LinkDict, self).pop(key, default)
            if modified and self.on_delete is not None and rv:
                self.on_delete(key)
            self.check_delete_callback_set(rv)
            return rv
        except KeyError:
            return None

    def clear(self):
        super().clear()
        if self.on_delete:
            for key in self:
                self.on_delete(key)

    __setitem__ = calls_update('__setitem__')
    __delitem__ = calls_delete('__delitem__')
    update = calls_update('update')
    del calls_update


class WebsocketHandler(logging.Handler):
    terminator = '\n'

    def __init__(self, callback=None):
        """
        Initialize the handler.

        If stream is not specified, sys.stderr is used.
        """
        logging.Handler.__init__(self)
        self.callback = callback

    def emit(self, record):
        """
        Emit a record.

        If a formatter is specified, it is used to format the record.
        The record is then written to the stream with a trailing newline.  If
        exception information is present, it is formatted using
        traceback.print_exception and appended to the stream.  If the stream
        has an 'encoding' attribute, it is used to determine how to do the
        output to the stream.
        """
        try:
            msg = self.format(record)
            if self.callback:
                self.callback(msg)
        except Exception as ex:
            print(str(ex))
            self.handleError(record)


def page_result(request, data):
    assert isinstance(data, list)
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    return {
        "code": 0,
        "count": len(data),
        "data": data[(page - 1) * limit: page * limit]
    }
