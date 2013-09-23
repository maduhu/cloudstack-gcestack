#!/usr/bin/env python
# encoding: utf-8
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

import json, urllib
from flask import request, url_for
from gcecloudstack import app, authentication
from gcecloudstack.services import requester
from gcecloudstack.controllers import zones, helper, operations, images, errors, machine_type


def _get_virtual_machines(authorization, args=None):
    command = 'listVirtualMachines'
    if not args:
        args = {}

    cloudstack_response = requester.make_request(
        command,
        args,
        authorization.client_id,
        authorization.client_secret
    )

    return cloudstack_response


def _deploy_virtual_machine(authorization, args):
    command = 'deployVirtualMachine'

    converted_args = {}
    template = images.get_template_by_name(
        authorization=authorization,
        image=args['template']
    )
    converted_args['templateid'] = template['id']

    zone = zones.get_zone_by_name(
        authorization=authorization,
        zone=args['zone']
    )
    converted_args['zoneid'] = zone['id']

    serviceoffering = machine_type.get_machinetype_by_name(
        authorization=authorization,
        machinetype=args['serviceoffering']
    )
    converted_args['serviceofferingid'] = serviceoffering['id']
    converted_args['displayname'] = args['name']
    converted_args['name'] = args['name']

    cloudstack_response = requester.make_request(
        command,
        converted_args,
        authorization.client_id,
        authorization.client_secret
    )

    return cloudstack_response

def _destroy_virtual_machine(authorization, instance):
    virtual_machine_id = _get_virtual_machine_by_name(authorization, instance)['id']
    print(virtual_machine_id)
    if virtual_machine_id is None:
        func_route = url_for('_destroy_virtual_machine', instance=instance)
        return(errors.resource_not_found(func_route))

    args = {
        'id': virtual_machine_id
    }
    return requester.make_request(
        'destroyVirtualMachine',
        args,
        authorization.client_id,
        authorization.client_secret
    )

def _cloudstack_virtual_machine_to_gce(cloudstack_response, zone, projectid):
    response = {}
    response['kind'] = 'compute#instance'
    response['id'] = cloudstack_response['id']
    response['creationTimestamp'] = cloudstack_response['created']
    response['status'] = cloudstack_response['state'].upper()
    response['name'] = cloudstack_response['name']
    response['description'] = cloudstack_response['name']
    response['machineType'] = cloudstack_response['serviceofferingname']
    response['image'] = cloudstack_response['templatename']
    response['canIpForward'] = 'true'
    response['networkInterfaces'] = []
    response['disks'] = []

    networking = {}
    networking['network'] = 'tobereviewed'
    networking['networkIP'] = cloudstack_response['nic'][0]['ipaddress']
    networking['name'] = cloudstack_response['nic'][0]['id']

    response['networkInterfaces'].append(networking)

    response['selfLink'] = urllib.unquote_plus(helper.get_root_url() + url_for(
        'getinstance',
        projectid=projectid,
        instance=cloudstack_response['name'],
        zone=zone
    ))
    response['zone'] = zone

    return response

def _get_virtual_machine_by_name(authorization, instance):
    virtual_machine_list = _get_virtual_machines(
        authorization=authorization,
        args={
            'keyword': instance
        }
    )
    print('made it here')
    print(virtual_machine_list)

    if virtual_machine_list['listvirtualmachinesresponse']:
        response = helper.filter_by_name(
            data=virtual_machine_list['listvirtualmachinesresponse']['virtualmachine'],
            name=instance
        )
        return response
    else:
        return None


