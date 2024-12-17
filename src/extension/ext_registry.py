import subprocess
import sys
import os
import importlib.util
import sys
import yaml
import platform

from utils.logging import k_log


class ExtensionRegistry:
    def __init__(self, ext_path, enabled_exts, disabled_exts, ext_order, skip_install):
        self.enabled = enabled_exts
        self.disabled = disabled_exts
        self.order = ext_order
        self.skip_install = skip_install

        self.root = ext_path
        if not os.path.exists(self.root):
            os.mkdir(self.root)

        self.extensions = {}

    def get_ext_folders(self):
        return [
            entry.name
            for entry in os.scandir(self.root)
            if entry.is_dir() and not entry.name.startswith(".")
        ]

    def get_enabled_extensions(self):
        return (
            [] if self.enabled is None else [x.strip() for x in self.enabled.split(",")]
        )

    def get_disabled_extensions(self):
        return (
            []
            if self.disabled is None or self.disabled == ""
            else [x.strip() for x in self.disabled.split(",")]
        )

    def reorder_extensions(self, ext_folders):
        if self.order == "":
            return ext_folders

        if ";" in self.order:
            first, last = [
                [value.strip() for value in part.split(",")]
                for part in self.order.split(";")
            ]
        else:
            first, last = [self.order], []

        ordered_ext_folders = []
        for item in first:
            if item in ext_folders:
                ordered_ext_folders.append(item)

        for item in ext_folders:
            if item not in first and item not in last:
                ordered_ext_folders.append(item)

        for item in last:
            if item in ext_folders:
                ordered_ext_folders.append(item)

        return ordered_ext_folders

    def register(self, kubin):
        ext_folders = self.get_ext_folders()
        kubin.log(f"found {len(ext_folders)} extensions")

        enabled_exts = self.get_enabled_extensions()
        if len(enabled_exts) > 0:
            ext_folders = filter(lambda ext: ext in enabled_exts, ext_folders)
            kubin.log(f"only following extensions are enabled: {self.enabled}")

        disabled_exts = self.get_disabled_extensions()
        ext_folders = self.reorder_extensions(ext_folders)

        for i, extension in enumerate(ext_folders):
            if extension in disabled_exts:
                kubin.log(f"extension [{i+1}] '{extension}' disabled, skipping")
            else:
                kubin.log(f"extension [{i+1}] '{extension}' found")
                extension_reqs_path = f"{self.root}/{extension}/requirements.txt"
                extension_reqs_no_deps_path = (
                    f"{self.root}/{extension}/requirements_no_deps.txt"
                )
                extension_installed = f"{self.root}/{extension}/.installed"

                if not self.skip_install and os.path.isfile(extension_reqs_path):
                    if os.path.exists(extension_installed):
                        kubin.log(
                            f"extension [{i+1}] '{extension}' installation integrity verified"
                        )
                    else:
                        kubin.log(
                            f"extension [{i+1}] '{extension}' has requirements.txt, installing"
                        )

                        arguments = []
                        ext_config = f"{self.root}/{extension}/setup_ext.yaml"

                        if os.path.exists(ext_config):
                            with open(ext_config, "r") as stream:
                                ext_conf = yaml.safe_load(stream)
                                arguments = ext_conf.get("pip_args", None)
                                arguments = [arguments] if arguments is not None else []

                        install_main_res_success = self.install_pip_reqs(
                            extension_reqs_path, arguments=arguments
                        )
                        if os.path.isfile(extension_reqs_no_deps_path):
                            kubin.log(
                                f"extension [{i+1}]  '{extension}' has requirements_no_deps.txt, installing without dependencies"
                            )
                            install_nodeps_res_success = self.install_pip_reqs(
                                extension_reqs_no_deps_path,
                                arguments=arguments + ["--no-deps"],
                            )
                        else:
                            install_nodeps_res_success = True

                        if install_main_res_success and install_nodeps_res_success:
                            open(extension_installed, "a").close()

                extension_py_path = f"{self.root}/{extension}/setup_ext.py"
                if os.path.exists(extension_py_path):
                    extension_folder = f"{self.root}/{extension}"
                    sys.path.append(extension_folder)
                    spec = importlib.util.spec_from_file_location(
                        extension, extension_py_path
                    )
                    if spec is not None:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[extension] = module
                        if spec.loader is not None:
                            spec.loader.exec_module(module)

                            if hasattr(module, "mount") and callable(
                                getattr(module, "mount")
                            ):
                                module.mount(kubin)

                            extension_info = module.setup(kubin)
                            extension_info["_name"] = extension
                            extension_info["_path"] = extension_folder
                            self.extensions[extension] = extension_info

                    kubin.log(
                        f"extension [{i+1}] '{extension}' successfully registered"
                    )
                else:
                    kubin.log(
                        f"setup_ext.py not found for extension [{i+1}] '{extension}', extension will not be registered"
                    )

        postinstall_reqs_installed = f"{self.root}/.installed"
        if os.path.exists(postinstall_reqs_installed):
            kubin.log("extension post-install phase: verified")
        else:
            kubin.log(
                "extension post-install phase, installing from extensions/requirements.txt"
            )

            root_reqs = f"{self.root}/requirements.txt"
            if os.path.exists(root_reqs):
                post_install_reqs_success = self.install_pip_reqs(root_reqs)
            else:
                post_install_reqs_success = True

            if post_install_reqs_success:
                open(postinstall_reqs_installed, "a").close()

    def install_pip_reqs(self, reqs_path, arguments=[]):
        current_platform = platform.system()

        if current_platform == "Windows":
            venv_activation_path = os.path.join("venv", "Scripts", "activate.bat")
        else:
            venv_activation_path = os.path.join("venv", "bin", "activate")

        pip_install_cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            reqs_path,
        ] + arguments

        try:
            if os.path.exists(venv_activation_path):
                if current_platform == "Windows":
                    activation_cmd = [
                        "cmd.exe",
                        "/C",
                        venv_activation_path + " && " + " ".join(pip_install_cmd),
                    ]
                    subprocess.check_call(activation_cmd)
                else:
                    activation_cmd = [
                        "sh",
                        "-c",
                        f". {venv_activation_path} && {' '.join(pip_install_cmd)}",
                    ]
                    subprocess.check_call(activation_cmd)
            else:
                subprocess.check_call(pip_install_cmd)

            print(f"packages required by '{reqs_path}' installed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error during pip install -r '{reqs_path}': {e}")
            return False
        except Exception as e:
            print(
                f"An unexpected error occurred during pip install -r '{reqs_path}': {e}"
            )
            return False

    def standalone(self):
        return list(
            {
                key: value
                for key, value in self.extensions.items()
                if value.get("tab_ui", None) is not None
            }.values()
        )

    def injectable(self):
        return list(
            {
                key: value
                for key, value in self.extensions.items()
                if value.get("inject_ui", None) is not None
            }.values()
        )

    def force_reinstall(self, ext=None):
        ext_folders = self.get_ext_folders()
        for i, extension in enumerate(ext_folders):
            if ext is None or extension == ext:
                extension_installed = f"{self.root}/{extension}/.installed"
                if os.path.exists(extension_installed):
                    os.remove(extension_installed)
                    k_log(
                        f"extension [{i+1}] '{extension}' will be reinstalled on next run"
                    )

    def is_installed(self, ext):
        return os.path.exists(f"{self.root}/{ext}/.installed")

    def locate_resources(self):
        client_folders = []
        client_files = []

        for _, value in self.extensions.items():
            client_path = os.path.join(value["_path"], "client")
            if os.path.exists(client_path):
                client_folders.append(client_path)
                for file_name in os.listdir(client_path):
                    client_file_path = os.path.join(client_path, file_name)

                    if os.path.isfile(client_file_path) and (
                        file_name.endswith(".js") or file_name.endswith(".css")
                    ):
                        client_files.append(client_file_path)

        return client_folders, client_files

    def bind_hooks(self, kubin):
        for ext_name, ext_target in {
            key: value
            for key, value in self.extensions.items()
            if value.get("hook_fn", None) is not None
        }.items():
            kubin.params.hook_store.register_hook(ext_name, ext_target["hook_fn"])

    def propagate_params_changes(self, k_params):
        for ext_name, ext_target in {
            key: value
            for key, value in self.extensions.items()
            if value.get("params_changed", None) is not None
        }.items():
            ext_target["params_changed"](k_params)
