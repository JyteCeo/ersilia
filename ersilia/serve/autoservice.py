import os
import tempfile
import shutil

from .services import (
    SystemBundleService,
    VenvEnvironmentService,
    CondaEnvironmentService,
    DockerImageService,
)
from .api import Api
from ..default import DEFAULT_BATCH_SIZE
from .. import ErsiliaBase
from ..utils import tmp_pid_file


DEFAULT_OUTPUT = None


class AutoService(ErsiliaBase):
    def __init__(self, model_id, service_class=None, config_json=None):
        ErsiliaBase.__init__(self, config_json=config_json)
        self.logger.debug("Setting AutoService for {0}".format(model_id))
        self.config_json = config_json
        self.model_id = model_id
        self._meta = None
        if service_class is None:
            self.logger.debug("No service class provided, deciding automatically")
            service_class_file = os.path.join(
                self._get_bundle_location(model_id), "service_class.txt"
            )
            if os.path.exists(service_class_file):
                self.logger.debug(
                    "Service class file exists in folder {0}".format(service_class_file)
                )
                with open(service_class_file, "r") as f:
                    s = f.read()
                self.logger.debug("Service class: {0}".format(s))
                if s == "system":
                    self.service = SystemBundleService(
                        model_id, config_json=config_json
                    )
                elif s == "venv":
                    self.service = VenvEnvironmentService(
                        model_id, config_json=config_json
                    )
                elif s == "conda":
                    self.service = CondaEnvironmentService(
                        model_id, config_json=config_json
                    )
                elif s == "docker":
                    self.service = DockerImageService(model_id, config_json=config_json)
                else:
                    self.service = None
            else:
                self.logger.debug(
                    "No service class file exists in {0}".format(service_class_file)
                )
                with open(service_class_file, "w") as f:
                    if SystemBundleService(
                        model_id, config_json=config_json
                    ).is_available():
                        self.service = SystemBundleService(
                            model_id, config_json=config_json
                        )
                        f.write("system")
                    elif VenvEnvironmentService(
                        model_id, config_json=config_json
                    ).is_available():
                        self.service = VenvEnvironmentService(
                            model_id, config_json=config_json
                        )
                        f.write("venv")
                    elif CondaEnvironmentService(
                        model_id, config_json=config_json
                    ).is_available():
                        self.service = CondaEnvironmentService(
                            model_id, config_json=config_json
                        )
                        f.write("conda")
                    elif DockerImageService(
                        model_id, config_json=config_json
                    ).is_available():
                        self.service = DockerImageService(
                            model_id, config_json=config_json
                        )
                        f.write("docker")
                    else:
                        self.service = None
        else:
            self.logger.info("Service class provided")
            # predefined service class
            if service_class(model_id, config_json).is_available():
                self.service = service_class(model_id, config_json=config_json)
            else:
                self.service = None
        self._set_apis()

    def _set_api(self, api_name):
        def _method(input, output=DEFAULT_OUTPUT, batch_size=DEFAULT_BATCH_SIZE):
            return self.api(api_name, input, output, batch_size)

        setattr(self, api_name, _method)

    def _set_apis(self):
        if self.service is None:
            return
        apis_list = os.path.join(
            self._get_bundle_location(self.model_id), "apis_list.txt"
        )
        if os.path.exists(apis_list):
            with open(apis_list, "r") as f:
                for l in f:
                    api_name = l.rstrip()
                    self._set_api(api_name)
        else:
            with open(apis_list, "w") as f:
                for api_name in self.service._get_apis_from_bento():
                    self._set_api(api_name)
                    f.write(api_name + os.linesep)
        self.apis_list = apis_list

    def get_apis(self):
        apis = []
        with open(self.apis_list, "r") as f:
            for l in f:
                api = l.rstrip()
                apis.append(api)
        return sorted(apis)

    def is_available(self):
        if self.service is None:
            return False
        else:
            return True

    def is_served(self):
        tmp_file = tmp_pid_file(self.model_id)
        if os.path.exists(tmp_file):
            return True
        else:
            return False

    def _pids_from_file(self, fn):
        pids = []
        with open(fn, "r") as f:
            for l in f:
                pids += [int(l.split(" ")[0])]
        return pids

    def _kill_pids(self, pids):
        for pid in pids:
            try:
                os.kill(pid, 9)
            except:
                self.logger.info("PID {0} is unassigned".format(pid))

    def clean_before_serving(self):
        self.logger.debug("Cleaning processes before serving")
        tmp_file = tmp_pid_file(self.model_id)
        dir_name = os.path.dirname(tmp_file)
        pids = []
        for proc_file in os.listdir(dir_name):
            if proc_file[-3:] != "pid":
                continue
            proc_file = os.path.join(dir_name, proc_file)
            pids += self._pids_from_file(proc_file)
            os.remove(proc_file)
        self.logger.debug("Cleaning {0} processes".format(pids))
        self._kill_pids(pids)

    def clean_temp_dir(self):
        self.logger.debug("Cleaning temp dir")
        tmp_folder = tempfile.gettempdir()
        for d in os.listdir(tmp_folder):
            if "ersilia-" in d:
                d = os.path.join(tmp_folder, d)
                self.logger.debug("Flushing temporary directory {0}".format(d))
                shutil.rmtree(d)

    def serve(self):
        self.clean_before_serving()
        self.clean_temp_dir()
        self.service.serve()
        tmp_file = tmp_pid_file(self.model_id)
        with open(tmp_file, "a+") as f:
            f.write("{0} {1}{2}".format(self.service.pid, self.service.url, os.linesep))

    def close(self):
        tmp_file = tmp_pid_file(self.model_id)
        pids = self._pids_from_file(tmp_file)
        self._kill_pids(pids)
        os.remove(tmp_file)
        self.clean_temp_dir()

    def api(
        self, api_name, input, output=DEFAULT_OUTPUT, batch_size=DEFAULT_BATCH_SIZE
    ):
        self.logger.debug("API: {0}".format(api_name))
        self.logger.debug("MODEL ID: {0}".format(self.model_id))
        self.logger.debug("SERVICE URL: {0}".format(self.service.url))
        if batch_size is None:
            batch_size = DEFAULT_BATCH_SIZE
        else:
            batch_size = batch_size
        _api = Api(
            model_id=self.model_id,
            url=self.service.url,
            api_name=api_name,
            save_to_lake=False,
            config_json=self.config_json,
        )
        for result in _api.post(input=input, output=output, batch_size=batch_size):
            if self._meta is None:
                do_meta = True
            else:
                if api_name not in self._meta:
                    do_meta = True
                else:
                    do_meta = False
            if do_meta:
                self._latest_meta = _api.meta()
                self._meta = {api_name: self._latest_meta}
            if api_name not in self._meta:
                self._meta = {api_name: _api.meta()}
            yield result