@app.route('/' + app.config['PATH'] + '<projectid>/aggregated/instances', methods=['GET'])
@authentication.required
def aggregatedlistinstances(authorization, projectid):
    zone_list = zones.get_zone_names(authorization=authorization)
    virtual_machine_list = _get_virtual_machines(authorization=authorization)

    items = {}

    for zone in zone_list:
        zones_instances = []
        if virtual_machine_list['listvirtualmachinesresponse']:
            for instance in virtual_machine_list['listvirtualmachinesresponse']['virtualmachine']:
                zones_instances.append(
                    _cloudstack_virtual_machine_to_gce(
                        cloudstack_response=instance,
                        projectid=projectid,
                        zone=zone
                    )
                )
        items['zone/' + zone] = {}
        items['zone/' + zone]['zone'] = zone
        items['zone/' + zone]['instances'] = zones_instances

    populated_response = {
        'kind': 'compute#instanceAggregatedList',
        'id': 'projects/' + projectid + '/instances',
        'selfLink': request.base_url,
        'items': items
    }
    return helper.create_response(data=populated_response)


@app.route('/' + app.config['PATH'] + '<projectid>/zones/<zone>/instances', methods=['GET'])
@authentication.required
def listinstances(authorization, projectid, zone):
    instance = None
    filter = helper.get_filter(request.args)

    if 'name' in filter:
        instance = filter['name']

    items = []

    if instance:
        virtual_machine = _get_virtual_machine_by_name(
            authorization=authorization,
            instance=instance
        )
        if virtual_machine:
            items.append(
                _cloudstack_virtual_machine_to_gce(
                    cloudstack_response=virtual_machine,
                    projectid=projectid,
                    zone=zone
                )
            )
    else:
        virtual_machine_list = _get_virtual_machines(authorization=authorization)
        if virtual_machine_list['listvirtualmachinesresponse']:
            for instance in virtual_machine_list['listvirtualmachinesresponse']['virtualmachine']:
                items.append(
                    _cloudstack_virtual_machine_to_gce(
                        cloudstack_response=instance,
                        projectid=projectid,
                        zone=zone,
                    )
                )

    populated_response = {
        'kind': 'compute#instance_list',
        'id': 'projects/' + projectid + '/instances',
        'selfLink': request.base_url,
        'items': items
    }

    return helper.create_response(data=populated_response)


@app.route('/' + app.config['PATH'] + '<projectid>/zones/<zone>/instances/<instance>', methods=['GET'])
@authentication.required
def getinstance(projectid, authorization, zone, instance):
    response = _get_virtual_machine_by_name(
        authorization=authorization,
        instance=instance
    )

    if response:
        return helper.create_response(
            data=_cloudstack_virtual_machine_to_gce(
                cloudstack_response=response,
                projectid=projectid,
                zone=zone
            )
        )
    else:
        function_route = url_for('getinstance', projectid=projectid, instance=instance)
        return errors.resource_not_found(function_route)


@app.route('/' + app.config['PATH'] + '<projectid>/zones/<zone>/instances', methods=['POST'])
@authentication.required
def addinstance(authorization, projectid, zone):
    data = json.loads(request.data)
    args = {}
    args['name'] = data['name']
    args['serviceoffering'] = data['machineType'].rsplit('/', 1)[1]
    args['template'] = data['image'].rsplit('/', 1)[1]
    args['zone'] = zone

    deploymentResult = _deploy_virtual_machine(authorization, args)

    if 'errortext' in deploymentResult['deployvirtualmachineresponse']:
        populated_response = {
            'kind': 'compute#operation',
            'operationType': 'insert',
            'targetLink': '',
            'status': 'DONE',
            'progress': 100,
            'error': {
                'errors': [{
                    'code': 'RESOURCE_ALREADY_EXISTS',
                    'message': 'the resource \'projects/\'' + projectid + '/zones/' + zone + '/instances/' +
                    args['name']
                }]
            }
        }
    else:
        populated_response = operations.create_response(
            projectid=projectid,
            operationid=deploymentResult['deployvirtualmachineresponse']['jobid'],
            authorization=authorization
        )

    return helper.create_response(data=populated_response)

@app.route('/' + app.config['PATH'] + '<projectid>/zones/<zone>/instances/<instance>', methods=['DELETE'])
@authentication.required
def deleteinstance(projectid, authorization, zone, instance):
    cloudstack_response = _destroy_virtual_machine(authorization, instance)
    instance_deleted = operations.delete_instance_response(cloudstack_response['destroyvirtualmachineresponse'])
    return helper.create_response(data=instance_deleted)
