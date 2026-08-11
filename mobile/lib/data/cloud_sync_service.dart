import 'dart:convert';
import 'dart:math';

import 'cloud_client.dart';
import 'local_store.dart';

class CloudSyncSummary {
  const CloudSyncSummary({
    required this.pushed,
    required this.pulled,
    required this.applied,
    required this.syncedAt,
  });

  final int pushed;
  final int pulled;
  final int applied;
  final DateTime syncedAt;
}

class CloudSyncService {
  const CloudSyncService({required this.client, required this.store});

  static const entityTypes = {
    'local_task',
    'focus_session',
    'habit',
    'habit_checkin',
    'reflection',
  };

  final CloudClient client;
  final LocalStore store;

  Future<CloudSyncSummary> synchronize() async {
    final deviceId = await _deviceId();
    final local = <String, Map<String, Object?>>{};
    for (final entity in await store.exportSyncEntities()) {
      local[_key(entity)] = entity;
    }
    final shadowRows = await store.loadCloudShadow();
    final shadow = <String, Map<String, Object?>>{
      for (final row in shadowRows)
        '${row['entity_type']}\u0000${row['entity_id']}': row,
    };
    final pending = _pendingRecords(local, shadow, deviceId);
    await client.mergeRecords(pending);

    final pulled = await client.fetchRecords();
    final changed = <Map<String, Object?>>[];
    for (final raw in pulled) {
      final record = normalizeRecord(raw);
      if (record == null) continue;
      final previous = shadow[_key(record)];
      if (previous == null || !_shadowMatches(previous, record)) {
        changed.add(record);
      }
    }
    changed.sort(_applyOrder);
    await store.applyCloudRecords(changed);
    final syncedAt = DateTime.now().toUtc();
    await store.setCloudState('last_sync', syncedAt.toIso8601String());
    return CloudSyncSummary(
      pushed: pending.length,
      pulled: pulled.length,
      applied: changed.length,
      syncedAt: syncedAt,
    );
  }

  List<Map<String, Object?>> _pendingRecords(
    Map<String, Map<String, Object?>> local,
    Map<String, Map<String, Object?>> shadow,
    String deviceId,
  ) {
    final now = DateTime.now().toUtc().toIso8601String();
    final pending = <Map<String, Object?>>[];
    for (final entry in local.entries) {
      final entity = entry.value;
      final payload = entity['payload']! as Map<String, Object?>;
      final previous = shadow[entry.key];
      if (previous != null &&
          previous['deleted_at'] == null &&
          previous['payload_json'] == canonicalJson(payload)) {
        continue;
      }
      pending.add({
        'entity_type': entity['entity_type'],
        'entity_id': entity['entity_id'],
        'payload': payload,
        'client_updated_at': now,
        'device_id': deviceId,
        'deleted_at': null,
      });
    }
    for (final entry in shadow.entries) {
      if (local.containsKey(entry.key) || entry.value['deleted_at'] != null) {
        continue;
      }
      pending.add({
        'entity_type': entry.value['entity_type'],
        'entity_id': entry.value['entity_id'],
        'payload': <String, Object?>{},
        'client_updated_at': now,
        'device_id': deviceId,
        'deleted_at': now,
      });
    }
    return pending;
  }

  Future<String> _deviceId() async {
    final existing = await store.getCloudState('device_id');
    if (existing != null && existing.isNotEmpty) return existing;
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes
        .map((value) => value.toRadixString(16).padLeft(2, '0'))
        .join();
    final id =
        '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
    await store.setCloudState('device_id', id);
    return id;
  }

  static Map<String, Object?>? normalizeRecord(Map<String, Object?> raw) {
    final type = raw['entity_type']?.toString() ?? '';
    final id = raw['entity_id']?.toString() ?? '';
    final payloadValue = raw['payload'];
    final clientUpdated = _timestamp(raw['client_updated_at']);
    final serverUpdated = _timestamp(raw['server_updated_at']);
    final deviceId = raw['device_id']?.toString() ?? '';
    final deleted = raw['deleted_at'] == null
        ? null
        : _timestamp(raw['deleted_at']);
    if (!entityTypes.contains(type) ||
        id.isEmpty ||
        id.length > 300 ||
        payloadValue is! Map ||
        clientUpdated == null ||
        serverUpdated == null ||
        deviceId.isEmpty ||
        (raw['deleted_at'] != null && deleted == null)) {
      return null;
    }
    final payload = payloadValue.map(
      (key, value) => MapEntry('$key', value as Object?),
    );
    return {
      'entity_type': type,
      'entity_id': id,
      'payload': payload,
      'payload_json': canonicalJson(payload),
      'client_updated_at': clientUpdated,
      'server_updated_at': serverUpdated,
      'device_id': deviceId.substring(0, min(200, deviceId.length)),
      'deleted_at': deleted,
    };
  }

  static String? _timestamp(Object? value) {
    final parsed = DateTime.tryParse(value?.toString() ?? '');
    return parsed?.toUtc().toIso8601String();
  }

  static bool _shadowMatches(
    Map<String, Object?> previous,
    Map<String, Object?> record,
  ) =>
      previous['payload_json'] == record['payload_json'] &&
      previous['client_updated_at'] == record['client_updated_at'] &&
      previous['device_id'] == record['device_id'] &&
      previous['deleted_at'] == record['deleted_at'];

  static int _applyOrder(
    Map<String, Object?> left,
    Map<String, Object?> right,
  ) {
    const upsert = {
      'habit': 0,
      'local_task': 1,
      'focus_session': 1,
      'reflection': 1,
      'habit_checkin': 2,
    };
    const deletion = {
      'habit_checkin': 0,
      'focus_session': 1,
      'local_task': 1,
      'reflection': 1,
      'habit': 2,
    };
    final leftDeleted = left['deleted_at'] != null;
    final rightDeleted = right['deleted_at'] != null;
    if (leftDeleted != rightDeleted) return leftDeleted ? -1 : 1;
    final priorities = leftDeleted ? deletion : upsert;
    return priorities[left['entity_type']]!.compareTo(
      priorities[right['entity_type']]!,
    );
  }

  static String _key(Map<String, Object?> record) =>
      '${record['entity_type']}\u0000${record['entity_id']}';
}

String canonicalJson(Object? value) => jsonEncode(_canonical(value));

Object? _canonical(Object? value) {
  if (value is Map) {
    final keys = value.keys.map((key) => '$key').toList()..sort();
    return {for (final key in keys) key: _canonical(value[key])};
  }
  if (value is List) return value.map(_canonical).toList();
  return value;
}
