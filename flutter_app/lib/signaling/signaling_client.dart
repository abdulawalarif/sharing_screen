import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/status.dart' as ws_status;
import 'package:web_socket_channel/web_socket_channel.dart';

typedef SignalHandler = void Function(Map<String, dynamic> message);

/// WebSocket signaling client (viewer role).
class SignalingClient {
  SignalingClient({required this.url});

  final String url;

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  final List<SignalHandler> _listeners = <SignalHandler>[];
  bool _helloSent = false;

  bool get isConnected => _channel != null && _helloSent;

  void addListener(SignalHandler handler) => _listeners.add(handler);

  void removeListener(SignalHandler handler) => _listeners.remove(handler);

  Future<void> connect() async {
    await disconnect();
    final uri = Uri.parse(url);
    _channel = WebSocketChannel.connect(uri);
    await _channel!.ready;
    _sub = _channel!.stream.listen(
      _onData,
      onError: (Object error) {
        _emit({'type': 'error', 'code': 'socket', 'message': '$error'});
      },
      onDone: () {
        _helloSent = false;
        _emit({'type': 'bye', 'reason': 'socket_closed'});
      },
    );
    send({'type': 'hello', 'role': 'viewer'});
    _helloSent = true;
  }

  void send(Map<String, dynamic> message) {
    final ch = _channel;
    if (ch == null) return;
    ch.sink.add(jsonEncode(message));
  }

  Future<void> disconnect() async {
    await _sub?.cancel();
    _sub = null;
    final ch = _channel;
    _channel = null;
    _helloSent = false;
    if (ch != null) {
      await ch.sink.close(ws_status.normalClosure);
    }
  }

  void _onData(dynamic raw) {
    try {
      final decoded = jsonDecode(raw as String);
      if (decoded is Map<String, dynamic>) {
        _emit(decoded);
      } else if (decoded is Map) {
        _emit(Map<String, dynamic>.from(decoded));
      }
    } catch (_) {
      _emit({
        'type': 'error',
        'code': 'invalid',
        'message': 'Bad signaling payload',
      });
    }
  }

  void _emit(Map<String, dynamic> message) {
    for (final handler in List<SignalHandler>.from(_listeners)) {
      handler(message);
    }
  }
}
