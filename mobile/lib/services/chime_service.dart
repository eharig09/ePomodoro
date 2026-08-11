import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';

class ChimeService {
  AudioPlayer? _player;
  Uint8List? _cached;

  Future<void> play() async {
    final player = _player ??= AudioPlayer();
    _cached ??= _buildChime();
    await player.stop();
    await player.play(BytesSource(_cached!), volume: 0.65);
  }

  Future<void> dispose() async => _player?.dispose();

  Uint8List _buildChime() {
    const sampleRate = 22050;
    const seconds = 3;
    const samples = sampleRate * seconds;
    final dataSize = samples * 2;
    final bytes = ByteData(44 + dataSize);

    void text(int offset, String value) {
      for (var index = 0; index < value.length; index++) {
        bytes.setUint8(offset + index, value.codeUnitAt(index));
      }
    }

    text(0, 'RIFF');
    bytes.setUint32(4, 36 + dataSize, Endian.little);
    text(8, 'WAVE');
    text(12, 'fmt ');
    bytes.setUint32(16, 16, Endian.little);
    bytes.setUint16(20, 1, Endian.little);
    bytes.setUint16(22, 1, Endian.little);
    bytes.setUint32(24, sampleRate, Endian.little);
    bytes.setUint32(28, sampleRate * 2, Endian.little);
    bytes.setUint16(32, 2, Endian.little);
    bytes.setUint16(34, 16, Endian.little);
    text(36, 'data');
    bytes.setUint32(40, dataSize, Endian.little);

    for (var index = 0; index < samples; index++) {
      final time = index / sampleRate;
      final attack = math.min(1.0, time / 0.08);
      final release = math.min(1.0, (seconds - time) / 1.4);
      final envelope = attack * release * math.exp(-time * 0.35);
      final tone =
          math.sin(2 * math.pi * 523.25 * time) * 0.55 +
          math.sin(2 * math.pi * 659.25 * time) * 0.30 +
          math.sin(2 * math.pi * 783.99 * time) * 0.15;
      final sample = (tone * envelope * 10500).round().clamp(-32768, 32767);
      bytes.setInt16(44 + index * 2, sample, Endian.little);
    }
    return bytes.buffer.asUint8List();
  }
}
