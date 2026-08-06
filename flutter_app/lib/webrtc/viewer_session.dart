import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import '../signaling/signaling_client.dart';

enum ViewerStatus {
  disconnected,
  connecting,
  waitingForOffer,
  negotiating,
  connected,
  reconnecting,
  error,
}

class ViewerStats {
  const ViewerStats({
    this.fps = 0,
    this.latencyMs,
    this.bitrateKbps,
  });

  final double fps;
  final int? latencyMs;
  final double? bitrateKbps;
}

/// WebRTC answerer that displays the desktop screen track.
class ViewerSession extends ChangeNotifier {
  ViewerSession({required this.signalingUrl});

  final String signalingUrl;

  final RTCVideoRenderer remoteRenderer = RTCVideoRenderer();

  SignalingClient? _signaling;
  RTCPeerConnection? _pc;
  Timer? _reconnectTimer;
  Timer? _statsTimer;
  Timer? _rttTimer;

  ViewerStatus status = ViewerStatus.disconnected;
  String? lastError;
  ViewerStats stats = const ViewerStats();
  bool _disposed = false;
  bool _autoReconnect = true;
  int _reconnectAttempt = 0;

  int _frames = 0;
  int _lastBytes = 0;
  DateTime _lastStatsAt = DateTime.now();

  Future<void> init() async {
    await remoteRenderer.initialize();
  }

  Future<void> connect({bool autoReconnect = true}) async {
    _autoReconnect = autoReconnect;
    _reconnectTimer?.cancel();
    _setStatus(ViewerStatus.connecting);
    lastError = null;
    notifyListeners();

    try {
      await _teardownPeer();
      final signaling = SignalingClient(url: signalingUrl);
      signaling.addListener(_onSignal);
      await signaling.connect();
      _signaling = signaling;
      _setStatus(ViewerStatus.waitingForOffer);
      _reconnectAttempt = 0;
      _startStatsLoop();
      _startRttProbe();
    } catch (e) {
      lastError = '$e';
      _setStatus(ViewerStatus.error);
      _scheduleReconnect();
    }
  }

  Future<void> disconnect({bool reconnect = false}) async {
    if (!reconnect) {
      _autoReconnect = false;
      _reconnectTimer?.cancel();
    }
    _statsTimer?.cancel();
    _rttTimer?.cancel();
    await _teardownPeer();
    final signaling = _signaling;
    _signaling = null;
    if (signaling != null) {
      signaling.removeListener(_onSignal);
      await signaling.disconnect();
    }
    stats = const ViewerStats();
    if (!reconnect) {
      _setStatus(ViewerStatus.disconnected);
    }
  }

  Future<void> _teardownPeer() async {
    final pc = _pc;
    _pc = null;
    if (pc != null) {
      await pc.close();
    }
    remoteRenderer.srcObject = null;
  }

  void _onSignal(Map<String, dynamic> message) {
    final type = message['type'];
    switch (type) {
      case 'ready':
        _setStatus(ViewerStatus.waitingForOffer);
        break;
      case 'offer':
        unawaited(_handleOffer(message['sdp'] as String));
        break;
      case 'ice':
        unawaited(_handleRemoteIce(message));
        break;
      case 'stats':
        _handleStatsEcho(message);
        break;
      case 'bye':
        lastError = 'Host disconnected';
        _setStatus(ViewerStatus.reconnecting);
        unawaited(disconnect(reconnect: true).then((_) => _scheduleReconnect()));
        break;
      case 'error':
        lastError = message['message']?.toString() ?? 'Signaling error';
        _setStatus(ViewerStatus.error);
        if (message['code'] == 'viewer_busy') {
          _autoReconnect = false;
        } else {
          _scheduleReconnect();
        }
        break;
    }
  }

