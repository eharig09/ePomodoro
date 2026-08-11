import 'dart:convert';

import 'package:epomodoro_mobile/data/cloud_client.dart';
import 'package:epomodoro_mobile/data/cloud_sync_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('canonical JSON is stable across map insertion order', () {
    expect(
      canonicalJson({
        'z': 1,
        'a': {'second': 2, 'first': 1},
      }),
      canonicalJson({
        'a': {'first': 1, 'second': 2},
        'z': 1,
      }),
    );
  });

  test('remote records are validated and timestamps normalized', () {
    final record = CloudSyncService.normalizeRecord({
      'entity_type': 'reflection',
      'entity_id': '2026-08-10',
      'payload': {'mood': 4, 'journal': 'Good day'},
      'client_updated_at': '2026-08-10T10:00:00-04:00',
      'server_updated_at': '2026-08-10T14:00:01Z',
      'device_id': 'desktop',
      'deleted_at': null,
    });

    expect(record, isNotNull);
    expect(record!['client_updated_at'], '2026-08-10T14:00:00.000Z');
    expect(record['payload_json'], '{"journal":"Good day","mood":4}');
    expect(
      CloudSyncService.normalizeRecord({
        'entity_type': 'unknown',
        'entity_id': 'bad',
        'payload': <String, Object?>{},
      }),
      isNull,
    );
  });

  test('service-role JWTs are rejected by cloud configuration', () {
    final claims = base64Url
        .encode(utf8.encode(jsonEncode({'role': 'service_role'})))
        .replaceAll('=', '');
    expect(
      () => CloudConfig.validate(
        'https://example.supabase.co',
        'header.$claims.signature',
      ),
      throwsA(isA<CloudException>()),
    );
  });
}
