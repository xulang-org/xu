# Bounded MQTT 3.1.1 client

`#embedded/mqtt` is a pure Xu, transport-independent client. `create` or
`reset` configures an ASCII client ID, one subscription and a retained QoS1
last-will topic. The will payload is `0`; applications can publish a richer
online status on that topic after `ready()` becomes true.

Call `poll(now_ms)` only when the transport can accept the returned bytes.
It emits CONNECT, SUBSCRIBE, publications, PUBACKs and keepalive traffic.
Pass received TCP stream chunks to `feed(&bytes,now_ms)` and drain `read()`.
The codec accepts fragmented and concatenated packets, including retained
publications arriving before SUBACK. A transport reconnect needs `reset`
and a fresh subscription. Time is milliseconds modulo 2^31.

The profile uses clean sessions, QoS0/1 inbound publications, QoS1 outgoing
publications, a 20-second keepalive and bounded retries. PUBACK confirms MQTT
receipt, not completion of an application operation. Packet size is at most
2048 bytes, publication payloads at most 768 bytes, with four incoming
messages and eight queued outgoing publications. Duplicate QoS1 packet IDs
with DUP set are suppressed within a sixteen-entry receive window. Consume
messages regularly; malformed packets, unsupported QoS2 or exhausted queues
fail the session. Inspect `failed()` and `error` before reconnecting.

Topics and client IDs use this profile's printable ASCII subset. CONNECT
username/password authentication, TLS, persistent sessions and MQTT 5 are
outside this client. The ESP32 demo explicitly selects a local test broker.
It supplies operation IDs and result caching above MQTT for command retries.

RETAIN describes a stored snapshot delivered to a new subscription. A broker
clears this flag when forwarding a new publication to an existing subscription,
even if the publisher requested storage. A command sender must use
`retain=false`; rejecting retained deliveries prevents replay on subscription
recovery, not execution of a publisher's live message.

The packet and state contracts follow the
[OASIS MQTT 3.1.1 specification](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).
The host acceptance harness also exchanges real packets with Mosquitto.
