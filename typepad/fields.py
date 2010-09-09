# Copyright (c) 2009-2010 Six Apart Ltd.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of Six Apart Ltd. nor the names of its contributors may
#   be used to endorse or promote products derived from this software without
#   specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import logging

import simplejson as json
import urlparse

import remoteobjects.dataobject
import remoteobjects.fields
from remoteobjects.fields import *
import remoteobjects.http
import typepad.tpobject

class Link(remoteobjects.fields.Link):

    """A `TypePadObject` property representing a link from one TypePad API
    object to another.

    This `Link` works like `remoteobjects.fields.Link`, but builds links using
    the TypePad API URL scheme. That is, a `Link` on ``/asset/1.json`` called
    ``events`` links to ``/asset/1/events.json``.

    """

    def __init__(self, cls, api_url, api_url_names={}, **kwargs):
        super(Link, self).__init__(cls, **kwargs)
        self.api_name = self.api_url = api_url
        self.api_url_names = api_url_names

    def __get__(self, instance, type=None, **kwargs):
        """Generates the `TypePadObject` representing the target of this
        `Link` object.

        This `__get__()` implementation implements the ``../x/target.json`` style
        URLs used in the TypePad API.

        """
        if instance is None:
            return self

        try:
            # Build a param list for format specifier replacement. We just grab from kwargs and also add in
            # 'id' automatically (since it is known).  If an api_url_names dict is provided (mapping pynames to 
            # api_names), use it to convert whatever params it specifies to api_names.
            params = kwargs.copy()
            params['id'] = instance.url_id
            for pyname, api_name in self.api_url_names:
                if pyname in params and api_name not in params:
                    params[api_name] = params[pyname]
                    del params[pyname]
                    del kwargs[pyname] # delete this now too since the cleanup step below won't find it.
            
            endpoint = _get_endpoint_from_instance(instance)
            newurl = endpoint + (self.api_url % params)
            
            # Now we have to clean up and remove the kwargs we consumed in the URL path
            for kwarg in kwargs.keys():
                if '%%(%s)s'%kwarg in self.api_url:
                    del kwargs[kwarg]
            
            cls = self.cls
            if isinstance(cls, basestring):
                cls = remoteobjects.dataobject.find_by_name(cls)
            ret = cls.get(newurl, **kwargs)
            return ret
        except Exception, e:
            logging.error(str(e))
            raise


class ActionEndpoint(remoteobjects.fields.Property):

    def __init__(self, api_url, post_type, response_type=None, api_url_names={}, **kwargs):
        self.api_name = self.api_url = api_url
        self.api_url_names = api_url_names
        self.post_type = post_type
        self.response_type = response_type
        super(ActionEndpoint, self).__init__(**kwargs)

    def install(self, attrname, cls):
        self.of_cls = cls
        self.attrname = attrname
        if self.api_name is None:
            self.api_name = attrname

    def __get__(self, instance, owner):
        def post(**kwargs):
            post_obj = self.post_type(**kwargs)

            # Build a param list for format specifier replacement. We just grab from kwargs and also add in
            # 'id' automatically (since it is known).  If an api_url_names dict is provided (mapping pynames to 
            # api_names), use it to convert whatever params it specifies to api_names.
            params = kwargs.copy()
            params['id'] = instance.url_id
            for pyname, api_name in self.api_url_names:
                if pyname in params and api_name not in params:
                    params[api_name] = params[pyname]
                    del params[pyname]
                    del kwargs[pyname] # delete this now too since the cleanup step below won't find it.
            
            endpoint = _get_endpoint_from_instance(instance, default=typepad.client.endpoint)
            newurl = endpoint + (self.api_url % params)
            
            # Now we have to clean up and remove the kwargs we consumed in the URL path
            for kwarg in kwargs.keys():
                if '%%(%s)s'%kwarg in self.api_url:
                    del kwargs[kwarg]
            
            body = json.dumps(post_obj.to_dict(), default=remoteobjects.http.omit_nulls)
            headers = {'content-type': post_obj.content_types[0]}
            request = post_obj.get_request(url=newurl, method='POST',
                body=body, headers=headers)

            resp, content = typepad.client.request(**request)

            # If there's no response type, raise any errors but don't return anything.
            if self.response_type is None:
                typepad.tpobject.TypePadObject.raise_for_response(newurl, resp, content)
                return

            resp_obj = self.response_type.get(newurl)
            resp_obj.update_from_response(newurl, resp, content)
            return resp_obj

        return post


def _get_endpoint_from_instance(instance, default=''):
    """
    Given an instance of a TypePadObject, return its client endpoint.
    """
    if hasattr(instance, '_http') and instance._http and instance._http.endpoint:
        return instance._http.endpoint
    elif hasattr(instance, '_location') and instance._location:
        parts = urlparse.urlparse(instance._location)
        if parts[0] and parts[1]:
            return '%s://%s' % (parts[0], parts[1])
    else:
        return default
    
