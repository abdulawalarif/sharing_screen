import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import '../webrtc/viewer_session.dart';
import 'stats_overlay.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _hostController = TextEditingController(text: '192.168.1.1');
  final _portController = TextEditingController(text: '8080');
  bool _useAdb = false;
  ViewerSession? _session;
  bool _busy = false;

  @override
  void dispose() {
    _session?.dispose();
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  String get _signalingUrl {
    if (_useAdb) {
      return 'ws://127.0.0.1:${_portController.text.trim()}/ws';
    }
    return 'ws://${_hostController.text.trim()}:${_portController.text.trim()}/ws';
  }

  Future<void> _toggleConnect() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final existing = _session;
      if (existing != null &&
          existing.status != ViewerStatus.disconnected &&
          existing.status != ViewerStatus.error) {
        await existing.disconnect();
        existing.dispose();
        setState(() => _session = null);
        return;
      }

      existing?.dispose();
      final session = ViewerSession(signalingUrl: _signalingUrl);
      await session.init();
      session.addListener(_onSessionUpdate);
      setState(() => _session = session);
      await session.connect();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _onSessionUpdate() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final session = _session;
    final connected = session?.status == ViewerStatus.connected;
    final active = session != null &&
        session.status != ViewerStatus.disconnected;

    return Scaffold(
      backgroundColor: const Color(0xFF0E1116),
      body: SafeArea(
        child: connected
            ? _FullscreenViewer(session: session!)
            : _ConnectPanel(
                hostController: _hostController,
                portController: _portController,
                useAdb: _useAdb,
                onAdbChanged: (v) => setState(() => _useAdb = v),
                busy: _busy,
                active: active,
                session: session,
                signalingUrl: _signalingUrl,
                onToggle: _toggleConnect,
              ),
      ),
    );
  }
}

class _ConnectPanel extends StatelessWidget {
  const _ConnectPanel({
    required this.hostController,
    required this.portController,
    required this.useAdb,
    required this.onAdbChanged,
    required this.busy,
    required this.active,
    required this.session,
    required this.signalingUrl,
    required this.onToggle,
  });

  final TextEditingController hostController;
  final TextEditingController portController;
  final bool useAdb;
  final ValueChanged<bool> onAdbChanged;
  final bool busy;
  final bool active;
  final ViewerSession? session;
  final String signalingUrl;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final status = session?.status ?? ViewerStatus.disconnected;
    final statusLabel = switch (status) {
      ViewerStatus.disconnected => 'Disconnected',
      ViewerStatus.connecting => 'Connecting…',
      ViewerStatus.waitingForOffer => 'Waiting for desktop…',
      ViewerStatus.negotiating => 'Negotiating WebRTC…',
      ViewerStatus.connected => 'Connected',
      ViewerStatus.reconnecting => 'Reconnecting…',
      ViewerStatus.error => 'Error',
    };

    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
      children: [
        Text(
          'Screen Share',
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w700,
                letterSpacing: -0.5,
              ),
        ),
        const SizedBox(height: 8),
        Text(
          'Mirror an Ubuntu desktop over WebRTC.',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: Colors.white70,
              ),
        ),
        const SizedBox(height: 28),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('USB via ADB reverse'),
          subtitle: const Text('Signaling → 127.0.0.1 (media still uses Wi‑Fi)'),
          value: useAdb,
          onChanged: onAdbChanged,
        ),
        const SizedBox(height: 8),
        if (!useAdb)
          TextField(
            controller: hostController,
            decoration: const InputDecoration(
              labelText: 'Desktop LAN IP',
              hintText: '192.168.1.10',
              border: OutlineInputBorder(),
            ),
            keyboardType: TextInputType.url,
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9a-fA-F.:]')),
            ],
          ),
        if (!useAdb) const SizedBox(height: 12),
        TextField(
          controller: portController,
          decoration: const InputDecoration(
            labelText: 'Signaling port',
            border: OutlineInputBorder(),
          ),
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
        ),
        const SizedBox(height: 16),
        Text(
          'URL: $signalingUrl',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Colors.white54,
                fontFamily: 'monospace',
              ),
        ),
        const SizedBox(height: 24),
        Row(
          children: [
            _StatusDot(status: status),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                statusLabel,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
          ],
        ),
        if (session?.lastError != null) ...[
          const SizedBox(height: 8),
          Text(
            session!.lastError!,
            style: const TextStyle(color: Color(0xFFFF8A80)),
          ),
        ],
        const SizedBox(height: 28),
        FilledButton(
          onPressed: busy ? null : onToggle,
          style: FilledButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
          ),
          child: Text(active ? 'Disconnect' : 'Connect'),
        ),
        const SizedBox(height: 20),
        Text(
          'Wi‑Fi: phone and desktop on the same network.\n'
          'ADB: run  adb reverse tcp:8080 tcp:8080  on the desktop.',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Colors.white54,
                height: 1.4,
              ),
        ),
      ],
    );
  }
}

class _FullscreenViewer extends StatelessWidget {
  const _FullscreenViewer({required this.session});

  final ViewerSession session;

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        ColoredBox(
          color: Colors.black,
          child: RTCVideoView(
            session.remoteRenderer,
            objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitContain,
          ),
        ),
        Positioned(
          left: 12,
          top: 12,
          child: StatsOverlay(session: session),
        ),
        Positioned(
          right: 12,
          top: 8,
          child: IconButton.filledTonal(
            tooltip: 'Disconnect',
            onPressed: () => session.disconnect(),
            icon: const Icon(Icons.close),
          ),
        ),
      ],
    );
  }
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.status});

  final ViewerStatus status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      ViewerStatus.connected => const Color(0xFF3DDC97),
      ViewerStatus.error => const Color(0xFFFF6B6B),
      ViewerStatus.reconnecting ||
      ViewerStatus.connecting ||
      ViewerStatus.negotiating ||
      ViewerStatus.waitingForOffer =>
        const Color(0xFFFFC857),
      ViewerStatus.disconnected => Colors.white38,
    };
    return Container(
      width: 10,
      height: 10,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    );
  }
}
