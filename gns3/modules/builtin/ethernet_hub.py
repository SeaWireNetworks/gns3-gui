# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 GNS3 Technologies Inc.
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

import uuid
from gns3.node import Node
from gns3.ports.ethernet_port import EthernetPort

import logging
log = logging.getLogger(__name__)


class EthernetHub(Node):
    """
    Ethernet hub.

    :param module: parent module for this node
    :param server: GNS3 server instance
    :param project: Project instance
    """
    URL_PREFIX = "ethernet_hub"

    def __init__(self, module, server, project):

        super().__init__(module, server, project)
        self.setStatus(Node.started)  # this is an always-on node
        self._ports = []
        self._settings = {"name": "",
                          "ports": []}

    def isAlwaysOn(self):
        """
        Indicates that this node is always running and cannot be stopped.

        :returns: boolean
        """

        return True

    def setup(self, name=None, node_id=None, ports=None, default_name_format="Hub{0}"):
        """
        Setups this hub.

        :param name: optional name for this hub
        :param node_id: node identifier on the server
        :param ports: ports to automatically be added when creating this hub
        """

        # let's create a unique name if none has been chosen
        if not name:
            name = self.allocateName(default_name_format)

        if not name:
            self.error_signal.emit(self.id(), "could not allocate a name for this Ethernet hub")
            return

        self._settings["name"] = name
        params = {"name": name}
        if node_id:
            params["node_id"] = node_id
        if ports:
            params["ports"] = ports
        self._create(params)

    def _setupCallback(self, result, error=False, **kwargs):
        """
        Callback for setup.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if not super()._setupCallback(result, error=error, **kwargs):
            return

        if "ports" in result:
            for port_info in result["ports"]:
                port = EthernetPort(port_info["name"])
                port.setAdapterNumber(0)  # adapter number is always 0
                port.setPortNumber(port_info["port_number"])
                port.setStatus(EthernetPort.started)
                self._ports.append(port)
                log.debug("port {} has been added".format(port_info["port_number"]))

        if self._loading:
            self.loaded_signal.emit()
        else:
            self.setInitialized(True)
            log.info("HUB instance {} has been created".format(self.name()))
            self.created_signal.emit(self.id())
            self._module.addNode(self)

    def update(self, new_settings):
        """
        Updates the settings for this Ethernet hub.

        :param new_settings: settings dictionary
        """

        params = {}
        if "ports" in new_settings:
            params["ports"] = []
            for port_number in new_settings["ports"]:
                params["ports"].append({"port_number": int(port_number),
                                        "name": "Ethernet{}".format(port_number)})

        if "name" in new_settings and new_settings["name"] != self.name():
            if self.hasAllocatedName(new_settings["name"]):
                self.error_signal.emit(self.id(), 'Name "{}" is already used by another node'.format(new_settings["name"]))
                return
            params["name"] = new_settings["name"]

        if params:
            self._update(params)

    def _updatePort(self, port_name, port_number):

        # update the port if existing
        for port in self._ports:
            if port.portNumber() == port_number:
                port.setName(port_name)
                log.debug("port {} has been updated".format(port_number))
                return

        # otherwise create a new port
        port = EthernetPort(port_name)
        port.setAdapterNumber(0)  # adapter number is always 0
        port.setPortNumber(port_number)
        port.setStatus(EthernetPort.started)
        self._ports.append(port)
        log.debug("port {} has been added".format(port_number))

    def updateCallback(self, result, error=False, **kwargs):
        """
        Callback for update.

        :param result: server response
        :param error: indicates an error (boolean)
        """

        if not super().updateCallback(result, error=error, **kwargs):
            return False

        if error:
            log.error("error while updating {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        else:
            if "ports" in result:
                updated_port_list = []
                # add/update ports
                for port_info in result["ports"]:
                    self._updatePort(port_info["name"], port_info["port_number"])
                    updated_port_list.append(port_info["port_number"])

                # delete ports
                for port in self._ports.copy():
                    if port.isFree() and port.portNumber() not in updated_port_list:
                        self._ports.remove(port)
                        log.debug("port {} has been removed".format(port.portNumber()))

                self._settings["ports"] = list(map(int, updated_port_list))
            if "name" in result:
                self._settings["name"] = result["name"]
                self.updateAllocatedName(result["name"])
            log.info("{} has been updated".format(self.name()))
            self.updated_signal.emit()

    def info(self):
        """
        Returns information about this Ethernet hub.

        :returns: formatted string
        """

        info = """Ethernet hub {name} is always-on
  Local node ID is {id}
  Server's node ID is {node_id}
  Hub's server runs on {host}:{port}
""".format(name=self.name(),
           id=self.id(),
           node_id=self._node_id,
           host=self._server.host(),
           port=self._server.port())

        port_info = ""
        for port in self._ports:
            if port.isFree():
                port_info += "   Port {} is empty\n".format(port.name())
            else:
                port_info += "   Port {name} {description}\n".format(name=port.name(),
                                                                     description=port.description())

        return info + port_info

    def dump(self):
        """
        Returns a representation of this Ethernet hub
        (to be saved in a topology file)

        :returns: representation of the node (dictionary)
        """

        hub = super().dump()
        hub["properties"]["name"] = self.name()
        return hub

    def load(self, node_info):
        """
        Loads an Ethernet hub representation
        (from a topology file).

        :param node_info: representation of the node (dictionary)
        """

        super().load(node_info)
        settings = node_info["properties"]
        name = settings.pop("name")

        # Ethernet hubs do not have an UUID before version 2.0
        node_id = settings.get("node_id", str(uuid.uuid4()))

        ports = []
        if "ports" in node_info:
            ports = [{"port_number": port["port_number"], "name": port["name"]} for port in node_info["ports"]]

        log.info("Ethernet hub {} is loading".format(name))
        self.setName(name)
        self.setup(name, node_id, ports)

    def name(self):
        """
        Returns the name of this hub.

        :returns: name (string)
        """

        return self._settings["name"]

    def settings(self):
        """
        Returns all this hub settings.

        :returns: settings dictionary
        """

        return self._settings

    def ports(self):
        """
        Returns all the ports for this hub.

        :returns: list of Port instances
        """

        return self._ports

    def configPage(self):
        """
        Returns the configuration page widget to be used by the node properties dialog.

        :returns: QWidget object
        """

        from .pages.ethernet_hub_configuration_page import EthernetHubConfigurationPage
        return EthernetHubConfigurationPage

    @staticmethod
    def defaultSymbol():
        """
        Returns the default symbol path for this node.

        :returns: symbol path (or resource).
        """

        return ":/symbols/hub.svg"

    @staticmethod
    def symbolName():

        return "Ethernet hub"

    @staticmethod
    def categories():
        """
        Returns the node categories the node is part of (used by the device panel).

        :returns: list of node category (integer)
        """

        return [Node.switches]

    def __str__(self):

        return "Ethernet hub"