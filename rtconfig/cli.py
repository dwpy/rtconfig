# -*- coding: utf-8 -*-
"""
cmd tools.
"""
import os
import sys
import click
import platform
import traceback
from rtconfig.server import create_app


def get_system_info():
    python_info = "python {}.{}.{}".format(sys.version_info[0],
                                           sys.version_info[1],
                                           sys.version_info[2])
    platform_system = platform.system().lower()
    platform_release = platform.release()
    platform_info = "{} {}".format(platform_system, platform_release)
    return "{}, {}".format(python_info, platform_info)


@click.group()
@click.version_option(version='1.0',
                      message='%(prog)s %(version)s, {}'
                      .format(get_system_info()))
@click.option('--project-dir',
              help='The project directory.  Defaults to CWD')
@click.option('--debug/--no-debug',
              default=False,
              help='Print debug logs to stderr.')
@click.pass_context
def cli(ctx, project_dir, debug=False):
    if project_dir is None:
        project_dir = os.getcwd()
    else:
        project_dir = os.path.abspath(project_dir)
    ctx.obj['project_dir'] = project_dir
    ctx.obj['debug'] = debug
    os.chdir(project_dir)


@cli.command('update_user')
@click.argument('username', required=True)
@click.argument('password', required=True)
def update_user(username, password):
    app = create_app()
    auth = app.config['AUTH_MANAGER']
    auth.update_user(username, password)
    click.echo(f"Update user {username} success.")


def main():
    try:
        return cli(obj={})
    except Exception:
        click.echo(traceback.format_exc(), err=True)
        return 2


if __name__ == '__main__':
    main()
