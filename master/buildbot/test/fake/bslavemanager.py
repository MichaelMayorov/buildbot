# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from twisted.application import service
from twisted.internet import defer

class FakeBuildslaveManager(service.MultiService):

    def __init__(self, master):
        service.MultiService.__init__(self)
        self.setName('buildslaves')
        self.master = master

        # BuildslaveRegistration instances keyed by buildslave name
        self.registrations = {}

        # connection objects keyed by buildslave name
        self.connections = {}

    def register(self, buildslave):
        # TODO: doc that reg.update must be called, too
        buildslaveName = buildslave.slavename
        reg = FakeBuildslaveRegistration(self.master, buildslave)
        self.registrations[buildslaveName] = reg
        return defer.succeed(reg)

    def _unregister(self, registration):
        del self.registrations[registration.buildslave.slavename]


class FakeBuildslaveRegistration(object):

    def __init__(self, master, buildslave):
        self.master = master
        self.buildslave = buildslave

    @defer.inlineCallbacks
    def unregister(self):
        yield self.master.buildslaves._unregister(self)
        yield self.master.pbmanager._unregister(self.portstr, self.buildslave.slavename)

    @defer.inlineCallbacks
    def update(self, slave_config, global_config):
        self.portstr = global_config.protocols['pb']['port']
        self.pbReg = yield self.master.pbmanager.register(
                global_config.protocols['pb']['port'],
                slave_config.slavename, slave_config.password, None
                )

