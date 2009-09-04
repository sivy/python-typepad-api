"""
Tests drawn from https://intranet.sixapart.com/wiki/index.php/TPX:API_Endpoints_Implemented_for_Potion

    # TODO
    # - blocked members
    #   - that they should not be able to create posts/favorites
    # - featured members (i don't think we have filters for them yet)
    #   - that we cannot block a featured member
    # - test for failure of post by non-member / blocked user
    # - asset deletion failure by a non-creator, non-admin user
    # - comment deletion failure by non-commenter user

Input test data should have this form:

    testdata = {
        'configuration': {
            'backend_url': '...',
            'oauth_consumer_key': '...',
            'oauth_consumer_secret': '...',
            'cookies': { 'micro_pool_id': '1' }
        },
        'admin': {
            'xid': '...',
            'oauth_key': '...',
            'oauth_secret': '...'
        },
        'member': {
            'xid': '...',
            'oauth_key': '...',
            'oauth_secret': '...'
        },
        'blocked': {
            'xid': '...',
            'oauth_key': '...',
            'oauth_secret': '...',
        },
        'featured': {
            'xid': '...',
            'oauth_key': '...',
            'oauth_secret': '...',
        },
        'group': {
            'xid': '...',
            'name': '...'
            'oauth_key': '...',
            'oauth_secret': '...'
        }
    }

    the member should follow admin
    the admin should follow member

    the member should have 2 or more elsewhere accounts

    'blocked' identifies a member who will become blocked by the
    test suite

Numbering prefix scheme for tests.
Some tests should be run in a specific order. The only way to do this
is through the test method name, as tests are run in alphabetic order.

    0 - POSTs for setting up data for tests

    1 - GET requests, relying on test data as described above.

    2 - Relationship test to unblock the blocked member
    3 - Test to (re-)block the user who was blocked to begin with

    4 - PUT requests

    5 - POST requests for parent objects (assets)
    6 - POST requests for child objects (favorites, comments)

    7 - DELETE requests for child objects (favorites, comments)
    8 - DELETE requests for top-level objects (assets)

    9 - DELETE for remaining assets (final cleanup)

"""


import httplib
import logging
import os
from pprint import pprint
import re
import time
import unittest
from urllib import urlencode, unquote
from urlparse import urlsplit, urlunsplit, urlparse
import cgi
import base64

import httplib2
import nose
import nose.plugins.attrib
from oauth import oauth
import simplejson as json

from remoteobjects.http import HttpObject
from tests import utils
from tests import test_api
import typepad


def load_test_data():
    filename = os.getenv('TEST_TYPEPAD_JSON')
    if filename is None:
        raise nose.SkipTest('no test data provided')
    f = open(filename, 'r')
    s = f.read()
    f.close()
    return json.loads(s)


def setUpModule():
    global testdata
    testdata = load_test_data()
    typepad.client.endpoint = testdata['configuration']['backend_url']
    testdata['assets'] = []
    testdata['assets_created'] = []
    testdata['comments_created'] = []
    if 'coookies' in testdata['configuration']:
        typepad.client.cookies.update(testdata['configuration']['cookies'])


def attr(*args, **kwargs):
    """Decorator wrapper for the nose 'attrib' attr decorator.
    
    This attr decorator recognizes the 'user' attribute when assigned and
    calls the `credentials_for` method of the TestTypePad class to apply the
    appropriate OAuth credentials.

    This wrapper also attempts to derive the HTTP method from the docstring of
    the wrapped function and assigns a 'method' attribute if found.
    """
    def wrap(fn):
        user = kwargs.get('user', None)
        if fn.__doc__ is not None:
            m = re.match(r'^(GET|DELETE|PUT|POST) ', fn.__doc__)
            if m is not None:
                verb = m.groups()[0]
                kwargs['method'] = verb
        @nose.plugins.attrib.attr(*args, **kwargs)
        def test_user(self, *args, **kwargs):
            if user is not None:
                self.credentials_for(user)
            fn(self, *args, **kwargs)
            self.clear_credentials()
        utils.update_wrapper(test_user, fn)
        return test_user
    return wrap


