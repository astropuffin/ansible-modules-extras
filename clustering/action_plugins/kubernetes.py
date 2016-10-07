# (c) 2015, Michael DeHaan <michael.dehaan@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import base64
import datetime
import os
import pwd
import time
import json
import requests
import yaml

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.module_utils._text import to_bytes, to_native, to_text
from ansible.plugins.action import ActionBase
from ansible.utils.hashing import checksum_s
from ansible.utils.boolean import boolean
from ansible.module_utils.urls import fetch_url

############################################################################
############################################################################
# For API coverage, this Ansible module provides capability to operate on
# all Kubernetes objects that support a "create" call (except for 'Events').
# In order to obtain a valid list of Kubernetes objects, the v1 spec file
# was referenced and the below python script was used to parse the JSON
# spec file, extract only the objects with a description starting with
# 'create a'. The script then iterates over all of these base objects
# to get the endpoint URL and was used to generate the KIND_URL map.
#
# import json
# from urllib2 import urlopen
#
# r = urlopen("https://raw.githubusercontent.com/kubernetes"
#            "/kubernetes/master/api/swagger-spec/v1.json")
# v1 = json.load(r)
#
# apis = {}
# for a in v1['apis']:
#     p = a['path']
#     for o in a['operations']:
#         if o["summary"].startswith("create a") and o["type"] != "v1.Event":
#             apis[o["type"]] = p
#
# def print_kind_url_map():
#     results = []
#     for a in apis.keys():
#         results.append('"%s": "%s"' % (a[3:].lower(), apis[a]))
#     results.sort()
#     print "KIND_URL = {"
#     print ",\n".join(results)
#     print "}"
#
# if __name__ == '__main__':
#     print_kind_url_map()
############################################################################
############################################################################

KIND_URL = {
    "binding": "/api/v1/namespaces/{namespace}/bindings",
    "endpoints": "/api/v1/namespaces/{namespace}/endpoints",
    "limitrange": "/api/v1/namespaces/{namespace}/limitranges",
    "namespace": "/api/v1/namespaces",
    "node": "/api/v1/nodes",
    "persistentvolume": "/api/v1/persistentvolumes",
    "persistentvolumeclaim": "/api/v1/namespaces/{namespace}/persistentvolumeclaims",  # NOQA
    "pod": "/api/v1/namespaces/{namespace}/pods",
    "podtemplate": "/api/v1/namespaces/{namespace}/podtemplates",
    "replicationcontroller": "/api/v1/namespaces/{namespace}/replicationcontrollers",  # NOQA
    "resourcequota": "/api/v1/namespaces/{namespace}/resourcequotas",
    "secret": "/api/v1/namespaces/{namespace}/secrets",
    "service": "/api/v1/namespaces/{namespace}/services",
    "serviceaccount": "/api/v1/namespaces/{namespace}/serviceaccounts"
}
USER_AGENT = "ansible-k8s-module/0.0.1"

