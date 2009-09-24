"""

typepad provides connectivity to the TypePad API through remote objects.

The `typepad` package contains `RemoteObject` implementations for TypePad's
content objects and an OAuth client for making authenticated requests to the
API.

"""

__version__ = '1.1'
__date__ = '7 August 2009'
__author__ = 'Six Apart Ltd.'
__credits__ = """Brad Choate
Leah Culver
Mark Paschal"""

from urlparse import urljoin, urlparse

import httplib2

import batchhttp.client
from remoteobjects import RemoteObject, ListObject
from typepad.oauthclient import *

class TypePadClient(batchhttp.client.BatchClient, OAuthHttp):

    """An HTTP user agent for performing TypePad API requests.

    A `TypePadClient` instance supports the same interface as `httplib2.Http`
    instances, plus some special methods for performing OAuth authenticated
    requests, and using TypePad's batch HTTP endpoint.

    Each `TypePadClient` instance also has a `cookies` member, a dictionary
    containing any additional HTTP cookies to send when making API requests.

    """

    endpoint = 'http://api.typepad.com/'
    """The URL against which to perform TypePad API requests."""

    def __init__(self, *args, **kwargs):
        self.cookies = dict()
        kwargs['endpoint'] = self.endpoint
        super(TypePadClient, self).__init__(*args, **kwargs)

    def request(self, uri, method="GET", body=None, headers=None, redirections=httplib2.DEFAULT_MAX_REDIRECTS, connection_type=None):
        """Makes the given HTTP request, as specified.

        If the instance's ``cookies`` dictionary contains any cookies, they
        will be sent along with the request.

        See `httplib2.Http.request()` for more information.

        """
        if self.cookies:
            if headers is None:
                headers = {}
            else:
                headers = dict(headers)
            cookies = ['='.join((key, value)) for key, value in self.cookies.items()]
            headers['cookie'] = '; '.join(cookies)
        return super(TypePadClient, self).request(uri, method, body, headers, redirections, connection_type)

    def signed_request(self, uri, method=None, body=None, headers=None):
        """Performs the given request, after signing the URL with the user
        agent's configured OAuth credentials.

        If the given URL is not an absolute URL, it is taken as relative to
        this instance's endpoint first.

        """
        host = urlparse(uri)[1]
        if not host:
            uri = urljoin(self.endpoint, uri)
        return super(TypePadClient, self).signed_request(uri=uri, method=method, body=body, headers=headers)

client = TypePadClient()
"""A user agent instance for making TypePad API requests."""

from typepad.tpobject import *
from typepad import fields
from typepad.api import *
