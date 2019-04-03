# Software License Agreement (BSD License)
#
# Copyright (c) 2018, Fraunhofer FKIE/CMS, Alexander Tiderko
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Fraunhofer nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import os
import rospy
import threading
import yaml

from .common import utf8

GRPC_TIMEOUT = 15.0
''':var GRPC_TIMEOUT: timeout for connection to remote gRPC-server'''

RESPAWN_SCRIPT = 'rosrun node_manager_fkie respawn'
''':var RESPAWN_SCRIPT: start prefix to launch ROS-Nodes with respawn script'''

LOG_PATH = ''.join([os.environ.get('ROS_LOG_DIR'), os.path.sep]) if os.environ.get('ROS_LOG_DIR') else os.path.join(os.path.expanduser('~'), '.ros/log/')
''':var LOG_PATH: logging path where all screen configuration and log files are stored.'''


class Settings:

    def __init__(self, filename='', version=''):
        self._mutex = threading.RLock()
        self.version = version
        self.filename = filename
        if not self.filename:
            self.filename = os.path.expanduser('~/.config/ros.fkie/node_manager_daemon.yaml')
        cfg_path = os.path.dirname(self.filename)
        if not os.path.isdir(cfg_path):
            os.makedirs(cfg_path)
        self._reload_callbacks = []
        self.reload()
        global GRPC_TIMEOUT
        GRPC_TIMEOUT = self.param('global/grpc_timeout', 15.0)

    def default(self):
        '''
        Value supports follow keys: {:value, :min, :max, :default, :hint(str), :ro(bool)}
        '''
        result = {
            'global': {
                'version': {':value': self.version, ':ro': True},
                'file': {':value': self.filename, ':ro': True},
                'grpc_timeout': {':value': 15.0, ':min': 0, ':default': 15.0, ':hint': "timeout for connection to remote gRPC-server"},
                'only_diagnostics_agg': False,
                'reset': False,
            },
            'sysmon':
            {
                'CPU':
                {
                    'load_warn_level': 0.9
                },
                'Disk':
                {
                    'usage_warn_level': {':value': 100, ':default': 100.0, ':hint': "values in MB"},
                    'path': LOG_PATH
                },
                'Memory':
                {
                    'usage_warn_level': {':value': 100, ':default': 100.0, ':hint': "values in MB"},
                },
                'Network':
                {
                    'load_warn_level': {':value': 0.9, ':default': 0.9, ':hint': "Percent of the maximum speed"},
                    'speed': {':value': 6, ':default': 6, ':hint': "Maximal speed in MBit"},
                    'interface': ''
                }
            }
        }
        # :TODO: 'paths': {':type': 'path[]', ':value': {'path': {':type': 'string', ':value': ''}}}
        return result

    def param(self, param_name, default_value=None, extract_value=True):
        '''
        Returns parameter value for given param_name.
        :param str param_name: name of the parameter. Namespace is separated by '/'.
        :param default_value: returns this value if parameter was not found (Default: None)
        :param bool extract_value: Since value is a dictionary with additional informations,
            try to extract value by default on True or return all options by False (Default: True).
        '''
        result = default_value
        try:
            path = param_name.split('/')
            # print "  PATH", path
            value = self._cfg
            for item in path:
                # print "    item", item
                value = value[item]
                # print "      ", value
            if isinstance(value, dict):
                if extract_value and ':value' in value:
                    result = value[':value']
                else:
                    result = value
            else:
                result = value
        except Exception as exc:
            print exc
        return result

    def set_param(self, param_name, value):
        try:
            path = os.path.dirname(param_name).split('/')
            cfg_item = self._cfg
            for item in path:
                if item:
                    if item in cfg_item:
                        cfg_item = cfg_item[item]
                    else:
                        cfg_item[item] = {}
                        cfg_item = cfg_item[item]
            pname = os.path.basename(param_name)
            if pname in cfg_item:
                if isinstance(cfg_item[pname], dict):
                    if self._is_writable(cfg_item[pname]):
                        cfg_item[pname][':value'] = value
                    else:
                        raise Exception('%s is a read only parameter!' % param_name)
                else:
                    cfg_item[pname] = value
            else:
                # create new parameter entry
                cfg_item[pname] = {':value': value}
            self.save()
        except Exception as exc:
            print exc

    def reload(self):
        '''
        Load the configuration from file. If file does not exists default configuration will be used.
        After configuration is loaded all subscribers are notified.
        '''
        with self._mutex:
            try:
                with open(self.filename, 'r') as stream:
                    result = yaml.load(stream)
                    rospy.loginfo('loaded configuration from %s' % self.filename)
                    self._cfg = result
            except (yaml.YAMLError, IOError) as exc:
                rospy.loginfo('%s: use default configuration!' % utf8(exc))
                self._cfg = self.default()
            self._notify_reload_callbacks()

    def save(self):
        with open(self.filename, 'w') as stream:
            try:
                stream.write(yaml.dump(self._cfg))
                rospy.logdebug("Configuration saved to '%s'" % self.filename)
            except yaml.YAMLError as exc:
                rospy.logwarn("Cant't save configuration to '%s': %s" % (self.filename, utf8(exc)))

    def yaml(self, nslist=[]):
        return yaml.dump(self._cfg)

    def apply(self, data):
        '''
        Applies data (string representation of YAML).
        After new data are set the configuration will be saved to file.
        All subscribers are notified.
        '''
        with self._mutex:
            self._cfg = self._apply_recursive(yaml.load(data), self._cfg)
            do_reset = self.param('global/reset', False)
            if do_reset:
                rospy.loginfo("Reset configuration requested!")
                self._cfg = self.default()
            else:
                rospy.logdebug("new configuration applied, save now.")
            self.save()
            self._notify_reload_callbacks()

    def _apply_recursive(self, new_data, curr_value):
        new_cfg = dict()
        for key, value in curr_value.items():
            try:
                if isinstance(value, dict):
                    if self._is_writable(value):
                        new_cfg[key] = self._apply_recursive(new_data[key], value)
                elif key not in [':hint', ':default', ':ro', ':min', ':max']:
                    if isinstance(new_data, dict):
                        new_cfg[key] = new_data[key]
                    else:
                        new_cfg[key] = new_data
                else:
                    new_cfg[key] = value
            except Exception:
                import traceback
                print "TMP:", traceback.format_exc(), "use old value:", value
                new_cfg[key] = value
        return new_cfg

    def _is_writable(self, value):
        if ':ro' in value:
            return value[':ro']
        return True

    def add_reload_listener(self, callback, call=True):
        '''
        Adds a subscriber to change notifications. All subscribers are notified on any changes.
        :param callback: Method of type callback(Settings)
        :param call: if True the callback is called after adding. (Default: True)
        '''
        with self._mutex:
            if callback not in self._reload_callbacks:
                self._reload_callbacks.append(callback)
                if call:
                    callback(self)

    def _notify_reload_callbacks(self):
        with self._mutex:
            for callback in self._reload_callbacks:
                callback(self)