class ActionModule(ActionBase):

    def api_request(self, result, url, method="GET", headers=None, data=None, auth=None):
        body = None
        if data:
            data = json.dumps(data)
        if token:
            if headers is None:
                headers = {}
            headers["Authorization"] = "Bearer {}".format(token)
        if method == "GET":
            r = requests.get(url, headers=headers, auth=auth)
        elif method == "POST":
            r = requests.post(url, headers=headers, data=data, auth=auth)
        elif method == "PUT":
            r = requests.put(url, headers=headers, data=data, auth=auth)
        elif method == "DELETE":
            r = requests.delete(url, headers=headers, auth=auth)
        elif method == "PATCH":
            r = requests.patch(url, headers=headers, data=data, auth=auth)
        else:
            result['failed'] = True
            result['msg'] = json.dumps({'msg': "%s is not an proper http method" % method})
            return -1, None

        if r.status_code == -1:
            result['failed'] = True
            result['msg'] = json.dumps({'msg': "Failed to execute the API request: %s" % body, 'url': url, 'method':method, 'headers':headers})
        if r.text is not None:
            body = json.loads(r.text)
        return r.status_code, body
    
    
    def k8s_create_resource(self, result, url, data, auth):
        status, body = self.api_request(result, url, method="POST", data=data, headers={"Content-Type": "application/json"}, auth=auth)
        if status == 409:
            name = data["metadata"].get("name", None)
            status, body = self.api_request(result, url + "/" + name)
            return False, body
        elif status >= 400:
            result['failed'] = True
            result['msg'] = json.dumps({'msg':"failed to create the resource: %s" % body, 'url':url})
        return True, body
    
    
    def k8s_delete_resource(self, result, url, data, auth):
        name = data.get('metadata', {}).get('name')
        if name is None:
            result['failed'] = True
            result['msg'] = "Missing a named resource in object metadata when trying to remove a resource"
    
        url = url + '/' + name
        status, body = self.api_request(result, url, method="DELETE", auth=auth)
        if status == 404:
            return False, "Resource name '%s' already absent" % name
        elif status >= 400:
            result['failed'] = True
            result['msg'] = json.dumps({'msg':"failed to delete the resource '%s': %s" % (name, body), 'url':url})
        return True, "Successfully deleted resource name '%s'" % name
    

    def k8s_replace_resource(self, result, url, data, auth):
        #TODO: rather than error out, check if it already exists, and create if not
        name = data.get('metadata', {}).get('name')
        if name is None:
            result['failed'] = True
            result['msg'] = json.dumps({'msg':"Missing a named resource in object metadata when trying to replace a resource"})
    
        headers = {"Content-Type": "application/json"}
        url = url + '/' + name
        status, body = self.api_request(result, url, method="PUT", data=data, headers=headers, auth=auth)
        if status == 409:
            name = data["metadata"].get("name", None)
            info, body = self.api_request(result, url + "/" + name, auth=auth)
            return False, body
        elif status >= 400:
            result['failed'] = True
            result['msg'] = json.dumps({'msg':"failed to replace the resource '%s': %s" % (name, body), 'url':url})
        return True, body


    def k8s_update_resource(self, result, url, data, auth):
        name = data.get('metadata', {}).get('name')
        if name is None:
            result['failed'] = True
            result['msg'] = json({'msg':"Missing a named resource in object metadata when trying to update a resource"})
    
        headers = {"Content-Type": "application/strategic-merge-patch+json"}
        url = url + '/' + name
        status, body = self.api_request(result, url, method="PATCH", data=data, headers=headers, auth=auth)
        if status == 409:
            name = data["metadata"].get("name", None)
            status, body = self.api_request(result, url + "/" + name, auth=auth)
            return False, body
        elif status >= 400:
            result['failed'] = True
            result['msg'] = json.dumps({'msg':"failed to update the resource '%s': %s" % (name, body), 'url':url})
        return True, body


    def get_template_source(self, filepath):
        try:
            source = self._find_needle('templates', source)
            b_source = to_bytes(source)
            with open(b_source, 'r') as f:
                template_data = to_text(f.read())

            return template_data

        except AnsibleError as e:
            result['failed'] = True
            result['msg'] = to_native(e)
            return None

    def template(self, template_path, task_vars):
        try:
            template_data = self.get_template_source(template_path)

            temp_vars = task_vars.copy()
            temp_vars['template_host']     = os.uname()[1]
            temp_vars['template_path']     = template_path

            # Create a new searchpath list to assign to the templar environment's file
            # loader, so that it knows about the other paths to find template files
            searchpath = [self._loader._basedir, os.path.dirname(template_path)]
            if self._task._role is not None:
                if C.DEFAULT_ROLES_PATH:
                    searchpath[:0] = C.DEFAULT_ROLES_PATH
                searchpath.insert(1, self._task._role._role_path)

            self._templar.environment.loader.searchpath = searchpath

            old_vars = self._templar._available_variables
            self._templar.set_available_variables(temp_vars)
            resultant = self._templar.template(template_data, preserve_trailing_newlines=True, escape_backslashes=False, convert_data=False)
            self._templar.set_available_variables(old_vars)
        except Exception as e:
            result['failed'] = True
            result['msg'] = type(e).__name__ + ": " + str(e)
            return None

        try:
            data = yaml.load(resultant)
        except yaml.YAMLError, exc:
            if hasattr(exc, 'problem_mark'):
                mark = exc.problem_mark
                result['failed'] = True
                result['msg'] = "Error parsing YAML: error position: (%s:%s)" % (mark.line+1, mark.column+1)
            else:
                result['failed'] = True
                result['msg'] = "Unknown error parsing YAML"
            return None

        return data


    def run(self, tmp=None, task_vars=None):
        ''' handler for managing the kubernetes objects '''
        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)

        api_endpoint = self._task.args.get('api_endpoint')
        username = self._task.args.get('username', None)
        password = self._task.args.get('password', None)
        global token #TODO: don't use a global. pass a header object
        token = self._task.args.get('token')
        insecure = self._task.args.get('insecure', False)
        template_path = self._task.args.get('template', None)
        inline = self._task.args.get('inline', None)
        state  = self._task.args.get('state', None)

        # check for required params
        if api_endpoint is None:
            result['failed'] = True
            result['msg'] = "api_endpoint is required"

        auth = None
        if username is not None or password is not None:
            if username is not None and password is not None:
                auth=(username, password)
            else:
                result['failed'] = True
                result['msg'] = "username and password must both be provided if either is provided"

        if not isinstance(insecure, bool):
            result['failed'] = True
            result['msg'] = "insecure must be a valid boolean"

        if state is None:
            result['failed'] = True
            result['msg'] = "state is required"

        if template_path is not None or inline is not None:
            if template_path is not None:
                data = self.template(template_path, task_vars)
            else:
                data = inline
        else:
            result['failed'] = True
            result['msg'] = "either template or inline is required"

        if 'failed' in result:
            return result

        # some data massaging given that input params are valid
        if not isinstance(data, list):
            data = [ data ]

        transport = 'https'
        if insecure:
            transport = 'http'
    
        target_endpoint = "%s://%s" % (transport, api_endpoint)
    
        result['changed'] = False
        body = []

        # send the specs to kubernetes
        for item in data:
            namespace = "default"
            if item and 'metadata' in item:
                namespace = item.get('metadata', {}).get('namespace', "default")
                kind = item.get('kind', '').lower()
                try:
                    url = target_endpoint + KIND_URL[kind]
                except KeyError:
                    result['failed'] = True
                    result['msg'] = "invalid resource kind specified in the data: '%s'" % kind
                url = url.replace("{namespace}", namespace)
            else:
                url = target_endpoint
    
            if state == 'present':
                item_changed, item_body = self.k8s_create_resource(result, url, item, auth)
            elif state == 'absent':
                item_changed, item_body = self.k8s_delete_resource(result, url, item, auth)
            elif state == 'replace':
                item_changed, item_body = self.k8s_replace_resource(result, url, item, auth)
            elif state == 'update':
                item_changed, item_body = self.k8s_update_resource(result, url, item, auth)
    
            result['changed'] |= item_changed
            body.append(item_body)

        return result