class TestTypePad(unittest.TestCase):

    @attr(user='member')
    def test_0_setup_test_data(self):
        """Sets up some test data for our group."""

        group_id = self.testdata['group']['xid']
        member_id = self.testdata['member']['xid']

        post1 = self.post_asset()
        post1.content = "This post is needed to test list operations."
        typepad.Group.get_by_url_id(group_id).post_assets.post(post1)
        self.assertValidAsset(post1)

        self.testdata['assets_created'].append(post1.xid)

        # lets pause to reflect (and allow timestamps between these assets to differ)
        time.sleep(2)

        post2 = self.post_asset()
        post2.content = "This post will be favorited and commented on."
        typepad.Group.get_by_url_id(group_id).post_assets.post(post2)
        self.assertValidAsset(post2)

        self.testdata['assets_created'].append(post2.xid)

        # the older post should be favorited

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        typepad.client.complete_batch()

        fav = typepad.Favorite()
        fav.in_reply_to = post1.asset_ref
        user.favorites.post(fav)

        self.assertValidFavorite(fav)

        # the older post should have 2 comments

        content = (
            """Lorem ipsum dolor sit amet, consectetur adipisicing elit, """
            """sed do eiusmod tempor incididunt ut labore et dolore magna """
            """aliqua. Ut enim ad minim veniam, quis nostrud exercitation """
            """ullamco laboris nisi ut aliquip ex ea commodo consequat. """
            """Duis aute irure dolor in reprehenderit in voluptate velit """
            """esse cillum dolore eu fugiat nulla pariatur. Excepteur """
            """sint occaecat cupidatat non proident, sunt in culpa qui """
            """officia deserunt mollit anim id est laborum."""
        )

        comment1 = typepad.Comment()
        comment1.title = ''
        comment1.content = content
        post1.comments.post(comment1)

        # validate comment asset now that it's been posted
        self.assertValidAsset(comment1)
        self.assertEquals(comment1.in_reply_to.url_id, post1.url_id)
        self.assertEquals(comment1.content, content)

        self.testdata['comments_created'].append(comment1.xid)

        content = 'Yeah, what he said.'

        comment2 = typepad.Comment()
        comment2.title = ''
        comment2.content = content
        post1.comments.post(comment2)

        self.assertValidAsset(comment2)
        self.assertEquals(comment2.in_reply_to.url_id, post1.url_id)

        self.testdata['comments_created'].append(comment2.xid)

        # now, load testdata['assets'] with these test assets
        self.load_test_assets()

    @attr(user='group')
    def test_1_GET_applications_id(self):
        """GET /applications/<id>.json (group)
        
        Tests the application endpoint using the configured OAuth consumer key
        (which is the application id). Also tests that the application's
        "owner" object is the group that has been identified in the test
        configuration.
        """

        api_key = self.testdata['configuration']['oauth_consumer_key']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        app = typepad.Application.get_by_api_key(api_key)
        group = typepad.Group.get_by_url_id(group_id)
        typepad.client.complete_batch()

        self.assertValidApplication(app)
        self.assertValidGroup(group)
        self.assertEquals(app.api_key, api_key)

        # Test owner property
        self.assertEquals(app.owner.xid, group_id)
        self.assertEquals(app.owner.links['self'].href,
            group.links['self'].href)

    @attr(user='group')
    def test_1_GET_application_id__invalid(self):
        """GET /applications/invalid.json (group)
        
        Tests the /applications endpoint with an invalid application
        key. This should result in a 404 error.
        """

        typepad.client.batch_request()
        bad_app = typepad.Application.get_by_api_key('invalid')
        self.assertNotFound(typepad.client.complete_batch)

    @attr(user='group')
    def test_1_GET_assets_id(self):
        """GET /assets/<id>.json (group)
        
        Tests the /assets endpoint using the first 18 assets found in the
        group event stream (loaded during the test setup method).
        """

        self.assert_(len(self.testdata['assets']) >= 2,
            'Must have 2 or more assets to test')

        member_id = self.testdata['member']['xid']
        group_id = self.testdata['group']['xid']
        assets = []

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        # '18' because the batch processor is limited to 20 subrequests.
        for asset_id in self.testdata['assets'][:18]:
            assets.append(typepad.Asset.get_by_url_id(asset_id))
        user = typepad.User.get_by_url_id(member_id)
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        self.assertValidUser(user)

        for asset in assets:
            self.assert_(group.id in asset.groups)
            self.assertValidAsset(asset)

    @attr(user='group')
    def test_1_GET_assets_id__invalid(self):
        """GET /assets/invalid.json (group)
        
        Tests the /assets endpoint using an invalid asset id. This should
        result in a 404 error.
        """

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id('invalid')
        self.assertNotFound(typepad.client.complete_batch)

    @attr(user='group')
    def test_8_DELETE_assets_id__by_group(self):
        """DELETE /assets/<id>.json (group)

        Tests deletion of an asset using group credentials. This should result
        in a 403 error (FORBIDDEN).
        """

        self.assert_(len(self.testdata['assets_created']))

        asset_id = self.testdata['assets_created'][0]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        self.assert_(not asset.can_delete)
        self.assertForbidden(asset.delete)

    @attr(user='group')
    def test_8_DELETE_assets_id__comment__by_group(self):
        """DELETE /assets/<id>.json (comment asset; group)

        Tests deletion of a comment using group credentials. This should
        result in a 403 error (FORBIDDEN).
        """

        self.assert_(len(self.testdata['comments_created']))

        asset_id = self.testdata['comments_created'][0]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        self.assert_(not asset.can_delete)
        self.assertForbidden(asset.delete)

    @attr(user='admin')
    def test_8_DELETE_assets_id__by_admin(self):
        """DELETE /assets/<id>.json (admin)

        Tests deletion of an asset using admin credentials.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87922')

        self.assert_(len(self.testdata['assets_created']))

        asset_id = self.testdata['assets_created'].pop()

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        self.assert_(asset.can_delete)
        asset.delete()

        # now, see if we can select it. hopefully this fails.
        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        self.assertNotFound(typepad.client.complete_batch)

    @attr(user='admin')
    def test_8_DELETE_assets_id__comment__by_admin(self):
        """DELETE /assets/<id>.json (comment asset; admin)

        Tests deletion of a comment using admin credentials.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87922')

        self.assert_(len(self.testdata['comments_created']))

        asset_id = self.testdata['comments_created'].pop()

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        self.assert_(asset.can_delete)
        asset.delete()

        # now, see if we can select it. hopefully this fails.
        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        self.assertNotFound(typepad.client.complete_batch)

    @attr(user='member')
    def test_9_DELETE_assets_id__post__by_member(self):
        """DELETE /assets/<id>.json (member)

        Tests deletion of an asset using member credentials.
        """

        self.assert_(len(self.testdata['assets_created']))

        for asset_id in self.testdata['assets_created']:
            typepad.client.batch_request()
            asset = typepad.Asset.get_by_url_id(asset_id)
            typepad.client.complete_batch()

            self.assertValidAsset(asset)
            self.assert_(asset.can_delete)
            asset.delete()

            # now, see if we can select it. hopefully this fails.
            typepad.client.batch_request()
            asset = typepad.Asset.get_by_url_id(asset_id)
            self.assertNotFound(typepad.client.complete_batch)

        self.testdata['assets_created'] = []

    @attr(user='member')
    def test_9_DELETE_assets_id__comment__by_member(self):
        """DELETE /assets/<id>.json (comment asset; member)

        Tests deletion of a comment using member credentials.
        """

        self.assert_(len(self.testdata['comments_created']))

        for asset_id in self.testdata['comments_created']:
            typepad.client.batch_request()
            asset = typepad.Asset.get_by_url_id(asset_id)
            typepad.client.complete_batch()

            self.assertValidAsset(asset)
            self.assert_(asset.can_delete)
            asset.delete()

            # now, see if we can select it. hopefully this fails.
            typepad.client.batch_request()
            asset = typepad.Asset.get_by_url_id(asset_id)
            self.assertNotFound(typepad.client.complete_batch)

        self.testdata['comments_created'] = []

    @attr(user='group')
    def test_4_PUT_assets_id__by_group(self):
        """PUT /assets/<id>.json (group)
        
        Tests updating an asset using group's credentials. This should
        result in a 403 error (FORBIDDEN).
        """

        asset_id = self.testdata['assets'][0]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)

        # Lets change this asset and put it back and see what happens
        orig_title = asset.title
        asset.title = 'Changed by test suite by group'
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87859
        # self.assertForbidden(asset.put)
        try:
            asset.put()
            self.fail('group credentials allowed an update to an asset')
        except:
            pass

        # Re-select this asset to verify it has not been updated.

        typepad.client.batch_request()
        asset2 = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset2)

        self.assertEquals(asset2.title, orig_title)

    @attr(user='member')
    def test_4_PUT_assets_id__by_member(self):
        """PUT /assets/<id>.json (member)

        Tests updating an asset using member credentials.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87900')

        asset_id = self.testdata['assets'][0]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)

        # Lets change this asset and put it back and see what happens
        asset.title = 'Changed by test suite by creator'
        asset.put()

        # Re-select this asset to verify it has been updated.
        typepad.client.batch_request()
        asset2 = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset2)

        self.assertEquals(asset2.title, 'Changed by test suite by creator')

        asset.title = ''
        asset.put()

    @attr(user='admin')
    def test_4_PUT_assets_id__by_admin(self):
        """PUT /assets/<id>.json (admin)
        
        Tests updating an asset using admin credentials.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87900')

        asset_id = self.testdata['assets'][0]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)

        # Lets change this asset and put it back and see what happens
        asset.title = 'Changed by test suite by admin'
        asset.put()

        # Re-select this asset to verify it has been updated.
        typepad.client.batch_request()
        asset2 = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset2)
        self.assertEquals(asset2.title, 'Changed by test suite by admin')

        asset.title = ''
        asset.put()

    @attr(user='group')
    def test_1_GET_assets_id_comments(self):
        """GET /assets/<id>/comments.json (group)
        
        Tests selection of comments for a specific asset.
        """

        self.assert_(len(self.testdata['assets']) >= 2,
            'Must have 2 or more assets to test')

        asset_id = self.testdata['assets'][1]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        listset = self.filterEndpoint(asset.comments)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        self.assertValidFilter(listset)

        comments = listset[0]
        for comment in comments:
            self.assertValidAsset(comment)

    @attr(user='member')
    def test_6_POST_assets_id_comments(self):
        """POST /assets/<id>/comments.json (member)
        
        Tests posting a comment to an asset.
        """

        asset_id = self.testdata['assets'][1]

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)

        content = "Hey there, here's a comment."
        comment = typepad.Comment()
        comment.title = ''
        comment.content = content
        asset.comments.post(comment)
        # validate comment asset now that it's been posted
        self.assertValidAsset(comment)
        self.assertEquals(comment.in_reply_to.url_id, asset.url_id)
        self.assertEquals(comment.content, content)

        self.testdata['comments_created'].append(comment.xid)

    @attr(user='group')
    def test_1_GET_assets_id_favorites(self):
        """GET /assets/<id>/favorites.json (group)
        
        Tests selecting favorites for a specific asset.
        """

        self.assert_(len(self.testdata['assets']) >= 2,
            'Must have 2 or more assets to test')

        asset_id = self.testdata['assets'][1]
        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_url_id(asset_id)
        favs = asset.favorites.filter()
        # FIXME: this requires 2 or more favorites on the top-most asset
        # listset = self.filterEndpoint(asset.favorites)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        # self.assertValidFilter(listset)

        # favs = listset[0]
        for fav in favs:
            self.assertValidFavorite(fav)

        self.assertEquals(favs.entries[0].author.url_id, member_id)
        self.assertEquals(favs.entries[0].in_reply_to.url_id, asset_id)

    def test_5_POST_batch_processor(self):
        """POST /batch-processor.json
        """

        raise nose.SkipTest(
            'We test this endpoint through our other tests.')

    def upload_asset(self, ident, asset, filename, file_type, content):
        """Helper method for posting a file to the TypePad API.

        ident is one of the user identifiers (group, member, admin, blocked)
        content is the base64 encoded file contents to post."""

        api_key = self.testdata['configuration']['oauth_consumer_key']

        typepad.client.batch_request()
        app = typepad.Application.get_by_api_key(api_key)
        typepad.client.complete_batch()

        post_type = asset['objectTypes'][0]
        post_type = post_type[post_type.rindex(':')+1:]

        self.assertValidApplication(app)

        # make sure we don't have any oauth credentials; we're not using
        # oauth in this way for the browser-upload endpoint
        typepad.client.clear_credentials()

        # FIXME: browser-upload relies on 'post_type' parameter instead
        # of objectTypes assigned to asset? That's weird.
        boundary = 'BoUnDaRyStRiNg'
        body = (
            """--%(boundary)s\n"""
            """Content-Disposition: form-data; name="redirect_to\n"""
            """\n"""
            """http://127.0.0.1:8000/ajax/upload_url\n"""
            """--%(boundary)s\n"""
            """Content-Disposition: form-data; name="post_type"\n"""
            """\n"""
            """%(post_type)s\n"""
            """--%(boundary)s\n"""
            """Content-Disposition: form-data; name="asset"\n"""
            """\n"""
            """%(asset)s\n"""
            """--%(boundary)s\n"""
            """Content-Disposition: form-data; name="file"; filename="%(filename)s"\n"""
            """Content-Type: %(mime_type)s\n"""
            """\n"""
            """%(file)s\n"""
            """--%(boundary)s--""").replace('\n', '\r\n') % \
            { 'asset': json.dumps(asset),
              'boundary': boundary,
              'file': base64.decodestring(content),
              'filename': filename,
              'post_type': post_type,
              'mime_type': file_type }

        consumer = oauth.OAuthConsumer(
            key = self.testdata['configuration']['oauth_consumer_key'],
            secret = self.testdata['configuration']['oauth_consumer_secret'],
        )
        token = oauth.OAuthToken(
            self.testdata[ident]['oauth_key'],
            self.testdata[ident]['oauth_secret'],
        )
        oauth_client = typepad.OAuthClient(consumer, token)

        remote_url = app.browser_upload_endpoint
        url = oauth_client.get_file_upload_url(remote_url)

        headers = {
            'Content-Type': 'multipart/form-data; boundary=%s' % boundary,
            'Content-Length': str(len(body)),
        }
        response = None
        content = None
        # don't follow the redirect; we want it for ourselves
        response, content = typepad.client.request(url, 'POST',
            body, headers, 0)

        self.assert_(response)
        self.assertEquals(response.status, httplib.FOUND)
        self.assert_('location' in response)

        urlparts = urlsplit(response['location'])
        params = cgi.parse_qs(urlparts[3])

        self.assert_('status' in params)

        if ident in ('member', 'admin', 'featured'): # test for a successful upload
            self.assert_('error' not in params)
            self.assert_(int(params['status'][0]) != httplib.BAD_REQUEST, 'returned status is BAD_REQUEST')
            self.assert_('asset_url' in params)
            parts = urlparse(params['asset_url'][0])

            self.credentials_for('group')
            posted_asset = typepad.Asset.get(parts[2], batch=False)

            self.assertValidAsset(posted_asset)
            self.assertEquals(posted_asset.primary_object_type(), asset['objectTypes'][0])

            self.testdata['assets_created'].append(posted_asset.xid)
        else: # test for a failure
            self.assertEquals(int(params['status'][0]), httplib.UNAUTHORIZED)

    @attr(user='member')
    def test_5_POST_browser_upload__photo__by_member(self):
        """POST /browser-upload.json (photo; member)
        """

        asset = {
            'content': 'This is a test upload',
            'objectTypes': ['tag:api.typepad.com,2009:Photo']
        }
        content = "\n".join(
            """iVBORw0KGgoAAAANSUhEUgAAACAAAAAWCAYAAAChWZ5EAAAAqUlEQVRIx8XTsQ2AIBCFYcM+OoOV"""
            """lQu4gxM4jQswAyUrsAI1A6BXaKIiiLkHxSV0338EGu99U2nEPn1NvK0VcOI1Ai546YAHXjIgiJcK"""
            """eMVLBERxdEASRwYQ3qVwVMBnHBEQxK21ozFmQge8bq61nqWUKzIgiDvnBtpcKbVQAJ3vNwHdnDCC"""
            """78MZEH1w6Bv4/NoRbyDrq3F/Qzb8TwArnhvAjucECG74mA3T52uZi1CUIgAAAABJRU5ErkJggg=="""
        )
        self.upload_asset('member', asset, 'photo.png', 'image/png', content)

    @attr(user='member')
    def test_5_POST_browser_upload__audio__by_member(self):
        """POST /browser-upload.json (audio; member)
        """

        asset = {
            'content': 'A small audio post',
            'objectTypes': ['tag:api.typepad.com,2009:Audio']
        }
        content = "\n".join(
            """//tQZAAAAAAAf4UAAAgAAA0goAABFVWnQ7kKAAAAADSDAAAAgEAYCAQCAUBAIAYABADkguG8AkDk"""
            """fDIoN1fFnCC3hiIUiHw/hiEUkGrgt+/xNoZFC30R0GKtf8MjCkQ1aGARSQau//C34TaGKQtBD9gs"""
            """iBuL//E2hgEG+h0QWRACggFhIGQIgwFrskkYnP+A4CBhn4GyjgYlABnSABQoWkLQQtFGOFBGQBA4"""
            """6Yt+iBgxLf4fMMaIKjMkcLmIMdIqVTInk1l3////84jMUlGSAP/7QGQAiPJHRcrvAqAIAAANIOAA"""
            """AQeBEymgH5PgAAA0gAAABAAAA/3+sEX+9Wut7erUtfU3umtal9m3qzMxKJsl77/rf39a///MS6gi"""
            """iXwAAyBiYZgdkdQGiyUAMLhRhCUcRiXTXv+nsW38QgAbf/WBl/fed5Rptb7a3MVWOXc70ykQs3mp"""
            """f9f62T////3q7q/FGXmBgIeBdgOXiNbqQ/T1Bbv+nsV/IwAAAAPv/rAw9dt6+dpk//swZAcI8dZF"""
            """SugF5PgAAA0gAAABB4ETK6AGsWAAADSAAAAEX211Szeu3iKBY76J/r9vVP///+u4duR9eAVD5sTh"""
            """mJwSsR/4xSW7D9P/xb+8Acff6gRUR/PcvPU+a7RFTLQNnus2mJa9l7fr////+yRqTI6hGIJiQDJH"""
            """yAwGDhSJHGaZ41qf/ZQWR2ZNAAAAF+/+qCX///3qKDfN//tAZAeI8o5GSmgn5ygAAA0gAAABCXUb"""
            """J6CLnKAAADSAAAAEsq85hVkCaxGSImdmOZWUdDr3mM9f2Rm8/70MY89/vPtSGKKnaQ5qdZUCZx2y"""
            """gJqhgPfemZ3I9SiwTxOFgwU1z//WcAF229oAH///1h0gu4MEYfy5SzWWejulaIN6Oylm6yG/+lDS"""
            """lmeuOEqjVd2WczaIIKBpfc4QQQaHQwCF0lTQw7z/W5TZTEpY8Cv//QoAAAD/+0BkAYryVkXK6CLf"""
            """KAAADSAAAAEI0RcpoI9coAAANIAAAAQb//7IJf///f6OqGjAdJ5azqGeyw8uj0Gv1dqpoVUIU/9N"""
            """XIp0Y+vcN25i9DcAuuyAs4cPKNLSTXJLYcmZ+kBchWBEkOm7/kABtYGv///hnyQRCMcyqSQ6zSZr"""
            """uJ0z2SyL0ENbc2PYy+TPbv/n/bTpM5d/Xd/3OXPrADKzFV28i8CxrCXVeHtIafGVW/+I6gAABv/7"""
            """MGQBiPG2QspoAaN4AAANIAAAAQZZCymgCbHgAAA0gAAABBfv/qwwq+/kiPImEgsdBUEkBPDchpup"""
            """NFFV3c4jU2vq6///6u/+rSRJoAxIHiNX//3U/6QBv//rA1ZNaF+Xq7JdlCq7sqGSqLSToxqtgjnk"""
            """0X16bLVX9tupq//TJAH8Shznq+//+ToADgMD/kL////////QkEISrv/7EGQIj/CGQkuYAT8IAAAN"""
            """IAAAAQAAAaQAAAAgAAA0gAAABExBTUUzLjk4qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"""
            """qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//sQZCIP8AAAaQAAAAgAAA0gAAABAAABpAAA"""
            """ACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"""
            """qqqqqqqqqqqqqqqqqqqqqqqqqqo="""
        )
        self.upload_asset('member', asset, 'audio.mp3', 'audio/mpeg', content)

    @attr(user='group')
    def test_5_POST_browser_upload__photo__by_group(self):
        """POST /browser-upload.json (photo; group)
        """

        asset = {
            'content': 'This is a test upload',
            'objectTypes': ['tag:api.typepad.com,2009:Photo']
        }
        content = "\n".join(
            """iVBORw0KGgoAAAANSUhEUgAAACAAAAAWCAYAAAChWZ5EAAAAqUlEQVRIx8XTsQ2AIBCFYcM+OoOV"""
            """lQu4gxM4jQswAyUrsAI1A6BXaKIiiLkHxSV0338EGu99U2nEPn1NvK0VcOI1Ai546YAHXjIgiJcK"""
            """eMVLBERxdEASRwYQ3qVwVMBnHBEQxK21ozFmQge8bq61nqWUKzIgiDvnBtpcKbVQAJ3vNwHdnDCC"""
            """78MZEH1w6Bv4/NoRbyDrq3F/Qzb8TwArnhvAjucECG74mA3T52uZi1CUIgAAAABJRU5ErkJggg=="""
        )
        self.upload_asset('group', asset, 'test.png', 'image/png', content)

    @attr(user='group')
    def test_1_GET_events_id(self):
        """GET /events/<id>.json (group)
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87901')

    @attr(user='group')
    def test_1_GET_favorites_id(self):
        """GET /favorites/<id>.json (group)
        
        Tests selection of a single favorite object.
        """

        self.assert_(len(self.testdata['assets']) >= 2,
            'Must have 2 or more assets to test')

        # asset:user
        member_id = self.testdata['member']['xid']
        asset_id = self.testdata['assets'][1]

        typepad.client.batch_request()
        fav = typepad.Favorite.get_by_user_asset(member_id, asset_id)
        typepad.client.complete_batch()

        self.assertValidFavorite(fav)
        self.assertEquals(fav.in_reply_to.url_id, asset_id)
        self.assertEquals(fav.author.url_id, member_id)

    @attr(user='group')
    def test_7_DELETE_favorites_id__by_group(self):
        """DELETE /favorites/<id>.json (group)
        
        Tests deletion of a favorite object using group credentials.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87864')

        self.assert_(len(self.testdata['assets_created']))

        member_id = self.testdata['member']['xid']
        asset_id = self.testdata['assets_created'][0]

        self.assertForbidden(
            typepad.Favorite.get_by_user_asset(member_id, asset_id).delete)

    @attr(user='member')
    def test_7_DELETE_favorites_id__by_member(self):
        """DELETE /favorites/<id>.json (member)
        
        Tests deletion of a favorite object using member credentials.
        """

        self.assert_(len(self.testdata['assets_created']))

        member_id = self.testdata['member']['xid']
        asset_id = self.testdata['assets_created'][0]

        typepad.Favorite.get_by_user_asset(member_id, asset_id).delete()

        typepad.client.batch_request()
        fav = typepad.Favorite.get_by_user_asset(member_id, asset_id)
        self.assertNotFound(typepad.client.complete_batch)

    @attr(user='admin')
    def test_7_DELETE_favorites_id__by_admin(self):
        """DELETE /favorites/<id>.json (admin)
        
        Tests deletion of a favorite object using admin credentials.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87902')

        self.assert_(len(self.testdata['assets_created']))

        member_id = self.testdata['member']['xid']
        asset_id = self.testdata['assets_created'][1]

        typepad.Favorite.get_by_user_asset(member_id, asset_id).delete()

        typepad.client.batch_request()
        fav = typepad.Favorite.get_by_user_asset(member_id, asset_id)
        self.assertNotFound(typepad.client.complete_batch)

    @attr(user='group')
    def test_1_GET_groups_id(self):
        """GET /groups/<id>.json (group)
        
        Tests selection of a group object using group credentials.
        """

        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        self.assertEquals(group.url_id, group_id)
        self.assertEquals(group.display_name, self.testdata['group']['name'])

    @attr(user='group')
    def test_1_GET_groups_id_events(self):
        """GET /groups/<id>/events.json (group)
        
        Tests endpoint for selecting the group event stream.
        """

        self.assert_(len(self.testdata['assets']) >= 2,
            'Must have 2 or more assets to test')

        group_id = self.testdata['group']['xid']
        member_id = self.testdata['member']['xid']
        asset_id = self.testdata['assets'][0]

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        listset = self.filterEndpoint(group.events)
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        self.assertEquals(group.url_id, group_id)
        self.assertValidFilter(listset)

        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87911
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?88008
        events = [x for x in listset[0] if x.object and len(x.object.groups) > 0]
        for event in events:
            self.assertValidEvent(event)

        self.assertEquals(events[0].actor.url_id, member_id)
        self.assertEquals(events[0].object.url_id, asset_id)
        self.assertEquals(events[0].object.author.url_id, member_id)
        self.assertTrue(events[0].object.groups[0].endswith(group_id))

    @attr(user='member')
    def test_5_POST_groups_id_link_assets(self):
        """POST /groups/<id>/link-assets.json (member)
        
        Tests endpoint for creating a new link asset within the group.
        """

        group_id = self.testdata['group']['xid']

        link = self.link_asset()

        typepad.Group.get_by_url_id(group_id).link_assets.post(link)
        self.assertValidAsset(link)

        self.testdata['assets_created'].append(link.xid)

    @attr(user='group')
    def test_1_GET_groups_id_memberships(self):
        """GET /groups/<id>/memberships.json (group)
        
        Tests selection of group memberships.
        """

        group_id = self.testdata['group']['xid']
        admin_id = self.testdata['admin']['xid']
        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        everyone = group.memberships.filter()
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        for rel in everyone:
            self.assertValidRelationship(rel)

        self.assert_(len(everyone) > 0, 'memberships should be non-zero')
        self.assert_(admin_id in [a.target.xid for a in everyone],
            'configured admin should exist in memberships')
        self.assert_(member_id in [a.target.xid for a in everyone],
            'configured member should exist in memberships')

    @attr(user='group')
    def test_1_GET_groups_id_memberships_admin(self):
        """GET /groups/<id>/memberships/@admin.json (group)
        
        Tests selection of group administrator memberships.
        """

        group_id = self.testdata['group']['xid']
        admin_id = self.testdata['admin']['xid']

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        admins = group.memberships.filter(admin=True)
        everyone = group.memberships.filter()
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        for rel in admins:
            self.assertValidRelationship(rel)
        for rel in everyone:
            self.assertValidRelationship(rel)

        # yes, we have one or more admins!
        self.assert_(len(admins) > 0, 'admin membership should be non-zero')
        self.assert_(admin_id in [a.target.xid for a in admins],
            'configured admin should exist in admin memberships')
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?84133
        # Restore this test once the above bug is resolved.
        # self.assertNotEqual(admins.total_results, everyone.total_results,
        #     'Filtered member list size should be less than unfiltered list: %d != %d' %
        #     ( admins.total_results, everyone.total_results ))

    @attr(user='group')
    def test_1_GET_groups_id_memberships_member(self):
        """GET /groups/<id>/memberships/@member.json (group)
        
        Tests selection of a group member relationships.
        """

        group_id = self.testdata['group']['xid']
        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        listset = self.filterEndpoint(group.memberships, member=True)
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        self.assertValidFilter(listset)

        members = listset[0]
        for member in members:
            self.assertValidRelationship(member)

        self.assert_(member_id in [a.target.xid for a in members],
            'configured admin should exist in admin memberships')

    @attr(user='group')
    def test_1_GET_groups_id_notifications(self):
        """GET /groups/<id>/notifications.json (group)
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87903')

    @attr(user='member')
    def test_5_POST_groups_id_photo_assets(self):
        """POST /groups/<id>/photo-assets.json (member)
        
        Tests posting a photo asset.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87928')

    @attr(user='member')
    def test_5_POST_groups_id_audio_assets(self):
        """POST /groups/<id>/audio-assets.json (member)
        
        Tests posting an audio asset.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87928')

    @attr(user='member')
    def test_5_POST_groups_id_post_assets__by_member(self):
        """POST /groups/<id>/post-assets.json (member)
        
        Tests posting a text post asset using member credentials.
        """

        group_id = self.testdata['group']['xid']

        post = self.post_asset()

        typepad.Group.get_by_url_id(group_id).post_assets.post(post)
        self.assertValidAsset(post)

        self.testdata['assets_created'].append(post.xid)

    @attr(user='group')
    def test_5_POST_groups_id_post_assets__by_group(self):
        """POST /groups/<id>/post-assets.json (group)

        Tests posting a text post asset using group credentials.
        """

        group_id = self.testdata['group']['xid']

        post = self.post_asset()
        post.content = 'Test post asset by group'

        self.assertUnauthorized(
            typepad.Group.get_by_url_id(group_id).post_assets.post, post)

    @attr(user='blocked')
    def test_5_POST_groups_id_post_assets__by_blocked(self):
        """POST /groups/<id>/post-assets.json (blocked)
        
        Tests posting a text post asset using a blocked user's credentials.
        """

        group_id = self.testdata['group']['xid']

        post = self.post_asset()
        post.content = 'Test post asset by blocked user'

        self.assertForbidden(
            typepad.Group.get_by_url_id(group_id).post_assets.post, post)

    @attr(user='member')
    def test_5_POST_groups_id_video_assets(self):
        """POST /groups/<id>/video-assets.json
        
        Tests posting a video asset using member credentials.
        """

        group_id = self.testdata['group']['xid']

        video = self.video_asset()

        typepad.Group.get_by_url_id(group_id).video_assets.post(video)
        self.assertValidAsset(video)

        self.testdata['assets_created'].append(video.xid)

    @attr(user='group')
    def test_5_POST_groups_id_video_assets__by_group(self):
        """POST /groups/<id>/video-assets.json

        Tests posting a video asset using group credentials.
        """

        group_id = self.testdata['group']['xid']

        video = self.video_asset()
        video.content = 'Test video post by group'

        self.assertUnauthorized(
            typepad.Group.get_by_url_id(group_id).video_assets.post, video)

    @attr(user='blocked')
    def test_5_POST_groups_id_video_assets__by_blocked(self):
        """POST /groups/<id>/video-assets.json (blocked)

        Tests posting a video asset using a blocked user's credentials.
        """

        group_id = self.testdata['group']['xid']
        video = self.video_asset()

        self.assertForbidden(
            typepad.Group.get_by_url_id(group_id).video_assets.post, video)

    @attr(user='group')
    def test_1_GET_relationships_id(self):
        """GET /relationships/<id>.json (group)
        
        Tests the selection of a single relationship object.
        """

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        followers = user.relationships.filter(follower=True, max_results=1)
        typepad.client.complete_batch()

        self.assertValidUser(user)

        rel = followers[0]
        self.assertValidRelationship(rel)

        rel_link = rel.links['self'].href

        typepad.client.batch_request()
        rel2 = typepad.Relationship.get(rel_link)
        typepad.client.complete_batch()

        self.assertValidRelationship(rel2)

    @attr(user='group')
    def test_1_GET_relationship_id_status(self):
        """GET /relationships/<id>/status.json (group)
        
        Tests the selection of a relationship's status.
        """

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        followers = user.relationships.filter(follower=True, max_results=1)
        typepad.client.complete_batch()

        self.assertValidUser(user)

        rel = followers[0]
        self.assertValidRelationship(rel)

        rel_status = rel.links['status'].href

        typepad.client.batch_request()
        status = typepad.RelationshipStatus.get(rel_status)
        typepad.client.complete_batch()

        self.assertValidRelationshipStatus(status)

    def update_relationship(self, ident, action):
        """Updates the group relationship of a particular user."""

        raise nose.SkipTest("FIXME: https://intranet.sixapart.com/bugs/default.asp?88128")

        if not ident in self.testdata:
            raise nose.SkipTest("missing configuration for %s user" % ident)

        group_id = self.testdata['group']['xid']
        user_id = self.testdata[ident]['xid']

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(group_id)
        typepad.client.complete_batch()

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(user_id)
        memberships = user.memberships.filter(by_group=group)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assert_(len(memberships) == 1)
        self.assertValidRelationship(memberships[0])
        self.assertEquals(memberships[0].target.xid, group_id)

        if action == 'block':
            self.assert_(not memberships[0].is_blocked())
            memberships[0].block()
        elif action == 'unblock':
            self.assert_(memberships[0].is_blocked())
            status = typepad.RelationshipStatus.get(memberships[0].status_url(), batch=False)
            status.types = ["tag:api.typepad.com,2009:Member"]
            status.put()

        typepad.client.batch_request()
        new_membership = user.memberships.filter(by_group=group)
        typepad.client.complete_batch()

        self.assert_(len(new_mebership) == 1)
        self.assertValidRelationship(new_membership[0])

        # confirm relationship now reflects status we expect
        if action == 'block':
            self.assert_(new_membership[0].is_blocked())
            self.assert_(not new_membership[0].is_member())
        elif action == 'unblock':
            self.assert_(not new_membership[0].is_blocked())
            self.assert_(new_membership[0].is_member())

    @attr(user='admin')
    def test_4_PUT_relationships_id_status__unblock_blocked__by_admin(self):
        """PUT /relationships/<id>/status.json (unblock; admin)
        
        Tests the endpoint to update a relationship status.
        """

        # This endpoint can only be used by an administrator.
        self.update_relationship('blocked', 'block')

    @attr(user='admin')
    def test_3_PUT_relationships_id_status__block_admin__by_admin(self):
        """PUT /relationships/<id>/status.json (block admin; admin)
        
        Tests the endpoint to update a relationship status.
        """

        # This request should fail, since we should not be allowed to
        # block ourselves, or other admins.
        self.assertForbidden(self.update_relationship, 'admin', 'block')

    @attr(user='admin')
    def test_3_PUT_relationships_id_status__block_featured__by_admin(self):
        """PUT /relationships/<id>/status.json (block featured; admin)
        
        Tests the endpoint to update a relationship status.
        """

        # This request should fail, since we should not be allowed to
        # block featured users
        self.assertForbidden(self.update_relationship, 'featured', 'block')

    @attr(user='group')
    def test_3_PUT_relationships_id_status__block_blocked__by_group(self):
        """PUT /relationships/<id>/status.json (group)
        """

        self.assertForbidden(self.update_relationship, 'blocked', 'block')

    @attr(user='member')
    def test_3_PUT_relationships_id_status__block_blocked__by_member(self):
        """PUT /relationships/<id>/status.json (member)
        """

        self.assertForbidden(self.update_relationship, 'blocked', 'block')

    @attr(user='admin')
    def test_2_PUT_relationship_id_status__unblock_blocked__by_admin(self):
        """PUT /relationships/<id>/status.json (block; admin)
        
        Tests the endpoint to update a relationship status.
        """

        self.update_relationship('blocked', 'unblock')

    @attr(user='group')
    def test_1_GET_users_id(self):
        """GET /users/<id>.json (group)
        
        Tests the selection of a single user object.
        """

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertEquals(user.xid, member_id)

    @attr(user='group')
    def test_1_GET_users_invalid(self):
        """GET /users/(invalid).json (group)
        """

        typepad.client.batch_request()
        self.assertRaises(ValueError, typepad.User.get_by_url_id, '(invalid)')
        typepad.client.complete_batch()

    @attr(user='group')
    def test_1_GET_users__(self):
        """GET /users/.json (group)
        """

        typepad.client.batch_request()
        self.assertRaises(ValueError, typepad.User.get_by_url_id, '')
        typepad.client.complete_batch()

    @attr(user='group')
    def test_1_GET_users_id_elsewhere_accounts(self):
        """GET /users/<id>/elsewhere-accounts.json (group)
        
        Tests the selection of the elsewhere account for the configured
        member.
        """

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.elsewhere_accounts)
        typepad.client.complete_batch()

        self.assertValidFilter(listset)
        elsewhere = listset[0]

        self.assertValidUser(user)
        self.assert_(elsewhere is not None)
        self.assert_(len(elsewhere) > 0)

    @attr(user='group')
    def test_1_GET_users_id_events(self):
        """GET /users/<id>/events.json (group)
        
        Tests the selection of an event stream for a specific user.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87756')

    @attr(user='group')
    def test_1_GET_users_id_events_by_group_id(self):
        """GET /users/<id>/events/@by-group/<id>.json (group)
        
        Tests the selection of the group-specific event stream for a specific
        user.
        """

        member_id = self.testdata['member']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.events, by_group=group_id)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87911
        events = [x for x in listset[0] if x.object]
        for event in events:
            self.assertValidEvent(event)

        self.assertEquals(events[0].actor.url_id, member_id)
        self.assertEquals(events[0].object.author.url_id, member_id)
        self.assertTrue(events[0].object.groups[0].endswith(group_id))

    @attr(user='group')
    def test_1_GET_users_id_favorites(self):
        """GET /users/<id>/favorites.json (group)
        
        Tests the selection of the favorites for a specific user.
        """

        raise nose.SkipTest(
            'FIXME: https://intranet.sixapart.com/bugs/default.asp?87904')

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.favorites)
        typepad.client.complete_batch()

        self.assertValidFilter(listset)
        favs = listset[0]
        for fav in favs:
            self.assertValidFavorite(fav)

    @attr(user='member')
    def test_6_POST_users_id_favorites(self):
        """POST /users/<id>/favorites.json (member)
        
        Tests the endpoint for creating a new favorite for a user.
        """

        # we wind up deleting two favorites (one by member, one by admin),
        # so lets make sure we created at least 2
        self.assert_(len(self.testdata['assets_created']) >= 2)

        for asset_id in self.testdata['assets_created']:
            member_id = self.testdata['member']['xid']

            typepad.client.batch_request()
            user = typepad.User.get_by_url_id(member_id)
            asset = typepad.Asset.get_by_url_id(asset_id)
            typepad.client.complete_batch()

            self.assertValidUser(user)
            self.assertValidAsset(asset)

            fav = typepad.Favorite()
            fav.in_reply_to = asset.asset_ref
            user.favorites.post(fav)

            self.assertValidFavorite(fav)

            typepad.client.batch_request()
            fav2 = typepad.Favorite.get_by_user_asset(member_id, asset_id)
            typepad.client.complete_batch()

            self.assertValidFavorite(fav2)

    @attr(user='group')
    def test_1_GET_users_id_memberships(self):
        """GET /users/<id>/memberships.json (group)
        
        Tests the endpoint for selecting memberships for a specific user.
        """

        member_id = self.testdata['member']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.memberships)
        typepad.client.complete_batch()

        self.assertValidFilter(listset)

        memberships = listset[0]
        self.assert_(group_id in [x.source.xid for x in memberships])

    @attr(user='group')
    def test_1_GET_users_id_memberships_admin(self):
        """GET /users/<id>/memberships/@admin.json (group)
        
        Tests the endpoint for selecting a user's relationships for groups
        they administer.
        """

        admin_id = self.testdata['admin']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(admin_id)
        listset = self.filterEndpoint(user.memberships, admin=True)
        typepad.client.complete_batch()

        # FIXME: https://intranet.sixapart.com/bugs/default.asp?88434
        # self.assertValidFilter(listset)

        memberships = listset[0]
        self.assert_(group_id in [x.source.xid for x in memberships])

    @attr(user='group')
    def test_1_GET_users_id_memberships_by_group_id(self):
        """GET /users/<id>/memberships/@by-group/<id>.json (group)

        Tests the endpoint for selecting a group membership for a specific
        user.
        """

        member_id = self.testdata['member']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        memberships = user.memberships.filter()
        # FIXME: can't use this without having 2 or more group memberships
        # listset = self.filterEndpoint(user.memberships,
        #     by_group=group_id)
        typepad.client.complete_batch()

        # self.assertValidFilter(listset)

        # memberships = listset[0]
        self.assert_(member_id in [x.target.xid for x in memberships])

    @attr(user='group')
    def test_1_GET_users_id_memberships_member(self):
        """GET /users/<id>/memberships/@member.json (group)
        
        Tests the endpoint for selecting a user's relationships for
        groups they are a member of.
        """

        member_id = self.testdata['member']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        memberships = user.memberships.filter(member=True)
        # FIXME: can't use this without having 2 or more member memberships
        # listset = self.filterEndpoint(user.memberships, member=True)
        typepad.client.complete_batch()

        # self.assertValidFilter(listset)

        # memberships = listset[0]
        self.assert_(group_id in [x.source.xid for x in memberships])

    @attr(user='group')
    def test_1_GET_users_id_notifications(self):
        """GET /users/<id>/notifications.json (group)
        
        Tests the endpoint for gathering a user's notifications.
        """

        self.assert_(len(self.testdata['assets']) >= 2,
            'Must have 2 or more assets to test')

        admin_id = self.testdata['admin']['xid']
        asset_id = self.testdata['assets'][1]

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(admin_id)
        listset = self.filterEndpoint(user.notifications)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        inbox = listset[0]
        for event in inbox:
            self.assertValidEvent(event)

        self.assert_(asset_id in [x.object.url_id for x in inbox if x.object])

    @attr(user='group')
    def test_1_GET_users_id_relationships(self):
        """GET /users/<id>/relationships.json (group)

        Tests the endpoint for selecting all of a user's relationships.
        """

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.relationships)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        contacts = listset[0]
        for contact in contacts:
            self.assertValidRelationship(contact)

        self.assert_(member_id in [x.source.xid for x in contacts])

    @attr(user='group')
    def test_1_GET_users_id_relationships_by_group_id(self):
        """GET /users/<id>/relationships/@by-group/<id>.json (group)

        Selects user relationships within a specific group.
        """

        member_id = self.testdata['member']['xid']
        admin_id = self.testdata['admin']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.relationships, by_group=group_id)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        contacts = listset[0]
        for contact in contacts:
            self.assertValidRelationship(contact)

        self.assert_(member_id in [x.source.xid for x in contacts])

    @attr(user='group')
    def test_1_GET_users_id_relationships_follower(self):
        """GET /users/<id>/relationships/@follower.json (group)

        Tests the endpoint for selecting the user's followers.
        """

        member_id = self.testdata['member']['xid']
        admin_id = self.testdata['admin']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.relationships, follower=True)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        contacts = listset[0]
        for contact in contacts:
            self.assertValidRelationship(contact)

        self.assert_(member_id in [x.source.xid for x in contacts])
        self.assert_(admin_id in [x.target.xid for x in contacts])

    @attr(user='group')
    def test_1_GET_users_id_relationships_follower_by_group_id(self):
        """GET /users/<id>/relationships/@follower/@by-group/<id>.json (group)

        Tests the endpoint for selecting the user's followers within a group.
        """

        member_id = self.testdata['member']['xid']
        admin_id = self.testdata['admin']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.relationships,
            follower=True, by_group=group_id)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        contacts = listset[0]
        for contact in contacts:
            self.assertValidRelationship(contact)

        self.assert_(member_id in [x.source.xid for x in contacts])
        self.assert_(admin_id in [x.target.xid for x in contacts])

    @attr(user='group')
    def test_1_GET_users_id_relationships_following(self):
        """GET /users/<id>/relationships/@following.json (group)
        
        Tests selection of a user's global following list.
        """

        member_id = self.testdata['member']['xid']
        admin_id = self.testdata['admin']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.relationships, following=True)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        contacts = listset[0]
        for contact in contacts:
            self.assertValidRelationship(contact)

        self.assert_(member_id in [x.source.xid for x in contacts])
        self.assert_(admin_id in [x.target.xid for x in contacts])

    @attr(user='group')
    def test_1_GET_users_id_relationships_following_by_group_id(self):
        """GET /users/<id>/relationships/@following/@by-group/<id>.json (group)
        
        Tests selection of a user's following list within a group.
        """

        member_id = self.testdata['member']['xid']
        admin_id = self.testdata['admin']['xid']
        group_id = self.testdata['group']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_by_url_id(member_id)
        listset = self.filterEndpoint(user.relationships, following=True,
            by_group=group_id)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertValidFilter(listset)

        contacts = listset[0]
        for contact in contacts:
            self.assertValidRelationship(contact)

        self.assert_(member_id in [x.source.xid for x in contacts])
        self.assert_(admin_id in [x.target.xid for x in contacts])

    @attr(user='member')
    def test_1_GET_users_self__by_member(self):
        """GET /users/@self (member)
        """

        member_id = self.testdata['member']['xid']

        typepad.client.batch_request()
        user = typepad.User.get_self()
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertEquals(user.xid, member_id)

    @attr(user='group')
    def test_1_GET_users_id__using_id(self):
        """GET /users/id.json (group)
        """

        member_id = self.testdata['member']['xid']
        uri = "tag:api.typepad.com,2009:%s" % member_id

        typepad.client.batch_request()
        user = typepad.User.get_by_id(uri)
        typepad.client.complete_batch()

        self.assertValidUser(user)
        self.assertEquals(user.xid, member_id)

    @attr(user='group')
    def test_1_GET_assets_id__using_id(self):
        """GET /assets/id.json (group)
        """

        asset_id = self.testdata['assets'][1]
        uri = "tag:api.typepad.com,2009:%s" % asset_id

        typepad.client.batch_request()
        asset = typepad.Asset.get_by_id(uri)
        typepad.client.complete_batch()

        self.assertValidAsset(asset)
        self.assertEquals(asset.xid, asset_id)

    @attr(user='group')
    def test_1_GET_groups_id__using_id(self):
        """GET /groups/id.json (group)
        """

        group_id = self.testdata['group']['xid']
        uri = "tag:api.typepad.com,2009:%s" % group_id

        typepad.client.batch_request()
        group = typepad.Group.get_by_id(uri)
        typepad.client.complete_batch()

        self.assertValidGroup(group)
        self.assertEquals(group.xid, group_id)

    ### Supporting functions for this test suite

    def setUp(self):
        """Configures the test class prior to each test method.
        """

        if not os.getenv('TEST_TYPEPAD'):
            raise nose.SkipTest('no TypePad tests without TEST_TYPEPAD=1')
        if not os.getenv('TEST_TYPEPAD_JSON'):
            raise nose.SkipTest('no TypePad tests without TEST_TYPEPAD_JSON')

        global testdata
        if 'configuration' not in testdata:
            raise nose.SkipTest('cannot run tests without configuration in test data')

        self.testdata = testdata

        if not len(self.testdata['assets']):
            self.load_test_assets()

    @attr(user='group')
    def load_test_assets(self):
        """Fetches the event stream for the group and populates the testdata
        dictionary with the assets found."""

        typepad.client.batch_request()
        group = typepad.Group.get_by_url_id(self.testdata['group']['xid'])
        events = group.events.filter()
        typepad.client.complete_batch()

        self.testdata['assets'] = []
        for event in events:
            # FIXME: https://intranet.sixapart.com/bugs/default.asp?88008
            if event.object and len(event.object.groups) > 0:
                self.testdata['assets'].append(event.object.xid)

        self.clear_credentials()

    def credentials_for(self, ident):
        if ident not in self.testdata:
            raise nose.SkipTest('no credentials for %s tests' % ident)
        consumer = oauth.OAuthConsumer(
            self.testdata['configuration']['oauth_consumer_key'],
            self.testdata['configuration']['oauth_consumer_secret'],
        )
        token = oauth.OAuthToken(
            self.testdata[ident]['oauth_key'],
            self.testdata[ident]['oauth_secret'],
        )
        backend = urlparse(self.testdata['configuration']['backend_url'])
        typepad.client.clear_credentials()
        typepad.client.add_credentials(consumer, token, domain=backend[1])

    def clear_credentials(self):
        typepad.client.clear_credentials()

    def assertValidAsset(self, asset):
        """Checks given asset for properties that should be present on all assets.
        """

        self.assert_(isinstance(asset, typepad.Asset),
            'object %r is not a typepad.Asset' % asset)
        self.assert_(asset.author)
        self.assert_(asset.actor)
        self.assertValidUser(asset.author)
        # asset.content is not required for some asset types
        # self.assert_(asset.content)
        self.assert_(asset.text_format)
        self.assert_(asset.text_format in ('text', 'html'))
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?88008
        # self.assert_(len(asset.groups) > 0)
        self.assert_(asset.id)
        self.assert_(asset.url_id)
        self.assert_(len(asset.object_types) > 0)
        object_type = asset.primary_object_type()
        self.assert_(object_type)
        self.assert_(asset.published)
        self.assert_(len(asset.links) > 0)
        self.assert_('self' in asset.links)
        self.assert_(asset.links['self'].href)
        self.assertEquals(asset.links['self'].type, 'application/json')
        self.assert_('favorites' in asset.links)
        self.assert_(asset.links['favorites'].href)
        self.assert_(asset.links['favorites'].type, 'application/json')
        self.assert_(asset.links['favorites'].total >= 0)
        self.assertEquals(asset.links['favorites'].total, asset.favorite_count())
        self.assert_('replies' in asset.links)
        self.assert_(asset.links['replies'].href)
        self.assert_(asset.links['replies'].type, 'application/json')
        self.assert_(asset.links['replies'].total >= 0)
        self.assertEquals(asset.links['replies'].total, asset.comment_count())
        if 'alternate' in asset.links:
            self.assert_('alternate' in asset.links)
            self.assert_(asset.links['alternate'].href)
            self.assertEquals(asset.links['alternate'].type, 'text/html')
        self.assert_(object_type.startswith('tag:api.typepad.com'))
        self.assertValidAssetRef(asset.asset_ref)
        if object_type == 'tag:api.typepad.com,2009:Link':
            # additional properties we expect for link assets
            self.assert_('target' in asset.links)
            self.assert_(asset.links['target'].href)
        elif object_type == 'tag:api.typepad.com,2009:Photo':
            # additional properties we expect for photo assets
            self.assert_('enclosure' in asset.links)
            self.assert_(asset.links['enclosure'].href)
            self.assert_(asset.links['enclosure'].height)
            self.assert_(asset.links['enclosure'].width)
            self.assert_(asset.links['enclosure'].type.startswith('image/'))
            self.assert_('preview' in asset.links)
            self.assert_(asset.links['preview'].href)
            self.assert_(asset.links['preview'].height)
            self.assert_(asset.links['preview'].width)
            self.assert_(asset.links['preview'].type.startswith('image/'))
        elif object_type == 'tag:api.typepad.com,2009:Audio':
            self.assert_('enclosure' in asset.links)
            self.assert_(asset.links['enclosure'].href)
            self.assert_(asset.links['enclosure'].type.startswith('audio/'))
        elif object_type == 'tag:api.typepad.com,2009:Post':
            pass
        elif object_type == 'tag:api.typepad.com,2009:Comment':
            # FIXME: we have a data problem for one of our comments; parent object was deleted but the comment remained
            if len(asset.groups) > 0:
                self.assert_(asset.in_reply_to)
                self.assertValidAssetRef(asset.in_reply_to)
        elif object_type == 'tag:api.typepad.com,2009:Video':
            self.assert_('enclosure' in asset.links)
            self.assert_(asset.links['enclosure'].html)
            self.assert_(asset.links['enclosure'].height)
            self.assert_(asset.links['enclosure'].width)
            # self.assertEquals(asset.links['enclosure'].type, 'text/html')
        else:
            self.fail('asset has an unexpected objectType: %s' % \
                object_type)
        if asset.source:
            self.assert_(asset.source.links)
            self.assert_(asset.source.original_link)
            self.assert_('alternate' in asset.source.links)
            self.assert_(asset.source.links['alternate'].href)
            self.assertEquals(asset.source.links['alternate'].type,
                'text/html')
            self.assert_(asset.source.provider)

            self.assert_(asset.source.provider.icon)
            self.assert_(asset.source.provider.name)
            self.assert_(asset.source.provider.uri)

    def assertValidUser(self, user):
        """Checks given asset for properties that should be present on all assets.
        """

        self.assert_(isinstance(user, typepad.User),
            'object %r is not a typepad.User' % user)
        self.assert_(user.id)
        self.assert_(user.url_id)
        self.assert_(len(user.object_types) > 0)
        self.assertEquals(user.object_types[0],
            'tag:api.typepad.com,2009:User')
        # this asserts as false when the user's interests is empty
        # self.assert_(user.interests)

        self.assert_(len(user.links) > 0)

        self.assert_('self' in user.links)
        self.assert_(user.links['self'].href)
        self.assertEquals(user.links['self'].type, 'application/json')

        self.assert_('elsewhere-accounts' in user.links)
        self.assert_(user.links['elsewhere-accounts'].href)
        self.assertEquals(user.links['elsewhere-accounts'].type,
            'application/json')

        self.assert_(user.links['follow-frame-content'].href)
        self.assert_(user.links['follow-frame-content'].height)
        self.assert_(user.links['follow-frame-content'].width)
        self.assertEquals(user.links['follow-frame-content'].type,
            'text/html')

        self.assert_('alternate' in user.links)
        self.assert_(user.links['alternate'].href)
        self.assertEquals(user.links['alternate'].type, 'text/html')

        # this link is available when a user is accessing their own
        # user object
        if 'membership-management-page' in user.links:
            self.assert_(user.links['membership-management-page'].href)
            self.assertEquals(user.links['membership-management-page'].type, 'text/html')

        # this link is available when a user is accessing their own
        # user object
        if 'profile-edit-page' in user.links:
            self.assert_(user.links['profile-edit-page'].href)
            self.assertEquals(user.links['profile-edit-page'].type, 'text/html')

        self.assert_('avatar' in user.links)
        self.assert_(user.links['avatar'].href)
        self.assert_(user.links['avatar'].height)
        self.assert_(user.links['avatar'].width)

    def assertValidEvent(self, event):
        """Checks given asset for properties that should be present on all assets."""

        self.assert_(isinstance(event, typepad.Event),
            'object %r is not a typepad.Event' % event)
        self.assert_(event.id)
        self.assert_(event.xid)
        self.assert_(event.url_id)
        self.assert_(event.published)
        self.assert_(len(event.links) > 0)
        self.assert_('self' in event.links)
        self.assert_(event.links['self'].href)
        self.assertEquals(event.links['self'].type, 'application/json')
        self.assert_(len(event.verbs) > 0)
        self.assert_(event.verbs[0].startswith('tag:api.typepad.com,2009:'))
        self.assert_(event.actor)
        self.assertValidUser(event.actor)
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87911
        # self.assert_(event.object)
        # self.assertValidAsset(event.object)
        if event.object is not None:
            self.assertValidAsset(event.object)

    def assertValidGroup(self, group):
        """Checks given asset for properties that should be present on all assets.
        """

        self.assert_(isinstance(group, typepad.Group),
            'object %r is not a typepad.Group' % group)
        self.assert_(group.id)
        self.assert_(group.url_id)
        self.assert_(group.display_name)
        self.assert_(len(group.links) > 0)
        self.assert_('self' in group.links)
        self.assert_(group.links['self'].href)
        self.assertEquals(group.links['self'].type, 'application/json')
        self.assert_(len(group.object_types) > 0)
        self.assertEquals(group.object_types[0],
            'tag:api.typepad.com,2009:Group')

    def assertValidApplication(self, app):
        self.assert_(isinstance(app, typepad.Application),
            'object %r is not a typepad.Application' % app)
        self.assert_(app.links)
        links = ('oauth-request-token-endpoint', 'oauth-authorization-page',
            'oauth-identification-page', 'signout-page',
            'session-sync-script', 'oauth-access-token-endpoint',
            'user-flyouts-script', 'self')
        for link in links:
            self.assert_(link in app.links, 'no %s link present' % link)
            self.assert_(app.links[link].href, 'no href on %s link' % link)
            if link.endswith('-script'):
                self.assertEquals(app.links[link].type, 'text/javascript',
                    'type %s is invalid for %s link' % \
                    (app.links[link].type, link))
            elif link.endswith('-page'):
                self.assertEquals(app.links[link].type, 'text/html',
                    'type %s is invalid for %s link' % \
                    (app.links[link].type, link))
        self.assert_(app.oauth_request_token)
        self.assert_(app.oauth_authorization_page)
        self.assert_(app.oauth_access_token_endpoint)
        self.assert_(app.session_sync_script)
        self.assert_(app.oauth_identification_page)
        self.assert_(app.signout_page)
        self.assert_(app.user_flyouts_script)
        self.assert_(app.browser_upload_endpoint)
        self.assertEquals(app.links['self'].type, 'application/json')
        self.assert_(app.owner)
        self.assertValidGroup(app.owner)

    def assertValidFavorite(self, fav):
        self.assert_(isinstance(fav, typepad.Favorite),
            'object %r is not a typepad.Favorite' % fav)
        self.assert_(fav.id)
        self.assert_(fav.url_id)
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87913
        # self.assert_(fav.published)
        self.assertValidUser(fav.author)
        self.assertValidAssetRef(fav.in_reply_to)

    def assertValidRelationshipStatus(self, rel):
        self.assert_(isinstance(rel, typepad.RelationshipStatus),
            'object %r is not a typepad.Relationship' % rel)
        self.assert_(rel.types)
        self.assert_(len(rel.types) > 0)
        for type_ in rel.types:
            self.assert_(type_ in (
                'tag:api.typepad.com,2009:Contact',
                'tag:api.typepad.com,2009:Admin',
                'tag:api.typepad.com,2009:Blocked',
                'tag:api.typepad.com,2009:Member'),
                "type '%s' is unrecognized" % type_
            )

    def assertValidRelationship(self, rel):
        self.assert_(isinstance(rel, typepad.Relationship),
            'object %r is not a typepad.Relationship' % rel)
        self.assert_(rel.links)
        self.assert_('self' in rel.links)
        self.assert_(rel.links['self'].href)
        self.assertEquals(rel.links['self'].type, 'application/json')
        self.assert_(rel.status)
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87929
        # Most user-to-user relationships have created and status.types,
        # but there are some odd cases that don't.
        if isinstance(rel.source, typepad.Group) or \
            isinstance(rel.target, typepad.Group):
            self.assert_(rel.created)
            self.assert_(len(rel.status.types) > 0)
            self.assert_(rel.status.types[0] in rel.created)
        self.assert_(rel.source)
        if rel.source.object_types[0] == 'tag:api.typepad.com,2009:Group':
            self.assertValidGroup(rel.source)
        elif rel.source.object_types[0] == 'tag:api.typepad.com,2009:User':
            self.assertValidUser(rel.source)
        else:
            self.fail('unexpected object type %s for relationship source' % \
                rel.source.object_types[0])
        self.assert_(rel.target)
        if rel.target.object_types[0] == 'tag:api.typepad.com,2009:Group':
            self.assertValidGroup(rel.target)
        elif rel.target.object_types[0] == 'tag:api.typepad.com,2009:User':
            self.assertValidUser(rel.target)
        else:
            self.fail('unexpected object type %s for relationship target' % \
                rel.target.object_types[0])

    def assertValidAssetRef(self, ref):
        self.assert_(ref.url_id)
        self.assert_(isinstance(ref, typepad.AssetRef),
            'object %r is not a typepad.AssetRef' % ref)
        # FIXME: https://intranet.sixapart.com/bugs/default.asp?87953
        # self.assert_(ref.href)
        # self.assertEquals(ref.type, 'application/json')
        self.assertValidUser(ref.author)
        self.assert_(ref.object_types)
        self.assert_(len(ref.object_types) > 0)
        self.assert_(ref.object_types[0].startswith('tag:api.typepad.com'))

    def filterEndpoint(self, endpoint, *args, **kwargs):
        full = endpoint.filter(**kwargs)
        slice1 = endpoint.filter(start_index=2, **kwargs)
        slice2 = endpoint.filter(max_results=1, **kwargs)
        slice3 = endpoint.filter(start_index=2, max_results=1, **kwargs)
        slice4 = endpoint.filter(max_results=0, **kwargs)
        return (full, slice1, slice2, slice3, slice4)

    def assertValidFilter(self, listset):
        (full, slice1, slice2, slice3, slice4) = listset
        self.assert_(isinstance(full, typepad.ListObject),
            'object %r is not a typepad.ListObject' % full)
        # api result set should never exceed 50 entries
        self.assert_(len(full.entries) <= 50)
        # regardless of start-index/max-results parameters, the total-results
        # parameter should be the same as the full selection
        self.assert_(full.total_results > 1,
            'list must have more than 1 item to test start-index query parameter')
        if full.total_results < 50:
            self.assertEquals(len(slice1.entries), slice1.total_results - 1)
        # lets not require this for now
        # self.assert_(full.total_results < 50, 'list must have fewer than 50 items to test properly')
        self.assertEquals(len(slice2.entries), 1)
        self.assertEquals(len(slice3.entries), 1)
        self.assertEquals(len(slice4.entries), 0)
        self.assertEquals(full.total_results, slice1.total_results)
        self.assertEquals(full.total_results, slice2.total_results)
        self.assertEquals(full.total_results, slice3.total_results)
        self.assertEquals(full.total_results, slice4.total_results)

    def assertForbidden(self, *args, **kwargs):
        self.assertRaises(HttpObject.Forbidden, *args, **kwargs)

    def assertUnauthorized(self, *args, **kwargs):
        self.assertRaises(HttpObject.Unauthorized, *args, **kwargs)

    def assertNotFound(self, *args, **kwargs):
        self.assertRaises(HttpObject.NotFound, *args, **kwargs)

    def post_asset(self):
        """Creates a Post asset instance for testing purposes."""

        post = typepad.Post()
        post.title = ''
        post.content = 'Test text post'

        return post

    def video_asset(self):
        """Creates a Video asset instance for testing purposes."""

        video = typepad.Video()

        rel = typepad.Link()
        rel.href = 'http://www.youtube.com/watch?v=pWdZTqHtJ3U'
        rel.rel = 'enclosure'
        video.title = ''
        video.links = typepad.LinkSet()
        video.links.add(rel)
        video.content = 'Test video post'

        return video

    def link_asset(self):
        """Creates a Link asset instance for testing purposes."""

        link = typepad.LinkAsset()
        rel = typepad.Link()
        rel.href = 'http://www.typepad.com/'
        rel.rel = 'target'
        link.title = ''
        link.links = typepad.LinkSet()
        link.links.add(rel)
        link.content = 'Test link post'

        return link

if __name__ == '__main__':
    utils.log()
    unittest.main()
