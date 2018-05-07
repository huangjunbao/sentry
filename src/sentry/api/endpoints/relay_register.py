from __future__ import absolute_import

import six

from rest_framework import serializers, status
from rest_framework.response import Response

from django.core.cache import cache as default_cache
from django.utils import timezone

from sentry.utils import json
from sentry.api.base import Endpoint
from sentry.api.serializers import serialize
from sentry.models import Relay
from sentry.relay.utils import get_header_relay_id, get_header_relay_signature


from smith import create_register_challenge, validate_register_response, \
    get_register_response_relay_id, PublicKey


class RelaySerializer(serializers.Serializer):
    relay_id = serializers.CharField(max_length=64, required=True)
    public_key = serializers.CharField(max_length=64, required=True)


class RelayRegisterChallengeEndpoint(Endpoint):
    authentication_classes = ()
    permission_classes = ()

    def post(self, request):
        """
        Requests to Register a Relay
        ````````````````````````````

        Registers the relay with the sentry installation.  If a relay boots
        it will always attempt to invoke this endpoint.
        """
        try:
            json_data = json.loads(request.body)
        except ValueError:
            return Response({
                'detail': 'No valid json body',
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = RelaySerializer(data=json_data, partial=True)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        sig = get_header_relay_signature(request)
        if not sig:
            return Response({
                'detail': 'Missing relay signature',
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            challenge = create_register_challenge(request.body, sig)
        except Exception as exc:
            return Response({
                'detail': str(exc).splitlines()[0],
            }, status=status.HTTP_400_BAD_REQUEST)

        relay_id = six.text_type(challenge['relay_id'])
        if relay_id != get_header_relay_id(request):
            return Response({
                'detail': 'relay_id in payload did not match header',
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            relay = Relay.objects.get(relay_id=relay_id)
        except Relay.DoesNotExist:
            pass
        else:
            if relay.public_key != six.text_type(challenge['public_key']):
                return Response({
                    'detail': 'Attempted to register agent with a different public key',
                }, status=status.HTTP_400_BAD_REQUEST)

        default_cache.set('relay-auth:%s' % relay_id, {
            'token': challenge['token'],
            'public_key': six.text_type(challenge['public_key']),
        }, 60)
        return Response(serialize({
            'relay_id': six.text_type(challenge['relay_id']),
            'token': challenge['token'],
        }))


class RelayRegisterResponseEndpoint(Endpoint):
    authentication_classes = ()
    permission_classes = ()

    def post(self, request):
        """
        Registers a Relay
        `````````````````

        Registers the relay with the sentry installation.  If a relay boots
        it will always attempt to invoke this endpoint.
        """

        sig = sig = get_header_relay_signature(request)
        if not sig:
            return Response({
                'detail': 'Missing relay signature',
            }, status=status.HTTP_400_BAD_REQUEST)

        relay_id = six.text_type(get_register_response_relay_id(request.body))
        if relay_id != get_header_relay_id(request):
            return Response({
                'detail': 'relay_id in payload did not match header',
            }, status=status.HTTP_400_BAD_REQUEST)

        params = default_cache.get('relay-auth:%s' % relay_id)
        if params is None:
            return Response({
                'detail': 'Challenge expired'
            }, status=401)

        key = PublicKey.parse(params['public_key'])
        data = validate_register_response(key, request.body, sig)
        if data['token'] != params['token']:
            return Response({
                'detail': 'Token mismatch'
            }, status=401)

        try:
            relay = Relay.objects.get(relay_id=relay_id)
        except Relay.DoesNotExist:
            relay = Relay.objects.create(
                relay_id=relay_id,
                public_key=params['public_key'],
            )
        else:
            if relay.public_key != params['public_key']:
                return Response({
                    'detail': 'Attempted to register agent with a different public key',
                }, status=status.HTTP_400_BAD_REQUEST)
            relay.last_seen = timezone.now()
            relay.save()
        default_cache.delete('relay-auth:%s' % relay_id)

        return Response(serialize({
            'relay_id': relay.relay_id,
        }))
