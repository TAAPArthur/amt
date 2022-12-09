from subprocess import CalledProcessError
from threading import Lock
import logging
import os
import subprocess


class Runner:
    lock = Lock()

    def _create_env(self, env_extra={}, media_data=None, chapter_data=None):
        media_keys = {"id", "name", "alt_id", "server_id"}
        chapter_keys = {"id", "title", "number"}
        env = dict(os.environ)
        env.update(env_extra)
        for d, prefix, keys in ((media_data, "MEDIA", media_keys), (chapter_data, "CHAPTER", chapter_keys)):
            if d:
                for key in keys:
                    env[f"{prefix}_{key.upper()}"] = str(d[key])
        return env

    def _run_cmd(self, func, cmd, media_data=None, chapter_data=None, shell=False, wd=None, env_extra={}, **kwargs):
        logging.info("Running cmd %s: shell = %s, wd=%s", cmd, shell, wd)
        env = self._create_env(env_extra=env_extra, media_data=media_data, chapter_data=chapter_data)
        assert isinstance(cmd, str)
        return func(cmd, shell=shell, cwd=wd, env=env, **kwargs)

    def run_cmd_and_save_output(self, *args, **kwargs):
        return self._run_cmd(subprocess.check_output, *args, **kwargs).decode("utf-8")

    def run_cmd(self, *args, raiseException=False, **kwargs):
        try:
            self._run_cmd(subprocess.check_call, *args, **kwargs)
            return True
        except (CalledProcessError, KeyboardInterrupt):
            if raiseException:
                raise
            return False
