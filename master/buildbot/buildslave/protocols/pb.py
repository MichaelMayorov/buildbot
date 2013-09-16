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

from __future__ import absolute_import

from twisted.python import log
from twisted.internet import defer
from buildbot.buildslave.protocols import base
from twisted.spread import pb

class Listener(base.Listener):

    def __init__(self, master):
        base.Listener.__init__(self, master)

        # username : (password, portstr, PBManager registration)
        self._registrations = {}

    @defer.inlineCallbacks
    def updateRegistration(self, username, password, portStr):
        # NOTE: this method is only present on the PB protocol; others do not
        # use registrations
        if username in self._registrations:
            currentPassword, currentPortStr, currentReg = \
                    self._registrations[username]
        else:
            currentPassword, currentPortStr, currentReg = None, None, None

        if currentPassword != password or currentPortStr != portStr:
            if currentReg:
                yield currentReg.unregister()
                del self._registrations[username]
            if portStr:
                reg = self.master.pbmanager.register(
                        portStr, username, password, self._getPerspective)
                self._registrations[username] = (password, portStr, reg)
                defer.returnValue(reg)

    @defer.inlineCallbacks
    def _getPerspective(self, mind, buildslaveName):
        bslaves = self.master.buildslaves
        log.msg("slave '%s' attaching from %s" % (buildslaveName,
                                        mind.broker.transport.getPeer()))

        # try to use TCP keepalives
        try:
            mind.broker.transport.setTcpKeepAlive(1)
        except Exception:
            log.err("Can't set TcpKeepAlive")

        buildslave = bslaves.getBuildslaveByName(buildslaveName)
        conn = Connection(self.master, buildslave, mind)

        # inform the manager, logging any problems in the deferred
        accepted = yield bslaves.newConnection(conn, buildslaveName)

        # return the Connection as the perspective
        if accepted:
            defer.returnValue(conn)
        else:
            # TODO: return something more useful
            raise RuntimeError('rejected')

class Connection(base.Connection, pb.Avatar):

    def __init__(self, master, buildslave, mind):
        base.Connection.__init__(self, master, buildslave)
        self.mind = mind

    # methods called by the PBManager

    @defer.inlineCallbacks
    def attached(self, mind):
        # pbmanager calls perspective.attached; pass this along to the
        # buildslave
        yield self.buildslave.attached(self)
        # and then return a reference to the avatar
        yield self

    def detached(self, mind):
        self.mind = None
        self.notifyDisconnected()

    # disconnection handling

    def loseConnection(self):
        self.mind.broker.transport.loseConnection()

    # methods to send messages to the slave

    def remotePrint(self, message):
        return self.mind.callRemote('print', message=message)

    @defer.inlineCallbacks
    def remoteGetSlaveInfo(self):
        info = {}
        try:
            info = yield self.mind.callRemote('getSlaveInfo')
        except pb.NoSuchMethod, e:
            log.msg("BuildSlave.info_unavailable")
            log.msg(e)

        try:
            info["slave_commands"] = yield self.mind.callRemote('getCommands')
        except pb.NoSuchMethod, e:
            log.msg("BuildSlave.getCommands is unavailable - ignoring")

        try:
            info["version"] = yield self.mind.callRemote('getVersion')
        except pb.NoSuchMethod, e:
            log.msg("BuildSlave.getVersion is unavailable - ignoring")

        defer.returnValue(info)

    def remoteSetBuilderList(self, builders):
        def cache_builders(builders):
            self.builders = builders
            return builders
        d = self.mind.callRemote('setBuilderList', builders)
        d.addCallback(cache_builders)
        return d

    # perspective methods called by the slave

    def perspective_keepalive(self):
        log.msg('keepalive from slave') # TODO: temporary

    def perspective_shutdown(self):
        log.msg("slave %s wants to shut down" % self.slavename)
        # TODO: support that..

    def startCommands(self, RCInstance, builder_name, commandID, remote_command, args):
        slavebuilder = self.builders.get(builder_name)
        return slavebuilder.callRemote('startCommand',
            RCInstance, commandID, remote_command, args
        )

    def doKeepalive(self):
        return self.mind.callRemote('print', message="keepalive")

    def remoteShutdown(self):
        d = self.mind.callRemote('shutdown')
        d.addCallback(lambda _ : True) # successful shutdown request
        def check_nsm(f):
            f.trap(pb.NoSuchMethod) 
            return False # fall through to the old way
        d.addErrback(check_nsm)
        def check_connlost(f):
            f.trap(pb.PBConnectionLost)
            return True # the slave is gone, so call it finished
        d.addErrback(check_connlost)
        return d

    def remoteShutdownOldWay(self, slavename):
        log.msg("Shutting down (old) slave: %s" % slavename)
        d = self.mind.callRemote('shutdown')
        # The remote shutdown call will not complete successfully since the
        # buildbot process exits almost immediately after getting the
        # shutdown request.
        # Here we look at the reason why the remote call failed, and if
        # it's because the connection was lost, that means the slave
        # shutdown as expected.
        if d:
            def _errback(why):
                if why.check(pb.PBConnectionLost):
                    log.msg("Lost connection to %s" % slavename)
                else:
                    log.err("Unexpected error when trying to shutdown %s" % slavename)
            d.addErrback(_errback)
            return d
        log.err("Couldn't find remote builder to shut down slave")
        return defer.succeed(None)