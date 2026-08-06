import 'package:flutter/material.dart';

import '../webrtc/viewer_session.dart';

class StatsOverlay extends StatelessWidget {
  const StatsOverlay({super.key, required this.session});

  final ViewerSession session;

  @override
  Widget build(BuildContext context) {
    final stats = session.stats;
    final latency = stats.latencyMs;
    final bitrate = stats.bitrateKbps;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: DefaultTextStyle(
          style: const TextStyle(
            color: Colors.white,
            fontSize: 12,
            fontFeatures: [FontFeature.tabularFigures()],
            height: 1.35,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(session.status.name.toUpperCase()),
              Text('FPS  ${stats.fps.toStringAsFixed(1)}'),
              Text(
                latency == null ? 'LAT  —' : 'LAT  $latency ms',
              ),
              Text(
                bitrate == null
                    ? 'BR   —'
                    : 'BR   ${bitrate.toStringAsFixed(0)} kbps',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
