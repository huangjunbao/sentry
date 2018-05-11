from __future__ import absolute_import

from rest_framework.response import Response

from sentry.api.base import Endpoint
from sentry.api.authentication import RelayAuthentication
from sentry.relay import change_set, query


class RelayHeartbeatEndpoint(Endpoint):
    authentication_classes = (RelayAuthentication, )

    def post(self, request):
        changesets = request.relay_request_data.get('changesets')
        if changesets:
            change_set.execute_changesets(request.relay, changesets)

        queries = request.relay_request_data.get('queries')
        if queries:
            query_response = query.execute_queries(request.relay, queries)
        else:
            query_response = {}

        return Response({
            'queryResults': query_response,
        }, status=200)
