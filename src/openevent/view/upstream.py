"""Read-only SDK stub calls with a deadline supplied by each HTTP query."""

from openevent.sdk.proto import openevent_pb2


class HistoryClient:
    def __init__(self, client):
        # The SDK client owns its channel; View only uses its public stubs.
        self._client = client

    def get_status(self, principal, token, *, timeout):
        return self._client.event_stub.GetStatus(
            openevent_pb2.GetStatusRequest(principal=principal, token=token),
            timeout=timeout,
        )

    def get_channel(self, principal, token, channel_id, *, timeout):
        return self._client.channel_stub.GetChannel(
            openevent_pb2.GetChannelRequest(
                principal=principal, token=token, channel_id=channel_id,
            ),
            timeout=timeout,
        )

    def fetch(self, principal, token, from_seq, limit, only_my_recipient=False, channels=(), *, timeout):
        return self._client.event_stub.Fetch(
            openevent_pb2.FetchRequest(
                principal=principal, token=token, from_seq=from_seq, limit=limit,
                only_my_recipient=only_my_recipient, channels=list(channels),
            ),
            timeout=timeout,
        )
