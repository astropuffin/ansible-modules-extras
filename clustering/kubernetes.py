#!/usr/bin/python
# Copyright 2015 Google Inc. All Rights Reserved.
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
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>

DOCUMENTATION = '''
---
module: kubernetes
version_added: "2.1"
short_description: Manage Kubernetes resources.
description:
    - This module can manage Kubernetes resources on an existing cluster using
      the Kubernetes server API. Users can specify in-line API data, or
      specify an existing Kubernetes YAML file. Currently, this module,
        Supports HTTP Basic Auth and Auth Tokens
        Only supports 'strategic merge' for update, http://goo.gl/fCPYxT
options:
  api_endpoint:
    description:
      - The IPv4 API endpoint of the Kubernetes cluster.
    required: true
    default: null
    aliases: ["endpoint"]
  inline:
    description:
      - The Kubernetes YAML data to send to the API I(endpoint).
    required: true
    default: null
  template:
    description:
      - The Kubernetes YAML data to send to the API I(endpoint).
    required: true
    default: null
  state:
    description:
      - The desired action to take on the Kubernetes data.
    required: true
    default: "present"
    choices: ["present", "absent", "update", "replace"]
  username:
    description:
      - The HTTP Basic Auth username for the API I(endpoint). This should be set
        unless using the C('insecure') option. If C('password') is supplied then
        then this is required. Mutually exclusive with C('token')
    default: "admin"
    aliases: ["username"]
  password:
    description:
      - The HTTP Basic Auth password for the API I(endpoint). This should be set
        unless using the C('insecure') option. If C('username') is supplied then
        then this is required. Mutually exclusive with C('token')
    default: null
    aliases: ["password"]
  token:
    description:
      - the Authorization bearer token (http://kubernetes.io/docs/admin/authentication/)
        Mutually exclusive with C('username') and C('password')
    default: None
  insecure:
    description:
      - "Reverts the connection to using HTTP instead of HTTPS. This option should
        only be used when execuing the M('kubernetes') module local to the Kubernetes
        cluster using the insecure local port (locahost:8080 by default)."

author: "Eric Johnson (@erjohnso) <erjohnso@google.com>"
        "adapted by Joe schneider (@astropuffin) <j2@dronedeploy.com>"
'''

EXAMPLES = '''
# Create a kubernetes namespace from file
- name: Create a kubernetes namespace from file
  kubernetes:
    api_endpoint: example.com
    token: redacted
    template: ns.yml
    state: present

# Create a kubernetes namespace from template
- name: Create a kubernetes namespace from template
  kubernetes:
    api_endpoint: example.com
    username: admin
    password: redacted
    template: ns.yml.j2
    state: present
  with_items:
    - ansible-test

# Create a kubernetes namespace from inline
- name: Create a kubernetes namespace from inline
  kubernetes:
    api_endpoint: example.com
    token: redacted
    inline:
        kind: Namespace
        apiVersion: v1
        metadata:
          name: "{{ item }}"
          labels:
            label_env: test
            label_ver: latest
          annotations:
            a1: value1
            a2: value2
    state: present
  with_items:
    - ansible-test
'''

RETURN = '''
# Example response from creating a Kubernetes Namespace.
api_response:
    description: Raw response from Kubernetes API, content varies with API.
    returned: success
    type: dictionary
    contains:
        apiVersion: "v1"
        kind: "Namespace"
        metadata:
            creationTimestamp: "2016-01-04T21:16:32Z"
            name: "test-namespace"
            resourceVersion: "509635"
            selfLink: "/api/v1/namespaces/test-namespace"
            uid: "6dbd394e-b328-11e5-9a02-42010af0013a"
        spec:
            finalizers:
                - kubernetes
        status:
            phase: "Active"
'''

#This module is implemented as an action plugin