  Future<void> _handleOffer(String sdp) async {
    try {
      _setStatus(ViewerStatus.negotiating);
      await _teardownPeer();

      final pc = await createPeerConnection({
        'iceServers': <Map<String, dynamic>>[],
        'sdpSemantics': 'unified-plan',
      });
      _pc = pc;

      pc.onTrack = (RTCTrackEvent event) {
        if (event.streams.isNotEmpty) {
          remoteRenderer.srcObject = event.streams.first;
        }
        notifyListeners();
      };

      pc.onIceCandidate = (RTCIceCandidate? candidate) {
        if (candidate == null) {
          _signaling?.send({
            'type': 'ice',
            'candidate': null,
            'sdpMid': null,
            'sdpMLineIndex': null,
          });
          return;
        }
        _signaling?.send({
          'type': 'ice',
          'candidate': candidate.candidate,
          'sdpMid': candidate.sdpMid,
          'sdpMLineIndex': candidate.sdpMLineIndex,
        });
      };

      pc.onConnectionState = (RTCPeerConnectionState state) {
        if (state == RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          _setStatus(ViewerStatus.connected);
        } else if (state ==
                RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
            state ==
                RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
          _setStatus(ViewerStatus.reconnecting);
          unawaited(
            disconnect(reconnect: true).then((_) => _scheduleReconnect()),
          );
        }
      };

      await pc.setRemoteDescription(RTCSessionDescription(sdp, 'offer'));
      final answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      _signaling?.send({'type': 'answer', 'sdp': answer.sdp});
    } catch (e) {
      lastError = 'Failed to answer offer: $e';
      _setStatus(ViewerStatus.error);
      _scheduleReconnect();
    }
  }

  Future<void> _handleRemoteIce(Map<String, dynamic> message) async {
    final pc = _pc;
    final candidate = message['candidate'];
    if (pc == null || candidate == null) return;
    try {
      final midIndex = message['sdpMLineIndex'];
      final mLineIndex = midIndex is int
          ? midIndex
          : midIndex is num
              ? midIndex.toInt()
              : null;
      await pc.addCandidate(
        RTCIceCandidate(
          candidate as String,
          message['sdpMid'] as String?,
          mLineIndex,
        ),
      );
    } catch (e) {
      debugPrint('ICE add failed: $e');
    }
  }

  void _handleStatsEcho(Map<String, dynamic> message) {
    final tClient = message['t_client'];
    if (tClient is int) {
      final rtt = DateTime.now().millisecondsSinceEpoch - tClient;
      stats = ViewerStats(
        fps: stats.fps,
        latencyMs: rtt > 0 ? rtt ~/ 2 : rtt,
        bitrateKbps: stats.bitrateKbps,
      );
      notifyListeners();
    }
  }

  void _startRttProbe() {
    _rttTimer?.cancel();
    _rttTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      _signaling?.send({
        'type': 'stats',
        't_client': DateTime.now().millisecondsSinceEpoch,
      });
    });
  }

  void _startStatsLoop() {
    _statsTimer?.cancel();
    _lastStatsAt = DateTime.now();
    _lastBytes = 0;
    _frames = 0;
    _statsTimer = Timer.periodic(const Duration(seconds: 1), (_) async {
      final pc = _pc;
      if (pc == null) return;
      try {
        final reports = await pc.getStats();
        var bytes = 0;
        var frames = 0;
        for (final report in reports) {
          final values = report.values;
          final isInbound = report.type == 'inbound-rtp';
          final kind = values['kind']?.toString();
          if (isInbound && kind == 'video') {
            bytes = (values['bytesReceived'] as num?)?.toInt() ?? bytes;
            frames = (values['framesDecoded'] as num?)?.toInt() ??
                (values['framesReceived'] as num?)?.toInt() ??
                frames;
          }
        }
        final now = DateTime.now();
        final dt = now.difference(_lastStatsAt).inMilliseconds / 1000.0;
        if (dt > 0) {
          final fps = (frames - _frames) / dt;
          final kbps = ((bytes - _lastBytes) * 8 / dt) / 1000.0;
          stats = ViewerStats(
            fps: fps.clamp(0, 120),
            latencyMs: stats.latencyMs,
            bitrateKbps: kbps < 0 ? 0 : kbps,
          );
          notifyListeners();
        }
        _frames = frames;
        _lastBytes = bytes;
        _lastStatsAt = now;
      } catch (_) {
        // Stats are best-effort.
      }
    });
  }

  void _scheduleReconnect() {
    if (!_autoReconnect || _disposed) return;
    _reconnectTimer?.cancel();
    final delayMs = (500 * (1 << _reconnectAttempt.clamp(0, 4))).clamp(500, 8000);
    _reconnectAttempt++;
    _setStatus(ViewerStatus.reconnecting);
    _reconnectTimer = Timer(Duration(milliseconds: delayMs), () {
      unawaited(connect(autoReconnect: true));
    });
  }

  void _setStatus(ViewerStatus next) {
    status = next;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _autoReconnect = false;
    _reconnectTimer?.cancel();
    _statsTimer?.cancel();
    _rttTimer?.cancel();
    unawaited(disconnect());
    remoteRenderer.dispose();
    super.dispose();
  }
}
