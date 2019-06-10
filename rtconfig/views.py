from rtconfig.exceptions import *
from rtconfig.helpers import get_json_data, page_result
from alita import Blueprint, render_template, RedirectResponse
from alita_login import login_required, login_user, logout_user

api_view = Blueprint('api_view', url_prefix='/rtc/api')
page_view = Blueprint('page_view', url_prefix='/rtc')

page_view.register_error_handler(ProjectExistException, GlobalApiException('配置名称已存在'))
page_view.register_error_handler(ProjectNoFoundException, GlobalApiException('配置名称不存在'))
page_view.register_error_handler(ProjectExtensionInvalidException, GlobalApiException('存储格式不支持'))
page_view.register_error_handler(ProjectNameErrorException, GlobalApiException('配置项目名称格式不支持'))
page_view.register_error_handler(ConfigVersionException, GlobalApiException('配置项目版本已更改，无法执行修改。'))
page_view.register_error_handler(ProjectEnvErrorException, lambda r, e: GlobalApiException(
    '配置项{%s}名称或配置值错误' % e.options.get('env') or ''))


@page_view.route('/login', methods=['GET', 'POST'])
async def page_login(request):
    if request.method == "GET":
        return await render_template(request, 'login.html')
    else:
        username = request.json['username']
        password = request.json['password']
        auth_manager = request.app.config['AUTH_MANAGER']
        user = auth_manager.check_password(username, password)
        await login_user(request, auth_manager.load_user(user))
        return {'code': 0, "data": user['id']}


@page_view.route('/logout')
async def page_logout(request):
    logout_user(request)
    return RedirectResponse('/')


@page_view.route('/project')
@login_required
async def page_config_projects(request):
    return await render_template(request, 'list.html')


@page_view.route('/client')
@login_required
async def page_config_clients(request):
    config_name = request.args.get('config_name') or ''
    return await render_template(request, 'client.html', config_name=config_name)


@page_view.route('/detail')
@login_required
async def page_config_detail(request):
    config_name = request.args['config_name']
    return await render_template(
        request, 'detail.html', config_name=config_name,
    )


@page_view.route('/system')
@login_required
async def page_system_info(request):
    return await render_template(
        request, 'system.html',
        client_info=request.config_manager.client_info,
        system_info=request.config_manager.system_info,
    )


@api_view.route('/config/list')
@login_required
async def config_list(request):
    return page_result(request, request.config_manager.get_config_project_list())


@api_view.route('/config', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
async def config_detail(request):
    config_name = request.args['config_name']
    config_manager = request.config_manager
    if request.method == "POST":
        await config_manager.create_config_project(
            config_name, copy_from=request.json.get('copy_from')
        )
    elif request.method == "PUT":
        env = request.args.get('env')
        data = get_json_data(request)
        if not isinstance(data, dict):
            raise GlobalApiException('配置数据必须为字典')
        if not data:
            raise GlobalApiException('配置数据不能为空')
        if env:
            data = {key: dict(
                key=key,
                desc='',
                value=value
            ) for key, value in data.items()}
        await config_manager.update_config_project(
            request, config_name, data, env)
    elif request.method == "DELETE":
        await config_manager.remove_config_project(config_name)
        return {'code': 0, "data": {}}
    return {
        'code': 0,
        "data": config_manager.get_config_project_info(config_name)
    }


@api_view.route('/config/item', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
async def update_config_detail(request):
    config_name = request.args['config_name']
    env = request.args['env']
    config_manager = request.config_manager
    if request.method == 'GET':
        config_project = config_manager.get_config_project(config_name)
        env_data = config_project.source_data.get(env) or {}
        history_data = config_project.source_data.get('history') or {}
        env_history_data = history_data.get(env) or {}
        data = list(env_data.values())
        for i in data:
            i['history'] = env_history_data.get(i['key']) or []
        return page_result(request, list(env_data.values()))
    key = request.json.get('key')
    if not (key and config_manager.validate_name(key)):
        raise GlobalApiException('配置项名称为空或有误')
    if request.method in ["POST", "PUT"]:
        value = request.json.get('value')
        desc = request.json.get('desc')
        if not value:
            raise GlobalApiException('配置值不能为空')
        if request.method == "POST" and config_manager.env_key_exist(
                config_name, env, key):
            raise GlobalApiException(f'配置项[{key}]已存在')
        await config_manager.add_env_config(
            request, config_name, env, {
                key: dict(
                    key=key,
                    desc=desc,
                    value=value
                )}
            )
    elif request.method == "DELETE":
        await config_manager.remove_env_config(config_name, env, [key])
    return {'code': 0, "data": {}}


@api_view.route('/client')
@login_required
async def api_config_client(request):
    config_name = request.args.get('config_name')
    return page_result(request, request.config_manager.get_connection_clients(config_name))
