# -*- coding: utf-8 -*-
#
# Copyright (C) 2015 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import json
import shutil
import copy
from pkg_resources import parse_version


from .qt import QtCore
from .version import __version__

import logging
log = logging.getLogger(__name__)


class PeriodicCheckConfig(QtCore.QThread):

    """
    Timer for checking if the configuration file change
    on disk.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent

    def run(self):
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._parent._checkConfigChanged)
        self._timer.setInterval(1000)  #  milliseconds
        self._timer.start()
        self.exec_()


class LocalConfig(QtCore.QObject):

    """
    Handles the local GUI settings.
    """

    config_changed_signal = QtCore.Signal()

    def __init__(self, config_file=None):

        super().__init__()
        self._settings = {}

        if sys.platform.startswith("win"):
            filename = "gns3_gui.ini"
        else:
            filename = "gns3_gui.conf"

        self._migrateOldConfigPath()

        appname = "GNS3"

        if sys.platform.startswith("win"):

            # On windows, the system wide configuration file location is %COMMON_APPDATA%/GNS3/gns3_gui.conf
            common_appdata = os.path.expandvars("%COMMON_APPDATA%")
            system_wide_config_file = os.path.join(common_appdata, appname, filename)
        else:
            # On UNIX-like platforms, the system wide configuration file location is /etc/xdg/GNS3/gns3_gui.conf
            system_wide_config_file = os.path.join("/etc/xdg", appname, filename)

        if config_file:
            self._config_file = config_file
        else:
            self._config_file = os.path.join(LocalConfig.configDirectory(), filename)

        # First load system wide settings
        if os.path.exists(system_wide_config_file):
            self._readConfig(system_wide_config_file)

        config_file_in_cwd = os.path.join(os.getcwd(), filename)
        if os.path.exists(config_file_in_cwd):
            # use any config file present in the current working directory
            self._config_file = config_file_in_cwd
        elif not os.path.exists(self._config_file):
            try:
                # create the config file if it doesn't exist
                os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
                with open(self._config_file, "w", encoding="utf-8") as f:
                    json.dump({"version": __version__, "type": "settings"}, f)
            except OSError as e:
                log.error("Could not create the config file {}: {}".format(self._config_file, e))

        user_settings = self._readConfig(self._config_file)
        # overwrite system wide settings with user specific ones
        self._settings.update(user_settings)
        self._migrateOldConfig()
        self._writeConfig()

        self._check_thread = PeriodicCheckConfig(self)
        self._check_thread.start()

    @staticmethod
    def configDirectory():
        """
        Get the configuration directory
        """
        if sys.platform.startswith("win"):
            appdata = os.path.expandvars("%APPDATA%")
            path = os.path.join(appdata, "GNS3")
        else:
            home = os.path.expanduser("~")
            path = os.path.join(home, ".config", "GNS3")
        return os.path.normpath(path)

    def _migrateOldConfigPath(self):
        """
        Migrate pre 1.4 config path
        """

        # In < 1.4 on Mac the config was in a gns3.net directory
        # We have move to same location as Linux
        if sys.platform.startswith("darwin"):
            old_path = os.path.join(os.path.expanduser("~"), ".config", "gns3.net")
            new_path = os.path.join(os.path.expanduser("~"), ".config", "GNS3")
            if os.path.exists(old_path) and not os.path.exists(new_path):
                try:
                    shutil.copytree(old_path, new_path)
                except OSError as e:
                    print("Can't copy the old config: %s", str(e))

    def _migrateOldConfig(self):
        """
        Migrate pre 1.4 config
        """

        if "version" not in self._settings or parse_version(self._settings["version"]) < parse_version("1.4.0"):

            servers = self._settings.get("Servers", {})

            if "LocalServer" in self._settings:
                servers["local_server"] = copy.copy(self._settings["LocalServer"])

                # We migrate the server binary for OSX due to the change from py2app to CX freeze
                if servers["local_server"]["path"] == "/Applications/GNS3.app/Contents/Resources/server/Contents/MacOS/gns3server":
                    servers["local_server"]["path"] = "/Applications/GNS3.app/Contents/MacOS/gns3server"

            if "RemoteServers" in self._settings:
                servers["remote_servers"] = copy.copy(self._settings["RemoteServers"])

            self._settings["Servers"] = servers

            if "GUI" in self._settings:
                main_window = self._settings.get("MainWindow", {})
                main_window["hide_getting_started_dialog"] = self._settings["GUI"].get("hide_getting_started_dialog", False)
                self._settings["MainWindow"] = main_window

    def _readConfig(self, config_path):
        """
        Read the configuration file.
        """

        log.info("Load config from %s", config_path)
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._last_config_changed = os.stat(config_path).st_mtime
                config = json.load(f)
                self._settings.update(config)
        except (ValueError, OSError) as e:
            log.error("Could not read the config file {}: {}".format(self._config_file, e))

        # Update already loaded section
        for section in self._settings.keys():
            if isinstance(self._settings[section], dict):
                self.loadSectionSettings(section, self._settings[section])

        return dict()

    def _writeConfig(self):
        """
        Write the configuration file.
        """

        self._settings["version"] = __version__
        try:
            temporary = os.path.join(os.path.dirname(self._config_file), "gns3_gui.tmp")
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, sort_keys=True, indent=4)
            shutil.move(temporary, self._config_file)
            log.info("Configuration save to %s", self._config_file)
            self._last_config_changed = os.stat(self._config_file).st_mtime
        except (ValueError, OSError) as e:
            log.error("Could not write the config file {}: {}".format(self._config_file, e))

    def _checkConfigChanged(self):
        if self._last_config_changed < os.stat(self._config_file).st_mtime:
            log.info("Client config has changed, reloading it...")
            self._readConfig(self._config_file)
            self.config_changed_signal.emit()

    def configFilePath(self):
        """
        Returns the config file path.

        :returns: path to the config file.
        """

        return self._config_file

    def setConfigFilePath(self, config_file):
        """
        Set a new config file

        :returns: path to the config file.
        """

        self._config_file = config_file
        self._readConfig(self._config_file)

    def settings(self):
        """
        Get the settings.

        :returns: settings (dict)
        """

        return copy.deepcopy(self._settings)

    def setSettings(self, settings):
        """
        Save the settings.

        :param settings: settings to save (dict)
        """

        if self._settings != settings:
            self._settings.update(settings)
            self._writeConfig()

    def loadSectionSettings(self, section, default_settings):
        """
        Get all the settings from a given section.

        :param default_settings: setting names and default values (dict)

        :returns: settings (dict)
        """

        settings = self.settings().get(section, dict())

        def _copySettings(local, default):
            """
            Copy only existing settings, ignore the other.
            Add default values if require.
            """

            # use default values for missing settings
            for name, value in default.items():
                if name not in local:
                    local[name] = value
                elif isinstance(value, dict):
                    local[name] = _copySettings(local[name], default[name])
            return local

        settings = _copySettings(settings, default_settings)

        self._settings[section] = settings
        return copy.deepcopy(settings)

    def saveSectionSettings(self, section, settings):
        """
        Save all the settings in a given section.

        :param section: section name
        :param settings: settings to save (dict)
        """

        if section not in self._settings:
            self._settings[section] = {}

        if self._settings[section] != settings:
            self._settings[section].update(settings)
            log.info("Section %s has changed. Saving configuration", section)
            self._writeConfig()
        else:
            log.debug("Section %s has not changed. Skip saving configuration", section)

    @staticmethod
    def instance(config_file=None):
        """
        Singleton to return only on instance of LocalConfig.

        :returns: instance of LocalConfig
        """

        if not hasattr(LocalConfig, "_instance") or LocalConfig._instance is None:
            LocalConfig._instance = LocalConfig(config_file=config_file)
        return LocalConfig._instance
